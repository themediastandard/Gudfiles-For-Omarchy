"""Saved annotations, column order, real header dragging/keys and app font.
Run on an isolated Xvfb display with POINTER_QA_ISOLATED=1 and GDK_BACKEND=x11.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkX11', '4.0')
from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors
from tests.test_theme import LIGHT_PALETTES

assert os.environ.get('POINTER_QA_ISOLATED') == '1', 'Use a disposable Xvfb display.'
errors = []
def exception(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = exception


def settle(ms=200):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()
    assert not errors


def send(*args):
    subprocess.run([os.environ.get('XDOTOOL', 'xdotool'), *map(str, args)], check=True)
    settle(80)


def point(widget, fraction=.5):
    native = widget.get_native()
    geometry = subprocess.check_output([os.environ.get('XDOTOOL', 'xdotool'),
        'getwindowgeometry', '--shell', str(native.get_surface().get_xid())], text=True)
    origin = dict(line.split('=', 1) for line in geometry.splitlines())
    valid, bounds = widget.compute_bounds(native)
    assert valid
    dx, dy = native.get_surface_transform()
    return (int(origin['X']) + dx + bounds.get_x() + bounds.get_width() * fraction,
            int(origin['Y']) + dy + bounds.get_y() + bounds.get_height() / 2)


def drag(source, target, fraction=.8, *, movable=True):
    window = source.get_root()
    details = window.list_details
    saved = list(details.columns())
    start, end = point(source), point(target, fraction)
    send('mousemove', *map(round, start))
    send('mousedown', 1)
    for step in range(1, 13):
        send('mousemove', *(round(a + (b-a)*step/12) for a, b in zip(start, end)))
    assert details.columns() == saved, 'Preview wrote preferences before drop'
    if movable:
        assert details.drag_ghost.get_visible()
        assert details.display_columns != saved, 'Columns did not preview their new positions'
        assert details.display_columns[0] == 'name'
        assert any(cell.has_css_class('column-drag-slot') for _, cell in details._column_cells())
        capture(window, 'drag-' + window.colors['mode'])
    else:
        assert not details.drag_ghost.get_visible()
        assert details.display_columns == saved
    send('mouseup', 1)
    settle(350)
    assert not details.drag_ghost.get_visible()



def capture(window, name):
    if directory := os.environ.get('RATING_QA_SCREENSHOTS'):
        Path(directory).mkdir(parents=True, exist_ok=True)
        window.queue_draw()
        settle()
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
        window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(str(Path(directory) / f'{name}.png'))


with tempfile.TemporaryDirectory(prefix='gudfiles-ratings-') as temp:
    root = Path(temp)
    files = root / 'Files'
    files.mkdir()
    a, b, empty = [files / name for name in ['A shot.txt', 'B shot.txt', 'Unrated.txt']]
    for path in [a, b, empty]:
        path.write_text('Preview fixture')
    folder = files / 'Folder'
    folder.mkdir()
    app = PickerApplication(PickerRequest(current_folder=files), None)
    app.register(None)
    active = load_colors()
    dark = {**active, 'mode': 'dark', 'background': '#17191f', 'foreground': '#d7dce4',
            'bright_foreground': '#ffffff', 'light_foreground': '#b3bdcf',
            'dark_foreground': '#9ba5b5', 'accent': '#86a6f4'}
    for name, colors in [('active', active), ('light', LIGHT_PALETTES['latte']), ('dark', dark)]:
        print('Checking rating columns:', name, flush=True)
        with patch.object(Path, 'home', return_value=root / name), \
             patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
             patch('omarchy_file_picker.picker.load_colors', return_value=colors):
            request = PickerRequest(current_folder=files, explorer=True, multiple=True)
            window = PickerWindow(app, request, None)
            window.set_default_size(1200, 700)
            window._set_view('list')
            window.present()
            settle()
            details = window.list_details
            try:
                assert 'rating' in details.columns()
                details.set_columns(['name', 'rating', 'color', 'rejected', 'size'])
                window._apply_annotation([a], stars=2, color='red')
                window._apply_annotation([b], stars=5, color='blue', rejected=True)
                settle()
                assert details.rows[a]['rating'].get_text() == '★★'
                assert details.rows[b]['rating'].get_text() == '★★★★★'
                assert details.rows[b]['color'].get_text() == '● Blue'
                assert details.rows[b]['color'].has_css_class('label-blue')
                assert details.rows[b]['rejected'].get_text() == 'Yes'
                assert details.rows[empty]['rating'].get_text() == '—'
                assert not window.rating_badges[a].get_visible()
                # Later filesystem metadata must not replace saved annotations.
                details.ready(a, {'size': 10, '_media': True}, True)
                assert details.rows[a]['rating'].get_text() == '★★'
                with patch.object(window.ratings, 'set_many', side_effect=sqlite3.OperationalError('fixture error')), \
                     patch.object(window, '_show_error') as failed:
                    window._apply_annotation([a], stars=4)
                    assert failed.called
                assert details.rows[a]['rating'].get_text() == '★★'
                window.flow.select_child(window.children_by_path[a])
                details.buttons['rating'].emit('clicked')
                settle()
                assert window.entries == [folder, b, a, empty], window.entries
                window._apply_annotation([b], stars=1)
                settle()
                assert window.entries == [folder, a, b, empty]
                assert window._selected_paths() == [a]
                # The real drop must reorder headings and cells without sorting.
                sort = window.file_preferences['sort_key'], window.file_preferences['descending']
                send('windowfocus', window.get_surface().get_xid())
                drag(details.buttons['rating'], details.buttons['size'])
                expected = ['name', 'color', 'rejected', 'size', 'rating']
                assert details.columns() == expected, details.columns()
                assert (window.file_preferences['sort_key'], window.file_preferences['descending']) == sort
                assert window._selected_paths() == [a]
                assert details.dragged_column is None
                assert details.drag_timer == 0
                # Escape cancels an actual drag without changing order or sort.
                details.header_scroll.get_hadjustment().set_value(0)
                settle()
                start = point(details.buttons['color'])
                send('mousemove', *map(round, start))
                send('mousedown', 1)
                for offset in (10, 20, 40, 60):
                    send('mousemove', round(start[0] + offset), round(start[1]))
                assert details.dragged_column == 'color'
                send('key', 'Escape')
                send('mouseup', 1)
                assert details.columns() == expected
                assert details.dragged_column is None and details.drag_timer == 0
                assert details.display_columns == expected
                assert not any(cell.has_css_class('column-drag-slot') for _, cell in details._column_cells())
                # Dropping outside cancels the visible preview and its pending save.
                start, end = point(details.buttons['color']), point(details.buttons['rating'])
                send('mousemove', *map(round, start))
                send('mousedown', 1)
                send('mousemove', *map(round, end))
                assert details.display_columns != expected
                send('mousemove', round(end[0]), round(end[1] + 80))
                send('mouseup', 1)
                settle()
                assert details.display_columns == expected and details.columns() == expected
                assert not details.drag_ghost.get_visible()
                # Name cannot move by mouse, keyboard, or an API reorder.
                drag(details.buttons['name'], details.buttons['size'], movable=False)
                details.buttons['name'].grab_focus()
                send('key', 'alt+Right')
                details.move_column('name', 'size', True)
                settle()
                assert details.columns() == expected
                # Other headings move by key, stopping immediately after Name.
                details.buttons['rejected'].grab_focus()
                send('key', 'alt+Left')
                expected = ['name', 'rejected', 'color', 'size', 'rating']
                assert details.columns() == expected, details.columns()
                send('key', 'alt+Left')
                assert details.columns() == expected
                assert window.get_focus() is details.buttons['rejected']
                saved = json.loads(window.preferences_path.read_text())
                assert saved['list_columns'] == expected
                # Confirm the UI uses Noto Sans, including rating columns.
                label = details.rows[a]['rating']
                context = label.get_pango_context()
                font = context.get_font_map().load_font(context, context.get_font_description())
                family = font.describe().get_family()
                aliases = subprocess.check_output(['fc-match', 'Noto Sans', '-f', '%{family}'], text=True).split(',')
                assert family in aliases, (family, aliases)
                for width in (820, 1200):
                    window.set_default_size(width, 700)
                    settle()
                    row = window.children_by_path[a].get_child()
                    cell = row.get_first_child()
                    for key in details.columns():
                        _, bounds = cell.compute_bounds(window)
                        _, head = details.buttons[key].compute_bounds(window)
                        assert abs(bounds.get_x() - head.get_x()) <= 1
                        assert abs(bounds.get_width() - head.get_width()) <= 1
                        cell = cell.get_next_sibling()
                    capture(window, f'{name}-{width}')
                restored = PickerWindow(app, request, None)
                restored.present()
                settle()
                assert restored.list_details.columns() == expected
                assert restored.file_preferences['sort_key'] == 'rating'
                assert restored.list_details.rows[a]['rating'].get_text() == '★★'
                restored.destroy()
                settle()
                # Clearing an annotation refreshes every displayed owner.
                window._apply_annotation([a], stars=0, color='', rejected=False)
                settle()
                assert details.rows[a]['rating'].get_text() == '—'
                assert details.rows[a]['color'].get_text() == '—'
                assert not details.rows[a]['color'].has_css_class('label-red')
                assert window.entries == [folder, b, a, empty]
                # Overflowing headings remain reachable during a drag and by key.
                long_order = ['name', 'rating', 'size', 'modified', 'resolution', 'fps', 'codec']
                details.set_columns(long_order)
                window.set_default_size(820, 700)
                settle()
                adjustment = details.header_scroll.get_hadjustment()
                adjustment.set_value(0)
                settle()
                start = point(details.buttons['rating'])
                _, viewport = details.header_scroll.compute_bounds(window)
                dx, dy = window.get_surface_transform()
                send('mousemove', *map(round, start))
                send('mousedown', 1)
                for offset in (10, 20, 40):
                    send('mousemove', round(start[0] + offset), round(start[1]))
                send('mousemove', '--window', window.get_surface().get_xid(),
                     round(viewport.get_x() + viewport.get_width() - 8 + dx),
                     round(viewport.get_y() + viewport.get_height()/2 + dy))
                settle(1000)
                assert adjustment.get_value() > 20, (adjustment.get_value(), details.dragged_column, details.drag_scroll)
                send('key', 'Escape')
                send('mouseup', 1)
                assert details.columns() == long_order
                adjustment.set_value(0)
                details.buttons['rating'].grab_focus()
                for _ in range(len(long_order) - 1):
                    send('key', 'alt+Right')
                settle()
                assert details.columns() == ['name'] + long_order[2:] + ['rating']
                _, focused = details.buttons['rating'].compute_bounds(details.header_scroll)
                assert focused.get_x() >= -1
                assert focused.get_x() + focused.get_width() <= details.header_scroll.get_width() + 1
            finally:
                window.destroy()
                settle()
    print('PASS: persisted/live/failed ratings, annotation sorting, live column preview, pinned Name, real column drag, keyboard reorder, saved positions, alignment and Noto Sans in active/light/dark themes')
