"""Native column navigation, active-directory actions and shared interaction QA."""
import os
import json
import subprocess
from pathlib import Path
import tempfile
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(180, lambda: loop.quit() or False)
    loop.run()


class Gesture:
    def set_state(self, state):
        self.state = state

    def get_current_event_state(self):
        return Gdk.ModifierType(0)


colors = load_colors()
with tempfile.TemporaryDirectory(prefix='picker-columns-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
        patch('omarchy_file_picker.picker.load_colors', return_value=colors):
    root = Path(temp)
    projects = root / 'Projects'
    film = projects / 'Mountain Film'
    footage = film / 'Footage'
    footage.mkdir(parents=True)
    (root / 'Exports').mkdir()
    (film / 'Empty').mkdir()
    paths = [footage / f'{i:02d} - Camera notes.txt' for i in range(12)]
    for path in paths:
        path.write_text('A quiet morning in the mountains.\n')
    (footage / '.hidden.txt').write_text('hidden')
    request = PickerRequest(current_folder=root, title='Column View QA', explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    try:
        clients = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
        client = next(c for c in clients if c['pid'] == os.getpid() and c['class'] == 'org.omarchy.FilePicker')
        selector = json.dumps('address:' + client['address'])
        if not client['floating']:
            subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' + selector + '})'], check=True)
            settle()
        subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.resize({x=1200,y=800,relative=false,window=' + selector + '})'], check=True)
        settle()
        baseline = window.get_width(), window.get_height()
        window.columns_button.emit('clicked')
        settle()
        assert window.view_mode == 'columns'
        for folder in (projects, film, footage):
            window.flow.unselect_all()
            window.flow.select_child(window.children_by_path[folder])
            settle()
            assert window.columns.columns[-1].path == folder
            window.columns._key(None, Gdk.KEY_Right, 0, Gdk.ModifierType(0), window.columns.active)
            settle()
            assert window.current_dir == folder
        assert len(window.columns.columns) == 4
        assert (window.get_width(), window.get_height()) == baseline
        adjustment = window.columns.get_hadjustment()
        assert adjustment.get_upper() > adjustment.get_page_size()
        assert adjustment.get_value() > 0
        flow = window.flow
        flow.grab_focus()
        flow.emit('move-cursor', Gtk.MovementStep.BUFFER_ENDS, -1, False, False)
        flow.emit('move-cursor', Gtk.MovementStep.VISUAL_POSITIONS, 5, True, False)
        assert window._selected_paths() == paths[:6]
        flow.emit('move-cursor', Gtk.MovementStep.VISUAL_POSITIONS, -2, False, True)
        flow.emit('toggle-cursor-child')
        assert window._selected_paths() == [paths[0], paths[1], paths[2], paths[4], paths[5]]
        flow.select_all()
        assert window._selected_paths() == paths
        flow.unselect_all()
        flow.select_child(window.children_by_path[paths[2]])
        window.columns._key(None, Gdk.KEY_Left, 0, Gdk.ModifierType(0), window.columns.active)
        settle()
        assert window.current_dir == film
        window.columns._key(None, Gdk.KEY_Right, 0, Gdk.ModifierType(0), window.columns.active)
        settle()
        assert window._selected_paths() == [paths[2]]
        flow.unselect_all()
        flow.select_child(window.children_by_path[paths[0]])
        window.quicklook.show_file(paths[0])
        settle()
        window.quicklook.step(1)
        settle()
        assert window.quicklook.path == paths[1]
        window.quicklook.close()
        settle()
        settle()
        assert (window.get_width(), window.get_height()) == baseline
        assert window.current_dir == footage, ('after preview', window.current_dir)
        window._toggle_hidden(None)
        settle()
        assert footage / '.hidden.txt' in window.children_by_path, (window.current_dir, window._selected_paths(), [c.path for c in window.columns.columns])
        assert len(window.columns.columns) == 4
        window._toggle_hidden(None)
        settle()
        window._show_create_dialog('text')
        settle()
        assert (footage / 'untitled.txt').is_file()
        # Background right-click must target that column, not the last active one.
        ancestor = window.columns.columns[-2]
        _, bounds = ancestor.scroller.compute_bounds(window.browser_stack)
        x, y = bounds.get_x() + 30, bounds.get_y() + bounds.get_height() - 35
        window._on_context_pressed(Gesture(), 1, x, y)
        settle()
        assert window.current_dir == film and window._selected_paths() == []
        assert window.context_popover is not None
        window._close_context_menu()
        settle()
        assert window.current_dir == film, ('after context closed', window.current_dir, window.get_focus())
        window._show_create_dialog('text')
        settle()
        assert (film / 'untitled.txt').is_file(), (window.current_dir, list(root.rglob('untitled*')))
        assert not (root / 'untitled.txt').exists()
        # Empty child is a real column and an available destination.
        window.flow.unselect_all()
        window.flow.select_child(window.children_by_path[film / 'Empty'])
        settle()
        assert window.columns.columns[-1].entries == []
        window.columns._key(None, Gdk.KEY_Right, 0, Gdk.ModifierType(0), window.columns.active)
        assert window.current_dir == film / 'Empty'
        window._go_back(None)
        settle()
        assert window.current_dir == film
        window.navigate(footage)
        settle()
        window.flow.select_child(window.children_by_path[paths[2]])
        for mode in ('list', 'grid', 'columns'):
            window._set_view(mode)
            settle()
            assert window._selected_paths() == [paths[2]]
            assert (window.get_width(), window.get_height()) == baseline
        # Single selection and folder-only portal constraints remain authoritative.
        window.request.multiple = False
        window.request.directory = True
        window.navigate(film)
        settle()
        assert window.flow.get_selection_mode() == Gtk.SelectionMode.SINGLE
        assert all(path.is_dir() for path in window.entries)
        window.request.multiple = True
        window.request.directory = False
        window.navigate(root)
        for folder in (projects, film, footage):
            window.flow.unselect_all()
            window.flow.select_child(window.children_by_path[folder])
            settle()
            window.columns._key(None, Gdk.KEY_Right, 0, Gdk.ModifierType(0), window.columns.active)
            settle()
        assert window.current_dir == footage and len(window.columns.columns) == 4
        assert window.path_box.buttons[-1].get_label() == 'Footage'
        trail = window.path_scroll.get_hadjustment()
        assert abs(trail.get_value() - (trail.get_upper() - trail.get_page_size())) < 1, (trail.get_value(), trail.get_upper(), trail.get_page_size())
        if os.environ.get('COLUMNS_QA_SCREENSHOT'):
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(window.get_child()).snapshot(snapshot, window.get_width(), window.get_height())
            node = snapshot.to_node()
            if node:
                window.get_renderer().render_texture(node, None).save_to_png(os.environ['COLUMNS_QA_SCREENSHOT'])
        print('PASS: adjacent folder columns, horizontal overflow, native range/toggle/select-all, Quick Look, hidden filters, background context/create destination, empty folders, history, mode switching, portal constraints and stable geometry')
    finally:
        window.destroy()
