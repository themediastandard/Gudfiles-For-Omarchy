"""Real arrow navigation must keep an open portrait preview stable while loading.

Run on a disposable Xvfb display with POINTER_QA_ISOLATED=1 and GDK_BACKEND=x11.
All media are generated fixtures; no user files or audio settings are changed.
"""
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch

import gi
gi.require_version('Gdk', '4.0')
gi.require_version('GdkX11', '4.0')
gi.require_version('Gsk', '4.0')
from omarchy_file_picker import quicklook
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from gi.repository import GdkPixbuf, GdkX11, Gio, GLib, Gtk

GLib.set_application_name('Gudfiles Preview Navigation QA')
assert os.environ.get('POINTER_QA_ISOLATED') == '1', 'Use a disposable Xvfb display.'


def settle(ms=20):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Preview navigation condition timed out'


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', *args],
                   check=True, timeout=20)


def capture(window, name):
    if directory := os.environ.get('NAVIGATION_PREVIEW_SCREENSHOTS'):
        output = Path(directory)
        output.mkdir(parents=True, exist_ok=True)
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
        window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(str(output / f'{name}.png'))


with tempfile.TemporaryDirectory(prefix='gudfiles-preview-navigation-') as directory, \
        patch.object(Path, 'home', return_value=Path(directory)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]):
    root = Path(directory)
    for name, width, height in [('01-portrait', 180, 320), ('02-portrait', 180, 320),
                                ('05-landscape', 320, 180)]:
        pixels = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
        pixels.fill(0x4679cfff)
        pixels.savev(str(root / f'{name}.png'), 'png', [], [])
    for name in ('03-portrait', '04-portrait'):
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=180x320:rate=24',
               '-t', '4', '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2',
               str(root / f'{name}.mp4'))
    (root / '06-notes.txt').write_text('Preview navigation fixture\n')
    (root / '07-invalid.mp4').write_bytes(b'not a video')
    ffmpeg('-f', 'lavfi', '-i', 'anullsrc=r=8000:cl=mono', '-t', '0.5', '-c:a', 'aac',
           str(root / '08-audio-only.mp4'))

    request = PickerRequest(current_folder=root, explorer=True, title='Preview navigation QA')
    app = PickerApplication(request, None)
    app.register(None)
    with patch('omarchy_file_picker.picker.thumbnail_file', return_value=None):
        window = PickerWindow(app, request, None)
    window.present()
    until(window.get_mapped)
    window._set_view('columns')
    settle(100)
    preview = window.quicklook
    xid = window.get_surface().get_xid()

    def send(key):
        subprocess.run([os.environ.get('XDOTOOL', 'xdotool'), 'key', key], check=True)
        settle(50)

    subprocess.run([os.environ.get('XDOTOOL', 'xdotool'), 'windowfocus', str(xid)], check=True)
    frames = []
    def painted(_clock):
        if preview.get_visible():
            frames.append((preview.aspect_ratio, preview.rect, preview.progress))
    clock = window.get_frame_clock()
    observer = clock.connect('after-paint', painted)
    original_read = quicklook.read_preview
    try:
        gate = threading.Event()
        def initial_read(path, **kwargs):
            assert gate.wait(3)
            return original_read(path, **kwargs)
        with patch.object(quicklook, 'read_preview', initial_read):
            try:
                preview.show_file(root / '01-portrait.png')
                settle(280)
                assert frames and all(f[2] == 0 for f in frames)
            finally:
                gate.set()
            frames.clear()
            until(lambda: preview.kind == 'image' and preview.progress == 1)
        settle(80)
        portrait_rect = preview.rect
        assert all(math.isclose(f[0], 9 / 16, abs_tol=.002) and f[1] == portrait_rect
                   for f in frames if f[2] > 0), frames
        geometry = (window.get_width(), window.get_height(), window.browser_stack.get_height())

        def assert_portrait_frames(name):
            assert frames, name
            assert all(math.isclose(f[0], 9 / 16, abs_tol=.002) and
                       f[1] == portrait_rect and f[2] == 1 for f in frames), (name, frames)
            assert (window.get_width(), window.get_height(), window.browser_stack.get_height()) == geometry

        for name, kind in [('02-portrait.png', 'image'), ('03-portrait.mp4', 'media'),
                           ('04-portrait.mp4', 'media')]:
            gate = threading.Event()
            def delayed_read(path, **kwargs):
                assert gate.wait(3)
                return original_read(path, **kwargs)
            frames.clear()
            with patch.object(quicklook, 'read_preview', delayed_read):
                try:
                    send('Down')
                    assert preview.path == root / name
                    settle(280)
                    assert_portrait_frames(name + ' loading')
                    capture(window, name + '-loading')
                finally:
                    gate.set()
                until(lambda: preview.kind == kind and preview.progress == 1 and
                      (kind != 'media' or preview.media.is_prepared()))
                settle(100)
            assert_portrait_frames(name)
            capture(window, name)
            print('PASS:', name, 'portrait card stays fully open at identical bounds in every navigation frame', flush=True)

        # Prepared state can precede valid decoder dimensions. The existing
        # portrait card stays put until the next video's dimensions arrive.
        frames.clear()
        with patch.object(Gtk.MediaStream, 'get_intrinsic_aspect_ratio', lambda _media: 0):
            send('Up')
            until(lambda: preview.media is not None and preview.media.is_prepared())
            settle(280)
            assert_portrait_frames('delayed dimensions')
        preview.media.emit('invalidate-size')
        settle(100)
        assert_portrait_frames('resolved dimensions')

        # A late read and stale decoder signal must not replace the current file.
        stale = preview.media
        gate = threading.Event()
        frames.clear()
        def delayed_image(path, **kwargs):
            if path.name == '02-portrait.png':
                assert gate.wait(3)
            return original_read(path, **kwargs)
        with patch.object(quicklook, 'read_preview', delayed_image):
            try:
                send('Up')
                send('Up')
                until(lambda: preview.path.name == '01-portrait.png' and preview.kind == 'image')
                current_picture = preview.content.get_first_child()
            finally:
                gate.set()
            stale.emit('invalidate-size')
            settle(150)
        assert preview.path.name == '01-portrait.png' and preview.kind == 'image'
        assert preview.content.get_first_child() is current_picture
        assert_portrait_frames('rapid arrows and stale callbacks')

        settings = preview.get_settings()
        animations = settings.get_property('gtk-enable-animations')
        settings.set_property('gtk-enable-animations', False)
        try:
            frames.clear()
            for name in ('02-portrait.png', '03-portrait.mp4', '04-portrait.mp4'):
                send('Down')
                until(lambda: preview.path.name == name and preview.kind != 'loading' and
                      (preview.media is None or preview.media.is_prepared()))
            assert_portrait_frames('reduced motion')
        finally:
            settings.set_property('gtk-enable-animations', animations)

        # Once the requested content is ready, landscape and generic previews
        # still adopt their own geometry, with no replay of the opening zoom.
        for name, kind, ratio in [('05-landscape.png', 'image', 16 / 9),
                                  ('06-notes.txt', 'text', 0),
                                  ('07-invalid.mp4', 'info', 0),
                                  ('08-audio-only.mp4', 'media', 0)]:
            preview.show_file(root / '01-portrait.png')
            until(lambda: preview.kind == 'image' and math.isclose(preview.aspect_ratio, 9 / 16, abs_tol=.002))
            preview.show_file(root / name)
            until(lambda: preview.kind == kind and math.isclose(preview.aspect_ratio, ratio, abs_tol=.002)
                  and preview.progress == 1)
            settle(80)
            assert (window.get_width(), window.get_height(), window.browser_stack.get_height()) == geometry
        send('Escape')
        until(lambda: not preview.get_visible())
        assert preview.aspect_ratio == 0 and preview.media is None
        assert window.preview_overlay.get_child().get_sensitive()

        # Closing during an in-place load must also cancel its late result.
        preview.show_file(root / '01-portrait.png')
        until(lambda: preview.kind == 'image' and preview.progress == 1)
        gate = threading.Event()
        with patch.object(quicklook, 'read_preview', initial_read):
            try:
                send('Down')
                send('Escape')
                until(lambda: not preview.get_visible())
            finally:
                gate.set()
            settle(150)
        assert not preview.get_visible() and preview.media is None and preview.aspect_ratio == 0
        assert window.preview_overlay.get_child().get_sensitive()
        print('PASS: image opening, delayed dimensions, rapid arrows, stale callbacks, reduced motion, landscape/text/error/audio transitions and close', flush=True)
    finally:
        clock.disconnect(observer)
        if preview.get_visible():
            preview.close()
            until(lambda: not preview.get_visible())
        window.destroy()
