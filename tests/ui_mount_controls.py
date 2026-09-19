"""Real clicks on simulated device controls, on an isolated Xvfb display."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GdkX11', '4.0')
from gi.repository import Gio, GLib, Gtk, GdkX11
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import DEFAULT_COLORS, load_colors

assert os.environ.get('POINTER_QA_ISOLATED') == '1'
errors = []
def exception(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = exception


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(150, lambda: loop.quit() or False)
    loop.run()
    assert not errors


def click(widget, button=1):
    native = widget.get_native()
    valid, bounds = widget.compute_bounds(native)
    assert valid
    dx, dy = native.get_surface_transform()
    tool = os.environ['XDOTOOL']
    subprocess.run([tool, 'mousemove', '--window', str(native.get_surface().get_xid()),
                    str(round(bounds.get_x() + bounds.get_width()/2 + dx)),
                    str(round(bounds.get_y() + bounds.get_height()/2 + dy))], check=True)
    subprocess.run([tool, 'click', str(button)], check=True)
    settle()


class Mount:
    def __init__(self, path, uri, name, *, eject=False, unmount=True):
        self.path, self.uri, self.name = path, uri, name
        self.eject, self.unmount = eject, unmount
        self.calls, self.error = [], None
    def get_name(self): return self.name
    def get_root(self): return SimpleNamespace(get_path=lambda: str(self.path), get_uri=lambda: self.uri)
    def can_eject(self): return self.eject
    def can_unmount(self): return self.unmount
    def unmount_with_operation(self, flags, operation, cancel, callback):
        assert flags == Gio.MountUnmountFlags.NONE and operation is None
        self.calls.append(('unmount', callback))
    def eject_with_operation(self, flags, operation, cancel, callback):
        assert flags == Gio.MountUnmountFlags.NONE and operation is None
        self.calls.append(('eject', callback))
    def unmount_with_operation_finish(self, result):
        if self.error:
            raise self.error
        return True
    eject_with_operation_finish = unmount_with_operation_finish


with tempfile.TemporaryDirectory(prefix='gudfiles-mount-controls-') as temp:
    root = Path(temp)
    request = PickerRequest(current_folder=root, explorer=True)
    app = PickerApplication(request, None)
    app.register(None)
    active = load_colors()
    dark = {**DEFAULT_COLORS, 'mode': 'dark', 'background': '#17191f', 'foreground': '#d7dce4',
            'bright_foreground': '#ffffff', 'light_foreground': '#b3bdcf', 'dark_foreground': '#9ba5b5',
            'accent': '#86a6f4', 'selection': '#343f5b', 'dark_background': '#1f222b',
            'darker_background': '#353b49', 'lighter_background': '#282d39'}
    for theme, colors in [('active', active), ('light', DEFAULT_COLORS), ('dark', dark)]:
        mounts = [Mount(root / 'Media', 'smb://example.invalid/Media', 'Media'),
                  Mount(root / 'Card', (root / 'Card').as_uri(), 'Camera Card', eject=True),
                  Mount(root / 'System', 'file:///non-removable', 'System', unmount=False)]
        with patch.object(Path, 'home', return_value=root), \
             patch.object(Gio.VolumeMonitor, 'get_mounts', side_effect=lambda: mounts), \
             patch('omarchy_file_picker.picker.load_colors', return_value=colors):
            window = PickerWindow(app, request, None)
            window.set_default_size(1000, 700)
            window.present()
            settle()
            try:
                buttons = [b for b in window.location_buttons if b._sidebar_kind == 'mount']
                assert len(buttons) == 3
                assert not hasattr(buttons[-1], '_unmount_button')
                if directory := os.environ.get('MOUNT_QA_SCREENSHOTS'):
                    Path(directory).mkdir(parents=True, exist_ok=True)
                    snapshot = Gtk.Snapshot.new()
                    Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                    window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(str(Path(directory) / (theme + '.png')))
                with patch.object(window, '_open_mounted_location') as navigate, \
                     patch.object(window, '_show_error') as report:
                    nas = buttons[0]
                    icon = nas._unmount_button
                    assert icon.get_tooltip_text() == 'Disconnect Media'
                    assert window._sidebar_target(icon) is nas
                    click(nas)
                    navigate.assert_called_once_with(mounts[0].uri)
                    navigate.reset_mock()
                    # A physical control click must never also navigate.
                    window.file_job_active = True
                    click(icon)
                    assert not mounts[0].calls
                    assert report.call_args.args[0] == 'Device is in use'
                    window.file_job_active = False
                    click(icon)
                    assert len(mounts[0].calls) == 1 and not icon.get_sensitive()
                    click(icon)
                    assert len(mounts[0].calls) == 1
                    navigate.assert_not_called()
                    mounts[0].error = GLib.Error.new_literal(Gio.io_error_quark(), 'Busy', Gio.IOErrorEnum.BUSY)
                    mounts[0].calls[-1][1](mounts[0], None)
                    settle()
                    assert icon.get_sensitive()
                    assert report.call_args.args == ('Could not disconnect device', 'Busy')
                    mounts[0].error = None
                    click(icon)
                    removed = mounts.pop(0)
                    removed.calls[-1][1](removed, None)
                    settle()
                    assert not any(b._sidebar_key == 'media' for b in window.location_buttons)
                    card = next(b for b in window.location_buttons if b._sidebar_key == 'camera card')
                    assert card._unmount_button.get_tooltip_text() == 'Eject Camera Card'
                    click(card._unmount_button)
                    assert mounts[0].calls[-1][0] == 'eject'
                    navigate.assert_not_called()
                    removed = mounts.pop(0)
                    removed.calls[-1][1](removed, None)
                    settle()
            finally:
                window.destroy()
                settle()
        print('PASS:', theme, 'supported controls, real distinct clicks, busy guard, pending/duplicate, failure/retry, unmount/eject and refresh', flush=True)
