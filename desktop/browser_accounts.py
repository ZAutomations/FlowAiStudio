"""Named local browser sessions. Passwords and cookies never enter app JSON."""
import re
import threading
import uuid
from .storage import ROOT, atomic, read

_lock = threading.RLock()

def profiles(root=ROOT):
    return read(root / '.desktop/browser_accounts.json', [])

def add(label, root=ROOT):
    label = str(label).strip()
    if not label or len(label) > 60:
        raise ValueError('Enter an account label of 1–60 characters')
    with _lock:
        rows = profiles(root)
        if any(row['label'].casefold() == label.casefold() for row in rows):
            raise ValueError('That account label already exists')
        if len(rows) >= 50:
            raise ValueError('Maximum 50 saved browser profiles')
        row = {'id': uuid.uuid4().hex, 'label': label, 'port': 10320 + len(rows) * 3}
        rows.append(row)
        atomic(root / '.desktop/browser_accounts.json', rows)
        return row

def browser_options(config, root=ROOT):
    account = config.get('browser_account', '')
    if not account:
        return {}
    if not isinstance(account, str) or not re.fullmatch(r'[0-9a-f]{32}', account):
        raise ValueError('Choose a saved browser account')
    row = next((r for r in profiles(root) if r['id'] == account), None)
    if not row:
        raise ValueError('The selected browser account is unavailable')
    offset = {'gemini': 0, 'flow': 0 if config.get('share_google_profile') else 2, 'metaai': 1}.get(config.get('provider', 'flow'), 0)
    return {'profile_dir': root / 'zbot_profiles/accounts' / account,
            'cdp_port': row['port'] + offset, 'browser_account': account}
