"""Regression: navigation and long paths must not grow the chooser window."""
from pathlib import Path
import tempfile
import json
import os
import subprocess
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(200, lambda: loop.quit() or False)
    loop.run()


with tempfile.TemporaryDirectory(prefix='picker-layout-') as temp:
    root = Path(temp)
    folders = [root]
    for number in range(7):
        folder = folders[-1] / (f'Level-{number}-' + 'long-folder-name-' * 3)
        folder.mkdir()
        (folder / ('long-file-name-' * 12 + '.txt')).write_text('fixture')
        (folder / ('custom.' + 'extension' * 15)).write_text('fixture')
        folders.append(folder)
    request = PickerRequest(current_folder=root)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    baseline = window.get_width(), window.get_height()
    sizes = []
    try:
        for mode in ('grid', 'list'):
            window._set_view(mode)
            for folder in folders[1:]:
                window.navigate(folder)
                settle()
                size = window.get_width(), window.get_height()
                sizes.append(size)
                print(mode, 'depth', len(folder.relative_to(root).parts), 'size', size,
                      'minimum width', window.measure(Gtk.Orientation.HORIZONTAL, -1)[0], flush=True)
                for file in (p for p in window.entries if p.is_file()):
                    window.flow.select_child(window.children_by_path[file])
                    settle()
                    sizes.append((window.get_width(), window.get_height()))
            for folder in reversed(folders):
                window.navigate(folder)
                settle()
                sizes.append((window.get_width(), window.get_height()))
        assert all(size == baseline for size in sizes), (baseline, sizes)
        # Target this fixture's exact native window, never the user's active one.
        clients = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
        client = next(c for c in clients if c['pid'] == os.getpid() and c['class'] == 'org.omarchy.FilePicker')
        selector = json.dumps('address:' + client['address'])
        subprocess.run(['hyprctl', 'dispatch',
                        'hl.dsp.window.resize({x=1040,y=680,relative=false,window=' + selector + '})'], check=True)
        settle()
        resized = window.get_width(), window.get_height()
        assert resized == (1040, 680), resized
        for folder in (folders[-1], root, folders[-2]):
            window.navigate(folder)
            settle()
            assert (window.get_width(), window.get_height()) == resized
        adjustment = window.path_scroll.get_hadjustment()
        assert abs(adjustment.get_value() - (adjustment.get_upper() - adjustment.get_page_size())) < 1
        assert window.path_entry.get_text() == str(folders[-2])
        print('PASS: stable window size in grid/list, nested folders, long filenames, metadata and back navigation')
    finally:
        window.destroy()
