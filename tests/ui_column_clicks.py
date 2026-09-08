"""Physical scrolled-folder clicks on an explicitly isolated Xvfb display."""
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import gi
gi.require_version('GdkX11', '4.0')
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from gi.repository import Gio, GLib, Gtk, GdkX11


def settle(ms=250):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


assert os.environ.get('POINTER_QA_ISOLATED') == '1', 'Use a disposable Xvfb display.'
with tempfile.TemporaryDirectory(prefix='gudfiles-column-clicks-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]):
    root = Path(temp)
    folders = [root / f'Folder {i:02}' for i in range(70)]
    for folder in folders:
        folder.mkdir()
    branch = folders[50]
    nested = [branch / f'Nested {i:02}' for i in range(70)]
    for folder in nested:
        folder.mkdir()
    for name in ('A populated', 'B empty', 'C empty'):
        (nested[50] / name).mkdir()
    (nested[50] / 'A populated' / 'notes.txt').write_text('fixture')
    request = PickerRequest(current_folder=root, explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    xid = window.get_surface().get_xid()

    def send(*args):
        subprocess.run([os.environ['XDOTOOL'], *map(str, args)], check=True)
        settle()

    def click_row(column, path, *, button=1, double=False):
        row = column.children[path]
        valid, bounds = row.compute_bounds(column.scroller)
        assert valid
        adjustment = column.scroller.get_vadjustment()
        top = adjustment.get_value() + bounds.get_y()
        adjustment.clamp_page(top, top + bounds.get_height())
        settle(400)
        before = adjustment.get_value()
        samples = []
        handler = adjustment.connect('value-changed', lambda a: samples.append(a.get_value()))
        valid, bounds = row.compute_bounds(window)
        assert valid
        dx, dy = window.get_surface_transform()
        send('mousemove', '--window', xid, round(bounds.get_x() + 100 + dx),
             round(bounds.get_y() + bounds.get_height() / 2 + dy))
        send('click', *(['--repeat', 2, '--delay', 80] if double else []), button)
        adjustment.disconnect(handler)
        assert abs(adjustment.get_value() - before) < 2, ('scroll jumped', before, adjustment.get_value())
        assert not samples or min(samples) >= before - 2, ('transient scroll jump', before, samples)
        assert row.is_selected(), ('first click missed', path, window._selected_paths())

    def revealed(column):
        valid, bounds = column.panel.compute_bounds(window.columns)
        assert valid and bounds.get_x() >= -1
        assert bounds.get_x() + bounds.get_width() <= window.columns.get_width() + 1, (
            'new column not revealed', bounds.get_x(), bounds.get_width(), window.columns.get_width(),
            window.columns.get_hadjustment().get_value(), window.columns.get_hadjustment().get_upper(),
            window.columns.reveal_tick)

    try:
        send('windowfocus', xid)
        window._set_sort('name', False)
        window._set_view('columns')
        settle()
        baseline = window.get_width(), window.get_height()
        # Keep native focus at the top, then scroll far away before the click.
        first = window.columns.columns[0]
        first.flow.child_focus(Gtk.DirectionType.TAB_FORWARD)
        settle()
        click_row(first, branch)
        assert window.columns.columns[-1].path == branch
        before_open = first.scroller.get_vadjustment().get_value()
        click_row(first, branch, double=True)
        assert window.current_dir == branch
        first = window.columns.columns[0]
        assert abs(first.scroller.get_vadjustment().get_value() - before_open) < 2, 'folder activation reset parent scroll'
        second = next(c for c in window.columns.columns if c.path == branch)
        click_row(second, nested[50])
        third = window.columns.columns[-1]
        assert third.path == nested[50]
        revealed(third)
        click_row(third, nested[50] / 'A populated')
        revealed(window.columns.columns[-1])
        horizontal = window.columns.get_hadjustment()
        assert horizontal.get_value() > 0
        # Replacing an equally wide column need not change the adjustment's size.
        horizontal.set_value(max(0, horizontal.get_value() - 200))
        settle()
        click_row(third, nested[50] / 'B empty')
        empty = window.columns.columns[-1]
        assert empty.path.name == 'B empty' and not empty.entries and empty.empty.get_visible()
        revealed(empty)
        # A previously opened child should be revealed again after scrolling left.
        horizontal.set_value(max(0, horizontal.get_value() - 200))
        settle()
        click_row(third, nested[50] / 'B empty')
        revealed(empty)
        if screenshot := os.environ.get('COLUMN_CLICKS_QA_SCREENSHOT'):
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(window.get_child()).snapshot(snapshot, window.get_width(), window.get_height())
            window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(screenshot)
        # Right click a scrolled ancestor without moving it under the pointer.
        horizontal.set_value(0)
        settle()
        click_row(first, folders[49], button=3)
        assert window.context_popover and window.current_dir == root
        send('key', 'Escape')
        assert (window.get_width(), window.get_height()) == baseline
        print('PASS: first scrolled clicks, ancestor context clicks, populated/empty/same-child reveal, stable geometry')
    finally:
        window.destroy()
