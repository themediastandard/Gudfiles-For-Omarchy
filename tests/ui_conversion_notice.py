"""Real image conversion and a non-modal, geometry-neutral completion notice."""
import os
import tempfile
import time
from pathlib import Path

import cairo
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(100, lambda: loop.quit() or False)
    loop.run()


with tempfile.TemporaryDirectory(prefix='picker-conversion-') as temp:
    root = Path(temp)
    source = root / 'landscape.png'
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 240)
    context = cairo.Context(surface)
    context.set_source_rgb(.2, .45, .7)
    context.paint()
    surface.write_to_png(str(source))
    original = source.read_bytes()
    app = PickerApplication(PickerRequest(current_folder=root), None)
    app.register(None)
    window = PickerWindow(app, app.request, None)
    window._notify = lambda *_: None
    errors = []
    window._show_error = lambda *args: errors.append(args)
    window.present()
    settle()
    geometry = window.get_width(), window.get_height()
    try:
        window._convert_image(source, 'jpeg')
        deadline = time.monotonic() + 8
        while window.active_processes and time.monotonic() < deadline:
            settle()
        assert not window.active_processes and not errors, errors
        assert source.read_bytes() == original
        assert len(list(root.iterdir())) == 2
        assert window.conversion_notice.get_reveal_child()
        assert window.conversion_notice_filename.get_text() == window._selected_paths()[0].name
        settle()
        settle()
        assert (window.get_width(), window.get_height()) == geometry
        assert not any(w.get_visible() and w is not window for w in Gtk.Window.get_toplevels())
        capture = os.environ.get('CONVERSION_QA_SCREENSHOT')
        if capture:
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
            window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(capture)
        window._show_conversion_notice(root / ('long-name-' * 20 + '.jpg'))
        settle()
        assert (window.get_width(), window.get_height()) == geometry
        close = window.conversion_notice.get_child().get_last_child()
        close.emit('clicked')
        assert not window.conversion_notice.get_reveal_child()
        assert not window.conversion_notice_timer
        print('PASS: real conversion, preserved original, output selection, non-modal notice, long names, stable geometry and dismiss')
    finally:
        if hasattr(window, 'conversion_notice'):
            window._dismiss_conversion_notice()
        window.destroy()
