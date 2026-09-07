"""Native sorting controls, ordering, selection and shared preference regression.

PYTHONPATH=. python tests/ui_sorting.py
SORT_QA_SCREENSHOTS=/tmp/gudfiles-sort optionally captures the window and menu.
All file timestamps and preferences belong to disposable fixtures.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.model import PickerRequest
from gi.repository import GLib, Gtk


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(150, lambda: loop.quit() or False)
    loop.run()


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


def click(window, title):
    window.sort_button.popup()
    settle()
    button = next(w for w in descendants(window.sort_popover) if isinstance(w, Gtk.Button)
                  and any(isinstance(label, Gtk.Label) and label.get_text() == title
                          for label in descendants(w)))
    button.emit('clicked')
    settle()
    assert not window.sort_popover.get_visible()


def capture(widget, name):
    directory = os.environ.get('SORT_QA_SCREENSHOTS')
    if not directory:
        return
    snapshot = Gtk.Snapshot.new()
    Gtk.WidgetPaintable.new(widget).snapshot(snapshot, widget.get_width(), widget.get_height())
    node = snapshot.to_node()
    assert node is not None, name
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    widget.get_native().get_renderer().render_texture(node, None).save_to_png(str(path / f'{name}.png'))


with tempfile.TemporaryDirectory(prefix='gudfiles-sort-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)):
    root = Path(temp)
    folder = root / 'Footage'
    folder.mkdir()
    subfolder = folder / 'Exports'
    subfolder.mkdir()
    # Alphabetical, size and timestamp order deliberately disagree.
    oldest, middle, newest = [folder / name for name in ('A-notes.txt', 'M-edit.csv', 'Z-brief.md')]
    for path, size, timestamp in ((oldest, 30, 100), (middle, 10, 200), (newest, 20, 300)):
        path.write_text('x' * size)
        os.utime(path, (timestamp, timestamp))
    os.utime(subfolder, (50, 50))
    request = PickerRequest(current_folder=folder, explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    try:
        assert window.sort_button.get_parent() is window.toolbar
        assert window.sort_button.get_mapped()
        assert not window.preferences_path.exists(), 'Startup must not rewrite preferences'
        geometry = window.get_width(), window.get_height()
        for mode in ('grid', 'list', 'columns'):
            window._set_view(mode)
            settle()
            window.flow.select_child(window.children_by_path[middle])
            for title, expected in (
                ('Newest first', [newest, middle, oldest]),
                ('Oldest first', [oldest, middle, newest]),
                ('Name A–Z', [oldest, middle, newest]),
                ('Name Z–A', [newest, middle, oldest]),
                ('Largest first', [oldest, newest, middle]),
                ('Smallest first', [middle, newest, oldest]),
                ('Type A–Z', [middle, newest, oldest]),
                ('Type Z–A', [oldest, newest, middle]),
            ):
                click(window, title)
                assert window.entries == [subfolder, *expected], (mode, title, window.entries)
                rows = [w._picker_path for w in descendants(window.flow)
                        if isinstance(w, Gtk.FlowBoxChild)]
                assert rows == window.entries, (mode, title, rows)
                assert window._selected_paths() == [middle], (mode, title, window._selected_paths())
                assert title in window.sort_button.get_tooltip_text()
                assert (window.get_width(), window.get_height()) == geometry
            click(window, 'Newest first')
            click(window, 'Folders first')
            assert window.entries == [newest, middle, oldest, subfolder]
            assert window._selected_paths() == [middle]
            click(window, 'Folders first')
            assert window.entries == [subfolder, newest, middle, oldest]
        # Search and tabs continue using the chosen ordering.
        window.search.set_text('brief')
        settle(); settle()
        assert window.entries == [newest]
        window.search.set_text('')
        settle(); settle()
        original = window.tabs.current
        window.tabs.new(folder)
        settle()
        assert window.entries == [subfolder, newest, middle, oldest]
        window.tabs.select(original)
        settle()
        assert window.entries == [subfolder, newest, middle, oldest]
        # The context menu and top bar share the same callbacks and current mark.
        options = window._sort_menu_entries()
        assert options[0][2] == 'object-select-symbolic'
        options[1][3]()
        assert 'Oldest first' in window.sort_button.get_tooltip_text()
        assert window.entries == [subfolder, oldest, middle, newest]
        click(window, 'Newest first')
        stored = json.loads(window.preferences_path.read_text())
        assert (stored['sort_key'], stored['descending']) == ('modified', True)
        # New explorer/Open/Save windows restore the pair. An older window's
        # unrelated preference write must not replace a newer sort selection.
        for mode, explorer in (('open', True), ('open', False), ('save', False)):
            restored = PickerWindow(app, PickerRequest(current_folder=folder, mode=mode,
                                   explorer=explorer), None)
            restored.present()
            settle()
            try:
                assert restored.entries == [subfolder, newest, middle, oldest]
                assert 'Newest first' in restored.sort_button.get_tooltip_text()
                click(window, 'Oldest first')
                restored._set_file_preference('show_type', False, reload=False)
                saved = json.loads(window.preferences_path.read_text())
                assert (saved['sort_key'], saved['descending']) == ('modified', False)
                click(window, 'Newest first')
            finally:
                restored.destroy()
        window._set_view('list')
        window.present()
        settle()
        capture(window, 'toolbar')
        window.sort_button.popup()
        settle()
        capture(window.sort_popover, 'sort-menu')
        print('PASS: all sort choices in grid/list/columns, real row ordering, selection, folders toggle, '
              'stable geometry, search/tabs, context sync and explorer/Open/Save preference restoration')
    finally:
        window.destroy()
