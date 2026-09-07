"""Native chevron geometry, hit testing, wheel navigation and tooltip removal."""
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.breadcrumbs import BreadcrumbButton, TIP
from omarchy_file_picker.theme import load_colors


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(180, lambda: loop.quit() or False)
    loop.run()


colors = load_colors()
with tempfile.TemporaryDirectory(prefix='picker-crumbs-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch('omarchy_file_picker.picker.load_colors', return_value=colors):
    root = Path(temp)
    folders = [root]
    for part in ('Projects', 'Mountain Film', 'Footage', 'Camera A', 'Day 01', 'Selects'):
        folder = folders[-1] / part
        folder.mkdir()
        folders.append(folder)
    path = folders[-1] / 'clip.txt'
    path.write_text('fixture')
    request = PickerRequest(current_folder=folders[-1], title='Files', explorer=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    try:
        baseline = window.get_width(), window.get_height()
        assert window.children_by_path[path].get_tooltip_text() is None
        buttons = list(window.path_box.buttons)
        assert len(buttons) == len(folders)
        assert all(isinstance(button, BreadcrumbButton) for button in buttons)
        assert buttons[-1].current and not buttons[0].current
        for left, right in zip(buttons, buttons[1:]):
            _, a = left.compute_bounds(window.path_box)
            _, b = right.compute_bounds(window.path_box)
            assert abs(a.get_x() + a.get_width() - TIP - b.get_x()) < 1
            assert not right.contains(1, right.get_height() / 2)
            assert right.contains(TIP + 2, right.get_height() / 2)
        adjustment = window.path_scroll.get_hadjustment()
        end = adjustment.get_upper() - adjustment.get_page_size()
        assert end > 0
        assert abs(adjustment.get_value() - end) < 1
        selected_dir = window.current_dir
        window.path_wheel.emit('scroll', 0.0, -2.0)
        settle()
        assert adjustment.get_value() < end
        window.path_wheel.emit('scroll', 0.0, -1000.0)
        settle()
        assert adjustment.get_value() == 0
        window.path_wheel.emit('scroll', 1000.0, 0.0)
        settle()
        assert abs(adjustment.get_value() - end) < 1
        assert window.current_dir == selected_dir and (window.get_width(), window.get_height()) == baseline
        window.navigate(folders[2])
        settle()
        assert window.path_box.buttons[-1].current
        if os.environ.get('BREADCRUMBS_QA_SCREENSHOT'):
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(window.toolbar).snapshot(snapshot, window.toolbar.get_width(), window.toolbar.get_height())
            window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(os.environ['BREADCRUMBS_QA_SCREENSHOT'])
        window.path_box.buttons[1].emit('clicked')
        settle()
        assert window.current_dir == folders[1]
        assert window.path_entry.get_text() == str(folders[1])
        assert (window.get_width(), window.get_height()) == baseline
        print('PASS: connected chevrons, notch hit tests, current state, wheel both directions/bounds, ancestor clicks, stable geometry and no file path tooltip')
    finally:
        window.destroy()
