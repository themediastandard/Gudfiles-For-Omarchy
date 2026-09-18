"""Native responsive toolbar, Up navigation and search popover regression.

PYTHONPATH=. python tests/ui_toolbar.py
TOOLBAR_QA_SCREENSHOTS=/tmp/gudfiles-toolbar captures native fixture windows.
Only this process's disposable windows are floated/resized on Hyprland.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors
from tests.test_theme import LIGHT_PALETTES
from gi.repository import Gdk, Gio, GLib, Gtk


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(250, lambda: loop.quit() or False)
    loop.run()


def capture(widget, name):
    directory = os.environ.get('TOOLBAR_QA_SCREENSHOTS')
    if not directory:
        return
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    for _ in range(8):
        widget.queue_draw()
        settle()
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(widget).snapshot(snapshot, widget.get_width(), widget.get_height())
        node = snapshot.to_node()
        if node is not None:
            widget.get_native().get_renderer().render_texture(node, None).save_to_png(str(target / (name + '.png')))
            return
    raise AssertionError((name, 'Widget did not become drawable', widget.get_mapped()))


def contained(widget, container):
    ok, bounds = widget.compute_bounds(container)
    assert widget.get_mapped() and ok
    assert bounds.get_x() >= -1 and bounds.get_y() >= -1
    assert bounds.get_x() + bounds.get_width() <= container.get_width() + 1
    assert bounds.get_y() + bounds.get_height() <= container.get_height() + 1


with tempfile.TemporaryDirectory(prefix='gudfiles-toolbar-') as temp:
    root = Path(temp)
    folder = root / 'Projects' / 'A very long folder name for toolbar resizing' / 'Footage'
    folder.mkdir(parents=True)
    match = folder / 'notes.txt'
    match.write_text('fixture')
    (folder / 'other.txt').touch()
    colors = [('active', load_colors()), ('light', next(iter(LIGHT_PALETTES.values())))]
    app = PickerApplication(PickerRequest(current_folder=folder), None)
    app.register(None)
    for name, palette in colors:
        with patch.object(Path, 'home', return_value=root), \
                patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
                patch('omarchy_file_picker.picker.load_colors', return_value=palette), \
                patch('omarchy_file_picker.picker.recent_files', return_value=[]):
            window = PickerWindow(app, PickerRequest(current_folder=folder, explorer=True), None)
            # Keep native signal QA independent of focus changes on the user's desktop.
            window.search_popover.set_autohide(False)
            window.present()
            settle()
            try:
                client = next(c for c in json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
                              if c['pid'] == os.getpid())
                selector = json.dumps('address:' + client['address'])
                if not client['floating']:
                    subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' + selector + '})'], check=True, capture_output=True)
                    settle()
                for width in (1200, 960, 820, 1200):
                    subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.resize({x=' + str(width) + ',y=700,relative=false,window=' + selector + '})'], check=True, capture_output=True)
                    settle()
                    assert window.get_width() == width, (name, width, window.get_width())
                    for row in (window.toolbar.navigation, window.toolbar.actions):
                        contained(row, window.toolbar)
                        child = row.get_first_child()
                        while child:
                            contained(child, row)
                            child = child.get_next_sibling()
                    _, nav = window.toolbar.navigation.compute_bounds(window.toolbar)
                    _, actions = window.toolbar.actions.compute_bounds(window.toolbar)
                    if width in (820, 1200):
                        assert (actions.get_y() > nav.get_y()) == (width == 820), (width, nav, actions)
                    window._toggle_path_entry(None)
                    settle()
                    contained(window.path_entry, window.toolbar)
                    assert window.path_entry.get_text() == str(folder)
                    window._toggle_path_entry(None)
                    settle()
                    trail = window.path_scroll.get_hadjustment()
                    assert abs(trail.get_value() - (trail.get_upper() - trail.get_page_size())) < 1
                    if width in (820, 1200):
                        capture(window, f'{name}-{width}')
                # Resizing the sidebar also reduces the toolbar's own allocation.
                window.sidebar_split.set_position(600)
                settle()
                contained(window.toolbar.actions, window.toolbar)
                window.sidebar_split.set_position(300)
                for mode in ('grid', 'list', 'columns'):
                    window._set_view(mode)
                    window.navigate(folder)
                    settle()
                    window.up_button.emit('clicked')
                    settle()
                    assert window.current_dir == folder.parent
                    window.back_button.emit('clicked')
                    settle()
                    assert window.current_dir == folder
                    window._on_key_pressed(None, Gdk.KEY_f, 0, Gdk.ModifierType.CONTROL_MASK)
                    settle()
                    assert window.search_popover.get_mapped(), (name, mode, window.get_focus())
                    assert window.get_focus().is_ancestor(window.search)
                    with patch.object(window, '_finish') as finish:
                        window.search.set_text('notes')
                        window.search.emit('activate')
                        settle()
                        assert not window.search_popover.get_visible() and window.entries == [match]
                        finish.assert_not_called()
                    assert window.search_button.get_first_child().has_css_class('active')
                    window._open_search()
                    settle()
                    assert window.search.get_text() == 'notes'
                    capture(window.search, f'{name}-search')
                    window.search.emit('stop-search')
                    settle()
                    assert not window.search_popover.get_visible() and window.entries == [match]
                    window.active_filter_chips.get_first_child().emit('clicked')
                    settle()
                    assert not window.search.get_text() and len(window.entries) == 2
                    assert not window.search_button.get_first_child().has_css_class('active')
                window.navigate(Path('/'))
                settle()
                assert not window.up_button.get_sensitive()
                history = list(window.history)
                window.up_button.emit('clicked')
                assert window.current_dir == Path('/') and window.history == history
                window.navigate(folder)
                window._open_recent()
                settle()
                assert not window.up_button.get_sensitive()
                window.up_button.emit('clicked')
                assert window.special_mode == 'recent'
                original = window.tabs.current
                window.tabs.new(folder)
                settle()
                assert window.up_button.get_sensitive()
                window.search.set_text('notes')
                settle()
                searched = window.tabs.current
                window.tabs.select(original)
                settle()
                assert not window.up_button.get_sensitive()
                assert not window.search_button.get_first_child().has_css_class('active')
                window.tabs.select(searched)
                settle()
                assert window.search.get_text() == 'notes'
                assert window.search_button.get_first_child().has_css_class('active')
                print('PASS:', name, '820–1200px wrap/unwrapping, bounds, location, sidebar resize, all-view Up/search, history, root/Recent, tabs', flush=True)
            finally:
                window.destroy()
                settle()
