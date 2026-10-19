"""Windows user-scoped DPAPI storage for credentials entered in the new UI."""
import ctypes
import json
import os
from ctypes import wintypes

class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

def transform(data, decrypt=False):
    if os.name != 'nt':
        raise ValueError('Credential vault requires Windows DPAPI')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), 'Video Automation Studio', None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))

def load(path):
    if not path.exists():return {}
    try:return json.loads(transform(path.read_bytes(),decrypt=True))
    except OSError:
        # Windows DPAPI vaults belong to a machine/user. Moving the app must
        # still open safely so the new user can enter their own credentials.
        return {}

def save(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('wb') as stream:
        stream.write(transform(json.dumps(values).encode('utf-8')))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
