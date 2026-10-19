"""Nonblocking Windows instance lock, compatible with older app launches."""
import errno
import msvcrt
from pathlib import Path

def acquire(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+b')
    # Windows forbids reading a byte locked by another process. Lock first;
    # byte-range locks work beyond EOF, including a newly created empty file.
    stream.seek(0)
    try:
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as error:
        stream.close()
        if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            return None
        raise
    return stream
