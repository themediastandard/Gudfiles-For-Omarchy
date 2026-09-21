"""Grid size and selection totals through native widgets on isolated X11."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GdkX11', '4.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, GdkX11, Gio, GLib, Gtk
from omarchy_file_picker.model import PickerRequest, format_size
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.selection_summary import selection_totals
from omarchy_file_picker.thumbnail_widgets import SCHEDULER, Thumbnail
from omarchy_file_picker.theme import load_colors
from tests.test_theme import LIGHT_PALETTES

assert os.environ.get('POINTER_QA_ISOLATED') == '1'
errors = []
def exception(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = exception


def settle(ms=80):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()
    assert not errors
    assert SCHEDULER.running <= 2


def until(predicate):
    deadline = time.monotonic() + 15
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate()


def send(*args):
    subprocess.run([os.environ['XDOTOOL'], *map(str, args)], check=True)
    settle(240)


with tempfile.TemporaryDirectory(prefix='gudfiles-status-') as temp:
    root = Path(temp)
    folder = root / 'Files'; folder.mkdir()
    a, b = folder / 'A.txt', folder / 'B.txt'
    a.write_bytes(b'a' * 1024); b.write_bytes(b'b' * 2048)
    subfolder = folder / 'Folder'; subfolder.mkdir()
    pixels = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 600, 400)
    pixels.fill(0x4477aaff)
    photo = root / 'photo.png'; pixels.savev(str(photo), 'png', [], [])
    for i in range(100):
        (folder / f'Photo-{i:03}.png').symlink_to(photo)
    app = PickerApplication(PickerRequest(current_folder=folder), None)
    app.register(None)
    for mode in ('browser', 'open', 'save'):
        for theme, palette in [('active', load_colors()), ('light', LIGHT_PALETTES['latte'])]:
            print('Checking view status:', mode, theme, flush=True)
            with patch.object(Path, 'home', return_value=root / (mode + theme)), \
                 patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
                 patch('omarchy_file_picker.picker.load_colors', return_value=palette):
                request = PickerRequest(current_folder=folder, explorer=mode == 'browser', multiple=True,
                                        mode='save' if mode == 'save' else 'open')
                window = PickerWindow(app, request, None)
                window.set_default_size(1000, 700)
                window.present(); settle()
                status = window.view_status
                try:
                    assert status.get_mapped() and status.scale.get_sensitive()
                    assert status.summary.get_text() == ''
                    window.flow.select_child(window.children_by_path[a])
                    window.flow.select_child(window.children_by_path[b])
                    until(lambda: status.summary.get_text() == '2 files · ' + format_size(3072))
                    original_children = dict(window.children_by_path)
                    send('windowfocus', window.get_surface().get_xid())
                    status.scale.grab_focus()
                    send('key', 'End')
                    assert status.scale.get_value() == 312
                    assert window._selected_paths() == [a, b]
                    assert window.children_by_path == original_children
                    item = window.children_by_path[a].get_child()
                    assert item._grid_size_parts[0].get_size_request() == (312, 196)
                    send('key', 'Home')
                    assert item._grid_size_parts[0].get_size_request() == (96, 60)
                    # Actual grid allocations get denser, without replacing rows.
                    assert item.get_width() < 150, item.get_width()
                    # Drag the actual thumb, then restore the minimum by key.
                    geometry = subprocess.check_output([os.environ['XDOTOOL'], 'getwindowgeometry',
                        '--shell', str(window.get_surface().get_xid())], text=True)
                    origin = dict(line.split('=', 1) for line in geometry.splitlines())
                    _, bounds = status.scale.compute_bounds(window)
                    dx, dy = window.get_surface_transform()
                    x = round(int(origin['X']) + dx + bounds.get_x() + 5)
                    y = round(int(origin['Y']) + dy + bounds.get_y() + bounds.get_height()/2)
                    send('mousemove', x, y)
                    send('mousedown', 1)
                    send('mousemove', x + 65, y)
                    send('mouseup', 1)
                    assert status.scale.get_value() > 156, status.scale.get_value()
                    assert window._selected_paths() == [a, b]
                    send('key', 'Home')
                    assert status.get_height() <= 32, status.get_height()
                    _, text_bounds = status.summary.compute_bounds(status)
                    assert abs(text_bounds.get_x() + text_bounds.get_width()/2 - status.get_width()/2) <= 2
                    until(lambda: any(w.loaded for w in SCHEDULER.widgets if w.width == 96))
                    assert json.loads(window.preferences_path.read_text())['thumbnail_size'] == 96
                    for view in ('list', 'columns', 'grid'):
                        window._set_view(view); settle()
                        assert status.scale.get_sensitive() == (view == 'grid')
                        until(lambda: status.summary.get_text() == '2 files · ' + format_size(3072))
                    assert window.children_by_path[a].get_child()._grid_size_parts[0].get_size_request() == (96, 60)
                    window.flow.unselect_all(); settle()
                    assert status.summary.get_text() == ''
                    window.flow.select_child(window.children_by_path[subfolder])
                    until(lambda: status.summary.get_text() == '1 folder')
                    window.flow.select_child(window.children_by_path[a])
                    until(lambda: status.summary.get_text() == '1 file, 1 folder · ' + format_size(1024) + ' in files')
                    # A delayed old selection cannot replace a newer selection.
                    started, release = threading.Event(), threading.Event()
                    def delayed(paths, **kwargs):
                        started.set(); release.wait(3)
                        return selection_totals(paths, **kwargs)
                    with patch('omarchy_file_picker.view_status.selection_totals', side_effect=delayed):
                        status.update([a])
                        until(started.is_set)
                        status.update([b])
                        release.set()
                        until(lambda: status.summary.get_text() == '1 file · ' + format_size(2048))
                    status.update([folder / 'Missing.txt'])
                    until(lambda: status.summary.get_text() == '1 file · Size unavailable')
                    status.update([])
                    assert status.summary.get_text() == ''
                    # Saved size is picked up by a fresh window.
                    restored = PickerWindow(app, request, None)
                    restored.present(); settle()
                    assert restored.view_status.scale.get_value() == 96
                    restored.destroy(); settle()
                    if directory := os.environ.get('VIEW_STATUS_SCREENSHOTS'):
                        window.flow.unselect_all()
                        window.flow.select_child(window.children_by_path[a])
                        window.flow.select_child(window.children_by_path[b])
                        until(lambda: status.summary.get_text().startswith('2 files'))
                        snapshot = Gtk.Snapshot.new()
                        Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                        Path(directory).mkdir(parents=True, exist_ok=True)
                        window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(
                            str(Path(directory) / f'{mode}-{theme}.png'))
                finally:
                    window.destroy()
                    until(lambda: not SCHEDULER.running and not SCHEDULER.widgets)
    print('PASS: pointer/keyboard slider, real tile dimensions, selection/native-row preservation, bounded decoding, view sensitivity, persistence, centered totals, missing files and stale-reply cancellation')
