"""Native startup reveal and compositor checks using disposable files/settings."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import GLib, Gtk
from omarchy_file_picker.picker import PickerApplication, PickerWindow, parse_args


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(500, lambda: loop.quit() or False)
    loop.run()


with tempfile.TemporaryDirectory(prefix='gudfiles-reveal-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)):
    home = Path(temp)
    folder = home / 'Downloads'
    folder.mkdir()
    paths = [folder / f'{n:03d} - file.txt' for n in range(100)]
    for path in paths:
        path.write_text('Disposable reveal fixture.\n')
    hidden = folder / '.hidden.txt'
    hidden.touch()
    subfolder = folder / 'ZZ folder'
    subfolder.mkdir()
    symlink = folder / 'link.txt'
    symlink.symlink_to(paths[0])
    settings = home / '.config/omarchy-file-picker/preferences.json'
    settings.parent.mkdir(parents=True)
    app = PickerApplication(parse_args(['--external'])[0], None)
    app.register(None)
    for view in ('grid', 'list', 'columns'):
        settings.write_text(json.dumps({'view_mode': view, 'sort_key': 'name',
                                        'descending': False, 'folders_first': False}))
        for targets in ([paths[89]], [paths[89], paths[90]], [hidden], [subfolder], [symlink],
                        [folder / 'missing.txt']):
            args = ['--external']
            for target in targets:
                args.extend(['--select', str(target)])
            request, _ = parse_args(args)
            window = PickerWindow(app, request, None)
            window.present()
            settle()
            try:
                expected = [p for p in targets if p.exists()]
                assert window.current_dir == folder, (view, window.current_dir)
                assert window._selected_paths() == expected, (view, targets, window._selected_paths())
                assert not window.footer.get_visible()
                if expected:
                    child = window.children_by_path[expected[0]]
                    assert window.get_focus() is child, (view, 'focus differs from selection', window.get_focus())
                    valid, bounds = child.compute_bounds(window.file_scroller)
                    assert valid and bounds.get_y() >= -1, (view, bounds.get_y())
                    assert bounds.get_y() + bounds.get_height() <= window.file_scroller.get_height() + 1, \
                        (view, bounds.get_y(), bounds.get_height(), window.file_scroller.get_height())
                    if expected == [paths[89]] and window.is_active():
                        window.flow.emit('move-cursor', Gtk.MovementStep.VISUAL_POSITIONS, 1, False, False)
                        assert window._selected_paths() == [paths[90]], (view, 'next arrow')
                if os.environ.get('REVEAL_QA_HYPRLAND') == '1':
                    clients = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
                    client = next(c for c in clients if c['pid'] == os.getpid() and
                                  c['class'] == 'org.omarchy.FilePicker.External')
                    assert client['floating'], client
                print('PASS:', view, [p.name for p in targets], 'selected, visible, cursor ready')
            finally:
                window.destroy()
                settle()

    # Navigating before the first frame invalidates the queued launch reveal.
    request, _ = parse_args(['--select', str(paths[89])])
    window = PickerWindow(app, request, None)
    window.navigate(subfolder)
    window.present()
    settle()
    assert window.current_dir == subfolder and not window._selected_paths()
    window.destroy()
    print('PASS: startup reveal cannot replace later navigation')
