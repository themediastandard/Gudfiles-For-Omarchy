"""Open/Save/folder popups share the current browser header and keep their results."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from omarchy_file_picker.model import FileFilter, PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import DEFAULT_COLORS, load_colors


errors = []
original_hook = sys.excepthook
def callback_error(kind, value, traceback):
    errors.append(value)
    original_hook(kind, value, traceback)
sys.excepthook = callback_error


def settle(ms=200):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()
    assert not errors, errors


def contained(widget, container):
    ok, bounds = widget.compute_bounds(container)
    assert widget.get_mapped() and ok
    assert bounds.get_x() >= -1 and bounds.get_y() >= -1
    assert bounds.get_x() + bounds.get_width() <= container.get_width() + 1
    assert bounds.get_y() + bounds.get_height() <= container.get_height() + 1


palettes = [('active', load_colors()), ('light', DEFAULT_COLORS)]
with tempfile.TemporaryDirectory(prefix='gudfiles-picker-chrome-') as temporary:
    root = Path(temporary)
    folder = root / 'Long folder name for navigation and toolbar bounds'
    folder.mkdir()
    text = folder / 'notes.txt'
    text.write_text('fixture')
    (folder / 'other.bin').touch()
    with patch.object(Path, 'home', return_value=root), \
            patch.dict(os.environ, {'XDG_STATE_HOME': str(root / 'state')}):
        app = PickerApplication(PickerRequest(), None)
        app.register(None)
        for palette, colors in palettes:
            for kind in ('explorer', 'open', 'save', 'folder'):
                result = root / f'{palette}-{kind}.json'
                request = PickerRequest(current_folder=folder, explorer=kind == 'explorer',
                    directory=kind == 'folder', mode='save' if kind == 'save' else 'open',
                    title='Choose Folder' if kind == 'folder' else 'Custom caller title',
                    current_name='saved.txt', filters=[FileFilter('Text', ((0, '*.txt'),))],
                    choices=[dict(id='choice', label='Example choice', values=[], selected='true')])
                with patch('omarchy_file_picker.picker.load_colors', return_value=colors), \
                        patch.object(app, 'quit'):
                    window = PickerWindow(app, request, result)
                    window._set_view('list')
                    window.present()
                    settle()
                    try:
                        header = window.get_titlebar()
                        # X11 default sizes include the client-side shadow extents.
                        overhead = window.get_default_size()[0] - window.get_width()
                        for width in (820, 960, 1200):
                            window.set_default_size(width + overhead, 700)
                            settle(350)
                            assert window.get_width() == width, (kind, width, window.get_width())
                            assert header.has_css_class('compact-header')
                            assert 30 <= header.get_height() <= 32, (kind, header.get_height())
                            assert window.toolbar.is_ancestor(header)
                            for control in (window.toolbar.navigation, window.toolbar.actions,
                                    window.back_button, window.up_button, window.search_button,
                                    window.sort_button, window.grid_button, window.list_button,
                                    window.columns_button, window.transfer_button, window.help_button):
                                contained(control, header)
                            window._toggle_path_entry(None)
                            settle()
                            contained(window.path_entry, header)
                            assert window.path_entry.get_text() == str(folder)
                            window._toggle_path_entry(None)
                            settle()
                            if kind != 'explorer':
                                contained(window.accept_button, window.footer)
                                assert not window.chooser_prompt.get_mapped()
                                assert not window.metadata_viewport.get_mapped()
                                assert window.metadata.get_first_child() is None
                                assert not window.tabs.get_visible()
                        if kind == 'folder':
                            assert not window.filter_combo.get_mapped()
                        elif kind != 'explorer':
                            assert not window.filter_combo.get_mapped()
                            assert window.chooser_prompt.get_text() == request.title
                            # Quick Look disables browsing while keeping utilities available.
                            window.flow.select_child(window.children_by_path[text])
                            window.quicklook.show_file(text)
                            settle(450)
                            assert not window.up_button.is_sensitive()
                            assert window.help_button.is_sensitive()
                            window.quicklook.close()
                            settle(450)
                            assert window.toolbar.navigation.get_sensitive()
                        directory = os.environ.get('PICKER_CHROME_SCREENSHOTS')
                        if directory:
                            Path(directory).mkdir(parents=True, exist_ok=True)
                            window.queue_draw()
                            settle()
                            snapshot = Gtk.Snapshot.new()
                            Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                            window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(
                                str(Path(directory) / f'{palette}-{kind}.png'))
                        if kind != 'explorer':
                            if kind == 'save':
                                window.filename_entry.set_text('saved.txt')
                            window._accept()
                            payload = json.loads(result.read_text())
                            expected = folder / 'saved.txt' if kind == 'save' else folder if kind == 'folder' else text
                            assert payload['uris'] == [expected.as_uri()], payload
                            assert payload['choices'] == {'choice': 'true'}
                            if kind != 'folder':
                                assert payload['current_filter'] == ['Text', [[0, '*.txt']]], payload
                    finally:
                        window.destroy()
                        settle()
                print('PASS:', palette, kind, 'shared 30px header at 820/960/1200; controls/results', flush=True)
