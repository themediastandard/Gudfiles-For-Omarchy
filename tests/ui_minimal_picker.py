"""Native popup footer, list thumbnail and viewport regression checks."""
import json
import os
from pathlib import Path
import sys
import subprocess
import shutil
import tempfile
import time
from unittest.mock import patch

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.thumbnail_widgets import Thumbnail, SCHEDULER
from omarchy_file_picker.theme import DEFAULT_COLORS, load_colors
from gi.repository import GdkPixbuf, GLib, Gtk

errors = []
def callback_error(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = callback_error


def settle(ms=40):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()
    assert not errors, errors


def until(predicate):
    deadline = time.monotonic() + 20
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Thumbnail condition timed out'


with tempfile.TemporaryDirectory(prefix='minimal-picker-') as temporary, \
        patch.object(Path, 'home', return_value=Path(temporary)):
    root = Path(temporary)
    folder = root / 'Images'
    folder.mkdir()
    for index in range(120):
        pixels = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 120, 80)
        pixels.fill((0x2277aaff, 0xd68b3dff, 0x6a9966ff)[index % 3])
        pixels.savev(str(folder / f'Photo {index:03}.png'), 'png', [], [])
    (folder / 'Notes.txt').write_text('fixture')
    if shutil.which('ffmpeg') and shutil.which('ffmpegthumbnailer'):
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:d=1',
                        '-threads', '1', '-pix_fmt', 'yuv420p', str(folder / 'Clip.mp4')], check=True)
    config = root / '.config/omarchy-file-picker'
    config.mkdir(parents=True)
    (config / 'preferences.json').write_text(json.dumps({'view_mode': 'list'}))
    app = PickerApplication(PickerRequest(), None)
    app.register(None)
    for palette, colors in [('active', load_colors()), ('light', DEFAULT_COLORS)]:
        for mode in ('explorer', 'open', 'save', 'folder'):
            request = PickerRequest(current_folder=folder, explorer=mode == 'explorer',
                                    directory=mode == 'folder', mode='save' if mode == 'save' else 'open',
                                    current_name='Saved photo.png', title='Minimal picker QA')
            with patch('omarchy_file_picker.picker.load_colors', return_value=colors):
                window = PickerWindow(app, request, None)
            window.set_default_size(900, 650)
            window.present()
            settle(250)
            until(lambda: any(w.loaded for w in SCHEDULER.widgets))
            until(lambda: all(w.loaded for w in SCHEDULER.widgets if w.in_view() and w.path.suffix in {'.png', '.mp4'}))
            loaded = [w for w in SCHEDULER.widgets if w.loaded]
            assert 1 <= len(loaded) < 60, len(loaded)
            assert SCHEDULER.running <= 2
            assert all(w.in_view() and isinstance(w, Thumbnail) for w in loaded)
            row = window.children_by_path[folder / 'Photo 000.png']
            assert row.get_height() <= 30, row.get_height()
            if mode == 'explorer':
                assert not window.metadata_viewport.get_mapped()
                assert not window.footer.get_mapped()
            else:
                assert not window.metadata_viewport.get_mapped()
                assert window.metadata.get_first_child() is None
                assert not window.filter_combo.get_mapped()
                assert not window.chooser_prompt.get_mapped()
                assert window.footer.get_height() <= 46, window.footer.get_height()
                assert window.accept_button.get_mapped()
                if mode == 'save':
                    assert window.filename_entry.get_mapped()
                if mode != 'folder':
                    window.flow.select_child(row)
                    settle()
                    assert window.accept_button.get_sensitive()
                    assert window.metadata.get_first_child() is None
                else:
                    assert not row.get_sensitive()
            output = os.environ.get('MINIMAL_PICKER_SCREENSHOTS')
            if output:
                Path(output).mkdir(parents=True, exist_ok=True)
                settle()
                snapshot = Gtk.Snapshot.new()
                Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(
                    str(Path(output) / f'{palette}-{mode}.png'))
            adjustment = window.file_scroller.get_vadjustment()
            adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
            until(lambda: all(not w.loaded for w in loaded))
            until(lambda: any(w.loaded and w.path.name.startswith('Photo 11') for w in SCHEDULER.widgets))
            window._set_view('columns')
            until(lambda: SCHEDULER.running == 0 and not SCHEDULER.widgets)
            window._set_view('list')
            until(lambda: any(w.loaded for w in SCHEDULER.widgets))
            window.destroy()
            until(lambda: SCHEDULER.running == 0 and not SCHEDULER.widgets)
            print('PASS:', palette, mode, 'compact footer, 28px thumbnail rows, scrolling and cancellation', flush=True)
