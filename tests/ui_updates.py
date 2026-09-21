"""Native launch-path checks, with a delayed release server and isolated user state."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.help_window import show_help
from omarchy_file_picker import updates
from omarchy_file_picker.theme import DEFAULT_COLORS
from gi.repository import GLib, Gtk

errors = []
def exception(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = exception


def settle(seconds=.15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        time.sleep(.005)
    assert not errors, errors


def wait_for(predicate):
    end = time.monotonic() + 4
    while not predicate() and time.monotonic() < end:
        settle(.02)
    assert predicate()


def available(version='2.0.0'):
    return updates.UpdateResult('available', f'Gudfiles {version} is available.',
                                f'{updates.releases_url()}/tag/v{version}')


def capture(window, name):
    directory = os.environ.get('UPDATE_SCREENSHOTS')
    if directory:
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
        node = snapshot.to_node()
        assert node
        Path(directory).mkdir(parents=True, exist_ok=True)
        window.get_renderer().render_texture(node, None).save_to_png(str(Path(directory) / (name + '.png')))


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'Example.txt').write_text('Browsing stays usable during a release check.')
    app = PickerApplication(PickerRequest(current_folder=root, explorer=True, multiple=True), None)
    app.register(None)
    palettes = [('light', DEFAULT_COLORS), ('dark', {**DEFAULT_COLORS, 'mode': 'dark',
                 'background': '#222222', 'dark_background': '#191919', 'foreground': '#dddddd',
                 'light_foreground': '#bbbbbb', 'darker_background': '#111111',
                 'lighter_background': '#333333', 'selection': '#444444'})]
    for palette, colors in palettes:
        with patch('omarchy_file_picker.picker.load_colors', return_value=colors):
            gate = threading.Event()
            def delayed():
                assert gate.wait(4)
                return available()
            with patch.object(updates, 'check_for_updates', side_effect=delayed) as check:
                # Exercise actual Gtk.Application activation, not just the notice helper.
                app.activate()
                window = next(w for w in app.get_windows() if isinstance(w, PickerWindow))
                window.set_default_size(820, 560)
                app.update_checks.state.directory = root / palette
                wait_for(lambda: check.call_count == 1)
                assert not window.update_notice.get_visible()
                assert window.children_by_path[root / 'Example.txt']
                for view in ('list', 'columns', 'grid'):
                    window._set_view(view)
                    settle()
                second = PickerWindow(app, app.request, None)
                second.present()
                guide = show_help(window)
                guide.nav_buttons['about'].emit('clicked')
                guide.update_button.emit('clicked')
                settle()
                assert guide.update_running and check.call_count == 1
                gate.set()
                wait_for(lambda: not app.update_checks.running)
                assert guide.update_status.get_text() == available().message
                assert guide.release_link.get_uri() == available().url
                notices = [w.update_notice for w in (window, second) if w.update_notice.get_visible()]
                assert len(notices) == 1
                notice = notices[0]
                owner = notice.owner()
                owner.present()
                guide.close()
                settle()
                assert notice.label.get_text() == 'Gudfiles 2.0.0 is available'
                assert notice.get_height() < 48
                ok, bounds = notice.link.compute_bounds(owner)
                assert ok and bounds.get_x() >= 0 and bounds.get_x() + bounds.get_width() <= owner.get_width()
                links = []
                notice.link.connect('activate-link', lambda link: links.append(link.get_uri()) or True)
                notice.link.emit('activate-link')
                assert links == [available().url]
                capture(owner, palette)
                notice.dismiss_button.emit('clicked')
                assert not notice.get_visible()
                window.destroy()
                second.destroy()
                settle()
                app.activate()
                reopened = next(w for w in app.get_windows() if isinstance(w, PickerWindow))
                settle()
                assert not reopened.update_notice.get_visible() and check.call_count == 1
                # Manual refresh can reveal a subsequent version, and a failed check
                # removes the old notice rather than continuing to advertise it.
                guide = show_help(reopened)
                guide.nav_buttons['about'].emit('clicked')
                with patch.object(updates, 'check_for_updates', return_value=available('2.0.1')):
                    guide.update_button.emit('clicked')
                    wait_for(lambda: not app.update_checks.running)
                    assert reopened.update_notice.get_visible()
                    assert reopened.update_notice.link.get_uri() == available('2.0.1').url
                with patch.object(updates, 'check_for_updates', return_value=updates.UpdateResult('error', 'Offline')):
                    guide.update_button.emit('clicked')
                    wait_for(lambda: not app.update_checks.running)
                    assert not reopened.update_notice.get_visible()
                    assert guide.update_status.get_text() == 'Offline'
                reopened.destroy()
                settle()
            # Closing an owner before a request completes must not show or claim a notice.
            app.update_checks.state.directory = root / (palette + '-late')
            gate.clear()
            with patch.object(updates, 'check_for_updates', side_effect=delayed) as check:
                app.activate()
                window = next(w for w in app.get_windows() if isinstance(w, PickerWindow))
                wait_for(lambda: check.call_count == 1)
                notice = window.update_notice
                window.destroy()
                gate.set()
                wait_for(lambda: not app.update_checks.running)
                assert not notice.get_visible()
                assert app.update_checks.state.claim_notice(available())
            # Non-update results stay silent, including no stable release and failures.
            for status in ('current', 'ahead', 'unpublished', 'error'):
                app.update_checks.state.directory = root / (palette + status)
                with patch.object(updates, 'check_for_updates', return_value=updates.UpdateResult(status, status)):
                    app.activate()
                    window = next(w for w in app.get_windows() if isinstance(w, PickerWindow))
                    settle()
                    wait_for(lambda: not app.update_checks.running)
                    assert not window.update_notice.get_visible()
                    window.destroy()
                    settle()
            print('PASS:', palette, 'launch, responsive browsing, shared Help check, duplicate windows, link, dismissal, close, silent states')
    # Manual refresh racing a cached startup reply bypasses that cache.
    app.update_checks.state.directory = root / 'manual-cache-race'
    gate = threading.Event()
    calls = []
    def cached_then_fresh(*, force=False):
        calls.append(force)
        app.update_checks.state.used_cache = not force
        if not force:
            assert gate.wait(4)
        return available()
    with patch.object(app.update_checks.state, 'check', side_effect=cached_then_fresh):
        app.activate()
        window = next(w for w in app.get_windows() if isinstance(w, PickerWindow))
        wait_for(lambda: len(calls) == 1)
        guide = show_help(window)
        guide.nav_buttons['about'].emit('clicked')
        guide.update_button.emit('clicked')
        gate.set()
        wait_for(lambda: not app.update_checks.running)
        assert calls == [False, True]
        assert guide.update_status.get_text() == available().message
        window.destroy()
        settle()
    with patch.object(updates, 'check_for_updates') as check:
        for request in (PickerRequest(current_folder=root), PickerRequest(current_folder=root, mode='save'),
                        PickerRequest(current_folder=root, directory=True),
                        PickerRequest(current_folder=root, explorer=True, external=True)):
            window = PickerWindow(app, request, None)
            window.present()
            settle()
            assert window.update_notice is None
            window.destroy()
            settle()
        check.assert_not_called()
    print('PASS: Open/Save/folder/external launch isolation; no GTK callback exceptions')
