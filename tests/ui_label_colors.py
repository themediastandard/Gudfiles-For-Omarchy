"""Check actual GTK swatch foregrounds in both light and real desktop themes."""
from pathlib import Path
import tempfile
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import DEFAULT_COLORS, load_colors, label_colors, prepare_colors, contrast_ratio

EXPECTED = {'red': '#d96868', 'orange': '#c68b37', 'green': '#579a70',
            'blue': '#598dc8', 'purple': '#a47ac4'}
desktop_colors = load_colors()


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(100, lambda: loop.quit() or False)
    loop.run()


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


def verify(container, stage):
    expected = label_colors(theme)
    found = set()
    for button in descendants(container):
        if not isinstance(button, Gtk.Button) or not button.has_css_class('color-swatch'):
            continue
        name = next((name for name in EXPECTED if button.has_css_class('label-' + name)), None)
        if not name:
            continue
        found.add(name)
        color = button.get_child().get_color()
        actual = '#%02x%02x%02x' % tuple(round(v * 255) for v in (color.red, color.green, color.blue))
        assert actual == expected[name], (stage, name, actual, expected[name])
        if theme.get('mode') == 'light':
            assert contrast_ratio(actual, prepare_colors(theme)['selection']) >= 4.5
    assert found == set(EXPECTED), (stage, found)


app = None
for theme in (DEFAULT_COLORS, desktop_colors,
              {**DEFAULT_COLORS, 'mode': 'dark', 'background': '#1e1e2e',
               'foreground': '#cdd6f4', 'accent': '#89b4fa'}):
    with tempfile.TemporaryDirectory(prefix='picker-label-colors-') as temp, \
            patch.object(Path, 'home', return_value=Path(temp)), \
            patch('omarchy_file_picker.picker.load_colors', return_value=theme):
        root = Path(temp)
        path = root / 'sample.txt'
        path.write_text('Read-only fixture')
        request = PickerRequest(current_folder=root, explorer=True, title='Files')
        if app is None:
            app = PickerApplication(request, None)
            app.register(None)
        window = PickerWindow(app, request, None)
        window.present()
        settle()
        try:
            window.flow.select_child(window.children_by_path[path])
            settle()
            palette = next(w for w in descendants(window.metadata) if isinstance(w, Gtk.MenuButton)
                           and w.has_css_class('rating-color'))
            palette.popup()
            settle()
            verify(palette.get_popover(), theme['mode'] + ' metadata label palette')
            palette.popdown()
            settle()
            filtering = next(w for w in descendants(window.toolbar) if isinstance(w, Gtk.MenuButton)
                             and w.has_css_class('creative-filter'))
            filtering.popup()
            settle()
            verify(filtering.get_popover(), theme['mode'] + ' filter palette')
            filtering.popdown()
            settle()
            window.quicklook.show_file(path)
            settle()
            palette = next(w for w in descendants(window.quicklook.rating_box) if isinstance(w, Gtk.MenuButton))
            palette.popup()
            settle()
            verify(palette.get_popover(), theme['mode'] + ' Quick Look label palette')
            palette.popdown()
            window.quicklook.close()
            settle()
            print('PASS:', theme['mode'], 'all five colors in metadata, filter and Quick Look palettes')
        finally:
            window.destroy()
            settle()
