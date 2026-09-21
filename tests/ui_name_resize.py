"""Physical Name-column resizing on an isolated Xvfb display."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GdkX11', '4.0')
from gi.repository import GdkX11, Gio, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors
from tests.test_theme import LIGHT_PALETTES

assert os.environ.get('POINTER_QA_ISOLATED') == '1'
errors = []
def exception(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = exception


def settle(ms=180):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()
    assert not errors


def send(*args):
    subprocess.run([os.environ.get('XDOTOOL', 'xdotool'), *map(str, args)], check=True)
    settle(90)


def point(widget, fraction=1):
    native = widget.get_native()
    geometry = subprocess.check_output([os.environ.get('XDOTOOL', 'xdotool'),
        'getwindowgeometry', '--shell', str(native.get_surface().get_xid())], text=True)
    origin = dict(line.split('=', 1) for line in geometry.splitlines())
    valid, bounds = widget.compute_bounds(native)
    assert valid
    dx, dy = native.get_surface_transform()
    return (round(int(origin['X']) + dx + bounds.get_x() + bounds.get_width() * fraction - 2),
            round(int(origin['Y']) + dy + bounds.get_y() + bounds.get_height() / 2))


def aligned(window):
    details = window.list_details
    row = next(iter(window.children_by_path.values())).get_child()
    cell = row.get_first_child()
    for key in details.columns():
        _, body = cell.compute_bounds(window)
        _, head = details.buttons[key].compute_bounds(window)
        assert abs(body.get_x() - head.get_x()) <= 1, key
        assert abs(body.get_width() - head.get_width()) <= 1, (key, body.get_width(), head.get_width())
        cell = cell.get_next_sibling()


with tempfile.TemporaryDirectory(prefix='gudfiles-name-resize-') as temp:
    root = Path(temp)
    folder = root / 'Files'
    folder.mkdir()
    for i in range(65):
        (folder / f'Clip-{i:03}.txt').write_text('fixture')
    longest = folder / ('Z-' + 'Wide filename Wé世 ' * 7 + '.txt')
    longest.write_text('fixture')
    app = PickerApplication(PickerRequest(current_folder=folder), None)
    app.register(None)
    for mode in ('browser', 'open', 'save', 'folder'):
        for theme, palette in [('active', load_colors()), ('light', LIGHT_PALETTES['latte'])]:
            print('Checking name resizing:', mode, theme, flush=True)
            with patch.object(Path, 'home', return_value=root / (mode + theme)), \
                 patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
                 patch('omarchy_file_picker.picker.load_colors', return_value=palette):
                request = PickerRequest(current_folder=folder, explorer=mode == 'browser',
                                        mode='save' if mode == 'save' else 'open', directory=mode == 'folder')
                window = PickerWindow(app, request, None)
                window.set_default_size(960, 640)
                window._set_view('list')
                window.present()
                settle()
                details = window.list_details
                try:
                    send('windowfocus', window.get_surface().get_xid())
                    selected = next(iter(window.children_by_path))
                    if mode != 'folder':
                        window.flow.select_child(window.children_by_path[selected])
                    selection = window._selected_paths()
                    sort = window.file_preferences['sort_key'], window.file_preferences['descending']
                    before = details.buttons['name'].get_width()
                    start = point(details.buttons['name'])
                    send('mousemove', *start)
                    send('mousedown', 1)
                    send('mousemove', start[0] + 125, start[1])
                    assert details.buttons['name'].get_width() == before + 125
                    assert window.file_preferences['list_name_width'] == 0
                    aligned(window)
                    send('mouseup', 1)
                    assert window.file_preferences['list_name_width'] == before + 125
                    # Cancel restores the previous saved width.
                    start = point(details.buttons['name'])
                    send('mousemove', *start)
                    send('mousedown', 1)
                    send('mousemove', start[0] - 60, start[1])
                    send('key', 'Escape')
                    send('mouseup', 1)
                    assert details.buttons['name'].get_width() == before + 125
                    # Auto-fit includes the longest row below the viewport.
                    send('mousemove', *point(details.buttons['name']))
                    send('click', '--repeat', 2, '--delay', 100, 1)
                    settle()
                    fitted = details.buttons['name'].get_width()
                    label, _ = details.name_labels[longest]
                    assert not label.get_layout().is_ellipsized(), (fitted, label.get_width())
                    assert fitted > before + 125, fitted
                    assert (window.file_preferences['sort_key'], window.file_preferences['descending']) == sort
                    assert window._selected_paths() == selection
                    aligned(window)
                    horizontal = window.standard_scroller.get_hadjustment()
                    horizontal.set_value(min(200, horizontal.get_upper() - horizontal.get_page_size()))
                    settle()
                    aligned(window)
                    # Resize remains accurate when horizontally scrolled.
                    horizontal.set_value(max(0, fitted - 420))
                    settle()
                    start = point(details.buttons['name'])
                    send('mousemove', *start)
                    send('mousedown', 1)
                    send('mousemove', start[0] - 80, start[1])
                    send('mouseup', 1)
                    assert details.buttons['name'].get_width() == fitted - 80
                    aligned(window)
                    horizontal.set_value(0)
                    window._set_view('grid')
                    window._set_view('list')
                    settle()
                    assert details.buttons['name'].get_width() == fitted - 80
                    assert json.loads(window.preferences_path.read_text())['list_name_width'] == fitted - 80
                    restored = PickerWindow(app, request, None)
                    restored.present()
                    settle()
                    assert restored.list_details.buttons['name'].get_width() == fitted - 80
                    restored.destroy()
                    settle()
                    if directory := os.environ.get('NAME_RESIZE_SCREENSHOTS'):
                        horizontal.set_value(0)
                        details.fit_name()
                        window.set_default_size(1800, 640)
                        settle()
                        snapshot = Gtk.Snapshot.new()
                        Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                        Path(directory).mkdir(parents=True, exist_ok=True)
                        window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(
                            str(Path(directory) / f'{mode}-{theme}.png'))
                finally:
                    window.destroy()
                    settle()
    print('PASS: real edge drag, double-click fit, Escape, scroll alignment, sort/selection and saved width in browser/Open/Save/folder modes and active/light themes')
