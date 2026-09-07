"""Native help search, navigation, lifecycle and browser isolation.

HELP_QA_SCREENSHOTS=/tmp/files-help PYTHONPATH=. python tests/ui_help.py
Uses disposable files/preferences and GTK controller signals, not pointer input.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.help_catalog import CATEGORIES, FEATURES
from omarchy_file_picker.help_window import HelpWindow, show_help
from omarchy_file_picker.theme import DEFAULT_COLORS, load_colors
from gi.repository import Gdk, Gio, GLib, Gtk


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(250, lambda: loop.quit() or False)
    loop.run()


def widgets(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from widgets(child)
        child = child.get_next_sibling()


def capture(window, name):
    directory = os.environ.get('HELP_QA_SCREENSHOTS')
    if directory:
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
        node = snapshot.to_node()
        assert node is not None
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        window.get_renderer().render_texture(node, None).save_to_png(str(path / f'{name}.png'))


def press(window, key, state=Gdk.ModifierType(0)):
    controllers = window.observe_controllers()
    for index in range(controllers.get_n_items()):
        controller = controllers.get_item(index)
        if isinstance(controller, Gtk.EventControllerKey) and controller.get_propagation_phase() == Gtk.PropagationPhase.CAPTURE:
            return controller.emit('key-pressed', key, 0, state)
    raise AssertionError('Missing capture key controller')


with tempfile.TemporaryDirectory(prefix='files-help-qa-') as directory:
    root = Path(directory)
    source = root / 'Read me.txt'
    source.write_text('Help must not change this file or finish the picker.')
    app = PickerApplication(PickerRequest(current_folder=root), None)
    app.register(None)
    for name, colors in [('active', load_colors()), ('light', DEFAULT_COLORS)]:
        with patch.object(Path, 'home', return_value=root), \
                patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
                patch('omarchy_file_picker.picker.load_colors', return_value=colors):
            window = PickerWindow(app, PickerRequest(current_folder=root, explorer=True, multiple=True), None)
            window.present()
            settle()
            try:
                window.flow.select_child(window.children_by_path[source])
                settle()
                selected = window._selected_paths()
                window.help_button.emit('clicked')
                settle()
                guide = window.help_window
                assert guide.get_visible() and guide.get_transient_for() is window
                assert guide.visible_features == list(FEATURES)
                assert (guide.get_width(), guide.get_height()) <= (820, 720)
                original_size = guide.get_width(), guide.get_height()
                capture(guide, name + '-overview')
                for group in CATEGORIES:
                    guide.nav_buttons[group.key].emit('clicked')
                    settle()
                    assert guide.category == group.key and guide.nav_buttons[group.key].get_active()
                    assert guide.visible_features and all(f.category == group.key for f in guide.visible_features)
                    assert (guide.get_width(), guide.get_height()) == original_size
                guide.search.set_text('  cTrL+Shift+V  ')
                settle()
                assert [f.title for f in guide.visible_features] == ['Stage work for later']
                assert guide.category is None and guide.nav_buttons[None].get_active()
                assert len(guide.visible_features) < len(FEATURES)
                capture(guide, name + '-search')
                guide.search.set_text('no-such-feature-' * 300)
                settle()
                assert not guide.visible_features
                assert 'No features found' in [w.get_text() for w in widgets(guide) if isinstance(w, Gtk.Label)]
                assert (guide.get_width(), guide.get_height()) == original_size
                capture(guide, name + '-empty')
                clear = next(w for w in widgets(guide) if isinstance(w, Gtk.Button) and w.get_label() == 'Clear search')
                clear.emit('clicked')
                settle()
                assert guide.visible_features == list(FEATURES)
                guide.nav_buttons['preview'].emit('clicked')
                settle()
                capture(guide, name + '-preview')
                # A mapped Wayland window keeps its current size when its
                # default changes. Present a fresh surface at the minimum.
                compact = HelpWindow(window)
                compact.set_default_size(660, 480)
                compact.nav_buttons['preview'].emit('clicked')
                compact.present()
                settle()
                # The compositor may round up a requested native size.
                assert 660 <= compact.get_width() < original_size[0]
                assert 480 <= compact.get_height() < original_size[1]
                ok, bounds = compact.footer.compute_bounds(compact)
                assert ok and bounds.get_y() + bounds.get_height() <= compact.get_height()
                assert compact.scroll.get_hadjustment().get_upper() <= compact.scroll.get_hadjustment().get_page_size()
                capture(compact, name + '-compact')
                compact.set_focus(None)
                compact.set_visible(False)
                GLib.idle_add(lambda: compact.destroy() or False)
                settle()
                assert press(guide, Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK)
                assert guide.get_focus() is not None and guide.get_focus().is_ancestor(guide.search)
                assert press(guide, Gdk.KEY_Escape)
                settle()
                assert not guide.get_visible() and window.get_visible()
                assert window._selected_paths() == selected
                assert source.read_text() == 'Help must not change this file or finish the picker.'
                for mode in ('grid', 'list', 'columns'):
                    window._set_view(mode)
                    settle()
                    window.flow.select_child(window.children_by_path[source])
                    selected = window._selected_paths()
                    assert press(window, Gdk.KEY_F1)
                    settle()
                    assert window.help_window is guide and guide.get_visible()
                    assert len([w for w in Gtk.Window.get_toplevels() if isinstance(w, HelpWindow)]) == 1
                    guide.close_button.emit('clicked')
                    settle()
                    assert not guide.get_visible() and window._selected_paths() == selected
                window.quicklook.show_file(source)
                settle()
                assert press(window, Gdk.KEY_F1)
                settle()
                assert guide.get_visible() and window.quicklook.get_visible()
                guide.close()
                window.quicklook.close()
                settle()
                show_help(window)
                settle()
                print('PASS:', name, 'catalog, categories, global search, empty/long query, shortcuts, reuse, preview/picker isolation')
            finally:
                window.destroy()
                settle()
            assert not guide.get_visible() and not guide.get_realized()
            print('PASS: help closes with its owner')
            for mode, directory_only in [('open', False), ('open', True), ('save', False), ('save_files', False)]:
                result = root / 'result.json'
                picker = PickerWindow(app, PickerRequest(current_folder=root, mode=mode,
                                      directory=directory_only), result)
                picker.present()
                settle()
                try:
                    with patch.object(picker, '_finish') as finish:
                        picker.search.grab_focus()
                        assert press(picker, Gdk.KEY_F1)
                        settle()
                        assert picker.help_window.get_visible()
                        assert press(picker.help_window, Gdk.KEY_Escape)
                        settle()
                        finish.assert_not_called()
                        assert not result.exists() and picker.get_visible()
                finally:
                    picker.destroy()
                    settle()
            print('PASS:', name, 'real Open, folder, Save and SaveFiles windows remain open without writing a result')
