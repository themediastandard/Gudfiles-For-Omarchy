"""Native breadcrumb navigation, current-folder reveal and full-name tooltips."""
import os
import json
from pathlib import Path
import subprocess
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


def capture(window):
    target = os.environ.get('BREADCRUMBS_QA_SCREENSHOT')
    if not target:
        return
    for _ in range(8):
        window.toolbar.queue_draw()
        settle()
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(window.toolbar).snapshot(snapshot, window.toolbar.get_width(), window.toolbar.get_height())
        node = snapshot.to_node()
        if node is not None:
            window.get_renderer().render_texture(node, None).save_to_png(target)
            return
    raise AssertionError('Breadcrumb toolbar did not become drawable')


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
        # Make overflow deterministic even on a wide desktop with compact search.
        client = next(c for c in json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
                      if c['pid'] == os.getpid())
        selector = json.dumps('address:' + client['address'])
        if not client['floating']:
            subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' + selector + '})'], check=True)
            settle()
        subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.resize({x=1200,y=800,relative=false,window=' + selector + '})'], check=True)
        settle()
        baseline = window.get_width(), window.get_height()
        assert window.children_by_path[path].get_tooltip_text() is None
        buttons = list(window.path_box.buttons)
        assert len(buttons) == len(folders)
        assert all(isinstance(button, BreadcrumbButton) for button in buttons)
        assert all(button.get_tooltip_text() == button.get_label() for button in buttons)
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
        window.path_box.buttons[1].emit('clicked')
        settle()
        assert window.current_dir == folders[1]
        assert window.path_entry.get_text() == str(folders[1])
        assert (window.get_width(), window.get_height()) == baseline

        def current(folder):
            button = window.path_box.buttons[-1]
            assert button.current and button.get_label() == folder.name, (folder, button.get_label())
            assert button.get_tooltip_text() == folder.name
            assert window.path_entry.get_text() == str(folder)
            adjustment = window.path_scroll.get_hadjustment()
            assert abs(adjustment.get_value() - max(0, adjustment.get_upper() - adjustment.get_page_size())) < 1
            valid, bounds = button.compute_bounds(window.path_scroll)
            assert valid
            assert bounds.get_x() + bounds.get_width() <= window.path_scroll.get_width() + 1, (
                folder, bounds.get_x(), bounds.get_width(), window.path_scroll.get_width())
            if bounds.get_width() <= window.path_scroll.get_width():
                assert bounds.get_x() >= -1

        # Replacing the tail with an equally wide name must reveal it even when
        # the user previously scrolled left and GTK's adjustment size is unchanged.
        siblings = [folders[-2] / ('W' * 40 + suffix) for suffix in ('A', 'B')]
        for folder in siblings:
            folder.mkdir()
        for mode in ('grid', 'list'):
            window._set_view(mode)
            window.navigate(siblings[0])
            settle()
            current(siblings[0])
            window.path_wheel.emit('scroll', 0.0, -1000.0)
            settle()
            assert window.path_scroll.get_hadjustment().get_value() == 0
            window.navigate(siblings[1])
            settle()
            current(siblings[1])

        # A single folder selection opens its column without moving selection
        # out of the parent. The breadcrumb must include that newly opened folder.
        window._set_view('columns')
        window.navigate(root)
        settle()
        for folder in folders[1:]:
            parent = window.columns.columns[-1]
            parent.flow.select_child(parent.children[folder])
            settle()
            assert window.columns.columns[-1].path == folder
            assert window.current_dir == folder.parent
            assert window._selected_paths() == [folder]
            current(folder)
        window._toggle_path_entry(None)
        settle()
        assert window.path_entry.get_text() == str(folders[-1])
        window._toggle_path_entry(None)
        settle()
        current(folders[-1])
        original = window.tabs.current
        window.tabs.new(folders[1])
        settle()
        window.tabs.select(original)
        settle(); settle()
        current(folders[-1])
        assert window._selected_paths() == [folders[-1]]
        # Up follows the displayed folder; it must not skip an extra parent.
        window.up_button.emit('clicked')
        settle()
        assert window.current_dir == folders[-2]
        current(folders[-2])
        active = window.columns.active
        active.flow.select_child(active.children[siblings[0]])
        settle()
        current(siblings[0])
        active.flow.unselect_all()
        active.flow.select_child(active.children[siblings[1]])
        settle()
        current(siblings[1])
        assert not window.columns.columns[-1].entries, 'Empty child still belongs in the trail'
        active.flow.unselect_all()
        settle()
        current(folders[-2])
        window.navigate(folders[-1])
        settle()
        window.flow.select_child(window.children_by_path[path])
        settle()
        current(folders[-1])
        if os.environ.get('BREADCRUMBS_QA_SCREENSHOT'):
            window.navigate(siblings[1])
            settle()
            capture(window)
        print('PASS: current-folder reveal, equal-width siblings, nested column clicks, selection preservation, tabs, Up, empty folders, full-name tooltips, wheel navigation and stable geometry')
    finally:
        window.destroy()
