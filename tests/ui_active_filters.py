"""Visible filter chips, eye state, removal and bounded toolbar layout."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk
from omarchy_file_picker.model import FileFilter, PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors


def settle(ms=150):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'GTK condition timed out'


def chips(window):
    result = {}
    child = window.active_filter_chips.get_first_child()
    while child:
        result[child.filter_key] = child
        child = child.get_next_sibling()
    return result


def native_window():
    return next(c for c in json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
                if c['pid'] == os.getpid() and c['class'] == 'org.omarchy.FilePicker')


colors = load_colors()
with tempfile.TemporaryDirectory(prefix='picker-active-filters-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch('omarchy_file_picker.picker.load_colors', return_value=colors):
    root = Path(temp)
    path, hidden, excluded = (root / name for name in ('clip.txt', '.hidden.txt', 'other.bin'))
    for file in (path, hidden, excluded):
        file.write_text('fixture')
    request = PickerRequest(current_folder=root, explorer=True, multiple=True,
                            title='Files', filters=[FileFilter('Text files', ((0, '*.txt'),))])
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    try:
        client = native_window()
        selector = json.dumps('address:' + client['address'])
        if not client['floating']:
            subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' + selector + '})'], check=True)
        subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.resize({x=1200,y=800,relative=false,window=' + selector + '})'], check=True)
        settle(400)
        baseline = native_window()
        geometry = (baseline['at'], baseline['size'])
        assert set(chips(window)) == {'type'}
        assert excluded not in window.entries
        chips(window)['type'].emit('clicked')
        until(lambda: not window.active_filters.get_visible())
        assert excluded in window.entries
        assert window.hidden_button.get_icon_name() == 'view-conceal-symbolic'
        assert hidden not in window.entries
        window.hidden_button.emit('clicked')
        settle()
        assert window.show_hidden and hidden in window.entries
        assert window.hidden_button.get_icon_name() == 'view-reveal-symbolic'
        assert window.hidden_button.has_css_class('active')
        chips(window)['hidden'].emit('clicked')
        until(lambda: not window.show_hidden)
        assert hidden not in window.entries and not window.active_filters.get_visible()
        window._on_key_pressed(None, Gdk.KEY_h, 0, Gdk.ModifierType.CONTROL_MASK)
        settle()
        assert 'hidden' in chips(window)
        window.ratings.set_many([path], stars=5, color='blue')
        window.creative_filter = ('rated', 4, 'blue')
        window.filter_combo.set_active(1)
        window.search.set_text('clip')
        until(lambda: set(chips(window)) == {'search', 'type', 'mode', 'minimum', 'color', 'hidden'})
        assert window.entries == [path]
        assert window.active_filters.get_prev_sibling() is window.toolbar
        assert window.active_filters.get_next_sibling() is window.browser_overlay
        chips(window)['color'].emit('clicked')
        until(lambda: window.creative_filter == ('rated', 4, ''))
        assert 'mode' in chips(window) and 'minimum' in chips(window)
        window.search.set_text('a very long query ' * 80)
        until(lambda: 'search' in chips(window) and len(chips(window)['search'].get_tooltip_text()) > 500)
        settle()
        current = native_window()
        assert (current['at'], current['size']) == geometry
        window._clear_active_filter('all')
        until(lambda: not window.active_filters.get_visible())
        assert window.creative_filter == ('all', 0, '')
        assert window.filter_combo.get_active() == 0 and window.search.get_text() == ''
        assert not window.show_hidden and set(window.entries) == {path, excluded}
        window.creative_filter = ('rated', 3, 'blue')
        window._refresh_files()
        settle()
        if os.environ.get('FILTERS_QA_SCREENSHOT'):
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
            window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(os.environ['FILTERS_QA_SCREENSHOT'])
        print('PASS: eye icons/button/shortcut, chip state for all filters, individual/all removal, long query keeps native geometry, strip position and wider sidebar')
    finally:
        window.destroy()
