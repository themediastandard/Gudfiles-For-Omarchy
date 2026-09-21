"""Native folder-size rendering, sorting, freshness and cancellation regression."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

from omarchy_file_picker.model import PickerRequest, format_size
from omarchy_file_picker.folder_sizes import FolderSize
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors
from gi.repository import Gio, GLib, Gtk

errors = []
def exception(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = exception


def settle(ms=100):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()
    assert not errors


def until(predicate, message='Timed out'):
    deadline = time.monotonic() + 12
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), (message, window.view_mode, window.view_status.summary.get_text(), window._selected_paths())


def labels(widget):
    found = [widget] if isinstance(widget, Gtk.Label) else []
    child = widget.get_first_child()
    while child:
        found.extend(labels(child))
        child = child.get_next_sibling()
    return found


with tempfile.TemporaryDirectory(prefix='gudfiles-folder-sizes-') as temp:
    root = Path(temp)
    folder = root / 'Files'; folder.mkdir()
    large = folder / 'Large folder'; large.mkdir()
    nested = large / 'Nested'; nested.mkdir()
    (nested / '.hidden').write_bytes(b'a' * 4096)
    (large / 'Loop').symlink_to(large)
    small = folder / 'Small folder'; small.mkdir()
    (small / 'File').write_bytes(b'a' * 1024)
    empty = folder / 'Empty folder'; empty.mkdir()
    regular = folder / 'File.txt'; regular.write_bytes(b'a' * 2048)
    app = PickerApplication(PickerRequest(current_folder=folder), None)
    app.register(None)
    active = load_colors()
    palettes = (active, {**active, 'background': '#17191f',
                        'foreground': '#d7dce4', 'bright_foreground': '#ffffff'})
    for mode in ('browser', 'open', 'save', 'folder'):
        for palette_index, palette in enumerate(palettes):
            with patch.object(Path, 'home', return_value=root / f'home-{mode}-{palette_index}'), \
                    patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
                    patch('omarchy_file_picker.picker.load_colors', return_value=palette):
                request = PickerRequest(current_folder=folder, explorer=mode == 'browser',
                                        directory=mode == 'folder', multiple=True,
                                        mode='save' if mode == 'save' else 'open')
                window = PickerWindow(app, request, None)
                window.present(); settle()
                try:
                    for view in ('grid', 'list', 'columns'):
                        window.flow.unselect_all()
                        window.navigate(folder)
                        window._set_view(view); settle()
                        assert window.view_status.scale.get_mapped() == (view == 'grid')
                        assert window.view_status.get_start_widget().get_visible() == (view == 'grid')
                        assert window.view_status.get_end_widget().get_visible() == (view == 'grid')
                        until(lambda: window.folder_sizes.result(large) is not None, (mode, view, 'size'))
                        for path, size in ((large, 4096), (small, 1024), (empty, 0)):
                            until(lambda p=path, s=size: any(l.get_text() == format_size(s)
                                  for l in labels(window.children_by_path[p])), (mode, view, path))
                            assert any(l.get_mapped() and l.get_text() == format_size(size)
                                       for l in labels(window.children_by_path[path]))
                        # Drive the real selection signals for several folders
                        # and mixed files, including columns' deferred navigation.
                        window.flow.unselect_all()
                        window.flow.select_child(window.children_by_path[large])
                        window.flow.select_child(window.children_by_path[small])
                        until(lambda: window.view_status.summary.get_text() == '2 folders · ' + format_size(5120))
                        assert set(window._selected_paths()) == {large, small}
                        assert window.view_status.summary.get_mapped()
                        if mode != 'folder':
                            window.flow.select_child(window.children_by_path[regular])
                            until(lambda: window.view_status.summary.get_text() == '1 file, 2 folders · ' + format_size(7168))
                        _, bounds = window.view_status.summary.compute_bounds(window.view_status)
                        assert abs(bounds.get_x() + bounds.get_width()/2 - window.view_status.get_width()/2) <= 2
                        window.flow.unselect_all()
                        window.flow.select_child(window.children_by_path[small])
                        until(lambda: window.view_status.summary.get_text() == '1 folder · ' + format_size(1024),
                              (mode, view, window.view_status.summary.get_text()))
                        # Column selection opens a child column; reset selection
                        # explicitly to check a mixed total without navigation.
                        window.view_status.update([small, regular])
                        until(lambda: window.view_status.summary.get_text() == '1 file, 1 folder · ' + format_size(3072))
                        window.view_status.update([empty])
                        until(lambda: window.view_status.summary.get_text() == '1 folder · ' + format_size(0))
                        window.view_status.update([])
                        assert window.view_status.summary.get_text() == ''
                    window.flow.unselect_all()
                    window.navigate(folder)
                    window._set_view('list'); settle()
                    window._set_sort('size', True)
                    until(lambda: window.list_details.applied, 'size sort did not finish')
                    folders = [p for p in window.entries if p.is_dir()]
                    assert folders == [large, small, empty], folders
                    window._set_sort('size', False)
                    until(lambda: window.list_details.applied)
                    assert [p for p in window.entries if p.is_dir()] == [empty, small, large]
                    # A nested edit does not change its top-level directory stat.
                    # F5/refresh must discard the cached content measurement.
                    (nested / '.hidden').write_bytes(b'a' * 8192)
                    window._refresh_files()
                    until(lambda: window.folder_sizes.result(large) is not None and
                          window.folder_sizes.result(large).total == 8192)
                    (nested / '.hidden').write_bytes(b'a' * 4096)
                    # Incomplete totals stay visibly distinct from exact sizes.
                    window._set_sort('name', False)
                    until(lambda: window.folder_sizes.result(large) is not None)
                    window.folder_sizes.results[large] = (time.monotonic(), FolderSize(123, False, 'Some contents could not be read'))
                    window.folder_sizes.tick()
                    assert window.list_details.rows[large]['size'].get_text() == '≥ ' + format_size(123)
                    window.view_status.update([large])
                    until(lambda: 'known' in window.view_status.summary.get_text())
                    window.folder_sizes.results[large] = (time.monotonic(), FolderSize())
                    window.folder_sizes.tick()
                    assert window.list_details.rows[large]['size'].get_text() == 'Unavailable'
                    assert window.view_status.summary.get_text() == '1 folder · Size unavailable'
                    window.folder_sizes.results[large] = (0, FolderSize(999, True, ''))
                    window.folder_sizes.tick()
                    assert window.list_details.rows[large]['size'].get_text() == '…'
                    until(lambda: window.folder_sizes.result(large) is not None)
                    assert window.folder_sizes.result(large).total == 4096
                    if mode == 'browser' and palette_index == 0:
                        # The obsolete worker deliberately returns a success
                        # after cancellation; it must never reach the UI.
                        started = threading.Event()
                        original_reader = window.folder_sizes.worker.reader
                        def delayed(path, cancelled):
                            if path == large:
                                started.set()
                                while not cancelled():
                                    time.sleep(.005)
                                return FolderSize(999999, True, '')
                            return original_reader(path, cancelled)
                        window.folder_sizes.worker.reader = delayed
                        window.folder_sizes.invalidate()
                        window.view_status.update([])
                        window.view_status.update([large])
                        until(started.is_set)
                        window.view_status.update([small])
                        until(lambda: window.view_status.summary.get_text() == '1 folder · ' + format_size(1024))
                        assert window.folder_sizes.result(large) is None
                        window.folder_sizes.worker.reader = original_reader
                        window.folder_sizes.invalidate()
                        until(lambda: window.folder_sizes.result(large) is not None)
                    if directory := os.environ.get('FOLDER_SIZE_SCREENSHOTS'):
                        window.flow.unselect_all()
                        window.flow.select_child(window.children_by_path[large])
                        until(lambda: window.view_status.summary.get_text() == '1 folder · ' + format_size(4096))
                        snapshot = Gtk.Snapshot.new()
                        Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                        Path(directory).mkdir(parents=True, exist_ok=True)
                        window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(
                            str(Path(directory) / f'{mode}-{palette_index}.png'))
                finally:
                    worker = window.folder_sizes.worker
                    window.destroy(); settle()
                    worker.thread.join(2)
                    assert not worker.thread.is_alive()
                print('PASS:', mode, palette_index, flush=True)
print('PASS: sizes in all views/modes, thumbnail-only slider, centered multiple-folder totals, nested/hidden/link/empty contents, mixed selection, sort, refresh, partial errors, expiry and shutdown')
