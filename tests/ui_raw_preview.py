"""RAW_PREVIEW_SAMPLES=/path/to/valid/raws PYTHONPATH=. python tests/ui_raw_preview.py.

Uses existing RAW samples read-only and isolated preferences. Set
RAW_PREVIEW_SCREENSHOTS to capture the native preview without desktop overlays.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.image_preview import ZoomImage
from omarchy_file_picker.raw_preview import RawPreviewCancelled, is_raw_image
from gi.repository import Gdk, GLib, Gtk

GLib.set_application_name('Omarchy RAW Preview QA')


def settle(ms=25):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'RAW preview GTK condition timed out'


def capture(window, name):
    directory = os.environ.get('RAW_PREVIEW_SCREENSHOTS')
    if not directory:
        return
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    for _ in range(20):
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
        node = snapshot.to_node()
        if node:
            window.get_renderer().render_texture(node, None).save_to_png(str(output / f'{name}.png'))
            return
        settle()
    raise AssertionError('RAW preview was not drawable')


sample_root = Path(os.environ['RAW_PREVIEW_SAMPLES']).expanduser().absolute()
samples = sorted(path for path in sample_root.iterdir() if path.is_file() and is_raw_image(path))
assert samples, 'Provide at least one supported camera RAW sample'
checksums = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in samples}

with tempfile.TemporaryDirectory(prefix='raw-preview-ui-') as temporary, \
        patch.object(Path, 'home', return_value=Path(temporary)):
    root = Path(temporary)
    folder = root / 'RAW photos'
    folder.mkdir()
    paths = []
    for sample in samples:
        path = folder / sample.name
        path.symlink_to(sample)
        paths.append(path)
    portrait = None
    if shutil.which('exiftool'):
        original = next((p for p in samples if p.suffix.lower() == '.cr3'), None)
        if original:
            portrait = folder / 'Portrait.CR3'
            shutil.copyfile(original, portrait)
            subprocess.run(['exiftool', '-overwrite_original', '-n', '-Orientation=6', str(portrait)],
                           check=True, stdout=subprocess.DEVNULL, timeout=10)
            paths.append(portrait)
    request = PickerRequest(current_folder=folder, explorer=True, title='RAW preview verification')
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    until(window.get_mapped)
    if shutil.which('hyprctl'):
        def native_window():
            clients = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
            return next((c for c in clients if c['pid'] == os.getpid()
                         and c['class'] == 'org.omarchy.FilePicker'), None)
        until(lambda: native_window() is not None)
        client = native_window()
        selector = json.dumps('address:' + client['address'])
        if not client['floating']:
            subprocess.run(['hyprctl', 'dispatch',
                            'hl.dsp.window.float({action="toggle",window=' + selector + '})'],
                           check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['hyprctl', 'dispatch',
                        'hl.dsp.window.resize({x=1200,y=820,relative=false,window=' + selector + '})'],
                       check=True, stdout=subprocess.DEVNULL)
        until(lambda: (window.get_width(), window.get_height()) == (1200, 820))
    settle(250)
    preview = window.quicklook
    beats = [0]
    def heartbeat():
        beats[0] += 1
        return True
    timer = GLib.timeout_add(10, heartbeat)
    def key(value):
        return window._on_preview_key(None, value, 0, Gdk.ModifierType(0))
    try:
        baseline = window.get_width(), window.get_height()
        for index, path in enumerate(paths):
            window.flow.unselect_all()
            window.flow.select_child(window.children_by_path[path])
            window.children_by_path[path].grab_focus()
            before = beats[0]
            assert key(Gdk.KEY_space) == Gdk.EVENT_STOP
            until(lambda: preview.kind != 'loading' and preview.progress == 1)
            assert preview.kind == 'image', (path.name, preview.kind)
            assert beats[0] > before, 'Decoding blocked GTK'
            view = preview.content.get_first_child()
            assert isinstance(view, ZoomImage)
            until(lambda: view.get_width() > 0)
            assert view.texture.get_width() <= 1800 and view.texture.get_height() <= 1400
            assert (window.get_width(), window.get_height()) == baseline
            assert view.zoom == 1
            view.scroll.emit('scroll', 0.0, -2.0)
            assert view.zoom > 1
            view.click.emit('pressed', 2, 10.0, 10.0)
            assert view.zoom == 1
            if path == portrait:
                assert preview.aspect_ratio < 1, 'EXIF orientation was lost'
                capture(window, 'portrait')
            elif index == 0 or path.suffix.lower() in ('.cr3', '.x3f'):
                capture(window, path.suffix.lower()[1:])
            assert key(Gdk.KEY_Escape) == Gdk.EVENT_STOP
            until(lambda: not preview.get_visible())
            assert window._selected_paths() == [path]
            print('PASS:', path.name, 'Space preview, zoom/fit, geometry, close', flush=True)

        ordered = [path for path in window.entries if path.is_file()]
        if len(ordered) > 1:
            preview.show_file(ordered[0])
            until(lambda: preview.kind == 'image')
            assert key(Gdk.KEY_Right) == Gdk.EVENT_STOP
            until(lambda: preview.path == ordered[1] and preview.kind == 'image')
            preview.close()
            until(lambda: not preview.get_visible())

        # The UI must pass its current generation to the cancellable decoder.
        for action in ('close', 'next'):
            started, stopped = threading.Event(), threading.Event()
            def delayed(_path, *, cancelled):
                started.set()
                while not cancelled():
                    time.sleep(.01)
                stopped.set()
                raise RawPreviewCancelled()
            with patch('omarchy_file_picker.quicklook.read_raw_preview', side_effect=delayed):
                preview.show_file(ordered[0])
                until(started.is_set)
                if action == 'next' and len(ordered) > 1:
                    key(Gdk.KEY_Right)
                else:
                    key(Gdk.KEY_Escape)
                until(stopped.is_set)
                preview.close()
                until(lambda: not preview.get_visible())
            settle()
            assert not preview.get_visible()
        assert all(hashlib.sha256(p.read_bytes()).hexdigest() == value for p, value in checksums.items())
        assert not list(folder.glob('*.pp3')) and not list(folder.glob('*.xmp'))
        print('PASS: arrow browsing, cancellation on close/next, original checksums and no sidecars', flush=True)
    finally:
        GLib.source_remove(timer)
        window.destroy()
