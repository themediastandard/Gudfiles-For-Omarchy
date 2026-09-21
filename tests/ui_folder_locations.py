"""Favorites/MRU through native menus and real picker modes; disposable data only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gio, GLib, Gtk
from omarchy_file_picker.folder_locations import FolderLocations
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors
from tests.test_theme import LIGHT_PALETTES

if os.environ.get('POINTER_QA_ISOLATED') == '1':
    gi.require_version('GdkX11', '4.0')
    from gi.repository import GdkX11

errors = []
def exception(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = exception


def settle(ms=120):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()
    assert not errors


def until(predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate()


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


def labels(widget):
    return [w.get_label() for w in descendants(widget) if isinstance(w, Gtk.Label)]


def choose(window, text):
    button = next(w for w in descendants(window.context_popover)
                  if isinstance(w, Gtk.Button) and text in labels(w))
    assert button.get_sensitive()
    button.emit('clicked')
    settle()


def shortcuts(window, kind):
    return [b._picker_path for b in window.location_buttons if b._sidebar_kind == kind]


def right_click(window, path):
    if os.environ.get('POINTER_QA_ISOLATED') != '1':
        window._show_context_menu(30, 30, path)
        return
    tool = os.environ['XDOTOOL']
    xid = str(window.get_surface().get_xid())
    subprocess.run([tool, 'windowfocus', xid], check=True)
    geometry = subprocess.check_output([tool, 'getwindowgeometry', '--shell', xid], text=True)
    origin = dict(line.split('=', 1) for line in geometry.splitlines())
    valid, bounds = window.children_by_path[path].compute_bounds(window)
    assert valid
    dx, dy = window.get_surface_transform()
    x = round(int(origin['X']) + dx + bounds.get_x() + 15)
    y = round(int(origin['Y']) + dy + bounds.get_y() + bounds.get_height()/2)
    subprocess.run([tool, 'mousemove', str(x), str(y), 'click', '3'], check=True)
    until(lambda: window.context_popover is not None)


GLib.set_application_name('Gudfiles Folder Locations QA')
with tempfile.TemporaryDirectory(prefix='gudfiles-folders-') as temp:
    root = Path(temp)
    folders = [root / ('Folder ' + str(i)) for i in range(8)]
    for folder in folders:
        folder.mkdir()
        (folder / 'file.txt').write_text('fixture')
    app = PickerApplication(PickerRequest(current_folder=root), None)
    app.register(None)
    for mode in ('browser', 'open', 'save', 'folder'):
        for palette_name, palette in (('active', load_colors()), ('light', LIGHT_PALETTES['latte'])):
            home = root / (mode + palette_name)
            with patch.object(Path, 'home', return_value=home), \
                 patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
                 patch('omarchy_file_picker.picker.load_colors', return_value=palette):
                bookmark_file = home / '.config/gtk-3.0/bookmarks'
                bookmark_file.parent.mkdir(parents=True)
                original_bookmarks = folders[7].as_uri() + ' Shared bookmark\n'
                bookmark_file.write_text(original_bookmarks)
                request = PickerRequest(current_folder=root, explorer=mode == 'browser',
                                        mode='save' if mode == 'save' else 'open', directory=mode == 'folder')
                results = []
                window = PickerWindow(app, request, None, on_result=results.append)
                failures = []
                window._show_error = lambda *args: failures.append(args)
                window.present(); settle()
                assert shortcuts(window, 'favorite') == []
                assert shortcuts(window, 'recent-folder') == []
                for view in ('grid', 'list', 'columns'):
                    window.navigate(root)
                    window._set_view(view); settle()
                    target = folders[1]
                    window.flow.select_child(window.children_by_path[target]); settle()
                    before = window._selected_paths()
                    right_click(window, target)
                    choose(window, 'Add to Favorites')
                    assert shortcuts(window, 'favorite') == [target]
                    assert window._selected_paths() == before
                    favorite = next(b for b in window.location_buttons if b._sidebar_kind == 'favorite')
                    window._show_sidebar_context_menu(30, 30, favorite)
                    choose(window, 'Remove from Favorites')
                    assert shortcuts(window, 'favorite') == []
                    assert (target / 'file.txt').read_text() == 'fixture'
                    window._show_context_menu(30, 30, target)
                    choose(window, 'Add to Favorites')
                    # Verify new-window persistence and cross-window updates.
                    peer = PickerWindow(app, request, None, on_result=lambda _: None)
                    peer.present(); settle()
                    assert shortcuts(peer, 'favorite') == [target]
                    window._set_favorite(target, False)
                    until(lambda: shortcuts(peer, 'favorite') == [])
                    peer.destroy(); settle()
                    for folder in folders:
                        window.navigate(folder)
                    expected = list(reversed(folders[-5:]))
                    assert window.folder_locations.read()[1] == expected
                    # Programmatic selection restoration, refresh, sort and view
                    # changes must not turn a passive reload into another visit.
                    window._refresh_files(); settle()
                    assert window.folder_locations.read()[1] == expected
                    window._copy_files([folders[2] / 'file.txt'])
                    assert window.folder_locations.read()[1] == [folders[2], *expected[:4]]
                    window._copy_files([folders[0] / 'file.txt'], record=False)
                    assert window.folder_locations.read()[1] == [folders[2], *expected[:4]]
                    until(lambda: shortcuts(window, 'recent-folder') == [folders[2], *expected[:4]])
                    recent = next(b for b in window.location_buttons
                                  if b._sidebar_kind == 'recent-folder' and b._picker_path == folders[2])
                    window._show_sidebar_context_menu(30, 30, recent)
                    choose(window, 'Remove from Recents')
                    assert shortcuts(window, 'recent-folder') == expected[:4]
                    window._refresh_files(); settle()
                    assert window.folder_locations.read()[1] == expected[:4]
                    assert (folders[2] / 'file.txt').read_text() == 'fixture'
                    window.navigate(root)
                    window._set_favorite(target, True)
                    if view == 'columns':
                        window.flow.select_child(window.children_by_path[folders[3]])
                        settle()
                        assert window.folder_locations.read()[1][0] == folders[3]
                    window._set_favorite(target, False)
                window._set_favorite(folders[1], True)
                window._set_favorite(folders[2], True)
                window.navigate(folders[4]); settle()
                window._update_folder_sections()
                window.set_default_size(820, 700); settle()
                directory = os.environ.get('FOLDER_LOCATIONS_SCREENSHOTS')
                if directory:
                    out = Path(directory); out.mkdir(parents=True, exist_ok=True)
                    snapshot = Gtk.Snapshot.new()
                    Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                    window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(
                        str(out / f'{mode}-{palette_name}.png'))
                assert bookmark_file.read_text() == original_bookmarks
                window.quicklook.show_file(folders[6] / 'file.txt'); settle()
                assert window.folder_locations.read()[1][0] == folders[6]
                window.quicklook.close(); settle()
                window._apply_annotation([folders[5] / 'file.txt'], stars=3); settle()
                assert window.folder_locations.read()[1][0] == folders[5]
                # Failed favorites writes remain visibly unchanged and removable
                # shortcuts can refer to disconnected folders without deletion.
                with patch.object(window.folder_locations, 'set_favorite', side_effect=OSError('fixture full disk')):
                    window._set_favorite(folders[0], True)
                assert failures.pop()[0] == 'Could not update Favorites'
                assert folders[0] not in shortcuts(window, 'favorite')
                with patch.object(window.folder_locations, 'touch', side_effect=OSError('fixture full disk')):
                    window._copy_files([folders[0] / 'file.txt'])
                window._update_folder_sections()
                assert 'Could not save recent folders' in labels(window.sidebar)
                window._copy_files([folders[0] / 'file.txt'])
                window._update_folder_sections()
                assert 'Could not save recent folders' not in labels(window.sidebar)
                missing = root / 'disconnected'
                window._set_favorite(missing, True)
                button = next(b for b in window.location_buttons if getattr(b, '_picker_path', None) == missing)
                button.emit('clicked')
                assert failures.pop()[0] == 'Folder unavailable'
                window._set_favorite(missing, False)
                assert not failures
                # Choosing from a folder must win even when another folder was
                # used more recently in a different window.
                file = folders[4] / 'file.txt'
                if mode == 'save':
                    window.filename_entry.set_text('new.txt')
                    chosen = folders[4] / 'new.txt'
                elif mode == 'folder':
                    chosen = folders[4]
                else:
                    window.flow.select_child(window.children_by_path[file]); settle()
                    chosen = file
                window._record_recent_folders([folders[7]])
                if mode == 'browser':
                    with patch.object(Gio.AppInfo, 'launch_default_for_uri', return_value=True):
                        window._accept()
                    assert window.folder_locations.read()[1][0] == folders[4]
                    window.destroy()
                else:
                    window._accept()
                    assert results == [[chosen]], results
                    assert window.folder_locations.read()[1][0] == folders[4]
                settle()
                print('PASS:', mode, palette_name, 'all views; persistence, MRU, menus, failures and picker result', flush=True)
    assert not errors
