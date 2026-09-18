"""Native search scope, async lifetime, result locations and picker regression.

PYTHONPATH=. python tests/ui_search_scope.py
SEARCH_QA_SCREENSHOTS=/tmp/gudfiles-search captures native active/light surfaces.
Searches use real subprocesses against disposable roots, never user files.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from omarchy_file_picker.model import PickerRequest, FileFilter
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from gi.repository import GLib, Gtk, Gio
from omarchy_file_picker.search import SearchResult
from omarchy_file_picker.theme import load_colors
from tests.test_theme import LIGHT_PALETTES

callback_errors = []
original_hook = sys.excepthook
def callback_error(kind, value, traceback):
    callback_errors.append(value)
    original_hook(kind, value, traceback)
sys.excepthook = callback_error


def settle(seconds=.1):
    loop = GLib.MainLoop()
    GLib.timeout_add(max(1, int(seconds * 1000)), lambda: loop.quit() or False)
    loop.run()


def wait_for(check, seconds=6):
    deadline = time.monotonic() + seconds
    while not check() and time.monotonic() < deadline:
        settle(.03)
    assert check(), 'Timed out waiting for native search state'
    settle(.1)


def search(window, text, scope):
    window.search.set_text(text)
    window.search_scope_buttons[scope].set_active(True)
    window.search.emit('activate')
    if scope == 'computer' and text.strip():
        wait_for(lambda: window.search_result is not None and not window.search_pending)
    else:
        settle(.2)


def capture(widget, name):
    target = os.environ.get('SEARCH_QA_SCREENSHOTS')
    if not target:
        return
    Path(target).mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        widget.queue_draw()
        settle(.1)
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(widget).snapshot(snapshot, widget.get_width(), widget.get_height())
        node = snapshot.to_node()
        if node:
            widget.get_native().get_renderer().render_texture(node, None).save_to_png(str(Path(target) / (name + '.png')))
            return
    raise AssertionError('Snapshot unavailable')


with tempfile.TemporaryDirectory(prefix='gudfiles-scope-ui-') as temp:
    root = Path(temp)
    here, elsewhere = root / 'Current folder', root / 'Another drive'
    here.mkdir()
    elsewhere.mkdir()
    nested = here / 'Subfolder'
    nested.mkdir()
    paths = [here / 'needle.txt', nested / 'needle.txt', elsewhere / 'needle.txt']
    for path in paths:
        path.write_text('Search fixture')
    folder = elsewhere / 'needle folder'
    folder.mkdir()
    (folder / 'contents.txt').touch()
    hidden = elsewhere / '.needle.txt'
    hidden.touch()
    app = PickerApplication(PickerRequest(current_folder=here), None)
    app.register(None)
    for theme, colors in [('active', load_colors()), ('light', next(iter(LIGHT_PALETTES.values())))]:
        with patch.object(Path, 'home', return_value=root), \
             patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
             patch('omarchy_file_picker.picker.load_colors', return_value=colors), \
             patch.object(PickerWindow, '_computer_search_roots', return_value=[str(here), str(elsewhere)]):
            window = PickerWindow(app, PickerRequest(current_folder=here, explorer=True, multiple=True), None)
            window.search_popover.set_autohide(False)
            window.present()
            settle(.3)
            try:
                # Constrain only this fixture window; never move a user's window.
                client = next(c for c in json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
                              if c['pid'] == os.getpid())
                selector = json.dumps('address:' + client['address'])
                if not client['floating']:
                    subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' + selector + '})'], check=True, capture_output=True)
                subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.resize({x=820,y=700,relative=false,window=' + selector + '})'], check=True, capture_output=True)
                settle(.3)
                window._open_search()
                settle(.2)
                assert window.search_scope_buttons['folder'].get_active()
                content = window.search_popover.get_child()
                for button in window.search_scope_buttons.values():
                    valid, bounds = button.compute_bounds(content)
                    assert button.get_mapped() and valid and bounds.get_x() >= 0
                    assert bounds.get_x() + bounds.get_width() <= content.get_width()
                capture(window.search_popover, theme + '-scope')
                for mode in ('grid', 'list', 'columns'):
                    window._set_view(mode)
                    search(window, 'needle', 'folder')
                    assert window.entries == [paths[0]], (mode, window.entries)
                    search(window, 'needle', 'computer')
                    assert set(window.entries) == {*paths, folder}, (mode, window.entries)
                    assert window.search_status.get_mapped()
                    assert '4 results' in window.search_status_label.get_text()
                    assert not window.search_spinner.get_visible()
                    for path in paths:
                        assert window.children_by_path[path].get_tooltip_text() == str(path)
                    # Rendering/sorting a broad result set must not re-stat slow
                    # drives on GTK's thread. File actions still recheck live data.
                    original_stat = Path.stat
                    selected_for_preview = set(window._selected_paths())
                    def stat(path, *args, **kwargs):
                        assert path not in window.entries or path in selected_for_preview, ('Result metadata read on UI thread', path)
                        return original_stat(path, *args, **kwargs)
                    with patch.object(Path, 'stat', stat):
                        window._show_computer_results(window.search_result)
                    assert not window._can_paste()
                    with patch.object(window, '_finish') as finish:
                        window.flow.select_child(window.children_by_path[paths[-1]])
                        with patch.object(Gio.AppInfo, 'launch_default_for_uri') as opened:
                            window._accept()
                            assert opened.call_args.args[0] == paths[-1].as_uri()
                        finish.assert_not_called()
                    window.flow.unselect_all()
                    window.flow.select_child(window.children_by_path[folder])
                    settle(.15)
                    if mode == 'columns':
                        assert len(window.columns.columns) == 1
                    window.flow.emit('child-activated', window.children_by_path[folder])
                    settle(.2)
                    assert window.current_dir == folder and not window.search.get_text()
                    assert not window.search_status.get_visible()
                    window.navigate(here)
                search(window, 'needle', 'computer')
                window._toggle_hidden(None)
                wait_for(lambda: window.search_result is not None)
                assert hidden in window.entries
                window._toggle_hidden(None)
                wait_for(lambda: window.search_result is not None)
                # Sort/view changes reuse results and keep the selected result.
                window.flow.select_child(window.children_by_path[paths[-1]])
                with patch.object(window.search_service, 'submit', wraps=window.search_service.submit) as submit:
                    window._set_sort('name', True)
                    window._set_view('list')
                    settle(.2)
                    submit.assert_not_called()
                    assert window._selected_paths() == [paths[-1]]
                capture(window, theme + '-results')
                searched = window.tabs.current
                window.tabs.new(here)
                settle(.2)
                assert window.search_scope == 'folder' and not window.search.get_text()
                window.tabs.select(searched)
                wait_for(lambda: window.search_result is not None)
                assert window.search_scope == 'computer' and window.search.get_text() == 'needle'
                assert window._selected_paths() == [paths[-1]]
                # Refresh notices real filesystem changes outside the original folder.
                paths[-1].unlink()
                window._refresh_files()
                wait_for(lambda: window.search_result is not None)
                assert paths[-1] not in window.entries
                paths[-1].write_text('Search fixture')
                # Exercise late callbacks after query edits, scope, tabs, clear and teardown.
                callbacks = []
                with patch.object(window.search_service, 'submit', side_effect=lambda options, callback: callbacks.append(callback)):
                    window.search.set_text('old query')
                    window.search.emit('activate')
                    assert window.search_pending and window.search_spinner.get_mapped()
                    old = callbacks[-1]
                    window.search.set_text('new query')
                    old(SearchResult(paths=[Path('/stale-result')]))
                    settle(.03)
                    assert Path('/stale-result') not in window.entries
                    window.search.emit('activate')
                    callbacks[-1](SearchResult(paths=[paths[0]], timed_out=True, skipped=1))
                    wait_for(lambda: window.search_result is not None)
                    assert 'incomplete' in window.search_status_label.get_text()
                    assert 'could not be read' in window.search_status_label.get_text()
                    window._refresh_files()
                    callbacks[-1](SearchResult(error='Fixture failed'))
                    wait_for(lambda: window.search_result is not None)
                    assert 'Fixture failed' in window.search_status_label.get_text()
                    assert window.browser_stack.get_visible_child_name() == 'empty'
                    window._refresh_files()
                    stale = callbacks[-1]
                    window._set_search_scope('folder')
                    stale(SearchResult(paths=[Path('/stale-result')]))
                    settle(.2)
                    assert Path('/stale-result') not in window.entries
                    window._set_search_scope('computer')
                    stale = callbacks[-1]
                    window.tabs.new(here)
                    stale(SearchResult(paths=[Path('/stale-result')]))
                    settle(.2)
                    assert not window.search_pending and Path('/stale-result') not in window.entries
                    window.search.set_text('teardown')
                    window._set_search_scope('computer')
                    teardown = callbacks[-1]
                search(window, 'needle', 'computer')
                window.active_filter_chips.get_first_child().emit('clicked')
                settle(.3)
                assert not window.search.get_text() and not window.search_status.get_visible()
                teardown(SearchResult(paths=[Path('/stale-result')]))
                settle(.1)
                assert Path('/stale-result') not in window.entries
                print('PASS:', theme, 'scopes, all views, locations, async cancellation, tabs, selection, sorting, hidden, refresh, partial/error/clear', flush=True)
            finally:
                window.destroy()
                settle(.1)
                window.search_service.worker.join(2)
                assert not window.search_service.worker.is_alive()

    with patch.object(Path, 'home', return_value=root), \
         patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
         patch.object(PickerWindow, '_computer_search_roots', return_value=[str(here), str(elsewhere)]):
        for mode, directory in [('open', False), ('open', True), ('save', False)]:
            window = PickerWindow(app, PickerRequest(current_folder=here, mode=mode, directory=directory,
                                                     filters=[FileFilter('Text', ((0, '*.txt'),))]), None)
            window.present()
            settle(.1)
            try:
                search(window, 'needle', 'computer')
                expected = {folder} if directory else {*paths, folder}
                assert set(window.entries) == expected
                with patch.object(window, '_finish') as finish:
                    if directory or mode == 'save':
                        assert not window.accept_button.get_sensitive()
                        window._accept()
                        finish.assert_not_called()
                    chosen = folder if directory else paths[-1]
                    window.flow.select_child(window.children_by_path[chosen])
                    window._accept()
                    if mode == 'save':
                        assert window.current_dir == elsewhere and not window.search.get_text()
                        assert window.filename_entry.get_text() == paths[-1].name
                        finish.assert_not_called()
                    else:
                        assert finish.call_args.kwargs['paths'] == [chosen]
            finally:
                window.destroy()
                settle(.1)
        print('PASS: Open file, directory picker and Save destination semantics', flush=True)
    assert not callback_errors, callback_errors
