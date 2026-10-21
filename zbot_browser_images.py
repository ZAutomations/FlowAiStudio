#!/usr/bin/env python
"""Browser adapters for Gemini, Meta AI and Google Flow. Dedicated local profiles preserve user-completed sign-in. Persistent mode uses installed Chrome; CDP mode attaches to an explicitly launched Chrome session. Each worker operation owns its Playwright session. Provider selectors are best-effort and failures remain visible. No authentication or browser security checks are bypassed."""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from ai_studio_pipeline import Cancelled, check_cancel

DEFAULT_PROFILE_DIR = Path(__file__).resolve().parent / 'zbot_profiles'

# Browser profiles stay local; sign-in is always completed by the user.
_BROWSER_ARGS = [
    '--no-first-run',
    '--no-default-browser-check',
]

class ZBotImageGenerator:
    """Generate images through the real Meta AI / Gemini web app."""

    PROVIDERS = {
        'gemini': {'url': 'https://gemini.google.com/app', 'label': 'Gemini (Google)'},
        'metaai': {'url': 'https://www.meta.ai/', 'label': 'Meta AI'},
        'flow': {'url': 'https://labs.google/fx/tools/flow', 'label': 'Google Flow'},
    }

    def __init__(self, provider='gemini', profile_dir=None, log=None, mode='persistent', flow_project_url='', cancel=None, share_google_profile=False, flow_aspect_ratio='', cdp_port=None, browser_account='', browser_type='chrome'):
        if provider not in self.PROVIDERS:
            raise ValueError(f"Unknown provider {provider!r}. "
                             f"Choose from {list(self.PROVIDERS)}")
        if browser_type not in ('chrome', 'edge'):
            raise ValueError('Choose Google Chrome or Microsoft Edge')
        self.browser_type = browser_type
        self.browser_label = 'Microsoft Edge' if browser_type == 'edge' else 'Chrome'
        self.provider = provider
        self.profile_dir = Path(profile_dir) if profile_dir else DEFAULT_PROFILE_DIR
        self.browser_account = browser_account
        self._log_cb = log or (lambda msg, level='info': None)
        self.mode = mode                     # 'persistent' | 'cdp'
        self.share_google_profile = provider == 'flow' and bool(share_google_profile)
        self.cdp_port = 10312 if self.share_google_profile else {'gemini': 10312, 'metaai': 10313, 'flow': 10314}[provider]
        if cdp_port is not None:
            self.cdp_port = int(cdp_port)
        if browser_type == 'edge':
            self.profile_dir = self.profile_dir / 'edge'
            if cdp_port is None:
                self.cdp_port += 3000
        self.flow_project_url = flow_project_url
        self.flow_aspect_ratio = flow_aspect_ratio
        self._flow_image_mode_verified = False
        self._flow_settings_summary = ''
        self._flow_asset_prompts = {}
        self.cancel = cancel
        self._chrome_proc = None             # Chrome we launched for CDP mode
        self._op_lock = threading.Lock()     # one browser op at a time

    def _browser_error(self, message):
        return RuntimeError(str(message).replace('Chrome', self.browser_label))

    # ── helpers ────────────────────────────────────────────────────────
    def _log(self, msg, level='info'):
        try:
            self._log_cb(msg.replace('Chrome', self.browser_label), level)
        except Exception:
            pass

    @staticmethod
    def is_available():
        try:
            import playwright  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def find_chrome():
        """Path to the real installed Chrome, or None."""
        candidates = [
            Path(os.environ.get('PROGRAMFILES', r'C:\Program Files'))
            / 'Google/Chrome/Application/chrome.exe',
            Path(os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)'))
            / 'Google/Chrome/Application/chrome.exe',
            Path(os.environ.get('LOCALAPPDATA', ''))
            / 'Google/Chrome/Application/chrome.exe',
        ]
        for c in candidates:
            try:
                if c.is_file():
                    return str(c)
            except Exception:
                continue
        return shutil.which('chrome') or shutil.which('chrome.exe')

    @staticmethod
    def find_edge():
        for base in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
            candidate = Path(os.environ.get(base, '')) / 'Microsoft/Edge/Application/msedge.exe'
            if candidate.is_file():
                return str(candidate)
        return shutil.which('msedge') or shutil.which('msedge.exe')

    def find_browser(self):
        return self.find_edge() if self.browser_type == 'edge' else self.find_chrome()

    @property
    def _profile_path(self) -> Path:
        return self.profile_dir / ('profile_gemini' if self.share_google_profile else f'profile_{self.provider}')

    # ── session plumbing ───────────────────────────────────────────────
    def _launch_options(self, headless, extra_args=None):
        opts = dict(
            headless=headless,
            viewport={'width': 1280, 'height': 900},
            args=list(_BROWSER_ARGS) + list(extra_args or []),
        )
        if self.find_browser():
            opts['channel'] = 'msedge' if self.browser_type == 'edge' else 'chrome'       # real Chrome, not bundled Chromium
        elif self.browser_type == 'edge':
            raise self._browser_error('Microsoft Edge not found. Install Edge or select Google Chrome.')
        else:
            self._log('⚠️ Google Chrome not found — using bundled Chromium. '
                      'Google may block sign-in; install Chrome or use '
                      '"Normal Chrome mode".', 'warn')
        return opts

    @contextmanager
    def _session(self, headless=True, extra_args=None):
        """Yield a browser context for ONE operation in the CURRENT thread."""
        try:
            from ai_studio_browser_runtime import playwright_runtime
        except ImportError:
            raise self._browser_error(
                'Playwright is not installed.\n\n'
                'Install it once with:\n'
                '  pip install playwright\n'
                '  playwright install chromium')

        self._profile_path.mkdir(parents=True, exist_ok=True)
        if self.mode=='cdp':
            if self.share_google_profile:self._log('Flow uses the selected dedicated Google profile and its saved sign-in.', 'info')
            if not self._cdp_alive():self._start_real_chrome()
        with playwright_runtime() as pw:
            if self.mode == 'cdp':
                browser = self._connect_browser(pw)
                ctx = (browser.contexts[0] if browser.contexts
                       else browser.new_context())
                try:
                    yield ctx
                finally:
                    try:
                        browser.close()      # detach; leaves Chrome running
                    except Exception:
                        pass
            else:
                ctx = pw.chromium.launch_persistent_context(
                    str(self._profile_path),
                    **self._launch_options(headless, extra_args))
                try:
                    yield ctx
                finally:
                    try:
                        ctx.close()
                    except Exception:
                        pass

    def _prune_flow_landing_tabs(self):
        """An idle Flow landing renderer can block Playwright's all-tab attach.

        Close only known landing URLs, and only when a Flow project is already
        open. Never touch projects, Gemini conversations, or sign-in pages.
        """
        if self.provider != 'flow':
            return
        try:
            with urllib.request.urlopen(self._cdp_url + '/json/list', timeout=3) as response:
                targets = json.load(response)
            def flow_project(target):
                url = urlparse(target.get('url', ''))
                return target.get('type') == 'page' and url.hostname in ('flow.google.com','flow.google','labs.google') and '/project/' in url.path
            if not any(flow_project(target) for target in targets):
                return
            for target in targets:
                check_cancel(self.cancel)
                url = urlparse(target.get('url', ''))
                landing = ((url.hostname in ('flow.google.com','flow.google') and url.path in ('','/'))
                           or (url.hostname == 'labs.google' and url.path.rstrip('/') == '/fx/tools/flow'))
                if target.get('type') == 'page' and landing:
                    target_id = str(target.get('id', ''))
                    if not re.fullmatch(r'[A-Za-z0-9_-]+',target_id):
                        continue
                    with urllib.request.urlopen(self._cdp_url + '/json/close/' + target_id, timeout=3):
                        pass
                    self._log('Closed an unused Flow homepage tab to keep the project connection responsive.', 'info')
        except Cancelled:
            raise
        except Exception as error:
            self._log('Could not clean up idle Flow tabs: ' + str(error), 'warn')

    def _connect_browser(self, pw):
        check_cancel(self.cancel)
        self._prune_flow_landing_tabs()
        self._log('Connecting to the dedicated Chrome browser (maximum 15 seconds)…', 'info')
        try:
            browser = pw.chromium.connect_over_cdp(self._cdp_url, timeout=15_000)
        except Exception as error:
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
            if isinstance(error, PlaywrightTimeout):
                raise self._browser_error('Chrome connection timed out before any image requests were sent. Save the project and stop the job, then close all dedicated AI Studio Chrome windows (including their Flow/Gemini tabs). Retry Generate Images so AI Studio can reopen its saved profile. Your saved scene progress and Google login are retained.') from error
            raise
        try:
            check_cancel(self.cancel)
        except Cancelled:
            browser.close()
            raise
        self._log('Chrome connected. Opening the selected project…', 'info')
        return browser

    # ── CDP mode helpers ───────────────────────────────────────────────
    @property
    def _cdp_url(self):
        return f'http://127.0.0.1:{self.cdp_port}'

    def _cdp_alive(self):
        try:
            with urllib.request.urlopen(f'{self._cdp_url}/json/version', timeout=0.5) as r:
                return r.status == 200
        except Exception:
            return False

    def _handover_edge_login(self):
        """Close only this app's ordinary Edge profile before enabling CDP.

        Edge otherwise forwards the launch URL to the existing non-CDP process
        and silently ignores the requested debugging port. Never touch personal
        profiles or a browser already running with a debugging connection.
        """
        if self.browser_type not in ('edge','chrome') or os.name != 'nt' or self._cdp_alive():
            return
        profile = str(self._profile_path.resolve()).replace("'", "''")
        executable='msedge.exe' if self.browser_type=='edge' else 'chrome.exe'
        script = r"""
$target = '__PROFILE__'
$roots = @(Get-CimInstance Win32_Process -Filter "name = '__BROWSER_EXE__'" -ErrorAction Stop | Where-Object {
    $command = $_.CommandLine
    if ($command -match '--type=' -or $command -match '--remote-debugging-port=') { return $false }
    $match = [regex]::Match($command, '--user-data-dir=(?:"([^"]+)"|([^ ]+))')
    if (!$match.Success) { return $false }
    $path = if ($match.Groups[1].Success) {$match.Groups[1].Value} else {$match.Groups[2].Value}
    return [string]::Equals($path.TrimEnd('\'), $target.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)
})
foreach ($root in $roots) {
    $browserProcess = Get-Process -Id $root.ProcessId -ErrorAction SilentlyContinue
    if (!$browserProcess) { continue }
    if ($browserProcess.MainWindowHandle -ne 0) {
        $null = $browserProcess.CloseMainWindow()
        $null = $browserProcess.WaitForExit(10000)
        $browserProcess.Refresh()
    }
    # Edge Startup Boost may retain a background owner after the window closes.
    if (!$browserProcess.HasExited -and $browserProcess.MainWindowHandle -eq 0) {
        Stop-Process -Id $root.ProcessId -ErrorAction Stop
        $null = $browserProcess.WaitForExit(5000)
    }
    if (!$browserProcess.HasExited) { throw 'Dedicated Edge login window did not close. Finish any open dialog, then retry.' }
}
Write-Output $roots.Count
""".replace('__PROFILE__', profile).replace('__BROWSER_EXE__',executable)
        encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                                 '-EncodedCommand', encoded], capture_output=True,
                                text=True, timeout=30, creationflags=0x08000000)
        if result.returncode:
            raise self._browser_error(f'Could not hand over the dedicated {self.browser_label} login window. Close that dedicated window using menu > Exit, then Retry. Saved login and progress retained.')
        if result.stdout.strip() != '0':
            self._log(f'Dedicated {self.browser_label} login closed; reopening the same saved profile with its generation connection.', 'info')

    def _start_real_chrome(self):
        """Launch installed Chrome with its local debugging connection for generation."""
        chrome = self.find_browser()
        if not chrome:
            raise self._browser_error(f'{self.browser_label} not found. Install the selected browser to use '
                               'this mode, or use the default login mode.')
        self._handover_edge_login()
        self._profile_path.mkdir(parents=True, exist_ok=True)
        launch_url = self.PROVIDERS[self.provider]['url']
        project = urlparse(self.flow_project_url)
        if self.provider == 'flow' and project.scheme == 'https' and project.hostname in ('flow.google.com','flow.google','labs.google') and '/project/' in project.path:
            launch_url = self.flow_project_url
        args = [
            chrome,
            f'--remote-debugging-port={self.cdp_port}',
            f'--user-data-dir={self._profile_path}',
            '--no-first-run', '--no-default-browser-check', '--disable-background-mode',
            launch_url,
        ]
        self._log(f'🌐 Launching Chrome → {self.PROVIDERS[self.provider]["label"]}', 'info')
        self._chrome_proc = subprocess.Popen(args)
        deadline = time.monotonic() + 20
        exited_at=None
        while time.monotonic() < deadline:
            check_cancel(self.cancel)
            if self._cdp_alive():
                return True
            code=self._chrome_proc.poll()
            if code is not None:
                if code!=0:raise self._browser_error(f'Dedicated Chrome exited with code {code} before its connection started. Saved login and project retained; close the dedicated account browser and Retry generation.')
                if exited_at is None:exited_at=time.monotonic()
                # Chrome can hand off to its browser process before the local
                # endpoint is ready. Allow that startup race, but do not loop
                # indefinitely when an ordinary login window owns the profile.
                if time.monotonic()-exited_at>=5:
                    raise self._browser_error(f'The selected account’s Chrome profile is already open without generation connection on port {self.cdp_port}. Finish sign-in, then use Chrome menu (three dots) > Exit in that dedicated login browser so its background process also stops. Then Retry Build All / Generate Images. Do not click Login again. Saved login and Flow project retained.')
            time.sleep(0.5)
        raise self._browser_error('Chrome opened but its automation connection was unavailable. Use Chrome menu (three dots) > Exit in the dedicated AI Studio browser, then Retry Build All / Generate Images. Do not click Login again. Saved login and project retained.')

    # ── public operations ──────────────────────────────────────────────
    def login(self, timeout_seconds=1800):
        """Open a browser so the user can log in; the session is saved.

        Blocks the calling thread — run from a worker thread.
        """
        with self._op_lock:
            if self.provider in ('gemini', 'flow'):
                return self._login_google_manual(timeout_seconds)
            if self.mode == 'cdp':
                return self._login_cdp(timeout_seconds)
            return self._login_persistent(timeout_seconds)

    def _login_google_manual(self, timeout_seconds):
        """Human sign-in in ordinary Chrome; never attach Playwright during login.

        Reuse only this provider's dedicated profile when generation starts.
        Closing Chrome finishes the manual step, not proof of authentication.
        """
        chrome = self.find_browser()
        if not chrome:
            raise self._browser_error(f'Install or update {self.browser_label} to sign in. Google login does not use bundled Chromium.')
        if self._cdp_alive():
            raise self._browser_error('Close the dedicated AI Studio Chrome window, then click Login again. Google sign-in must happen before the generation connection starts. Other Chrome windows can remain open.')
        self._profile_path.mkdir(parents=True, exist_ok=True)
        url = self.PROVIDERS[self.provider]['url']
        if self.provider == 'flow':
            parsed = urlparse(self.flow_project_url)
            if parsed.scheme == 'https' and parsed.hostname in ('labs.google', 'flow.google.com', 'flow.google') and '/project/' in parsed.path:
                url = self.flow_project_url
        self._log('🌐 Opening ordinary Chrome for manual Google sign-in. Sign in yourself, open your provider/project, then use Chrome menu (three dots) > Exit in this dedicated browser. Closing just the window may leave Chrome running in the background. Automation starts only when generating.', 'info')
        if self.share_google_profile:
            self._log('Flow login uses the same dedicated profile as Gemini. Its existing Google sign-in is retained; no personal Chrome profile or cookies are copied.', 'info')
        process = subprocess.Popen([chrome, f'--user-data-dir={self._profile_path}',
                                    '--no-first-run', '--no-default-browser-check', '--disable-background-mode', '--new-window', url])
        started = time.monotonic()
        while process.poll() is None:
            check_cancel(self.cancel)
            if time.monotonic() - started >= timeout_seconds:
                self._log('Manual login timed out. Chrome remains open; finish signing in, use Chrome menu (three dots) > Exit in that dedicated browser, then retry generation.', 'warn')
                return False
            time.sleep(.5)
        if process.returncode:
            raise self._browser_error('Chrome could not complete the manual login window. Close the dedicated profile window and retry Login.')
        if time.monotonic() - started < 2:
            raise self._browser_error('Chrome handed this request to an already-open profile. Close all windows for the dedicated AI Studio profile, then retry Login. Other Chrome profiles can remain open.')
        self._log('✅ Manual Chrome window closed. Profile retained; generation will check whether sign-in succeeded.', 'success')
        return True

    def _login_persistent(self, timeout_seconds):
        self._log(f'🌐 Opening {self.provider} login window — sign in, then '
                  f'CLOSE the browser window.', 'info')
        with self._session(headless=False, extra_args=['--start-maximized']) as ctx:
            page = ctx.new_page()
            page.goto(self.PROVIDERS[self.provider]['url'], wait_until='domcontentloaded')
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                check_cancel(self.cancel)
                if not ctx.pages:            # user closed the last window
                    break
                time.sleep(1.0)
        self._log('✅ Login window closed. Session saved for future runs.', 'success')
        return True

    def _login_cdp(self, timeout_seconds):
        self._log('🌐 Launching a normal Chrome (no automation flags). Sign in — '
                  'this window stays open for generation.', 'info')
        if not self._cdp_alive():
            self._start_real_chrome()
        with self._session(headless=False) as ctx:
            page = None
            for p in ctx.pages:
                if self.PROVIDERS[self.provider]['url'].split('/')[2] in (p.url or ''):
                    page = p
                    break
            if page is None:
                page = ctx.new_page()
                page.goto(self.PROVIDERS[self.provider]['url'],
                          wait_until='domcontentloaded')
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                check_cancel(self.cancel)
                if self._wait_composer(page, timeout=3) is not None:
                    self._log('✅ Signed in — composer detected. You can generate now.',
                              'success')
                    return True
                time.sleep(2.0)
            self._log('⚠️ Timed out waiting for sign-in. Finish logging in, then '
                      'click Generate Images.', 'warn')
            return False

    def generate(self, prompt, out_path, timeout=300):
        """Generate ONE image. Returns (ok, detail). Convenience for the CLI."""
        results = self.generate_batch([(prompt, out_path)], timeout=timeout)
        return results[0] if results else (False, 'no input')

    def generate_batch(self, items, timeout=300, on_result=None, headless=False, recover_only=False, batch_size=None,retry_missing=False):
        """Generate many images sequentially in ONE browser tab/conversation.

        ``items``: list of ``(prompt, out_path)``.
        ``on_result``: optional ``fn(index, ok, detail)`` for progress.
        ``headless``: default False — a visible, real Chrome window is far less
            likely to be blocked/mis-served than headless (whose UA still says
            "HeadlessChrome").  Set True only if you don't mind the risk.
        Returns a list of ``(ok, detail)`` aligned with ``items``.
        Blocks the calling thread — run from a worker thread.
        """
        items = list(items)
        if not items:
            return []
        self.prime_flow_prompt_cache([Path(items[0][1]).parent/'image_batches.json'])
        started=time.monotonic()
        delivered={}
        callback=on_result
        if callback:
            def on_result(index,ok,detail):
                delivered[index]=(ok,detail)
                callback(index,ok,detail)
        with self._op_lock:
            try:
                with self._session(headless=headless) as ctx:
                    check_cancel(self.cancel)
                    page = self._batch_page(ctx, prompts=[prompt for prompt, path in items] if recover_only else None)
                    page.set_default_timeout(5000)
                    check_cancel(self.cancel)
                    self._log('Browser project ready. Loading saved image batch progress…', 'info')
                    self._log(f'Browser connection and project readiness: {time.monotonic()-started:.1f}s.')
                    if batch_size is not None and self.provider in ('gemini', 'flow'):
                        from ai_studio_image_batches import QueuedImageBatches
                        return QueuedImageBatches(self, page, items, batch_size, timeout, on_result, recover_only,retry_missing).run()
                    results = []
                    for i, (prompt, out_path) in enumerate(items):
                        check_cancel(self.cancel)
                        ok, detail = self._generate_one(page, prompt, out_path, timeout, recover_only=recover_only)
                        results.append((ok, detail))
                        if on_result:
                            try:
                                on_result(i, ok, detail)
                            except Exception as error:
                                raise self._browser_error('Could not save image result: ' + str(error)) from error
                        if not ok and any(word in str(detail).lower() for word in ('download failed', 'quota', 'limit reached', 'sign in', 'logged in', 'rate limit', 'refused', 'declined', 'flow setup', 'select image mode', 'could not submit')):
                            # A session/quota failure will affect every remaining scene.
                            for remaining in range(i + 1, len(items)):
                                results.append((False, 'Stopped after a browser/setup failure. Fix the reported controls or recover existing images before resuming.'))
                                if on_result:
                                    on_result(remaining, False, results[-1][1])
                            break
                    return results
            except Exception as e:
                self._log(f'❌ {self.provider} session error: {e}', 'error')
                results=[delivered.get(index,(False,str(e))) for index in range(len(items))]
                # Session failures can occur before the per-image callbacks.
                # Notify the host too so the real cause is visible and saved.
                if on_result:
                    for index in range(len(items)):
                        if index not in delivered:on_result(index,False,str(e))
                return results

    # ── one image ──────────────────────────────────────────────────────
    def prime_flow_prompt_cache(self,manifest_paths):
        """Reuse verified asset/prompt pairs, never infer identity from position."""
        if self.provider!='flow':return
        loaded=0
        for path in manifest_paths:
            try:
                state=json.loads(Path(path).read_text(encoding='utf-8'))
                if state.get('version')!=1 or state.get('provider')!='flow' or state.get('browser_account','')!=self.browser_account:continue
                for token,record in state.get('requests',{}).items():
                    asset=record.get('asset_id','');prompt=record.get('submitted_prompt','')
                    if (record.get('status') in ('matched','complete') and re.fullmatch(r'[0-9a-fA-F-]{36}',asset)
                        and re.fullmatch(r'AS_SCENE_[0-9a-f]{20}',token) and token in prompt):
                        self._flow_asset_prompts[asset]=prompt;loaded+=1
            except (OSError,ValueError,TypeError,AttributeError):continue
        if loaded:self._log(f'Reused {loaded} verified Flow asset identities; earlier image prompt popups do not need to be reopened.')

    def _submit_queued_prompt(self, page, prompt, timeout):
        """Submit one request without waiting for its image; batch collection maps it."""
        deadline = time.monotonic() + timeout
        error = self._queued_error(page)
        if error:
            return False, 'Not submitted: ' + error
        if self.provider == 'gemini':
            # Gemini chat may serialize responses. Respect its busy state;
            # never interrupt an earlier request to force apparent parallelism.
            while any(page.locator(sel).first.is_visible() for sel in self._stop_selectors()):
                check_cancel(self.cancel)
                if time.monotonic() >= deadline:
                    return False, 'Not submitted: Gemini is still busy with an earlier image request'
                error = self._queued_error(page)
                if error:
                    return False, 'Not submitted: ' + error
                time.sleep(.5)
        if self.provider == 'flow' and page.locator('.cdk-overlay-popover .prompt-text').first.is_visible():
            page.keyboard.press('Escape')
        composer = self._wait_composer(page, timeout=30)
        if composer is None:
            return False, 'Not submitted: could not find the image prompt composer'
        try:
            self._prepare_image_mode(page)
        except Cancelled:
            raise
        except Exception as error:
            return False, 'Not submitted: ' + str(error)
        if not self._focus_composer(page):
            return False, 'Not submitted: could not focus the image prompt composer'
        for selector in self._composer_selectors():
            locator = page.locator(selector).first
            if locator.is_visible():
                locator.fill(prompt, timeout=5000)
                break
        else:
            return False, 'Not submitted: could not fill the image prompt composer'
        if self.provider == 'flow':
            modern = page.get_by_role('button', name='Start generation', exact=True).first
            while modern.is_visible() and not modern.is_enabled():
                check_cancel(self.cancel)
                error = self._queued_error(page)
                if error:
                    return False, 'Not submitted: ' + error
                if time.monotonic() >= deadline:
                    return False, 'Not submitted: Flow did not enable another queue slot before the timeout'
                time.sleep(.5)
        if not self._press_send(page, prompt):
            return False, self._queued_error(page) or 'Could not submit the queued image request'
        return True, 'submitted'

    def _queued_error(self, page):
        text = self._last_reply_text(page).lower() if self.provider == 'gemini' else page.locator('body').inner_text().lower()
        if self.provider=='flow' and 'we noticed some unusual activity' in text:
            return ('Flow unusual-activity check: generation paused. Saved images and pending identities are retained. '
                    'Wait a few minutes and resolve the warning in Flow before retrying. This is not model quota; do not rotate models or accounts.')
        if 'could not connect to the recaptcha service' in text:
            return ('Flow cannot connect to its reCAPTCHA service. Check the browser internet connection and reload the saved Flow project manually, '
                    'then Retry. Completed images and the submitted thumbnail identity are retained; no duplicate request was sent.')
        if self.provider == 'gemini' and any(phrase in text for phrase in self._REFUSAL):
            return 'The model declined an image request. Batch paused; edit that scene before resuming.'
        for phrase in ('quota exceeded', 'limit reached', 'daily limit', 'too many requests',
                       "you've reached your usage limit", 'you’ve reached your usage limit',
                       'usage limit reached', 'you have reached your usage limit',
                       'not enough credits', 'insufficient credits', 'generating too quickly',
                       'sign in to continue'):
            if phrase in text:
                if phrase == 'sign in to continue':
                    return 'Sign-in required. Completed images and pending identities are saved.'
                return 'Account limit reached: ' + phrase + '. Completed images and pending identities are saved. Resume with this account when quota is available; uncertain requests are recovered before new submissions.'
        return ''

    def _queued_generation_busy(self,page):
        """Only allow an explicit replacement when the loaded Flow grid is idle."""
        if self.provider!='flow':return True
        return page.evaluate('''() => {
            const editor=document.querySelector('div.ProseMirror[contenteditable="true"],textarea');
            if(!editor)return true;
            const text=(document.body.innerText||'').toLowerCase();
            if(/generating|queued|in progress|loading media/.test(text))return true;
            return !!document.querySelector('[role="progressbar"],flow-generation-tile,flow-loading-tile');
        }''')

    def _flow_image_assets(self, page):
        return page.eval_on_selector_all('flow-image-tile img[data-media-id]', '''els => els.filter(e=>e.complete && e.naturalWidth>=256 && e.naturalHeight>=256).map(e=>({id:e.getAttribute('data-media-id'),src:e.currentSrc||e.src}))''')

    def _flow_asset_prompt(self, page, asset_id):
        if asset_id in self._flow_asset_prompts:
            return self._flow_asset_prompts[asset_id]
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', asset_id or ''):
            return ''
        if page.locator('.cdk-overlay-popover .prompt-text').first.is_visible():
            page.keyboard.press('Escape')
        tile = page.locator('flow-image-tile').filter(has=page.locator('img[data-media-id="' + asset_id + '"]')).first
        try:
            tile.hover(timeout=3000)
            tile.locator('.footer-left').click(timeout=3000)
            prompt = page.locator('.cdk-overlay-popover .prompt-text').first
            prompt.wait_for(state='visible', timeout=3000)
            text = prompt.inner_text()
            self._flow_asset_prompts[asset_id] = text
            page.keyboard.press('Escape')
            return text
        except Exception:
            return ''  # no verified prompt identity: never guess by tile position

    def _queued_image_results(self, page, records):
        matches = {}
        if not records:
            return matches
        if self.provider == 'gemini':
            for record in records:
                src = self._existing_image_for_prompt(page, record['submitted_prompt'])
                if not src and record['status'] == 'pending' and sum(r['prompt'] == record['prompt'] for r in records) == 1:
                    src = self._existing_image_for_prompt(page, record['prompt'])
                if src:
                    matches[record['token']] = {'src': src, 'asset_id': record['token']}
            return matches
        assets = self._flow_image_assets(page)
        norm = lambda value: ' '.join((value or '').split())
        for asset in assets:
            # A recovered manifest already has the asset's immutable identity.
            direct = [r for r in records if r.get('asset_id') == asset['id']]
            if not direct:
                prompt = self._flow_asset_prompt(page, asset['id'])
                direct = [r for r in records if r['token'] in prompt]
                if not direct:
                    direct = [r for r in records if r['status'] == 'pending' and norm(r['prompt']) == norm(prompt)]
            if len(direct) == 1:
                token = direct[0]['token']
                if token in matches and matches[token]['asset_id'] != asset['id']:
                    raise self._browser_error('Multiple assets match one scene request. Batch paused instead of assigning an ambiguous image.')
                matches[token] = {'src': asset['src'], 'asset_id': asset['id']}
        return matches

    def _batch_page(self, ctx, prompts=None):
        """Reuse the provider tab, navigating only when starting a new tab."""
        url = self.PROVIDERS[self.provider]['url']
        if self.provider == 'flow':
            parsed = urlparse(self.flow_project_url)
            if parsed.scheme != 'https' or parsed.hostname not in ('labs.google', 'flow.google.com', 'flow.google') or '/project/' not in parsed.path:
                raise ValueError('Enter an HTTPS Google Flow project URL from flow.google.com or labs.google in the Flow project URL field.')
            url = self.flow_project_url
        target = urlparse(url)
        if prompts and self.provider == 'gemini':
            candidates = [p for p in ctx.pages if not p.is_closed() and urlparse(p.url).hostname == target.hostname]
            scored = [(sum(bool(self._existing_image_for_prompt(p, prompt)) for prompt in prompts), p) for p in candidates]
            if scored:
                score, best = max(scored, key=lambda value: value[0])
                if score:
                    return best
        for page in ctx.pages:
            if page.is_closed():
                continue
            current = urlparse(page.url)
            if current.hostname == target.hostname and (self.provider != 'flow' or current.path.rstrip('/') == target.path.rstrip('/')):
                self._log('Reusing the existing ' + self.provider + ' project tab.', 'info')
                return page
        self._log('Loading the selected ' + self.provider + ' project URL (maximum 60 seconds)…', 'info')
        page = next((p for p in ctx.pages if not p.is_closed() and p.url in ('', 'about:blank')), None)
        if page is None:
            page = ctx.new_page()
        page.goto(url, wait_until='domcontentloaded', timeout=60_000)
        return page

    def _generate_one(self, page, prompt, out_path, timeout, recover_only=False):
        if not prompt or not str(prompt).strip():
            return False, 'Empty prompt'
        try:
            self._log(f'🖼 {self.provider}: “{str(prompt)[:60]}…”', 'info')
            existing = self._existing_image_for_prompt(page, str(prompt))
            if existing:
                if self._download_image(page, existing, out_path):
                    self._log('✅ Recovered existing image → ' + Path(out_path).name, 'success')
                    return True, out_path
                return False, 'Download failed for an existing image. Conversation preserved; no new prompt submitted.'
            if recover_only:
                return False, 'No matching generated image found for this scene; no prompt submitted.'

            composer = self._wait_composer(page)
            if composer is None:
                return False, ('Could not find the message composer. Are you '
                               'logged in? Run "Login" first, or the site layout changed.')

            self._prepare_image_mode(page)
            known = self._snapshot_image_srcs(page)
            previous_reply = self._last_reply_text(page).lower()
            if not self._focus_composer(page):
                return False, ('Could not click into the message composer. Are you '
                               'logged in? Run "Login" first, or the site layout changed.')
            # Fill a fresh locator, rather than typing thousands of characters slowly.
            filled = False
            for selector in self._composer_selectors():
                locator = page.locator(selector).first
                try:
                    if locator.is_visible():
                        locator.fill(str(prompt), timeout=5000)
                        filled = True
                        break
                except Exception:
                    continue
            if not filled:
                page.keyboard.insert_text(str(prompt))
            if not self._press_send(page, str(prompt)):
                return False, ('Typed the prompt but could not submit it — the '
                               'send button never took. The site layout may have '
                               'changed; check the selectors in _send_selectors().')

            src, why = self._wait_new_image(page, known, timeout, previous_reply)
            if not src:
                reply = self._last_reply_text(page)
                if reply:
                    return False, (f'{why}. The model replied: “{reply}” — the '
                                   'web app refused to produce an image for this '
                                   'account rather than the code missing it.')
                return False, why

            if self._download_image(page, src, out_path) and os.path.getsize(out_path) > 0:
                self._log(f'✅ Saved image ({os.path.getsize(out_path):,} B) '
                          f'→ {Path(out_path).name}', 'success')
                return True, out_path
            return False, 'Download failed for the generated image. Conversation preserved; recover it before generating more scenes.'
        except Exception as e:
            self._log(f'❌ {self.provider} error: {e}', 'error')
            return False, str(e)

    def _prepare_image_mode(self, page):
        if self.provider == 'gemini':
            # Google's Create image tool avoids routing the request to text chat.
            try:
                create = page.get_by_role('button', name=re.compile(r'^Create (an )?image', re.I)).first
                if create.is_visible():
                    create.click(timeout=3000)
                    return
                tools = page.get_by_role('button', name=re.compile(r'^Tools$', re.I)).first
                if tools.is_visible():
                    tools.click(timeout=3000)
                    image = page.get_by_text(re.compile(r'^Create (an )?image', re.I)).first
                    if image.is_visible():
                        image.click(timeout=3000)
                    else:
                        tools.click(timeout=3000)
            except Exception:
                # Gemini also recognizes an explicit create-image prompt directly.
                pass
        elif self.provider == 'flow':
            self._prepare_flow_image_mode(page)

    def _prepare_flow_image_mode(self, page):
        """Support current Flow's settings radios and guarded Start generation."""
        # Animate leaves the shared browser in Agent Mode. Its settings drawer
        # does not expose the ordinary image composer's Settings trigger.
        # Exit Agent Mode BEFORE looking for Image/x1/aspect controls.
        agent=page.locator('button.agent-mode-chip').first
        host=page.locator('flow-agent-mode-toggle-chip').first
        enabled=(agent.is_visible() and agent.get_attribute('aria-pressed')=='true') or (host.is_visible() and 'checked' in (host.get_attribute('class') or '').split())
        if enabled:
            stop=page.get_by_role('button',name=re.compile(r'^Stop(?: generation| generating)?$',re.I)).first
            if stop.is_visible():raise self._browser_error('Flow setup: Agent is still generating. Wait for it to finish before switching to image generation. No request submitted.')
            self._flow_image_mode_verified=False;self._flow_settings_summary=''
            self._log('Switching Flow from Agent Mode to ordinary image generation…')
            (agent if agent.is_visible() else host).click(timeout=5000)
            page.wait_for_function('''() => {
                const button=document.querySelector('button.agent-mode-chip');
                const host=document.querySelector('flow-agent-mode-toggle-chip');
                return button?.getAttribute('aria-pressed')!=='true' && !host?.classList.contains('checked');
            }''',timeout=5000)
            page.get_by_role('button',name='Settings trigger',exact=True).first.wait_for(state='visible',timeout=5000)
        # During a queued batch retain a verified, unchanged image-only model
        # selection instead of repeatedly opening a popup as tiles reflow.
        if self._flow_image_mode_verified and self._flow_settings_summary:
            trigger = page.get_by_role('button', name='Settings trigger', exact=True).first
            current = ' '.join(trigger.inner_text().split()) if trigger.is_visible() else ''
            agent = page.locator('button.agent-mode-chip').first
            if current == self._flow_settings_summary and re.search(r'Nano Banana|Imagen', current, re.I) and not (agent.is_visible() and agent.get_attribute('aria-pressed') == 'true'):
                return
        self._flow_image_mode_verified = False
        self._flow_settings_summary = ''
        modern = page.get_by_role('button', name='Start generation', exact=True).first
        if not modern.is_visible():
            legacy = page.get_by_role('button', name=re.compile(r'Generate (an )?Image', re.I)).first
            if legacy.is_visible():
                self._flow_image_mode_verified = True
                return
            raise self._browser_error('Flow setup: no recognized image-generation control. No request submitted.')
        trigger = page.get_by_role('button', name='Settings trigger', exact=True).first
        image_name = re.compile(r'(?:^|\s)Image$', re.I)
        image = page.get_by_role('radio', name=image_name).first
        try:
            if not image.is_visible():
                trigger.click(timeout=3000)
                image.wait_for(state='visible', timeout=3000)
            if image.get_attribute('aria-checked') != 'true':
                image.click(timeout=3000)
            page.get_by_role('radio', name=image_name, checked=True).first.wait_for(state='visible', timeout=3000)
            one = page.get_by_role('radio', name='x1', exact=True).first
            if one.get_attribute('aria-checked') != 'true':
                one.click(timeout=3000)
            page.get_by_role('radio', name='x1', exact=True, checked=True).first.wait_for(state='visible', timeout=3000)
            if self.flow_aspect_ratio:
                ratio_name = re.compile(r'(?:^|\s)' + re.escape(self.flow_aspect_ratio) + r'$')
                ratio = page.get_by_role('radio', name=ratio_name).first
                if ratio.get_attribute('aria-checked') != 'true':
                    ratio.click(timeout=3000)
                page.get_by_role('radio', name=ratio_name, checked=True).first.wait_for(state='visible', timeout=3000)
            trigger.click(timeout=3000)
            image.wait_for(state='hidden', timeout=3000)
            self._flow_settings_summary = ' '.join(trigger.inner_text().split())
            if not re.search(r'\bx1\b', self._flow_settings_summary):
                raise self._browser_error('Flow did not retain one-output selection.')
            self._flow_image_mode_verified = True
            self._log('Flow image settings verified: ' + self._flow_settings_summary)
        except Exception as error:
            raise self._browser_error('Flow setup: could not verify Image mode, x1 output and requested aspect ratio. No generation submitted. ' + str(error)) from error

    # ── DOM helpers (best-effort, provider-specific) ───────────────────
    def _composer_selectors(self):
        common = [
            'div.ql-editor[contenteditable="true"]',
            'rich-textarea div[contenteditable="true"]',
            'div[contenteditable="true"][role="textbox"]',
            'textarea',
        ]
        if self.provider == 'metaai':
            return ['textarea[data-testid="chat-input-textarea"]',
                    'div[contenteditable="true"]', 'textarea'] + common
        if self.provider == 'flow':
            return ['div.ProseMirror[contenteditable="true"]', 'textarea[placeholder*="prompt" i]', 'div[contenteditable="true"][role="textbox"]', 'textarea', 'div[contenteditable="true"]']
        return common

    def _send_selectors(self):
        # Gemini's send control is a Material icon button — a bare <button>
        # wrapping <mat-icon fonticon="arrow_upward">, with no aria-label and no
        # type="submit", so every human-readable selector misses it.  Match the
        # icon itself (the click bubbles to the enclosing <button>) first.
        arrow = [
            'button:has(mat-icon[fonticon="arrow_upward"])',
            'button:has([data-mat-icon-name="arrow_upward"])',
            'mat-icon[fonticon="arrow_upward"]',
            'mat-icon[data-mat-icon-name="arrow_upward"]',
            '[fonticon="arrow_upward"]',
        ]
        common = [
            'button[aria-label*="Send message"]',
            'button[aria-label*="Send"]',
            'button.send-button',
            'div.send-button',
            'button[type="submit"]',
        ]
        if self.provider == 'metaai':
            return ['button[aria-label*="Send"]', '[data-testid="send-button"]',
                    'button[aria-label*="Submit"]'] + common
        if self.provider == 'flow':
            return ['button[aria-label="Start generation"]', 'button:has-text("Generate Image")', 'button[aria-label*="Generate Image" i]']
        return arrow + common

    def _stop_selectors(self):
        # Same story as send: Gemini swaps the arrow for a stop square while it
        # is generating, and that button is an icon button too.
        return [
            'button:has(mat-icon[fonticon="stop"])',
            'button:has(mat-icon[fonticon="stop_circle"])',
            'mat-icon[fonticon="stop"]',
            '[fonticon="stop"]',
            'button[aria-label*="Stop"]',
            'button[aria-label*="Cancel"]',
            'button[aria-label*="cancel generating"]',
            '[data-testid="stop-generating-button"]',
        ]

    def _wait_composer(self, page, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            check_cancel(self.cancel)
            for sel in self._composer_selectors():
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        return el
                except Exception:
                    continue
            time.sleep(1.0)
        return None

    @staticmethod
    def _el_text(el):
        """Read whatever a composer element holds — textarea vs contenteditable."""
        try:
            tag = (el.evaluate('e => e.tagName') or '').upper()
        except Exception:
            tag = ''
        try:
            if tag in ('TEXTAREA', 'INPUT'):
                return (el.input_value() or '').strip()
            return (el.inner_text() or '').strip()
        except Exception:
            return ''

    def _composer_text(self, page):
        for sel in self._composer_selectors():
            try:
                el = page.query_selector(sel)
                if el:
                    return self._el_text(el)
            except Exception:
                continue
        return ''

    def _sent_ok(self, page, typed):
        """A message was sent iff the composer let go of what we typed.

        Polls briefly: Angular clears the editor a moment after the click, and
        reading too early would make a working click look like a miss — which
        would send the same prompt twice.
        """
        if not typed:
            return True
        needle = typed.strip()[:40]
        deadline = time.time() + 3.0
        while True:
            now = self._composer_text(page)
            if not now or needle not in now:
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.3)

    def _focus_composer(self, page, tries=3):
        """Click into the composer, re-resolving the selector on every attempt.

        Gemini re-renders the composer during hydration, which detaches any
        handle grabbed by _wait_composer() a moment earlier — clicking that
        stale handle raises 'Element is not attached to the DOM'.  page.click()
        takes a selector, not a handle, so it re-resolves and retries instead
        of dying on the swap.
        """
        for attempt in range(tries):
            for sel in self._composer_selectors():
                try:
                    if page.query_selector(sel) is None:
                        continue
                    page.click(sel, timeout=5000)
                    return True
                except Exception as e:
                    if attempt == 0:
                        self._log(f'⚠️ composer click missed ({sel}): '
                                  f'{str(e).splitlines()[0]}', 'warn')
                    continue
            time.sleep(1.0)
        return False

    def _press_send(self, page, typed=''):
        """Click the real send control and *verify* it took effect.

        The trap this replaces: Gemini renders no send button at all until the
        composer has text — until then that slot holds a mic — so querying the
        instant after `keyboard.type()` finds nothing and the old code fell
        silently through to Enter, leaving the prompt sitting in the box.  Wait
        for the button to render, then confirm the composer actually emptied
        instead of assuming the click worked.
        """
        if self.provider == 'flow':
            if not self._flow_image_mode_verified:
                self._log('Flow setup: Image mode was not verified; no prompt submitted.', 'error')
                return False
            if self._flow_settings_summary:
                current = ' '.join(page.get_by_role('button', name='Settings trigger', exact=True).first.inner_text().split())
                agent = page.locator('button.agent-mode-chip').first
                if current != self._flow_settings_summary or (agent.is_visible() and agent.get_attribute('aria-pressed') == 'true'):
                    self._log('Flow setup: generation settings changed after verification; no prompt submitted.', 'error')
                    return False
        selectors = self._send_selectors()
        try:
            page.wait_for_selector(', '.join(selectors), timeout=10_000,
                                   state='visible')
        except Exception:
            self._log('⚠️ send button did not appear within 10s', 'warn')

        # Several selectors resolve to the same button; click each distinct
        # element once so a slow-rendering composer cannot be sent twice.
        clicked = set()
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if not el:
                    continue
                box = el.bounding_box()
                key = (round(box['x']), round(box['y'])) if box else sel
                if key in clicked:
                    continue
                clicked.add(key)
                try:
                    el.click(timeout=4000)
                except Exception:
                    if self.provider == 'flow':
                        continue  # never force-click a disabled generation control
                    el.click(force=True, timeout=4000)
            except Exception:
                continue
            if self._sent_ok(page, typed):
                self._log(f'▶️ sent (matched {sel!r})')
                return True

        # Enter is how Gemini itself submits; the button may just be mislabelled.
        if self.provider == 'flow':
            return False
        try:
            page.keyboard.press('Enter')
        except Exception:
            return False
        if self._sent_ok(page, typed):
            self._log('▶️ sent (keyboard Enter)')
            return True
        return False

    def _wait_generation_done(self, page, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            any_stop = False
            for sel in self._stop_selectors():
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        any_stop = True
                        break
                except Exception:
                    continue
            if not any_stop:
                return True
            time.sleep(1.5)
        return True

    def _snapshot_image_srcs(self, page):
        try:
            return set(page.eval_on_selector_all(
                'img', 'els => els.map(e => e.currentSrc || e.src).filter(Boolean)'))
        except Exception:
            return set()

    # Gemini's own chrome is full of <img> tags — a 150x150 sparkle SVG, the
    # profile photo under /a/, the gstatic ring.  Size alone is not enough to
    # tell them from a generated picture, so screen the URLs too.
    _UI_IMG_MARKERS = ('gstatic.com', 'googleusercontent.com/a/', '/ogw/',
                       '.svg', 'avatar', 'logo', 'icon', 'sparkle', 'favicon')

    def _candidate_image_srcs(self, page):
        try:
            for scope in ('model-response img, .response-container img, div[data-testid*="message"] img',
                          'main img', 'img'):
                srcs = page.eval_on_selector_all(
                    scope,
                    """els => els.map(e => {
                        const s = e.currentSrc || e.src || '';
                        return {s, w: e.naturalWidth || 0, h: e.naturalHeight || 0};
                    }).filter(o => o.s && o.w >= 256 && o.h >= 256).map(o => o.s)""")
                srcs = [s for s in srcs
                        if not any(m in s.lower() for m in self._UI_IMG_MARKERS)]
                if srcs:
                    return list(srcs)
        except Exception:
            pass
        return []

    # Phrases that mean "no image is ever coming" — worth abandoning the wait
    # for, since the alternative is 5 minutes per scene across a whole batch.
    _REFUSAL = ('cannot generate', "can't generate", 'cannot create',
                "can't create", 'unable to generate', 'cannot render',
                'not able to generate', 'cannot produce')

    def _wait_new_image(self, page, known, timeout, previous_reply=''):
        deadline = time.time() + timeout
        last_check = 0.0
        while time.time() < deadline:
            check_cancel(self.cancel)
            for src in self._candidate_image_srcs(page):
                if src and src not in known:
                    return src, 'found new image'
            now = time.time()
            if now - last_check >= 5:
                last_check = now
                reply = self._last_reply_text(page).lower()
                if reply == previous_reply:
                    time.sleep(1.0)
                    continue
                if any(p in reply for p in self._REFUSAL):
                    return None, 'the model declined to generate an image'
                if any(p in reply for p in ('limit reached', 'quota exceeded', 'try again tomorrow', 'too many requests')):
                    return None, 'image quota/rate limit reached; resume later'
            time.sleep(1.0)
        return None, 'Timed out waiting for a new image to appear'

    @staticmethod
    def _last_reply_text(page, limit=240):
        """What the model actually said — the useful half of a failed run.

        Without this a refusal ("I cannot generate images") surfaces only as
        "timed out waiting for an image", which sends you hunting selectors
        for a problem that was never in the DOM.
        """
        try:
            txt = page.evaluate(
                """() => {
                    const els = document.querySelectorAll(
                        'model-response, .response-container, .model-response-text');
                    // Gemini leaves a trailing empty container behind, so walk
                    // back from the end to the last one that actually has text.
                    for (let i = els.length - 1; i >= 0; i--) {
                        const t = (els[i].innerText || '').trim();
                        if (t) return t;
                    }
                    return '';
                }""")
            return ' '.join(str(txt).split())[:limit]
        except Exception:
            return ''

    def _existing_image_for_prompt(self, page, prompt):
        """Match a complete user prompt to images in that individual chat turn."""
        if self.provider != 'gemini':
            return None
        try:
            return page.evaluate("""prompt => {
                const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                const needle = norm(prompt);
                const queries = [...document.querySelectorAll('user-query, .user-query')];
                for (const query of queries.reverse()) {
                    if (!norm(query.textContent).includes(needle)) continue;
                    let turn = query.parentElement;
                    for (let level = 0; turn && level < 7; level++, turn = turn.parentElement) {
                        if (turn.querySelectorAll('user-query').length > 1) break;
                        const images = [...turn.querySelectorAll('model-response img, .response-container img')];
                        const image = images.find(e => e.complete && e.naturalWidth >= 256 && e.naturalHeight >= 256);
                        if (image) return image.currentSrc || image.src;
                    }
                }
                return null;
            }""", prompt)
        except Exception:
            return None

    @staticmethod
    def _save_image_bytes(raw, out_path, cancel=None):
        from PIL import Image
        check_cancel(cancel)
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.width < 256 or image.height < 256:
                raise ValueError('Downloaded asset is a thumbnail or UI icon, not a scene image.')
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(str(out_path) + '.downloading')
            image.convert('RGB').save(temporary, format='PNG')
        check_cancel(cancel)
        os.replace(temporary, out_path)

    def _displayed_image_bytes(self, page, src):
        """Read decoded pixels from the matching image, in its owning frame.

        A revoked/frame-owned blob can remain visible even though fetch fails.
        Canvas preserves natural resolution; element capture is a final fallback.
        """
        for frame in page.frames:
            check_cancel(self.cancel)
            try:
                handles = frame.locator('img').element_handles()
            except Exception:
                continue
            for image in reversed(handles):
                try:
                    matches = image.evaluate('(e, src) => (e.currentSrc || e.src) === src && e.complete && e.naturalWidth >= 256 && e.naturalHeight >= 256', src)
                    if not matches:
                        continue
                    try:
                        data = image.evaluate("""e => {
                            const canvas = document.createElement('canvas');
                            canvas.width = e.naturalWidth; canvas.height = e.naturalHeight;
                            canvas.getContext('2d').drawImage(e, 0, 0);
                            return canvas.toDataURL('image/png');
                        }""")
                        return base64.b64decode(data.split(',', 1)[1])
                    except Exception:
                        self._log('Using displayed-image capture; the original download/canvas is unavailable.', 'warn')
                        return image.screenshot(type='png', timeout=15_000, animations='disabled')
                except Exception:
                    continue
        raise self._browser_error('The generated image is not loaded in this tab. Keep the conversation open and retry Recover Images.')

    def _browser_image_bytes(self,page,src):
        """Download through Chrome's authenticated network, not a separate client."""
        client=page.context.new_cdp_session(page);handle=None
        try:
            frame=client.send('Page.getFrameTree')['frameTree']['frame']['id']
            resource=client.send('Network.loadNetworkResource',{'frameId':frame,'url':src,'options':{'disableCache':False,'includeCredentials':True}})['resource']
            handle=resource.get('stream')
            if not resource.get('success') or not handle:raise self._browser_error('Chrome could not load the matched image resource.')
            chunks=[];size=0
            while True:
                check_cancel(self.cancel)
                part=client.send('IO.read',{'handle':handle,'size':1048576})
                chunk=base64.b64decode(part['data']) if part.get('base64Encoded') else part['data'].encode('utf-8')
                chunks.append(chunk);size+=len(chunk)
                if size>50_000_000:raise self._browser_error('Matched image exceeds the download size limit.')
                if part.get('eof'):return b''.join(chunks)
        finally:
            if handle:
                try:client.send('IO.close',{'handle':handle})
                except Exception:pass
            client.detach()

    def _download_image(self, page, src, out_path):
        try:
            check_cancel(self.cancel)
            # For blob URLs, read the already-decoded image first. Fetch can fail
            # in a different frame or after Gemini revokes the object URL.
            if src.startswith('blob:'):
                try:
                    raw = self._displayed_image_bytes(page, src)
                    self._save_image_bytes(raw, out_path, self.cancel)
                    return True
                except Cancelled:
                    raise
                except Exception as error:
                    self._log('Displayed-image extraction unavailable: ' + str(error).splitlines()[0], 'warn')
            if src.startswith('data:image'):
                raw = base64.b64decode(src.split(',', 1)[1])
            elif src.startswith('blob:'):
                data_url = page.evaluate(
                    """async src => {
                        const r = await fetch(src);
                        const b = await r.blob();
                        return new Promise(res => {
                            const fr = new FileReader();
                            fr.onload = () => res(fr.result);
                            fr.readAsDataURL(b);
                        });
                    }""", src)
                raw = base64.b64decode(str(data_url).split(',', 1)[1])
            else:
                if self.provider=='flow':
                    try:
                        raw=self._browser_image_bytes(page,src)
                        self._save_image_bytes(raw,out_path,self.cancel)
                        return True
                    except Cancelled:raise
                    except Exception:
                        self._log('Chrome image resource unavailable; trying direct download, then displayed pixels.', 'warn')
                resp = page.request.get(src, timeout=15_000 if self.provider=='flow' else 60_000)
                if not resp.ok:
                    raise self._browser_error('Image HTTP download failed; attempting displayed-image extraction.')
                raw = resp.body()
            self._save_image_bytes(raw, out_path, self.cancel)
            return True
        except Cancelled:
            raise
        except Exception as e:
            # Also handles authenticated HTTP images whose request download fails.
            try:
                raw = self._displayed_image_bytes(page, src)
                self._save_image_bytes(raw, out_path, self.cancel)
                return True
            except Cancelled:
                raise
            except Exception:
                pass
            self._log('Image download failed: '+str(e).splitlines()[0], 'error')
            return False

    def close(self):
        """No-op for API compatibility — sessions are per-operation now."""
        return


# ── CLI for testing login / generation ─────────────────────────────────
if __name__ == '__main__':
    import argparse

    ap = argparse.ArgumentParser(description='ZBot-style browser image gen')
    ap.add_argument('--provider', choices=['gemini', 'metaai'], default='gemini')
    ap.add_argument('--mode', choices=['persistent', 'cdp'], default='persistent')
    ap.add_argument('--login', action='store_true', help='open browser to log in')
    ap.add_argument('--prompt', default='A cinematic wide shot of a lonely lighthouse at sunset')
    ap.add_argument('--out', default='_zbot_test.png')
    args = ap.parse_args()

    def log(msg, level='info'):
        tag = {'info': '·', 'success': '+', 'error': '!', 'warn': '~'}.get(level, '·')
        line = f'{tag} {msg}'
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode('ascii', 'replace').decode('ascii'))

    print('Chrome found at:', ZBotImageGenerator.find_chrome())
    gen = ZBotImageGenerator(provider=args.provider, mode=args.mode, log=log)
    if args.login:
        gen.login()
    else:
        ok, detail = gen.generate(args.prompt, args.out)
        print('OK →', detail if ok else f'FAILED: {detail}')
