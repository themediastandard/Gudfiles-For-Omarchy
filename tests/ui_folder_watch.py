"""External filesystem changes through real GIO monitors and native GTK views.

Use an explicitly isolated Xvfb display and POINTER_QA_ISOLATED=1.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkX11', '4.0')
from gi.repository import Gio, GLib, GdkX11
from omarchy_file_picker.list_navigation import focus_file
from omarchy_file_picker.hover_scrub import HoverScrub
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow


errors = []
def report_error(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = report_error


def settle(ms=180):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()
    assert not errors, 'GTK callback failed'


def until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        settle(80)
    assert predicate(), 'Folder monitor condition timed out'
    settle()


assert os.environ.get('POINTER_QA_ISOLATED') == '1', 'Use an isolated Xvfb display.'
GLib.set_application_name('Gudfiles Folder Refresh QA')
with tempfile.TemporaryDirectory(prefix='gudfiles-watch-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]):
    home = Path(temp)
    root = home / 'Files'
    root.mkdir()
    files = [root / f'{index:03}-notes.txt' for index in range(90)]
    for path in files:
        path.write_text('Disposable external-refresh fixture')
    video = root / '000-video.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', 'color=c=blue:size=160x90:rate=4',
                    '-t', '1', '-an', '-c:v', 'libx264', '-threads', '1', str(video)],
                   check=True, timeout=20)
    request = PickerRequest(current_folder=root, explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle(350)
    xid = window.get_surface().get_xid()

    def key(name):
        subprocess.run([os.environ.get('XDOTOOL', 'xdotool'), 'windowfocus', str(xid)], check=True)
        subprocess.run([os.environ.get('XDOTOOL', 'xdotool'), 'key', '--clearmodifiers', name], check=True)
        settle()

    try:
        for mode in ('grid', 'list', 'columns'):
            window.navigate(root)
            window._set_view(mode)
            settle(350)
            selected = files[40]
            window.flow.unselect_all()
            window.flow.select_child(window.children_by_path[selected])
            focus_file(window, window.children_by_path[selected])
            settle(350)
            scroll = window.file_scroller.get_vadjustment().get_value()
            assert scroll > 0, (mode, 'fixture must be scrolled')
            added = root / f'zz-added-{mode}.txt'
            added.write_text('Created by another application')
            until(lambda: added in window.children_by_path)
            assert window._selected_paths() == [selected], (mode, window._selected_paths())
            assert getattr(window.get_focus(), '_picker_path', None) == selected, (mode, 'focus')
            assert abs(window.file_scroller.get_vadjustment().get_value() - scroll) < 2, (mode, 'scroll')
            if mode == 'list':
                # Content changes invalidate visible size/time metadata as well
                # as membership; a successful create alone cannot prove this.
                selected.write_text('Changed outside Gudfiles' * 300)
                until(lambda: window.list_details.data.get(selected, {}).get('size') == selected.stat().st_size)
                assert window._selected_paths() == [selected]
            key('Down')
            assert window._selected_paths() != [selected], (mode, 'stale GTK cursor')
            renamed = added.with_name(added.stem + '-renamed.txt')
            added.rename(renamed)
            until(lambda: renamed in window.children_by_path and added not in window.children_by_path)
            renamed.unlink()
            until(lambda: renamed not in window.children_by_path)
            # A background refresh must not move focus out of an editable control.
            window._toggle_path_entry(None)
            settle()
            assert window.path_entry.get_mapped()
            window.path_entry.set_text('/a/location/still/being/typed')
            settle()
            key('Home')
            key('shift+End')
            selected_text = (0, len(window.path_entry.get_text()))
            assert window.path_entry.get_selection_bounds() == selected_text, window.path_entry.get_selection_bounds()
            focus = window.get_focus()
            assert focus is window.path_entry or focus.is_ancestor(window.path_entry)
            added.touch()
            until(lambda: added in window.children_by_path)
            assert window.get_focus() is focus, (mode, 'editable focus stolen')
            assert window.path_entry.get_text() == '/a/location/still/being/typed'
            assert window.path_entry.get_selection_bounds() == selected_text, window.path_entry.get_selection_bounds()
            window._toggle_path_entry(None)
            added.unlink()
            until(lambda: added not in window.children_by_path)
            print(mode, 'external create/rename/delete, selection, scroll, cursor and text focus: PASS')

        window._set_view('columns')
        parent = root / 'Parent'
        child = parent / 'Child'
        child.mkdir(parents=True)
        for index in range(80):
            (child / f'{index:03}.txt').touch()
        until(lambda: parent in window.children_by_path)
        window.columns.enter_folder(window.columns.active, parent)
        settle()
        window.columns.enter_folder(window.columns.active, child)
        settle(300)
        assert [column.path for column in window.columns.columns] == [root, parent, child]
        focused = child / '050.txt'
        window.flow.unselect_all()
        window.flow.select_child(window.children_by_path[focused])
        focus_file(window, window.children_by_path[focused])
        settle(350)
        columns = list(window.columns.columns)
        positions = [column.scroller.get_vadjustment().get_value() for column in columns]
        horizontal = window.columns.get_hadjustment().get_value()
        sibling = parent / 'Sibling.txt'
        sibling.touch()
        until(lambda: sibling in columns[1].children)
        assert window.columns.columns == columns, 'Ancestor refresh rebuilt column trail'
        assert window.current_dir == child and window._selected_paths() == [focused]
        assert getattr(window.get_focus(), '_picker_path', None) == focused
        assert [column.scroller.get_vadjustment().get_value() for column in columns] == positions
        assert window.columns.get_hadjustment().get_value() == horizontal
        key('Down')
        # Removing an open descendant keeps the surviving parent usable.
        for path in child.iterdir():
            path.unlink()
        child.rmdir()
        until(lambda: len(window.columns.columns) == 2)
        assert window.current_dir == parent
        assert child not in window.children_by_path
        key('Down')
        print('columns ancestor refresh and removed open directory: PASS')

        window.navigate(root)
        window._set_view('grid')
        settle()
        window.flow.unselect_all()
        window.flow.select_child(window.children_by_path[video])
        focus_file(window, window.children_by_path[video])
        settle(350)
        def descendants(widget):
            yield widget
            child = widget.get_first_child()
            while child:
                yield from descendants(child)
                child = child.get_next_sibling()
        scrub = next(item for item in descendants(window.children_by_path[video])
                     if isinstance(item, HoverScrub))
        scrub.motion.emit('enter', 20.0, 20.0)
        until(lambda: scrub.frame is not None)
        during_hover = root / 'while-skimming.txt'
        during_hover.touch()
        settle(850)
        assert during_hover not in window.children_by_path, 'Refresh interrupted active video skimming'
        assert scrub.active and scrub.frame is not None and HoverScrub.active_for(window)
        scrub.motion.emit('leave')
        until(lambda: during_hover in window.children_by_path)
        assert not HoverScrub.active_for(window)
        print('external changes defer until video skim leaves: PASS')
        window._set_view('list')
        settle()
        previous_tab = window.tabs.current
        window.file_job_active = True
        pending = root / 'pending.txt'
        pending.touch()
        settle(550)
        assert pending not in window.children_by_path, 'Refresh raced active file operation'
        window.tabs.new(parent)
        window.file_job_active = False
        settle(700)
        assert window.current_dir == parent and pending not in window.children_by_path
        assert set(window.folder_watch.monitors) == {parent}
        window.tabs.select(previous_tab)
        settle(500)
        assert pending in window.children_by_path
        window._open_recent()
        assert not window.folder_watch.monitors
        vanished = home / 'Reconnected'
        vanished.mkdir()
        window.navigate(vanished)
        vanished.rmdir()
        until(lambda: window.empty_title.get_text() == 'Folder unavailable')
        vanished.mkdir()
        restored = vanished / 'restored.txt'
        restored.touch()
        until(lambda: restored in window.children_by_path)
        assert not window.folder_watch.missing
        window.navigate(root)
        assert set(window.folder_watch.monitors) == {root}
        watch = window.folder_watch
        window.destroy()
        settle()
        assert watch.closed and not watch.monitors and not watch.timer and not watch.retry_timer
        print('busy deferral, tab invalidation, special views and close cleanup: PASS')
    finally:
        window.destroy()
        settle()
