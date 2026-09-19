"""PYTHONPATH=. python tests/ui_thumbnails.py; optional THUMBNAIL_NEF=/path/file.NEF."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.thumbnail_widgets import Thumbnail, SCHEDULER
from gi.repository import GdkPixbuf, GLib, Gtk


def settle(ms=30):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Thumbnail condition timed out'


def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from walk(child)
        child = child.get_next_sibling()


errors = []
import sys
def report_error(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = report_error
with tempfile.TemporaryDirectory(prefix='thumbnail-ui-') as tmp, patch.object(Path, 'home', return_value=Path(tmp)):
    root = Path(tmp)
    folder = root / 'many photos'
    folder.mkdir()
    source = root / 'large.png'
    pixels = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 6000, 4000)
    pixels.fill(0x558833ff)
    pixels.savev(str(source), 'png', [], [])
    del pixels
    for index in range(1000):
        (folder / f'{index:04}.png').symlink_to(source)
    config = root / '.config/omarchy-file-picker'
    config.mkdir(parents=True)
    (config / 'preferences.json').write_text(json.dumps({'view_mode': 'list'}))
    request = PickerRequest(current_folder=folder, explorer=True, multiple=True, title='Thumbnail regression QA')
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle(200)
    started = time.monotonic()
    window._set_view('grid')
    switch_seconds = time.monotonic() - started
    assert switch_seconds < 4, switch_seconds
    beats = []
    timer = GLib.timeout_add(10, lambda: beats.append(time.monotonic()) or True)
    until(lambda: any(w.loaded for w in SCHEDULER.widgets))
    settle(1500)
    widgets = list(SCHEDULER.widgets)
    assert len(widgets) == 1000, len(widgets)
    assert SCHEDULER.running <= 2
    loaded = [w for w in widgets if w.loaded]
    assert 1 <= len(loaded) < 80, len(loaded)
    assert all(w.in_view() for w in loaded)
    assert any(isinstance(w, Gtk.Label) and w.get_text() == '6000 × 4000' for w in walk(window.flow))
    assert len(beats) > 40, len(beats)
    scroll = window.flow.get_ancestor(Gtk.ScrolledWindow)
    adjustment = scroll.get_vadjustment()
    adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
    until(lambda: all(not w.loaded for w in loaded))
    until(lambda: any(w.loaded and int(w.path.stem) > 900 for w in SCHEDULER.widgets))
    window._set_view('list')
    until(lambda: SCHEDULER.running == 0 and not SCHEDULER.widgets)
    print(f'PASS: 1000 large images; grid switch {switch_seconds:.2f}s; {len(loaded)} resident thumbnails; responsive GTK, scrolling and cancellation')

    # Slow worker replies cannot restore images after switching away.
    cancellations = []
    def slow(_path, cancelled):
        until_time = time.monotonic() + 5
        while not cancelled() and time.monotonic() < until_time:
            time.sleep(.01)
        cancellations.append(cancelled())
        return None
    with patch('omarchy_file_picker.picker.thumbnail_file', side_effect=slow):
        window._set_view('grid')
        until(lambda: SCHEDULER.running == 2)
        settle(200)
        window._set_view('columns')
        until(lambda: SCHEDULER.running == 0)
        assert cancellations == [True, True], cancellations
    window._set_view('grid')
    until(lambda: any(w.loaded for w in SCHEDULER.widgets))
    print('PASS: slow decoders cancelled on view switch; returning to grid recovers')

    sample = os.environ.get('THUMBNAIL_NEF')
    if sample:
        nef = Path(sample)
        original = hashlib.sha256(nef.read_bytes()).digest()
        raw_folder = root / 'RAW'
        raw_folder.mkdir()
        (raw_folder / 'Nikon.NEF').symlink_to(nef)
        window.navigate(raw_folder)
        until(lambda: any(w.loaded and w.path.suffix == '.NEF' for w in SCHEDULER.widgets), 30)
        window.flow.select_child(window.children_by_path[raw_folder / 'Nikon.NEF'])
        until(lambda: any(isinstance(w, Thumbnail) and w.loaded for w in walk(window.metadata)), 30)
        screenshot = os.environ.get('THUMBNAIL_SCREENSHOT')
        if screenshot:
            if window.quicklook.get_visible():
                window.quicklook.close()
                until(lambda: not window.quicklook.get_visible())
            settle(250)
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
            window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(screenshot)
        assert hashlib.sha256(nef.read_bytes()).digest() == original
        print('PASS: real Nikon NEF grid and selection-strip thumbnails; original bytes unchanged')
    broken = root / 'broken'
    broken.mkdir()
    (broken / 'bad.NEF').write_bytes(b'not a RAW file')
    window.navigate(broken)
    until(lambda: any(w.failed for w in SCHEDULER.widgets), 30)
    assert all(w.image.get_visible() and not w.loaded for w in SCHEDULER.widgets)
    window.navigate(folder)
    until(lambda: any(w.loaded for w in SCHEDULER.widgets))
    print('PASS: corrupt RAW keeps file icon; navigation recovers')
    window.destroy()
    until(lambda: SCHEDULER.running == 0 and not SCHEDULER.widgets)
    GLib.source_remove(timer)
    assert not errors, errors
