"""Native list heading alignment, customization, numeric media sorting and lazy work.
PYTHONPATH=. LIST_QA_SCREENSHOTS=/tmp/gudfiles-list python tests/ui_list_details.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.list_metadata import COLUMNS, DEFAULT_COLUMNS
from omarchy_file_picker.theme import load_colors
from tests.test_theme import LIGHT_PALETTES
from gi.repository import Gdk, GLib, Gtk

errors = []
def exception(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = exception


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(160, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 12
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Timed out waiting for metadata'
    assert not errors


def children(widget):
    child = widget.get_first_child()
    while child:
        yield child
        child = child.get_next_sibling()


def capture(window, name):
    directory = os.environ.get('LIST_QA_SCREENSHOTS')
    if directory:
        window.queue_draw()
        settle()
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
        node = snapshot.to_node()
        assert node
        Path(directory).mkdir(parents=True, exist_ok=True)
        window.get_native().get_renderer().render_texture(node, None).save_to_png(str(Path(directory) / (name + '.png')))


with tempfile.TemporaryDirectory(prefix='gudfiles-list-') as temp:
    root = Path(temp)
    folder = root / 'Footage'
    folder.mkdir()
    high, low = [folder / name for name in ('A-fast.mp4', 'Z-large.mp4')]
    for path, size, fps in ((high, '160x96', 60), (low, '320x180', 24)):
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        f'color=size={size}:rate={fps}', '-t', '1', '-c:v', 'libx264',
                        '-threads', '1', str(path)], check=True, timeout=15)
    for i in range(80):
        (folder / f'Notes-{i:03}.txt').write_text('fixture')
    app = PickerApplication(PickerRequest(current_folder=folder), None)
    app.register(None)
    dark = {**load_colors(), 'background': '#17191f', 'foreground': '#d7dce4',
            'bright_foreground': '#ffffff', 'accent': '#86a6f4'}
    for theme, palette in [('active', load_colors()), ('light', next(iter(LIGHT_PALETTES.values()))), ('dark', dark)]:
        with patch.object(Path, 'home', return_value=root / theme), \
                patch('omarchy_file_picker.picker.load_colors', return_value=palette):
            window = PickerWindow(app, PickerRequest(current_folder=folder, explorer=True, multiple=True), None)
            window._set_view('list')
            window.present()
            settle()
            details = window.list_details
            try:
                x11 = Gdk.Display.get_default().__gtype__.name == 'GdkX11Display'
                overhead = window.get_default_size()[0] - window.get_width()
                if not x11:
                    client = next(c for c in json.loads(subprocess.check_output(['hyprctl', 'clients', '-j'])) if c['pid'] == os.getpid())
                    selector = json.dumps('address:' + client['address'])
                    if not client['floating']:
                        subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' + selector + '})'], check=True, capture_output=True)
                        settle()
                def resize(width):
                    if x11:
                        window.set_default_size(width + overhead, 700)
                    else:
                        subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.resize({x=' + str(width) + ',y=700,relative=false,window=' + selector + '})'], check=True, capture_output=True)
                    settle()
                    assert window.get_width() == width
                def aligned():
                    row = window.children_by_path[high].get_child()
                    for key, cell in zip(details.columns(), children(row)):
                        _, cell_rect = cell.compute_bounds(window)
                        _, head_rect = details.buttons[key].compute_bounds(window)
                        assert abs(cell_rect.get_x() - head_rect.get_x()) <= 1, (key, cell_rect.get_x(), head_rect.get_x())
                        assert abs(cell_rect.get_width() - head_rect.get_width()) <= 1, (key, cell_rect.get_width(), head_rect.get_width())
                resize(1200)
                until(lambda: high in details.data and details.data[high].get('_media'))
                assert details.rows[high]['fps'].get_text() == '60'
                assert len(details.data) < 40, len(details.data)
                aligned()
                _, pinned = details.header.compute_bounds(window)
                vertical = window.standard_scroller.get_vadjustment()
                vertical.set_value(500)
                settle()
                _, after = details.header.compute_bounds(window)
                assert after.get_y() == pinned.get_y()
                vertical.set_value(0)
                window.flow.select_child(window.children_by_path[high])
                for key, first in [('fps', high), ('resolution', low)]:
                    details.buttons[key].emit('clicked')
                    assert details.status.get_visible()
                    until(lambda: details.applied)
                    assert window.entries[0] == first, (key, window.entries[:3])
                    assert [c._picker_path for c in children(window.flow)] == window.entries
                    assert window._selected_paths() == [high]
                    assert not details.status.get_visible()
                    details.buttons[key].emit('clicked')
                    until(lambda: details.applied)
                    assert window.entries[0] != first
                    assert window.entries[2].suffix == '.txt', window.entries[:3]
                details.buttons['name'].emit('clicked')
                settle()
                controllers = details.header.observe_controllers()
                gesture = next(controllers.get_item(i) for i in range(controllers.get_n_items())
                               if isinstance(controllers.get_item(i), Gtk.GestureClick))
                gesture.emit('pressed', 1, 50., 10.)
                settle()
                checks = {c.get_label(): c for c in children(details.popover.get_child()) if isinstance(c, Gtk.CheckButton)}
                assert not checks['Name'].get_sensitive()
                assert details.popover.get_mapped()
                capture(details.popover, theme + '-menu')
                checks['Date Created'].set_active(True)
                settle()
                assert 'created' in details.buttons
                details.set_columns(list(COLUMNS))
                settle()
                for width in (820, 1200):
                    resize(width)
                    aligned()
                    horizontal = window.standard_scroller.get_hadjustment()
                    horizontal.set_value(horizontal.get_upper() - horizontal.get_page_size())
                    settle()
                    aligned()
                    assert details.buttons['codec'].get_mapped()
                    capture(window, f'{theme}-{width}-all')
                    horizontal.set_value(0)
                assert details.menu_key(None, Gdk.KEY_F10, 0, Gdk.ModifierType.SHIFT_MASK)
                reset = next(c for c in children(details.popover.get_child()) if isinstance(c, Gtk.Button))
                reset.emit('clicked')
                until(lambda: high in details.data)
                capture(window, theme)
                saved = json.loads(window.preferences_path.read_text())
                assert saved['list_columns'] == DEFAULT_COLUMNS
                restored = PickerWindow(app, PickerRequest(current_folder=folder), None)
                restored.present()
                settle()
                assert restored.list_details.columns() == DEFAULT_COLUMNS
                restored.destroy()
                settle()
                window._set_view('grid')
                settle()
                assert not details.widget.get_visible()
                window._set_view('list')
                settle()
                assert details.widget.get_mapped()
                assert not errors
            finally:
                window.destroy()
                settle()
    print('PASS: native pinned/aligned headings, horizontal scrolling, right-click/keyboard menu, saved customization, numeric real-media sorting, selection and lazy metadata in active/light/dark themes')
