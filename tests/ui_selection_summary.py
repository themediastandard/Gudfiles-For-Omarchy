"""Media-only preview visibility, independent totals, and stable outer geometry."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GdkPixbuf, Gio, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import DEFAULT_COLORS, load_colors

errors = []
def callback_error(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = callback_error


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(250, lambda: loop.quit() or False)
    loop.run()
    assert not errors, errors


def texts(widget):
    result = [widget.get_text()] if isinstance(widget, Gtk.Label) else []
    child = widget.get_first_child()
    while child:
        result.extend(texts(child))
        child = child.get_next_sibling()
    return result


colors = load_colors()
with tempfile.TemporaryDirectory(prefix='picker-media-strip-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.dict(os.environ, {name: str(Path(temp) / name) for name in
                                ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME')}), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]):
    root = Path(temp)
    folder = root / 'Folder'
    folder.mkdir()
    document = root / 'Notes.txt'
    document.write_text('fixture')
    photo = root / 'Photo.PNG'
    pixels = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 320, 200)
    pixels.fill(0x2277aaff)
    pixels.savev(str(photo), 'png', [], [])
    video = root / 'Clip.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=320x200:d=1',
                    '-threads', '1', '-pix_fmt', 'yuv420p', str(video)], check=True)
    app = PickerApplication(PickerRequest(), None)
    app.register(None)
    for palette, theme in [('active', colors), ('light', DEFAULT_COLORS)]:
        for context in ('explorer', 'open', 'save'):
            request = PickerRequest(current_folder=root, explorer=context == 'explorer', multiple=True,
                                    mode='save' if context == 'save' else 'open')
            with patch('omarchy_file_picker.picker.load_colors', return_value=theme):
                window = PickerWindow(app, request, None)
            window.set_default_size(1000, 700)
            window.present()
            settle()
            try:
                for mode in ('grid', 'list', 'columns'):
                    window._set_view(mode)
                    window.flow.unselect_all()
                    settle()
                    size = window.get_width(), window.get_height()
                    full_height = window.browser_stack.get_height()
                    assert not window.metadata_viewport.get_mapped()
                    for paths, media in (([document], None), ([folder], None),
                                         ([folder, document], None), ([photo], photo),
                                         ([video], video), ([document, photo], photo),
                                         ([document], None), ([], None)):
                        window.flow.unselect_all()
                        for path in paths:
                            window.flow.select_child(window.children_by_path[path])
                        settle()
                        visible = context == 'explorer' and media is not None
                        assert window.metadata_viewport.get_mapped() == visible, (context, mode, paths)
                        assert window.view_status.get_mapped()
                        assert bool(window.view_status.summary.get_text()) == bool(paths)
                        assert (window.get_width(), window.get_height()) == size
                        if visible:
                            assert media.name in texts(window.metadata)
                            assert window.browser_stack.get_height() < full_height - 90
                            with patch.object(window, '_rating_controls', wraps=window._rating_controls) as rating:
                                window._update_metadata(paths[0])
                                rating.assert_called_once_with([media])
                        else:
                            assert window.metadata.get_first_child() is None
                            assert window.browser_stack.get_height() == full_height
                        if context == 'explorer' and mode == 'list' and palette == 'light' and paths in ([photo], [document]):
                            settle()
                            snapshot = Gtk.Snapshot.new()
                            Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                            name = 'photo' if media else 'clean'
                            window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(
                                f'/tmp/gudfiles-media-strip-{name}.png')
                    print('PASS:', palette, context, mode, 'media visibility, totals, rating scope and stable geometry', flush=True)
            finally:
                window.destroy()
                settle()
