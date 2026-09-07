"""Verify native GTK range/toggle selection in the standalone launch mode."""
from pathlib import Path
import tempfile
from unittest.mock import patch
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from omarchy_file_picker.picker import PickerApplication, PickerWindow, parse_args


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(150, lambda: loop.quit() or False)
    loop.run()


with tempfile.TemporaryDirectory(prefix='picker-selection-') as temp, patch.object(Path, 'home', return_value=Path(temp)):
    root = Path(temp)
    paths = [root / f'{i:02d}.txt' for i in range(10)]
    for path in paths:
        path.write_text('selection fixture')
    request, _ = parse_args(['--demo', temp])
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    try:
        assert window.flow.get_selection_mode() == Gtk.SelectionMode.MULTIPLE
        for mode in ('grid', 'list', 'columns'):
            window._set_view(mode)
            settle()
            flow = window.flow
            if mode == 'list':
                first = window.children_by_path[paths[0]]
                second = window.children_by_path[paths[1]]
                _, first_bounds = first.compute_bounds(flow)
                _, second_bounds = second.compute_bounds(flow)
                pitch = second_bounds.get_y() - first_bounds.get_y()
                assert 28 <= pitch <= 34, pitch
                print('PASS: compact list row pitch', pitch)
            flow.grab_focus()
            # The same GTK selection engine used by its native click gesture:
            # plain movement replaces, Shift extends, Ctrl moves without clearing.
            flow.emit('move-cursor', Gtk.MovementStep.BUFFER_ENDS, -1, False, False)
            assert window._selected_paths() == paths[:1]
            flow.emit('move-cursor', Gtk.MovementStep.VISUAL_POSITIONS, 6, True, False)
            assert window._selected_paths() == paths[:7], window._selected_paths()
            flow.emit('move-cursor', Gtk.MovementStep.VISUAL_POSITIONS, -2, True, False)
            assert window._selected_paths() == paths[:5]
            flow.emit('move-cursor', Gtk.MovementStep.VISUAL_POSITIONS, -2, False, True)
            flow.emit('toggle-cursor-child')
            assert window._selected_paths() == [paths[0], paths[1], paths[3], paths[4]]
            flow.select_child(window.children_by_path[paths[8]])
            assert window._selected_paths() == [paths[0], paths[1], paths[3], paths[4], paths[8]]
            flow.emit('move-cursor', Gtk.MovementStep.BUFFER_ENDS, 1, False, False)
            assert window._selected_paths() == paths[-1:]
            flow.select_all()
            assert window._selected_paths() == paths
            assert '10 items selected' in window.selection_label.get_text()
            print('PASS:', mode, 'native range extension/contraction, toggles, discontiguous selection, replace and Select All')
    finally:
        window.destroy()
