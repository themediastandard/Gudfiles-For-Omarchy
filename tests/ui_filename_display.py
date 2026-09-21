"""SMB filename display and original-path selection through real GTK views."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.filename_display import display_filename
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors
from gi.repository import Gio, GLib, Gtk


errors = []
def exception(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = exception


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(180, lambda: loop.quit() or False)
    loop.run()
    assert not errors


def labels(widget):
    found = [widget.get_text()] if isinstance(widget, Gtk.Label) else []
    child = widget.get_first_child()
    while child:
        found.extend(labels(child))
        child = child.get_next_sibling()
    return found


with tempfile.TemporaryDirectory(prefix='gudfiles-filename-display-') as temp:
    root = Path(temp)
    folder = root / 'Drone Clips\uf028'
    folder.mkdir()
    encoded = folder / 'Camera Notes\uf028'
    ordinary = folder / 'Camera Notes '
    for path in (encoded, ordinary):
        path.write_text('Original contents')
    app = PickerApplication(PickerRequest(current_folder=root), None)
    app.register(None)
    active = load_colors()
    palettes = (active, {**active, 'background': '#17191f',
                        'foreground': '#d7dce4', 'bright_foreground': '#ffffff'})
    for palette in palettes:
        for view in ('grid', 'list', 'columns'):
            with patch.object(Path, 'home', return_value=root / 'home'), \
                    patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
                    patch('omarchy_file_picker.picker.load_colors', return_value=palette):
                results = []
                request = PickerRequest(current_folder=folder, multiple=True)
                window = PickerWindow(app, request, None, on_result=results.append)
                window._set_view(view)
                window.present()
                settle()
                for path in (encoded, ordinary):
                    child = window.children_by_path[path]
                    assert 'Camera Notes ' in labels(child), (view, labels(child))
                    assert not any('\uf028' in text for text in labels(child))
                    window.flow.unselect_all()
                    window.flow.select_child(child)
                    settle()
                    assert window._selected_paths() == [path]
                assert not any('\uf028' in text for text in labels(window))
                window.flow.select_all()
                window._accept()
                settle()
                assert set(results[0]) == {encoded, ordinary}
                assert encoded.read_text() == ordinary.read_text() == 'Original contents'
    with patch.object(Path, 'home', return_value=root / 'home'), \
            patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]):
        request = PickerRequest(current_folder=folder, explorer=True)
        window = PickerWindow(app, request, None)
        window.present()
        settle()
        assert 'Drone Clips ' in labels(window)
        assert not any('\uf028' in text for text in labels(window))
        window.quicklook.show_file(encoded)
        settle()
        assert window.quicklook.title.get_text() == 'Camera Notes '
        window.quicklook.close()
        settle()
        if directory := os.environ.get('FILENAME_SCREENSHOTS'):
            window._set_view('list')
            settle()
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
            Path(directory).mkdir(parents=True, exist_ok=True)
            window.get_native().get_renderer().render_texture(snapshot.to_node(), None).save_to_png(
                str(Path(directory) / 'filenames.png'))
        window.destroy()
        settle()
    assert display_filename('intentional\uf028icon.txt') == 'intentional\uf028icon.txt'
    assert display_filename('Folder\uf028\uf028/file') == 'Folder  /file'
print('PASS: SMB display in all views and palettes; original paths survive picker acceptance')
