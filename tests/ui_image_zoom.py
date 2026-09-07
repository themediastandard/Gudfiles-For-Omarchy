"""Exercise real GTK controllers and rendering; no physical mouse injection."""
import math
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

import cairo
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.image_preview import ZoomImage


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(50, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'GTK condition timed out'


with tempfile.TemporaryDirectory(prefix='picker-zoom-') as temp, patch.object(Path, 'home', return_value=Path(temp)):
    root = Path(temp)
    for name, width, height in [('wide', 800, 500), ('tall', 100, 1600)]:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = cairo.Context(surface)
        context.set_source_rgb(.1, .5, .7)
        context.paint()
        context.set_source_rgb(.9, .5, .1)
        context.rectangle(0, 0, width / 2, height / 2)
        context.fill()
        surface.write_to_png(str(root / (name + '.png')))
    request = PickerRequest(current_folder=root)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    until(window.get_mapped)
    preview = window.quicklook
    try:
        for name in ('wide', 'tall'):
            preview.show_file(root / (name + '.png'))
            loader = preview.content.get_first_child().get_first_child()
            assert isinstance(loader, Gtk.Spinner) and loader.get_spinning()
            until(lambda: preview.kind == 'image' and preview.progress == 1)
            view = preview.content.get_first_child()
            assert isinstance(view, ZoomImage)
            until(lambda: view.get_width() > 0)
            baseline = (window.get_width(), window.get_height(), preview.rect,
                        view.get_width(), view.get_height())
            measure = view.measure(Gtk.Orientation.HORIZONTAL, -1)[:2]
            assert view.zoom == 1 and view.offset == (0, 0)
            view._motion(None, view.get_width() / 2, view.get_height() / 2)
            assert view.scroll.emit('scroll', 0.0, -4.0)
            assert 1 < view.zoom < 8
            # The image coordinate beneath the pointer stays anchored on zoom.
            px, py = view.get_width() / 2, view.get_height() * .55
            def coordinate():
                iw, ih = view.image_size()
                return ((px - (view.get_width() - iw) / 2 - view.offset[0]) / iw,
                        (py - (view.get_height() - ih) / 2 - view.offset[1]) / ih)
            before = coordinate()
            view._motion(None, px, py)
            view.scroll.emit('scroll', 0.0, -.25)
            assert all(math.isclose(a, b, abs_tol=1e-6) for a, b in zip(before, coordinate()))
            view.drag.emit('drag-begin', px, py)
            view.drag.emit('drag-update', 100000.0, -100000.0)
            view.drag.emit('drag-end', 100000.0, -100000.0)
            iw, ih = view.image_size()
            assert view.offset == (max(0, (iw - view.get_width()) / 2),
                                   -max(0, (ih - view.get_height()) / 2))
            view.scroll.emit('scroll', 0.0, -1000.0)
            assert view.zoom == 8
            settle()
            assert baseline == (window.get_width(), window.get_height(), preview.rect,
                                view.get_width(), view.get_height())
            assert view.measure(Gtk.Orientation.HORIZONTAL, -1)[:2] == measure == (0, 0)
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(view).snapshot(snapshot, view.get_width(), view.get_height())
            node = snapshot.to_node()
            bounds = node.get_bounds()
            assert bounds.get_x() >= 0 and bounds.get_y() >= 0
            assert bounds.get_x() + bounds.get_width() <= view.get_width() + .01
            assert bounds.get_y() + bounds.get_height() <= view.get_height() + .01
            rendered = window.get_renderer().render_texture(node, None)
            assert rendered.get_width() > 0 and rendered.get_height() > 0
            view.click.emit('pressed', 2, px, py)
            assert view.zoom == 1 and view.offset == (0, 0)
            view.scroll.emit('scroll', 0.0, -3.0)
            view.scroll.emit('scroll', 0.0, 1000.0)
            assert view.zoom == 1 and view.offset == (0, 0)
            view.scroll.emit('scroll', 0.0, -3.0)
            preview.close()
            until(lambda: not preview.get_visible())
        preview.show_file(root / 'wide.png')
        until(lambda: preview.kind == 'image')
        assert preview.content.get_first_child().zoom == 1
        preview.close()
        until(lambda: not preview.get_visible())
        print('PASS: loading spinner, wheel/smooth zoom, pointer anchoring, limits, pan bounds, reset, clipped rendering, stable layout and fresh-file fit')
    finally:
        window.destroy()
