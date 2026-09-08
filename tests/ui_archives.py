"""ZIP double clicks, background completion/failures and picker semantics."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch
import zipfile

import gi
gi.require_version('GdkX11', '4.0')
from omarchy_file_picker.archives import extract_zip
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from gi.repository import Gio, GLib, Gtk, GdkX11


def settle(ms=200):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'GTK condition timed out'


assert os.environ.get('POINTER_QA_ISOLATED') == '1', 'Use a disposable Xvfb display.'
with tempfile.TemporaryDirectory(prefix='gudfiles-archives-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
        patch.object(PickerWindow, '_play_sound') as sound, \
        patch.object(PickerWindow, '_show_error') as error, \
        patch.object(Gio.AppInfo, 'launch_default_for_uri') as launch:
    root = Path(temp)
    parent = root / 'Archives'
    parent.mkdir()
    source = parent / 'Camera files.ZIP'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('nested/data.txt', 'actual extracted bytes')
        archive.writestr('empty/', '')
    original = source.read_bytes()
    other = root / 'Elsewhere'
    other.mkdir()
    request = PickerRequest(current_folder=parent, explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    xid = window.get_surface().get_xid()

    def double_click(path):
        settle(350)  # completion can rebuild rows before their next allocation
        child = window.children_by_path[path]
        valid, bounds = child.compute_bounds(window)
        assert valid
        dx, dy = window.get_surface_transform()
        subprocess.run([os.environ['XDOTOOL'], 'mousemove', '--window', str(xid),
                        str(round(bounds.get_x() + bounds.get_width() / 2 + dx)),
                        str(round(bounds.get_y() + bounds.get_height() / 2 + dy)),
                        'click', '--repeat', '2', '--delay', '80', '1'], check=True)
        settle()

    release = threading.Event()
    try:
        subprocess.run([os.environ['XDOTOOL'], 'windowfocus', str(xid)], check=True)
        for i, mode in enumerate(('grid', 'list', 'columns')):
            window.navigate(parent)
            window._set_view(mode)
            settle()
            double_click(source)
            until(lambda: not window.file_job_active)
            destination = parent / ('Camera files' if i == 0 else f'Camera files ({i})')
            assert (destination / 'nested/data.txt').read_text() == 'actual extracted bytes'
            assert (destination / 'empty').is_dir()
            assert source.read_bytes() == original
            assert destination in window.children_by_path
            assert window.conversion_notice.get_reveal_child()
            assert window.conversion_notice_headline.get_text() == 'Extraction complete'
            assert window.conversion_notice_filename.get_text() == destination.name
            launch.assert_not_called()
            error.assert_not_called()
            if mode == 'columns':
                settle(350)
                if screenshot := os.environ.get('ARCHIVES_QA_SCREENSHOT'):
                    snapshot = Gtk.Snapshot.new()
                    Gtk.WidgetPaintable.new(window.get_child()).snapshot(snapshot, window.get_width(), window.get_height())
                    window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(screenshot)
                subprocess.run([os.environ['XDOTOOL'], 'key', 'Up'], check=True)
                settle()
                assert window._selected_paths() == [window.entries[window.entries.index(source) - 1]]
                subprocess.run([os.environ['XDOTOOL'], 'key', 'Down'], check=True)
                settle()
                assert window._selected_paths() == [source]

        # A slow extraction remains a single operation, protects normal close,
        # and must not pull the user away from a different tab on completion.
        started = threading.Event()
        def slow(path):
            started.set()
            assert release.wait(5)
            return extract_zip(path)
        with patch('omarchy_file_picker.archives.extract_zip', side_effect=slow) as extractor:
            double_click(source)
            until(started.is_set)
            assert window.conversion_notice.get_reveal_child()
            assert window.conversion_notice_headline.get_text() == 'Extracting ZIP…'
            assert window.conversion_notice_spinner.get_spinning()
            assert not window.conversion_notice_timer
            double_click(source)
            assert extractor.call_count == 1 and window.file_job_active
            with patch.object(app, 'quit') as quit_app:
                window._finish(cancelled=True)
                quit_app.assert_not_called()
            window.tabs.new(other)
            settle()
            assert window.current_dir == other
            release.set()
            until(lambda: not window.file_job_active)
            assert window.current_dir == other
            assert (parent / 'Camera files (3)/nested/data.txt').read_text() == 'actual extracted bytes'

        window.navigate(parent)
        settle()
        broken = parent / 'Broken.zip'
        broken.write_text('invalid')
        window._refresh_files()
        settle()
        window._dismiss_conversion_notice()
        error.reset_mock()
        sound.reset_mock()
        double_click(broken)
        until(lambda: not window.file_job_active)
        error.assert_called_once()
        sound.assert_not_called()
        assert not (parent / 'Broken').exists()
        assert not list(parent.glob('.gudfiles-extract-*'))
        assert not window.conversion_notice.get_reveal_child()

        # FileChooser Open/Save retain the ZIP as the returned selection.
        for mode in ('open', 'save'):
            picker = PickerWindow(app, PickerRequest(current_folder=parent, mode=mode), None)
            try:
                picker.present()
                settle()
                picker.flow.select_child(picker.children_by_path[source])
                with patch.object(picker, '_accept') as accept, patch.object(picker, '_extract_zip') as extract:
                    picker._on_child_activated(picker.flow, picker.children_by_path[source])
                    accept.assert_called_once()
                    extract.assert_not_called()
            finally:
                picker.destroy()
        print('PASS: physical ZIP double clicks in all views, real bytes, collision names, notice, duplicate/close guard, tab navigation, failure cleanup and picker selection')
    finally:
        release.set()
        window.destroy()
