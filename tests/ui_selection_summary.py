"""Collective selection previews in all views, without growing the window."""
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.selection_summary import SelectionStack
from omarchy_file_picker.theme import load_colors


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(150, lambda: loop.quit() or False)
    loop.run()


def texts(widget):
    result = [widget.get_text()] if isinstance(widget, Gtk.Label) else []
    child = widget.get_first_child()
    while child:
        result.extend(texts(child))
        child = child.get_next_sibling()
    return result


colors = load_colors()
with tempfile.TemporaryDirectory(prefix='picker-selection-summary-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
        patch('omarchy_file_picker.picker.load_colors', return_value=colors):
    root = Path(temp)
    folders = [root / name for name in ('Footage', 'Audio', 'Exports')]
    for folder in folders:
        folder.mkdir()
        (folder / 'not-an-additional-selection.txt').write_text('fixture')
    files = [root / name for name in ('Notes.txt', 'Shot list.txt')]
    for path in files:
        path.write_text('fixture')
    request = PickerRequest(current_folder=root, explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    try:
        for mode in ('grid', 'list', 'columns'):
            window._set_view(mode)
            settle()
            size = window.get_width(), window.get_height()
            strip_height = window.metadata_viewport.get_height()
            browser_height = window.browser_stack.get_height()
            for paths, kind, title, detail in (
                    (folders[:2], 'folders', '2 items selected', '2 folders'),
                    (folders, 'folders', '3 items selected', '3 folders'),
                    (files, 'files', '2 items selected', '2 files'),
                    ([folders[0], *files], 'mixed', '3 items selected', '1 folder · 2 files')):
                window.flow.unselect_all()
                for path in paths:
                    window.flow.select_child(window.children_by_path[path])
                settle()
                icon = window.metadata.get_first_child()
                assert isinstance(icon, SelectionStack) and icon.kind == kind
                assert title in texts(window.metadata) and detail in texts(window.metadata)
                assert (window.get_width(), window.get_height()) == size
                assert window.metadata_viewport.get_height() == strip_height
                assert window.browser_stack.get_height() == browser_height
                # Label changes must retain the collective preview and affect all selected items.
                window._apply_annotation(paths, color='blue')
                settle()
                assert all(window.ratings.get(path)[1] == 'blue' for path in paths)
                assert title in texts(window.metadata)
                # Group previews must never start a probe for the first selected item.
                with patch('omarchy_file_picker.picker.make_details_widget') as details:
                    window._update_metadata(paths[0])
                    details.assert_not_called()
                if kind == 'folders' and len(paths) == 3 and os.environ.get('SELECTION_SUMMARY_QA_SCREENSHOT'):
                    settle()
                    snapshot = Gtk.Snapshot.new()
                    Gtk.WidgetPaintable.new(window.metadata_viewport).snapshot(snapshot,
                        window.metadata_viewport.get_width(), window.metadata_viewport.get_height())
                    node = snapshot.to_node()
                    if node:
                        window.get_renderer().render_texture(node, None).save_to_png(os.environ['SELECTION_SUMMARY_QA_SCREENSHOT'])
            window.flow.unselect_all()
            window.flow.select_child(window.children_by_path[files[0]])
            settle()
            assert not isinstance(window.metadata.get_first_child(), SelectionStack)
            assert files[0].name in texts(window.metadata)
            window.flow.unselect_all()
            settle()
            assert 'Select a file to preview' in texts(window.metadata)
            print('PASS:', mode, 'folder/file/mixed counts, stacked icon, group labels, single/empty reset and stable geometry')
    finally:
        window.destroy()
