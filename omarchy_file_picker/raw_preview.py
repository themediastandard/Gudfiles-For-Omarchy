"""Bounded, cancellable camera RAW decoding for the in-window preview."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable

import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, Gio, GLib


DECODE_TIMEOUT = 90
_decode_slots = threading.BoundedSemaphore(2)


class RawPreviewCancelled(Exception):
    """The preview was closed or superseded by another file."""


def is_raw_image(path: Path) -> bool:
    # Python's mimetypes table omits many camera formats. The desktop MIME
    # database includes camera-specific types and their shared RAW parent.
    content_type, uncertain = Gio.content_type_guess(path.name, None)
    if uncertain:
        try:
            info = Gio.File.new_for_path(str(path)).query_info(
                'standard::content-type', Gio.FileQueryInfoFlags.NONE, None)
            content_type = info.get_content_type()
        except GLib.Error:
            return False
    return bool(content_type and Gio.content_type_is_a(content_type, 'image/x-dcraw'))


def _check_cancelled(cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise RawPreviewCancelled()


def read_raw_preview(path: Path, width: int = 1800, height: int = 1400,
                     cancelled: Callable[[], bool] | None = None):
    """Return oriented pixels without opening a viewer or changing the source."""
    cancelled = cancelled or (lambda: False)
    _check_cancelled(cancelled)
    helper = shutil.which('raw-preview')
    if not helper:
        raise RuntimeError('Camera RAW preview support is not installed.')
    # Rapid arrow navigation must not start an unbounded number of decoders.
    while not _decode_slots.acquire(timeout=.05):
        _check_cancelled(cancelled)
    try:
        _check_cancelled(cancelled)
        with tempfile.TemporaryDirectory(prefix='picker-raw-preview-') as directory:
            output = Path(directory) / 'preview.png'
            command = [helper, '--thumbnail', str(path.absolute()), str(output),
                       str(max(width, height))]
            with subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  start_new_session=True) as process:
                try:
                    deadline = time.monotonic() + DECODE_TIMEOUT
                    while process.poll() is None:
                        _check_cancelled(cancelled)
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Camera RAW preview took too long to load.')
                        try:
                            process.wait(timeout=.05)
                        except subprocess.TimeoutExpired:
                            pass
                    _check_cancelled(cancelled)
                    if process.returncode:
                        raise RuntimeError('This camera RAW file could not be previewed.')
                    return GdkPixbuf.Pixbuf.new_from_file_at_scale(
                        str(output), width, height, True)
                finally:
                    if process.poll() is None:
                        # Stop LibRaw/RawTherapee children as well as the wrapper.
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
    finally:
        _decode_slots.release()
