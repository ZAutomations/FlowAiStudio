from __future__ import annotations
import copy
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from .storage import ROOT, atomic, public, read, redact
KINDS = {'studio': {'voice', 'render', 'browser'}, 'animate': {'voice', 'render', 'browser'}, 'studio-batch': {'voice', 'render', 'browser'}, 'animate-batch': {'voice', 'render', 'browser'}}
TERMINAL = {'completed', 'failed', 'stopped', 'interrupted'}

def worker_python():
    from bootstrap import PYTHON
    return str(PYTHON) if PYTHON.is_file() else sys.executable

def download_scan_message(summary):
    message = f"Scan finished: {summary.get('saved', 0)} scene images saved; {summary.get('downloaded', 0)} new downloads."
    if summary.get('gaps'):
        message += f" {len(summary['gaps'])} unmatched gaps through scene {summary.get('highest_saved_scene', 0)}."
    elif summary.get('unmatched'):
        message += f" {summary['unmatched']} later scenes not matched."
    return message

def timestamped_log(line, started=None, now=None):
    now = time.time() if now is None else now
    stamp = datetime.fromtimestamp(now).astimezone().strftime('%Y-%m-%d %H:%M:%S %z')
    elapsed = max(0, now - started) if started is not None else 0
    return f'[{stamp}] [+{elapsed:.1f}s] {line}'

class Jobs:

    def __init__(self, store):
        self.store = store
        self.directory = store.root / '.desktop'
        self.lock = threading.RLock()
        self.closed = False
        self.processes = {}
        self.items = read(self.directory / 'jobs.json', [])
        for job in self.items:
            if job['state'] not in TERMINAL:
                job.update(state='interrupted', message='App closed. Retry to resume completed assets.')
        self.thread = threading.Thread(target=self._schedule, daemon=True)
        self.thread.start()

    def _save(self):
        atomic(self.directory / 'jobs.json', self.items)

    def list(self):
        with self.lock:
            return copy.deepcopy(self.items)

    def clear_finished(self):
        """Remove terminal history only; preserve active workers and their files."""
        with self.lock:
            remaining = [job for job in self.items if job['state'] not in TERMINAL]
            removed = len(self.items) - len(remaining)
            atomic(self.directory / 'jobs.json', remaining)
            self.items = remaining
            return removed

    def submit(self, kind, payload, settings=None):
        if kind not in KINDS:
            raise ValueError('Unknown operation')
        if public(payload) != payload:
            raise ValueError('Credentials are not allowed in jobs')
        with self.lock:
            if self.closed:
                raise ValueError('Application is shutting down')
            job = {'id': uuid.uuid4().hex, 'kind': kind, 'payload': payload, 'settings': public(settings if settings is not None else self.store.worker_settings()), 'state': 'queued', 'progress': 0, 'message': 'Waiting for available resources', 'created': time.time(), 'logs': [], 'result': None}
            self.items.append(job)
            self._save()
            return copy.deepcopy(job)

    def _find(self, job_id):
        return next((j for j in self.items if j['id'] == job_id), None)

    def stop(self, job_id):
        with self.lock:
            job = self._find(job_id)
            if job is None:
                raise ValueError('Job not found')
            if job['state'] in TERMINAL:
                return
            if job['state'] == 'queued':
                job.update(state='stopped', message='Removed from queue')
            else:
                job.update(state='stopping', message='Saving checkpoints; stopping worker')
                (self.directory / (job_id + '.cancel')).touch()
                threading.Thread(target=self._force_stop, args=(job_id,), daemon=True).start()
            self._save()

    def retry(self, job_id):
        with self.lock:
            job = self._find(job_id)
            if job is None or job['state'] not in TERMINAL:
                raise ValueError('Only a finished or stopped job can be retried')
            return self.submit(job['kind'], copy.deepcopy(job['payload']), copy.deepcopy(job['settings']))

    @staticmethod
    def conflicts(a, b):
        if KINDS[a['kind']] & KINDS[b['kind']]:
            return True
        paths = lambda j: [Path(j['payload'][k]).resolve() for k in ('output_folder', 'output', 'project', 'source_project', 'channel') if j['payload'].get(k)]
        return any((p == q or p in q.parents or q in p.parents for p in paths(a) for q in paths(b)))

    def _schedule(self):
        while not self.closed:
            with self.lock:
                running = [j for j in self.items if j['state'] in ('running', 'stopping')]
                changed = False
                for job in self.items:
                    if job['state'] == 'queued' and (not any((self.conflicts(job, j) for j in running))):
                        job.update(state='running', message='Starting engine', started=time.time())
                        running.append(job)
                        threading.Thread(target=self._run, args=(job,), daemon=True).start()
                        changed = True
                if changed:
                    self._save()
            time.sleep(0.4)

    def _run(self, job):
        settings = self.store.worker_settings()

        def overlay(old, new):
            for key, value in new.items():
                if isinstance(value, dict) and isinstance(old.get(key), dict):
                    overlay(old[key], value)
                else:
                    old[key] = copy.deepcopy(value)
        overlay(settings, job['settings'])
        request = {'kind': job['kind'], 'payload': job['payload'], 'settings': settings, 'cancel': str(self.directory / (job['id'] + '.cancel'))}
        try:
            process = subprocess.Popen([worker_python(), '-X', 'utf8', '-u', '-m', 'desktop.worker'], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            with self.lock:
                self.processes[job['id']] = process
            process.stdin.write(json.dumps(request) + '\n')
            process.stdin.close()
            progress_start, progress_span = (0, 100)
            for line in process.stdout:
                with self.lock:
                    line = redact(line.rstrip(), settings)
                    if line.startswith('@desktop:'):
                        try:
                            event = json.loads(line[9:])
                            if 'progress' in event:
                                job['progress'] = max(0, min(100, float(event['progress'])))
                            if 'message' in event:
                                job['message'] = event['message']
                            if 'result' in event:
                                job['result'] = event['result']
                            if 'batch' in event:
                                job['batch'] = event['batch']
                            if 'range_start' in event:
                                progress_start, progress_span = (event['range_start'], event['range_size'])
                            continue
                        except (ValueError, TypeError):
                            pass
                    job['logs'].append(timestamped_log(line, job.get('started')))
                    if job['kind'] in ('quick', 'ourscript'):
                        frame = re.search('Frame\\s+\\d+/\\d+\\s+\\((\\d+)%\\)', line)
                        if frame:
                            job['progress'] = min(100, progress_start + float(frame[1]) * progress_span / 100)
                    job['logs'] = job['logs'][-500:]
            code = process.wait()
            process.stdout.close()
            with self.lock:
                stopped = job['state'] == 'stopping'
                job['finished'] = time.time()
                job.update(state='stopped' if stopped else 'completed' if code == 0 else 'failed', message='Stopped. Retry resumes saved work.' if stopped else 'Completed' if code == 0 else 'Failed. Read the log and retry.')
                if code != 0 and (not stopped) and any(('Account limit reached:' in line for line in job['logs'])):
                    job['message'] = 'Account limit reached. Progress saved; retry with the same account when quota is available.'
                if code != 0 and (not stopped) and any(('Flow rejected scene(s)' in line for line in job['logs'])):
                    job['message'] = 'Flow rejected a scene. Review its content or supply a replacement image. Completed images are saved.'
                if code == 0 and (not stopped):
                    job['progress'] = 100
                    if job['kind'] == 'studio' and job['payload'].get('action') == 'download-all-images' and ((job.get('result') or {}).get('download') is not None):
                        job['message'] = download_scan_message(job['result']['download'])
                    if job['kind'] == 'studio' and job['payload'].get('action') == 'plan':
                        job['message'] = f"Parsed {(job.get('result') or {}).get('scenes', 0)} scenes. Complete — ready for images and voice."
        except Exception as error:
            with self.lock:
                job.update(state='failed', message=redact(error, settings))
        finally:
            with self.lock:
                self.processes.pop(job['id'], None)
                self._save()

    def _force_stop(self, job_id):
        time.sleep(10)
        with self.lock:
            process = self.processes.get(job_id)
            if process and process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    process.kill()

    def close(self):
        self.closed = True
        for job in self.list():
            if job['state'] not in TERMINAL:
                self.stop(job['id'])
        deadline = time.monotonic() + 12
        while self.processes and time.monotonic() < deadline:
            time.sleep(0.1)
