"""Small, versioned thumbnails produced outside the GTK process."""
from __future__ import annotations

import atexit
import hashlib
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zlib

IMAGE_TYPES = {'.avif', '.bmp', '.gif', '.heic', '.jpeg', '.jpg', '.png', '.tif', '.tiff', '.webp'}
VIDEO_TYPES = {'.avi', '.m4v', '.mkv', '.mov', '.mp4', '.webm'}
RAW_TYPES = {'.' + ext for ext in (
    '3fr ari arq arw bay bmq cap cr2 cr3 crw crn cs1 dc2 dcr dcs dng drf '
    'erf fff gpr ia iiq k25 kc2 kdc mdc mef mos mrw nef nefx nrw obm orf '
    'pef ptx pxn qtk raf raw rdc rw2 rwl rwz sr2 srf srw sti x3f').split()}
THUMBNAIL_SIZE = 360
DECODE_TIMEOUT = 20
_processes = {}
_process_lock = threading.Lock()


def _kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@atexit.register
def _shutdown():
    with _process_lock:
        pending = list(_processes.items())
    for process, directory in pending:
        _kill_group(process)
        shutil.rmtree(directory, ignore_errors=True)


def _valid_png(path):
    # Reject corrupt/oversized cache headers before decoding in the GTK process.
    try:
        if not 0 < path.stat().st_size < 2 * 1024 * 1024:
            return False
        data = path.read_bytes()
        if data[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR' or not (
                0 < int.from_bytes(data[16:20], 'big') <= THUMBNAIL_SIZE and
                0 < int.from_bytes(data[20:24], 'big') <= THUMBNAIL_SIZE):
            return False
        offset = 8
        while offset + 12 <= len(data):
            length = int.from_bytes(data[offset:offset + 4], 'big')
            end = offset + 8 + length
            if end + 4 > len(data) or zlib.crc32(data[offset + 4:end]) != int.from_bytes(data[end:end + 4], 'big'):
                return False
            if data[offset + 4:offset + 8] == b'IEND':
                return length == 0 and end + 4 == len(data)
            offset = end + 4
        return False
    except OSError:
        return False


def identity(path):
    stat = path.stat()
    return (str(path.absolute()), stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)


def thumbnail_file(path: Path, cancelled=lambda: False) -> Path | None:
    """Worker-only. Cache exact source versions; never publish partial results."""
    if path.suffix.casefold() not in IMAGE_TYPES | VIDEO_TYPES | RAW_TYPES or cancelled():
        return None
    try:
        version = identity(path)
        digest = hashlib.sha256(repr(version).encode()).hexdigest()
        directory = Path.home() / '.cache/omarchy-file-picker/thumbnails-v2'
        directory.mkdir(parents=True, exist_ok=True)
        cache = directory / f'{digest}.png'
        if _valid_png(cache):
            return cache
        cache.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix='.decode-', dir=directory) as temporary:
            output = Path(temporary) / 'thumbnail.png'
            command = [sys.executable, '-m', 'omarchy_file_picker.thumbnail_decode',
                       str(path.absolute()), str(output), str(THUMBNAIL_SIZE)]
            with subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  start_new_session=True) as process:
                with _process_lock:
                    _processes[process] = temporary
                try:
                    deadline = time.monotonic() + DECODE_TIMEOUT
                    while process.poll() is None:
                        if cancelled() or time.monotonic() >= deadline:
                            return None
                        try:
                            process.wait(timeout=.05)
                        except subprocess.TimeoutExpired:
                            pass
                    if process.returncode or cancelled() or identity(path) != version:
                        return None
                    if not _valid_png(output):
                        return None
                    os.replace(output, cache)
                    return cache
                finally:
                    # Include helper descendants, even if the wrapper has exited.
                    _kill_group(process)
                    process.wait()
                    with _process_lock:
                        _processes.pop(process, None)
    except (OSError, subprocess.SubprocessError):
        return None
