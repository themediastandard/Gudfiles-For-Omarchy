"""App folder choosers show contents but return folders only, in every view."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import DEFAULT_COLORS, load_colors


errors = []
original_hook = sys.excepthook
def callback_error(kind, value, traceback):
    errors.append(value)
    original_hook(kind, value, traceback)
sys.excepthook = callback_error


def settle(ms=180):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()
    assert not errors, errors


def visible_file(window, path):
    child = window.children_by_path[path]
    assert child.get_mapped(), f'File not rendered: {path.name}'
    assert not child.get_sensitive(), 'Files must not be folder choices'
    window.flow.emit('child-activated', child)
    assert not window.finished, 'Activating a file submitted the folder prompt'


palettes = [('active', load_colors()), ('light', DEFAULT_COLORS)]
with tempfile.TemporaryDirectory(prefix='gudfiles-folder-qa-') as temporary:
    root = Path(temporary)
    photos = root / 'Photos'
    photos.mkdir()
    photo = photos / 'photo.png'
    # A real small image exercises thumbnail loading as well as the filename.
    from gi.repository import GdkPixbuf
    pixels = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 32, 24)
    pixels.fill(0x5588CCFF)
    pixels.savev(str(photo), 'png', [], [])
    nested = photos / 'Nested'
    nested.mkdir()
    nested_photo = nested / 'another.png'
    nested_photo.write_bytes(photo.read_bytes())
    empty = root / 'Empty'
    empty.mkdir()
    with patch.object(Path, 'home', return_value=root), \
            patch.dict(os.environ, {'XDG_STATE_HOME': str(root / 'state')}):
        app = PickerApplication(PickerRequest(), None)
        app.register(None)
        for palette, colors in palettes:
            for view in ('grid', 'list', 'columns'):
                # Matches the legacy running portal's request serialization.
                request = PickerRequest.from_dict(dict(
                    mode='open', title='Open File', accept_label='Open',
                    current_folder=str(photos), directory=True, filters=[]))
                result = root / f'{palette}-{view}.json'
                with patch('omarchy_file_picker.picker.load_colors', return_value=colors), \
                        patch.object(app, 'quit'):
                    window = PickerWindow(app, request, result)
                    window.present()
                    window._set_view(view)
                    settle(400)
                    try:
                        assert not window.filter_combo.get_mapped()
                        assert window._active_filter() is None
                        visible_file(window, photo)
                        assert window.accept_button.get_sensitive()
                        # Nested navigation must retain context in every view.
                        child = window.children_by_path[nested]
                        window.flow.emit('child-activated', child)
                        settle(400)
                        assert window.current_dir == nested
                        visible_file(window, nested_photo)
                        assert window.browser_stack.get_visible_child_name() != 'empty'
                        if view == 'columns':
                            assert not window.columns.active.empty.get_visible()
                        # A files-only folder is not described as empty.
                        window.flow.unselect_all()
                        window._accept()
                        payload = json.loads(result.read_text())
                        assert payload['uris'] == [nested.as_uri()], payload
                        assert 'current_filter' not in payload
                    finally:
                        window.destroy()
                        settle()
                print('PASS:', palette, view, 'files visible; nested folder returned', flush=True)

        # Folder requests ignore inapplicable file filters, including SaveFiles.
        for mode in ('open', 'save_files'):
            request = PickerRequest.from_dict(dict(mode=mode, directory=True,
                current_folder=str(photos), filters=[['Text', [[0, '*.txt']]]]))
            window = PickerWindow(app, request, None)
            window.present()
            window._set_view('grid')
            settle()
            try:
                visible_file(window, photo)
                assert window._active_filter() is None
                # Whole-computer results show context but cannot submit a file.
                window._computer_search_roots = lambda: [str(photos)]
                window.search.set_text('photo')
                window._set_search_scope('computer')
                deadline = time.monotonic() + 10
                while window.search_pending and time.monotonic() < deadline:
                    settle()
                settle()
                assert not window.search_pending
                visible_file(window, photo)
                assert not window.accept_button.get_sensitive()
                window._accept()
                assert not window.finished
                window._set_search_scope('folder')
                window.search.set_text('')
                window.navigate(empty)
                settle(400)
                assert window.browser_stack.get_visible_child_name() == 'empty'
                assert window.accept_button.get_sensitive()
                window.navigate(photos)
                settle(400)
                visible_file(window, photo)
                target = os.environ.get('FOLDER_PICKER_SCREENSHOT')
                if target and mode == 'open':
                    snapshot = Gtk.Snapshot.new()
                    Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                    window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(target)
            finally:
                window.destroy()
                settle()
            print('PASS:', mode, 'filters ignored; search guarded; empty-folder recovery', flush=True)
