"""Creative workflow integration with isolated files/preferences/annotation DB."""
from pathlib import Path
import os
import tempfile
import time
from unittest.mock import patch

import cairo
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.ratings import RatingStore


def settle(ms=80):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'GTK state timed out'


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


def capture(widget, owner, path):
    # Screenshot generation needs an unobscured, actively rendered test window;
    # keep it opt-in, like other native visual QA, while behavior checks always run.
    if os.environ.get('CREATIVE_QA_SCREENSHOTS') != '1':
        return
    for _ in range(30):
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(widget).snapshot(snapshot, widget.get_width(), widget.get_height())
        node = snapshot.to_node()
        if node is not None:
            owner.get_renderer().render_texture(node, None).save_to_png(path)
            return
        settle()
    raise AssertionError(f'No rendered snapshot for {path}: mapped={widget.get_mapped()}, visible={widget.get_visible()}, '
                         f'size={widget.get_width()}x{widget.get_height()}, active={owner.is_active()}')


with tempfile.TemporaryDirectory(prefix='picker-creative-') as temp, patch.object(Path, 'home', return_value=Path(temp)):
    root = Path(temp)
    folder = root / 'Reference'
    folder.mkdir()
    paths = []
    for i, name in enumerate(('Mountain drive', 'Coastal sunset', 'Studio portrait', 'City at night')):
        path = root / (name + '.png')
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 800, 500)
        cr = cairo.Context(surface)
        gradient = cairo.LinearGradient(0, 0, 800, 500)
        gradient.add_color_stop_rgb(0, .12 + i * .1, .18, .28)
        gradient.add_color_stop_rgb(1, .5, .65 - i * .12, .6)
        cr.set_source(gradient)
        cr.paint()
        surface.write_to_png(str(path))
        paths.append(path)
    before = {p: p.read_bytes() for p in paths}
    request = PickerRequest(current_folder=root, multiple=True, explorer=True, title='Files')
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    until(window.get_mapped)
    try:
        for path in paths[:2]:
            window.flow.select_child(window.children_by_path[path])
        star = next(w for w in descendants(window.metadata) if isinstance(w, Gtk.Button)
                    and (w.get_tooltip_text() or '').startswith('4 stars'))
        star.emit('clicked')
        settle()
        palette = next(w for w in descendants(window.metadata) if isinstance(w, Gtk.MenuButton)
                       and (w.get_tooltip_text() or '').startswith('Color label'))
        palette.popup()
        until(lambda: palette.get_popover().get_mapped())
        blue = next(w for w in descendants(palette.get_popover()) if isinstance(w, Gtk.Button)
                    and w.get_tooltip_text() == 'Blue')
        blue.emit('clicked')
        settle()
        assert all(window.ratings.get(p) == (4, 'blue', False) for p in paths[:2])
        assert set(window._selected_paths()) == set(paths[:2])
        window.children_by_path[paths[0]].grab_focus()
        assert window._on_key_pressed(None, Gdk.KEY_5, 0, Gdk.ModifierType(0))
        settle()
        assert all(window.ratings.get(p)[0] == 5 for p in paths[:2])
        window.search.grab_focus()
        assert not window._on_key_pressed(None, Gdk.KEY_1, 0, Gdk.ModifierType(0))
        window._apply_annotation([paths[2]], rejected=True)
        settle()
        window.creative_filter = ('rated', 4, 'blue')
        window._refresh_files()
        assert set(window.entries) == {folder, *paths[:2]}
        window.creative_filter = ('rejected', 0, '')
        window._refresh_files()
        assert set(window.entries) == {folder, paths[2]}
        window.creative_filter = ('all', 0, '')
        window._refresh_files([paths[0]])
        until(lambda: any(isinstance(w, Gtk.MenuButton) and w.get_tooltip_text() == 'Media details'
                          and w.get_visible() for w in descendants(window.metadata)))
        assert not window.footer.get_visible() if hasattr(window, 'footer') else True
        initial = (window.get_width(), window.get_height(), window.metadata_viewport.get_height())
        window.quicklook.show_file(paths[0])
        until(lambda: window.quicklook.kind == 'image' and window.quicklook.progress == 1)
        assert window._on_preview_key(None, Gdk.KEY_3, 0, Gdk.ModifierType(0))
        settle()
        assert window.ratings.get(paths[0])[0] == 3
        capture(window.quicklook.card, window, '/tmp/omarchy-creative-preview.png')
        window.quicklook.close()
        until(lambda: not window.quicklook.get_visible())
        assert initial == (window.get_width(), window.get_height(), window.metadata_viewport.get_height())
        capture(window, window, '/tmp/omarchy-creative-browser.png')
        filter_button = next(w for w in descendants(window.toolbar) if isinstance(w, Gtk.MenuButton)
                             and w.get_tooltip_text() == 'Filter by rating and color')
        assert filter_button.get_popover().get_autohide()
        filter_button.popup()
        until(lambda: filter_button.get_popover().get_mapped())
        settle(200)
        capture(filter_button.get_popover().get_child(), window, '/tmp/omarchy-creative-filter.png')
        filter_button.popdown()
        until(lambda: not filter_button.get_popover().get_mapped())
        settle(200)
        info = next(w for w in descendants(window.metadata) if isinstance(w, Gtk.MenuButton)
                    and w.get_tooltip_text() == 'Media details')
        until(lambda: info.get_mapped() and info.is_sensitive())
        assert info.get_popover().get_autohide()
        info.popup()
        until(lambda: info.get_popover().get_mapped())
        settle(200)
        capture(info.get_popover().get_child(), window, '/tmp/omarchy-creative-details.png')
        info.popdown()
        until(lambda: not info.get_popover().get_mapped())
        persisted = RatingStore(window.ratings.database)
        persisted.refresh(paths)
        assert persisted.get(paths[0]) == (3, 'blue', False)
        assert all(p.read_bytes() == content for p, content in before.items())
        window.creative_filter = ('rated', 1, '')
        window._refresh_files([paths[0]])
        window.quicklook.show_file(paths[0])
        until(lambda: window.quicklook.kind == 'image' and window.quicklook.progress == 1)
        window._on_preview_key(None, Gdk.KEY_x, 0, Gdk.ModifierType(0))
        until(lambda: window.quicklook.path == paths[1] and window.quicklook.kind == 'image')
        window._on_preview_key(None, Gdk.KEY_x, 0, Gdk.ModifierType(0))
        until(lambda: not window.quicklook.get_visible())
        window.creative_filter = ('all', 0, '')
        window._refresh_files()
        window._set_view('list')
        settle()
        assert window.ratings.get(paths[0])[0] == 3
        assert window.rating_badges[paths[0]].get_visible()
        print('PASS: multiselect rating/labels, shortcuts/editable safety, filters retain folders, reject without delete, preview ratings, persistence, list/grid badges, unchanged media and geometry')
    finally:
        window.destroy()
