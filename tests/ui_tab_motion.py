"""Native painted-frame checks for tab open/close animation and interruption.

PYTHONPATH=. python tests/ui_tab_motion.py
TAB_MOTION_SCREENSHOTS=/tmp/gudfiles-tab-motion captures active/light strips.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors
from tests.test_theme import LIGHT_PALETTES
from gi.repository import Gdk, Gio, GLib, Gtk

errors = []
original_hook = sys.excepthook
def callback_error(kind, value, traceback):
    errors.append(value)
    original_hook(kind, value, traceback)
sys.excepthook = callback_error


def settle(ms=300):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def capture(widget, name):
    target = os.environ.get('TAB_MOTION_SCREENSHOTS')
    if not target:
        return
    if name.endswith('frame-6'):
        widget = widget.get_root()
    snapshot = Gtk.Snapshot.new()
    Gtk.WidgetPaintable.new(widget).snapshot(snapshot, widget.get_width(), widget.get_height())
    node = snapshot.to_node()
    if node:
        Path(target).mkdir(parents=True, exist_ok=True)
        widget.get_native().get_renderer().render_texture(node, None).save_to_png(str(Path(target) / (name + '.png')))


def frames(window, duration=360, name=''):
    samples = []
    def sample(*_):
        tabs = window.tabs
        samples.append([(slot.content, slot.get_width(), slot.weight) for slot in tabs.strip.slots])
        if name and len(samples) in (3, 6, 10):
            capture(tabs, f'{name}-frame-{len(samples)}')
        return True
    clock = window.get_frame_clock()
    tick = clock.connect('after-paint', sample)
    settle(duration)
    clock.disconnect(tick)
    return samples


def widths(samples, tab):
    return [next((width for content, width, _ in sample if content is tab.widget), 0)
            for sample in samples]


def settled(tabs):
    assert not tabs.strip.tick_id
    assert len(tabs.strip.slots) == len(tabs.items)
    values = [tab.widget.get_parent().get_width() for tab in tabs.items]
    assert max(values) - min(values) <= 1, values
    assert all(slot.weight == 1 for slot in tabs.strip.slots)


with tempfile.TemporaryDirectory(prefix='gudfiles-tab-motion-') as temp:
    root = Path(temp)
    (root / 'Project A').mkdir()
    (root / 'A much longer project folder name').mkdir()
    palettes = [('active', load_colors()), ('light', next(iter(LIGHT_PALETTES.values())))]
    app = PickerApplication(PickerRequest(current_folder=root), None)
    app.register(None)
    for name, palette in palettes:
        with patch.object(Path, 'home', return_value=root), \
             patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
             patch('omarchy_file_picker.picker.load_colors', return_value=palette):
            window = PickerWindow(app, PickerRequest(current_folder=root, explorer=True), None)
            window.present()
            settle()
            tabs = window.tabs
            settings = window.get_settings()
            original_animations = settings.get_property('gtk-enable-animations')
            settings.set_property('gtk-enable-animations', True)
            try:
                client = None
                deadline = time.monotonic() + 5
                while client is None and time.monotonic() < deadline:
                    client = next((c for c in json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
                                   if c['pid'] == os.getpid()), None)
                    if client is None:
                        settle(50)
                assert client is not None, 'Fixture window did not map'
                selector = json.dumps('address:' + client['address'])
                if not client['floating']:
                    subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' + selector + '})'], check=True, capture_output=True)
                for width in (1200, 820):
                    subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.resize({x=' + str(width) + ',y=700,relative=false,window=' + selector + '})'], check=True, capture_output=True)
                    settle()
                    geometry = window.get_width(), window.get_height()
                    first = tabs.current
                    baseline = first.widget.get_width()
                    added = tabs.new(root / 'A much longer project folder name')
                    assert len(tabs.items) == 2 and tabs.current is added
                    assert added.widget.get_parent().weight == 0
                    samples = frames(window, name=f'{name}-{width}-opening')
                    opening, neighbor = widths(samples, added), widths(samples, first)
                    assert len(set(opening)) >= 4, opening
                    assert all(b >= a - 1 for a, b in zip(opening, opening[1:])), opening
                    assert any(0 < weight < 1 for sample in samples for content, _, weight in sample if content is added.widget)
                    assert neighbor[-1] < baseline and all(b <= a + 1 for a, b in zip(neighbor, neighbor[1:])), neighbor
                    settled(tabs)
                    capture(tabs, f'{name}-{width}-open')
                    tabs.close(added)
                    slot = added.widget.get_parent()
                    assert added not in tabs.items and slot is not None
                    assert not slot.get_sensitive() and not slot.get_can_target()
                    samples = frames(window, name=f'{name}-{width}-closing')
                    closing, neighbor = widths(samples, added), widths(samples, first)
                    assert len(set(closing)) >= 4, closing
                    assert all(b <= a + 1 for a, b in zip(closing, closing[1:])), closing
                    assert all(b >= a - 1 for a, b in zip(neighbor, neighbor[1:])), neighbor
                    assert added.widget.get_parent() is None
                    settled(tabs)
                    assert abs(first.widget.get_width() - baseline) <= 1
                    assert (window.get_width(), window.get_height()) == geometry
                    capture(tabs, f'{name}-{width}-closed')
                # Interrupt opening with closing and reopening; state changes
                # immediately while outgoing visuals finish independently.
                transient = tabs.new(root / 'Project A')
                settle(60)
                tabs.close(transient)
                tabs.close(transient)
                tabs.reopen()
                reopened = tabs.current
                assert reopened.path == root / 'Project A'
                settle()
                settled(tabs)
                assert len(tabs.items) == 2 and transient.widget.get_parent() is None
                # Reordering during motion settles geometry before the move.
                newest = tabs.new(root)
                assert tabs.reorder(newest.id, tabs.items[0], 0)
                settle()
                settled(tabs)
                assert tabs.items[0] is newest
                # Closing a middle or first tab must not introduce a final gap
                # jump when its disappearing widget leaves the native tree.
                for victim in (tabs.items[1], tabs.items[0]):
                    survivor = tabs.items[-1]
                    tabs.close(victim)
                    samples = frames(window)
                    growing = widths(samples, survivor)
                    assert all(b >= a - 1 for a, b in zip(growing, growing[1:])), growing
                    settled(tabs)
                # Overflow must reveal the full selected tab after it expands.
                for _ in range(9):
                    tabs.new(root, background=True)
                tabs.select(tabs.items[-1])
                settle(450)
                settled(tabs)
                adjustment = tabs.scroll.get_hadjustment()
                valid, bounds = tabs.current.widget.compute_bounds(tabs.strip)
                assert valid and bounds.get_x() >= adjustment.get_value() - 1
                assert bounds.get_x() + bounds.get_width() <= adjustment.get_value() + adjustment.get_page_size() + 1
                assert tabs.strip.get_width() > tabs.scroll.get_width()
                # Disabling motion mid-transition settles all widths/fades.
                tabs.close(tabs.current)
                settings.set_property('gtk-enable-animations', False)
                settle(60)
                settled(tabs)
                reduced = tabs.new(root)
                assert not tabs.strip.tick_id and reduced.widget.get_parent().weight == 1
                tabs.close(reduced)
                assert reduced.widget.get_parent() is None and not tabs.strip.tick_id
                while len(tabs.items) > 1:
                    tabs.close(tabs.current)
                settle(100)
                with patch.object(window, '_finish') as finish:
                    tabs.close()
                    finish.assert_called_once_with(cancelled=True)
                    assert len(tabs.items) == 1
                # Destroy with an animation and reveal callback still running.
                settings.set_property('gtk-enable-animations', True)
                tabs.new(root)
                window.destroy()
                settle(80)
                assert not tabs.strip.tick_id and not tabs.reveal_tick
                assert not tabs.strip.settings_handler
                print('PASS:', name, 'painted open/close widths, fades, equal spacing, 820/1200px, interruption, reopen, reorder, overflow, reduced motion, final close and teardown', flush=True)
            finally:
                settings.set_property('gtk-enable-animations', original_animations)
                window.destroy()
                settle(80)
    assert not errors, errors
