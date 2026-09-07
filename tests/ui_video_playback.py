"""Strict codec QA: generated videos must play at real-time speed in Quick Look."""
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow

# PipeWire restores mute/volume by application name, outside Path.home().
# Keep silent QA from muting the user's Python-backed Files previews.
GLib.set_application_name('Omarchy File Picker Playback QA')


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(50, lambda: loop.quit() or False)
    loop.run()


def until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Playback condition timed out'


formats = [
    ('h264.mp4', ['-c:v', 'libx264', '-preset', 'ultrafast'], 'aac'),
    ('hevc.mp4', ['-c:v', 'libx265', '-preset', 'ultrafast', '-x265-params', 'log-level=error:pools=1'], 'aac'),
    ('prores.mov', ['-c:v', 'prores_ks', '-profile:v', '2', '-pix_fmt', 'yuv422p10le'], 'pcm_s16le'),
    ('vp9.webm', ['-c:v', 'libvpx-vp9', '-deadline', 'realtime', '-cpu-used', '8'], 'libopus'),
    ('av1.mp4', ['-c:v', 'libaom-av1', '-cpu-used', '8', '-crf', '40'], 'aac'),
]

with tempfile.TemporaryDirectory(prefix='picker-video-') as temp, patch.object(Path, 'home', return_value=Path(temp)):
    root = Path(temp)
    for name, encoder, audio in formats:
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
                        '-f', 'lavfi', '-i', 'testsrc2=size=160x96:rate=12',
                        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
                        '-t', '3', *encoder, '-threads', '2', '-c:a', audio,
                        str(root / name)], check=True, timeout=25)
    request = PickerRequest(current_folder=root)
    app = PickerApplication(request, None)
    app.register(None)
    # Thumbnail generation is unrelated to playback codec verification.
    with patch('omarchy_file_picker.picker.thumbnail_file', return_value=None):
        window = PickerWindow(app, request, None)
    window.present()
    until(window.get_mapped)
    preview = window.quicklook
    try:
        for name, _, _ in formats:
            preview.show_file(root / name)
            until(lambda: preview.kind != 'loading')
            assert preview.kind == 'media', (name, preview.kind)
            media = preview.media
            media.set_muted(True)
            until(lambda: media.is_prepared() or media.get_error() is not None)
            assert media.get_error() is None, (name, media.get_error())
            assert media.has_video() and media.has_audio(), name
            until(lambda: media.get_timestamp() > 150000)
            assert media.get_playing(), name
            started = time.monotonic()
            timestamp = media.get_timestamp()
            until(lambda: time.monotonic() - started >= 1.2)
            elapsed = time.monotonic() - started
            advanced = (media.get_timestamp() - timestamp) / 1_000_000
            assert abs(advanced - elapsed) < .2, (name, 'video seconds', advanced, 'wall seconds', elapsed)
            media.pause()
            until(lambda: not media.get_playing())
            assert media.is_seekable(), name
            media.seek(1500000)
            until(lambda: not media.is_seeking() and media.get_timestamp() >= 1400000)
            media.play()
            until(lambda: media.get_timestamp() > 1700000)
            preview.close()
            until(lambda: not preview.get_visible())
            assert preview.media is None and not media.get_playing()
            print('PASS:', name, 'video/audio decoding, real-time play, pause, seek, resume and stop on close', flush=True)
    finally:
        window.destroy()
