"""Observe every opening frame, including delayed video preparation; no real media."""
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker import quicklook
from gi.repository import GLib, Gtk

GLib.set_application_name('Gudfiles Initial Preview QA')


def settle(ms=20):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Preview condition timed out'


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', *args],
                   check=True, timeout=20)


def capture(window, name):
    if directory := os.environ.get('INITIAL_PREVIEW_SCREENSHOTS'):
        output = Path(directory)
        output.mkdir(parents=True, exist_ok=True)
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
        window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(str(output / f'{name}.png'))


with tempfile.TemporaryDirectory(prefix='gudfiles-initial-preview-') as directory, \
        patch.object(Path, 'home', return_value=Path(directory)):
    root = Path(directory)
    cases = []
    for name, width, height in [('portrait', 180, 320), ('landscape', 320, 180), ('square', 240, 240)]:
        path = root / f'{name}.mp4'
        ffmpeg('-f', 'lavfi', '-i', f'testsrc2=size={width}x{height}:rate=24',
               '-t', '2', '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', str(path))
        cases.append((path, width / height))
    rotated = root / 'rotated.mp4'
    ffmpeg('-i', str(root / 'landscape.mp4'), '-c', 'copy', '-metadata:s:v:0', 'rotate=90', str(rotated))
    # Opening must match the decoder's displayed orientation. The installed
    # GTK backend currently ignores this rotation tag; autorotation is separate
    # from eliminating a generic frame before the decoder is ready.
    cases.append((rotated, None))
    audio = root / 'audio-only.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'anullsrc=r=8000:cl=mono', '-t', '0.5', '-c:a', 'aac', str(audio))
    invalid = root / 'invalid.mp4'
    invalid.write_bytes(b'not a video')

    request = PickerRequest(current_folder=root, explorer=True, title='Initial preview QA')
    app = PickerApplication(request, None)
    app.register(None)
    with patch('omarchy_file_picker.picker.thumbnail_file', return_value=None):
        window = PickerWindow(app, request, None)
    window.present()
    until(window.get_mapped)
    until(lambda: window.browser_stack.get_height() > 0)
    settle(80)
    preview = window.quicklook
    original_geometry = (window.get_width(), window.get_height(), window.browser_stack.get_height())
    frames = []
    def painted(_clock):
        if preview.get_visible() and preview.target == 1 and preview.progress > 0:
            frames.append((preview.aspect_ratio, preview.rect[2:], preview.progress))
    clock = window.get_frame_clock()
    observer = clock.connect('after-paint', painted)
    try:
        original_read = quicklook.read_preview
        for path, ratio in cases:
            frames.clear()
            gate = threading.Event()
            def delayed_read(path, **kwargs):
                assert gate.wait(3)
                return original_read(path, **kwargs)
            with patch.object(quicklook, 'read_preview', delayed_read):
                preview.show_file(path)
                # A slow read must not expose a guessed player rectangle.
                settle(280)
                if path.stem == 'portrait':
                    capture(window, 'portrait-loading')
                gate.set()
                until(lambda: preview.kind == 'media' and preview.aspect_ratio > 0 and preview.progress == 1)
                settle(80)
            assert frames, path.name
            expected = ratio if ratio is not None else preview.media.get_current_image().get_intrinsic_aspect_ratio()
            assert all(math.isclose(frame[0], expected, abs_tol=.002) for frame in frames), (path.name, frames)
            assert all(frame[1] == frames[-1][1] for frame in frames), (path.name, frames)
            assert (window.get_width(), window.get_height(), window.browser_stack.get_height()) == original_geometry
            capture(window, path.stem)
            preview.close()
            until(lambda: not preview.get_visible())
            print('PASS:', path.name, 'correct aspect and identical target dimensions in every visible opening frame', flush=True)

        # Preparation and dimensions can arrive separately. A prepared stream
        # with unknown video dimensions still must not reveal a guessed card.
        frames.clear()
        with patch.object(Gtk.MediaStream, 'get_intrinsic_aspect_ratio', lambda _media: 0):
            preview.show_file(root / 'portrait.mp4')
            until(lambda: preview.media is not None and preview.media.is_prepared())
            settle(280)
            assert not frames and preview.progress == 0
        media = preview.media
        media.emit('invalidate-size')
        until(lambda: preview.progress == 1)
        assert frames and all(math.isclose(f[0], 9 / 16, abs_tol=.002) for f in frames)
        preview.close()
        until(lambda: not preview.get_visible())

        # Cancellation before dimensions arrive ignores all later decoder events.
        with patch.object(Gtk.MediaStream, 'get_intrinsic_aspect_ratio', lambda _media: 0):
            preview.show_file(root / 'portrait.mp4')
            until(lambda: preview.media is not None and preview.media.is_prepared())
            stale = preview.media
            preview.close()
            until(lambda: not preview.get_visible())
        stale.emit('invalidate-size')
        settle(100)
        assert not preview.get_visible() and preview.media is None
        assert window.preview_overlay.get_child().get_sensitive()

        # Switching while loading must not reveal the previous stream's shape.
        frames.clear()
        with patch.object(Gtk.MediaStream, 'get_intrinsic_aspect_ratio', lambda _media: 0):
            preview.show_file(root / 'portrait.mp4')
            until(lambda: preview.media is not None and preview.media.is_prepared())
            stale = preview.media
            preview.step(-1)
            assert preview.path == root / 'landscape.mp4'
            until(lambda: preview.media is not None and preview.media is not stale and preview.media.is_prepared())
            stale.emit('invalidate-size')
            settle(80)
            assert not frames
        preview.media.emit('invalidate-size')
        until(lambda: preview.progress == 1)
        assert frames and all(math.isclose(f[0], 16 / 9, abs_tol=.002) for f in frames)
        preview.close()
        until(lambda: not preview.get_visible())

        settings = preview.get_settings()
        animations = settings.get_property('gtk-enable-animations')
        settings.set_property('gtk-enable-animations', False)
        try:
            with patch.object(Gtk.MediaStream, 'get_intrinsic_aspect_ratio', lambda _media: 0):
                preview.show_file(root / 'portrait.mp4')
                until(lambda: preview.media is not None and preview.media.is_prepared())
                settle(80)
                assert preview.progress == 0
            preview.media.emit('invalidate-size')
            assert preview.progress == 1 and math.isclose(preview.aspect_ratio, 9 / 16, abs_tol=.002)
            preview.close()
            assert not preview.get_visible()
        finally:
            settings.set_property('gtk-enable-animations', animations)

        for path, kind in [(audio, 'media'), (invalid, 'info')]:
            preview.show_file(path)
            until(lambda: preview.kind == kind and preview.progress == 1)
            assert preview.aspect_ratio == 0
            preview.close()
            until(lambda: not preview.get_visible())
        print('PASS: delayed dimensions, cancellation, file switching, stale events, reduced motion, audio-only and decode-error fallback', flush=True)
    finally:
        clock.disconnect(observer)
        window.destroy()
