"""Native bounded summary/details card QA, isolated from user media/preferences."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.media_details import MediaDetailsService, make_details_widget


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(60, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'GTK metadata condition timed out'


with tempfile.TemporaryDirectory(prefix='picker-details-') as temporary, patch.object(Path, 'home', return_value=Path(temporary)):
    root = Path(temporary)
    movie = root / 'shot-01.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=160x96:rate=24', '-f', 'lavfi', '-i',
                    'anullsrc=r=48000:cl=stereo', '-t', '1', '-c:v', 'libx264',
                    '-threads', '1', '-c:a', 'aac', str(movie)], check=True, timeout=20)
    request = PickerRequest(current_folder=root)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    until(window.get_mapped)
    settle()
    settle()
    service = MediaDetailsService()
    try:
        baseline = (window.get_width(), window.get_height(), window.metadata_viewport.get_height())
        window._update_metadata(movie)
        # Exercise this helper regardless of whether root integration has landed.
        facts = window.metadata.get_last_child()
        row = make_details_widget(service, movie)
        facts.append(row)
        summary, button = row.get_first_child(), row.get_last_child()
        until(button.get_visible)
        assert '160 × 96' in summary.get_text()
        assert summary.get_max_width_chars() == 20
        assert 'Audio codec: AAC' in summary.get_tooltip_text()
        button.popup()
        until(lambda: button.get_popover().get_mapped())
        settle()
        settle()
        actual = (window.get_width(), window.get_height(), window.metadata_viewport.get_height())
        assert actual == baseline, (baseline, actual)
        assert button.get_popover().get_height() < 480
        assert button.get_popover().get_width() < 600
        card = button.get_popover().get_child()
        grid = card.get_last_child().get_child().get_child()
        assert grid.get_child_at(1, 0).get_text() == '160 × 96'
        assert not grid.get_child_at(1, 0).get_layout().is_ellipsized()
        if os.environ.get('MEDIA_QA_SCREENSHOT'):
            popover = button.get_popover()
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(popover).snapshot(snapshot, popover.get_width(), popover.get_height())
            texture = popover.get_native().get_renderer().render_texture(snapshot.to_node(), None)
            texture.save_to_png(os.environ['MEDIA_QA_SCREENSHOT'])
        button.popdown()
        until(lambda: not button.get_popover().get_visible())
        print('PASS: real asynchronous media summary, complete tooltip, bounded details card and stable window geometry')
    finally:
        service.close()
        window.destroy()
