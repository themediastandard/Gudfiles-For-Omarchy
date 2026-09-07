"""Native sidebar hit testing/actions; isolated bookmarks and simulated devices."""
import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors


def settle(delay=150):
    loop = GLib.MainLoop()
    GLib.timeout_add(delay, lambda: loop.quit() or False)
    loop.run()


def until(condition):
    deadline = time.monotonic() + 6
    while not condition() and time.monotonic() < deadline:
        settle()
    assert condition(), 'Timed out'


def labels(widget):
    result = [widget.get_text()] if isinstance(widget, Gtk.Label) else []
    child = widget.get_first_child()
    while child:
        result.extend(labels(child))
        child = child.get_next_sibling()
    return result


class Mount:
    def __init__(self, path, uri, *, eject=False, unmount=True):
        self.path, self.uri = path, uri
        self.eject, self.unmount = eject, unmount
        self.calls, self.error = [], None

    def get_name(self): return 'Test device'
    def get_root(self): return SimpleNamespace(get_path=lambda: str(self.path), get_uri=lambda: self.uri)
    def can_eject(self): return self.eject
    def can_unmount(self): return self.unmount

    def _remove(self, action, flags, operation, cancel, callback):
        assert flags == Gio.MountUnmountFlags.NONE and operation is None
        self.calls.append((action, cancel, callback))

    def unmount_with_operation(self, *args): self._remove('unmount', *args)
    def eject_with_operation(self, *args): self._remove('eject', *args)

    def unmount_with_operation_finish(self, result):
        if self.error:
            raise self.error
        return True

    eject_with_operation_finish = unmount_with_operation_finish


colors = load_colors()
with tempfile.TemporaryDirectory(prefix='picker-sidebar-actions-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.dict(os.environ, {'OMARCHY_FILE_PICKER_AUTOMATION': 'sidebar-context'}), \
        patch('omarchy_file_picker.picker.load_colors', return_value=colors):
    root = Path(temp)
    documents, bookmark, drive = (root / name for name in ('Documents', 'Production Files', 'Device'))
    for path in (documents, bookmark, drive):
        path.mkdir()
    selected = root / 'Keep selected.txt'
    selected.write_text('untouched')
    (bookmark / 'Keep me.txt').write_text('original')
    bookmarks = root / '.config/gtk-3.0/bookmarks'
    bookmarks.parent.mkdir(parents=True)
    untouched = 'smb://example.invalid/share Remote archive\n' + documents.as_uri() + ' My Documents\n'
    bookmarks.write_text(bookmark.as_uri() + ' Production\n' + untouched)
    nas = Mount(drive, 'smb://example.invalid/share')
    mounts = [nas]
    with patch.object(Gio.VolumeMonitor, 'get_mounts', side_effect=lambda: mounts):
        request = PickerRequest(current_folder=root, title='Sidebar Actions QA', explorer=True, multiple=True)
        app = PickerApplication(request, None)
        app.register(None)
        window = PickerWindow(app, request, None)
        errors = []
        window._show_error = lambda *args: errors.append(args)
        window.present()
        settle()

        def place(key):
            return next(button for button in window.location_buttons if button._sidebar_key == key)

        def menu(button):
            settle()
            valid, bounds = button.compute_bounds(window.sidebar_scroll)
            assert valid
            x, y = bounds.get_x() + 20, bounds.get_y() + bounds.get_height() / 2
            window.sidebar_context_gesture.emit('pressed', 1, x, y)
            settle()
            assert window.context_popover
            assert window.context_popover.get_parent() is window.sidebar_scroll
            valid, rect = window.context_popover.get_pointing_to()
            assert valid and (rect.x, rect.y) == (int(x), int(y))
            return labels(window.context_popover)

        def action(title):
            child = window.context_popover.get_child().get_first_child()
            while child:
                if isinstance(child, Gtk.Button) and title in labels(child):
                    return child
                child = child.get_next_sibling()
            raise AssertionError(('Missing action', title, labels(window.context_popover)))

        try:
            clients = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
            client = next(c for c in clients if c['pid'] == os.getpid() and c['class'] == 'org.omarchy.FilePicker')
            selector = json.dumps('address:' + client['address'])
            if not client['floating']:
                subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' + selector + '})'], check=True)
            subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.resize({x=1200,y=800,relative=false,window=' + selector + '})'], check=True)
            settle(350)
            baseline = window.get_width(), window.get_height()
            for mode in ('grid', 'list', 'columns'):
                window._set_view(mode)
                settle()
                window.flow.unselect_all()
                window.flow.select_child(window.children_by_path[selected])
                window.children_by_path[selected].grab_focus()
                settle()
                history, children = list(window.history), dict(window.children_by_path)
                texts = menu(place('documents'))
                assert all(t in texts for t in ('Open', 'Open in New Window', 'Show in Enclosing Folder',
                                                'Copy Location', 'Properties', 'Remove from Sidebar'))
                assert 'Move to Trash…' not in texts and 'Rename…' not in texts
                assert window.current_dir == root and window._selected_paths() == [selected]
                # File shortcuts must not act behind an open sidebar menu.
                with patch.object(window, '_confirm_remove') as remove:
                    window._on_key_pressed(None, Gdk.KEY_Delete, 0, Gdk.ModifierType(0))
                    remove.assert_not_called()
                window._on_key_pressed(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0))
                settle()
                assert window.current_dir == root and window._selected_paths() == [selected]
                assert window.history == history and window.children_by_path == children
                button = place('documents')
                button.grab_focus()
                window._on_key_pressed(None, Gdk.KEY_F10, 0, Gdk.ModifierType.SHIFT_MASK)
                assert window.context_popover.get_parent() is window.sidebar_scroll
                valid, bounds = button.compute_bounds(window.sidebar_scroll)
                valid, rect = window.context_popover.get_pointing_to()
                assert (rect.x, rect.y) == (int(bounds.get_x() + bounds.get_width()/2), int(bounds.get_y() + bounds.get_height()/2))
                action('Copy Location').emit('clicked')
                copied = []
                window.get_clipboard().read_text_async(None, lambda clip, res: copied.append(clip.read_text_finish(res)))
                until(lambda: bool(copied))
                assert copied == [str(documents)]
                assert window._selected_paths() == [selected]
                assert (window.get_width(), window.get_height()) == baseline
                menu(place('documents'))
                action('Open').emit('clicked')
                settle()
                assert window.current_dir == documents
                menu(place('documents'))
                action('Show in Enclosing Folder').emit('clicked')
                settle()
                assert window.current_dir == root and window._selected_paths() == [documents]
            print('PASS: sidebar pointer/keyboard anchors, selection/history and geometry in all three views', flush=True)

            window.flow.unselect_all()
            window.flow.select_child(window.children_by_path[selected])
            menu(place('documents'))
            action('Properties').emit('clicked')
            settle()
            dialog = next(w for w in Gtk.Window.get_toplevels() if w.get_title() == 'Properties' and w.get_visible())
            assert 'Documents' in labels(dialog) and 'Keep selected.txt' not in labels(dialog)
            dialog.response(Gtk.ResponseType.CLOSE)
            settle()
            menu(place('documents'))
            action('Remove from Sidebar').emit('clicked')
            settle()
            assert 'documents' not in [b._sidebar_key for b in window.location_buttons]
            assert documents.is_dir() and bookmarks.read_text().endswith(untouched)
            assert window.current_dir == root and window._selected_paths() == [selected]
            assert json.loads(window.preferences_path.read_text())['hidden_locations'] == ['documents']
            restored = PickerWindow(app, request, None)
            restored.present()
            settle()
            assert 'documents' not in [b._sidebar_key for b in restored.location_buttons]
            restored.destroy()
            window._show_sidebar_context_menu(15, 15)
            action('Restore Default Locations').emit('clicked')
            settle()
            assert place('documents')
            texts = menu(place('recent'))
            assert 'Properties' not in texts and 'Copy Location' not in texts
            action('Open').emit('clicked')
            settle()
            assert window.special_mode == 'recent' and place('recent').has_css_class('active')
            window.navigate(root)
            window.flow.select_child(window.children_by_path[selected])
            menu(place('production'))
            popover = window.context_popover
            action('Remove from Sidebar').emit('clicked')
            settle()
            assert bookmarks.read_text() == untouched
            assert (bookmark / 'Keep me.txt').read_text() == 'original'
            assert popover.get_parent() is None and window.context_popover is None
            window._set_bookmark(bookmark, False)
            assert bookmarks.read_text() == untouched, 'Repeated removal must not restore a bookmark'
            print('PASS: target properties, persistent hide/restore, Recent and shortcut-only bookmark removal', flush=True)

            # Scrolled rows must use viewport coordinates, not their box position.
            extra = []
            for index in range(24):
                path = root / f'Bookmark {index:02d}'
                path.mkdir()
                extra.append(path.as_uri() + '\n')
            bookmarks.write_text(untouched + ''.join(extra))
            window._refresh_sidebar()
            settle()
            adjustment = window.sidebar_scroll.get_vadjustment()
            adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
            settle()
            assert adjustment.get_value() > 0
            menu(place('bookmark 23'))
            with patch.object(window, '_copy_location') as copy:
                action('Copy Location').emit('clicked')
                copy.assert_called_once_with([root / 'Bookmark 23'])
            bookmarks.write_text(untouched)
            window._refresh_sidebar()
            settle()

            # A mounted sidebar target keeps the existing GVfs bridge verification.
            menu(place('test device'))
            with patch('omarchy_file_picker.picker.mounted_local_path', return_value=drive), \
                    patch.object(window, '_open_sidebar_window') as launch:
                generation = window._mount_open_generation
                action('Open in New Window').emit('clicked')
                assert window._mount_open_generation == generation
                until(lambda: launch.called)
                launch.assert_called_once_with(drive)
                assert window.current_dir == root
            job = window.transfer_queue.add([selected], documents)
            menu(place('test device'))
            assert not action('Disconnect').get_sensitive()
            window._remove_sidebar_mount(nas)
            assert not nas.calls and errors.pop()[0] == 'Device is in use'
            window.transfer_queue.cancel(job)
            until(lambda: not window.transfer_queue.unfinished)
            window._close_context_menu()
            menu(place('test device'))
            action('Disconnect').emit('clicked')
            assert nas.calls[-1][0] == 'unmount'
            nas.error = GLib.Error.new_literal(Gio.io_error_quark(), 'Device is busy', Gio.IOErrorEnum.BUSY)
            nas.calls[-1][2](nas, None)
            assert errors.pop() == ('Could not disconnect device', 'Device is busy')
            assert window.current_dir == root
            nas.error = None
            window.navigate(drive)
            menu(place('test device'))
            action('Disconnect').emit('clicked')
            mounts.clear()
            nas.calls[-1][2](nas, None)
            settle()
            assert window.current_dir == root
            assert not [b for b in window.location_buttons if b._sidebar_kind == 'mount']
            for eject, unmount, title in ((True, True, 'Eject'), (False, True, 'Unmount'), (False, False, None)):
                disk = Mount(drive, drive.as_uri(), eject=eject, unmount=unmount)
                mounts[:] = [disk]
                window._refresh_sidebar()
                settle()
                texts = menu(place('test device'))
                if title:
                    action(title).emit('clicked')
                    assert disk.calls[-1][0] == ('eject' if eject else 'unmount')
                    disk.calls[-1][2](disk, None)
                else:
                    assert not any(t in texts for t in ('Eject', 'Unmount', 'Disconnect'))
                    window._close_context_menu()
            print('PASS: mounted navigation, capabilities, no-force async removal, busy transfers and failure recovery', flush=True)

            # Launch a real independent explorer, then close only that test child.
            window._close_context_menu()
            process = window._open_sidebar_window(documents)
            assert process
            try:
                def child_visible():
                    clients = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
                    return any(c['pid'] == int(process.get_identifier()) for c in clients)
                until(child_visible)
                assert window.get_visible() and window.current_dir == root
            finally:
                process.send_signal(signal.SIGTERM)
                process.wait(None)
            assert not errors, errors
            window._set_bookmark(bookmark, True)
            settle()
            menu(place('production files'))
            if os.environ.get('SIDEBAR_ACTIONS_QA_SCREENSHOT'):
                output = Path(os.environ['SIDEBAR_ACTIONS_QA_SCREENSHOT'])
                for widget, path in ((window, output), (window.context_popover, output.with_stem(output.stem + '-menu'))):
                    snapshot = Gtk.Snapshot.new()
                    Gtk.WidgetPaintable.new(widget).snapshot(snapshot, widget.get_width(), widget.get_height())
                    node = snapshot.to_node()
                    assert node
                    texture = widget.get_native().get_renderer().render_texture(node, None)
                    texture.save_to_png(str(path))
            window._refresh_sidebar()
            settle()
            assert window.context_popover is None
            print('PASS: independent Files process and popup lifetime across sidebar rebuilds', flush=True)
        finally:
            window._close_context_menu()
            window.set_focus(None)
            window.set_visible(False)
            settle()
            window.destroy()
