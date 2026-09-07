"""Context actions for places, shared bookmarks and mounted devices."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk


class SidebarMenus:
    def _install_sidebar_context(self):
        self.sidebar_mount_operations = {}
        self.sidebar_context_gesture = Gtk.GestureClick(button=3)
        self.sidebar_context_gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.sidebar_context_gesture.connect('pressed', self._on_sidebar_context_pressed)
        self.sidebar_scroll.add_controller(self.sidebar_context_gesture)
        self.connect('unrealize', self._cancel_sidebar_operations)

    def _sidebar_target(self, widget):
        while widget and widget is not self.sidebar_scroll:
            if isinstance(widget, Gtk.Popover):
                return None
            if widget in self.location_buttons:
                return widget
            widget = widget.get_parent()
        return None

    def _on_sidebar_context_pressed(self, gesture, _presses, x, y):
        picked = self.sidebar_scroll.pick(x, y, Gtk.PickFlags.DEFAULT)
        widget = picked
        while widget and widget is not self.sidebar_scroll:
            if isinstance(widget, (Gtk.Popover, Gtk.Scrollbar)):
                return
            widget = widget.get_parent()
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._show_sidebar_context_menu(x, y, self._sidebar_target(picked))

    def _show_sidebar_context_menu(self, x, y, button=None, *, keyboard=False):
        self._close_context_menu()
        # The scroller survives bookmark edits and mount notifications. Parenting
        # to a replaceable sidebar button leaves GTK with a dangling popup.
        anchor = self.sidebar_scroll
        if keyboard and button:
            valid, bounds = button.compute_bounds(anchor)
            if valid:
                x = bounds.get_x() + bounds.get_width() / 2
                y = bounds.get_y() + bounds.get_height() / 2
        popover = Gtk.Popover(autohide=os.environ.get('OMARCHY_FILE_PICKER_AUTOMATION') != 'sidebar-context',
                              has_arrow=True)
        popover.add_css_class('file-context-menu')
        popover._sidebar_button = button
        popover.set_parent(anchor)
        popover.connect('closed', self._on_context_closed)
        rectangle = Gdk.Rectangle()
        rectangle.x, rectangle.y = int(x), int(y)
        rectangle.width = rectangle.height = 1
        popover.set_pointing_to(rectangle)
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        for edge in ('top', 'bottom', 'start', 'end'):
            getattr(menu, 'set_margin_' + edge)(5)
        popover.set_child(menu)
        self.context_submenus.clear()
        self.qa_submenu_button = None

        def action(title, callback, icon, *, enabled=True, tooltip=None):
            item = self._menu_button(title, callback, icon_name=icon)
            item.set_sensitive(enabled)
            if tooltip:
                item.set_tooltip_text(tooltip)
            menu.append(item)

        def separator():
            menu.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        if button:
            path = getattr(button, '_picker_path', None)
            mount = getattr(button, '_sidebar_mount', None)
            kind = button._sidebar_kind
            action('Connect to NAS…' if kind == 'connect' else 'Open',
                   lambda: button.emit('clicked'), 'network-server-symbolic' if kind == 'connect' else 'folder-open-symbolic')
            if path:
                if self.request.explorer:
                    action('Open in New Tab', lambda: self.tabs.new(path), 'tab-new-symbolic')
                if mount:
                    uri = mount.get_root().get_uri()
                    action('Open in New Window', lambda: self._open_mounted_location(uri, new_window=True), 'window-new-symbolic')
                else:
                    action('Open in New Window', lambda: self._open_sidebar_window(path), 'window-new-symbolic')
                    if path.parent != path:
                        action('Show in Enclosing Folder', lambda: self._reveal_sidebar_folder(path), 'go-up-symbolic')
                separator()
                action('Copy Location', lambda: self._copy_location([path]), 'edit-copy-symbolic')
                action('Properties', lambda: self._show_properties([path]), 'dialog-information-symbolic')
            if kind in {'location', 'bookmark'}:
                separator()
                action('Remove from Sidebar', lambda: self._remove_sidebar_item(button), 'list-remove-symbolic',
                       tooltip='Remove this shortcut; the folder and its contents stay where they are.')
            if mount and (mount.can_eject() or mount.can_unmount()):
                separator()
                title = self._sidebar_mount_action(mount)
                busy = self._sidebar_device_busy() or mount.get_root().get_uri() in self.sidebar_mount_operations
                action(title, lambda: self._remove_sidebar_mount(mount), 'media-eject-symbolic', enabled=not busy,
                       tooltip='Finish or cancel file operations and transfers before disconnecting a device.' if busy else None)
        else:
            action('Connect to NAS…', lambda: self._show_nas_dialog(None), 'network-server-symbolic')
        if not button or self.file_preferences['hidden_locations']:
            separator()
            action('Restore Default Locations', self._restore_sidebar_locations, 'view-refresh-symbolic',
                   enabled=bool(self.file_preferences['hidden_locations']))
        self.context_popover = popover
        popover.popup()

    def _remove_sidebar_item(self, button):
        if button._sidebar_kind == 'bookmark':
            self._set_bookmark(button._picker_path, False)
        else:
            hidden = self.file_preferences['hidden_locations']
            self._set_file_preference('hidden_locations', sorted(set(hidden) | {button._sidebar_key}), reload=False)
            self._refresh_sidebar()

    def _restore_sidebar_locations(self):
        self._set_file_preference('hidden_locations', [], reload=False)
        self._refresh_sidebar()

    def _reveal_sidebar_folder(self, path):
        self.navigate(path.parent)
        child = self.children_by_path.get(path)
        if child:
            self.flow.select_child(child)
            child.grab_focus()

    def _open_sidebar_window(self, path):
        if not path.is_dir():
            self._show_error('Could not open folder', 'This folder is no longer available.')
            return
        # A separate explorer process owns its own close/transfer lifecycle and
        # cannot complete or cancel the originating portal request.
        launcher = Gio.SubprocessLauncher(flags=Gio.SubprocessFlags.NONE)
        package_root = str(Path(__file__).resolve().parent.parent)
        launcher.setenv('PYTHONPATH', os.pathsep.join(filter(None, (package_root, os.environ.get('PYTHONPATH')))), True)
        try:
            return launcher.spawnv([sys.executable, '-m', 'omarchy_file_picker.picker', '--demo', str(path)])
        except GLib.Error as error:
            self._show_error('Could not open new window', error.message)

    @staticmethod
    def _sidebar_mount_action(mount):
        if mount.can_eject():
            return 'Eject'
        return 'Unmount' if mount.get_root().get_uri().startswith('file:') else 'Disconnect'

    def _sidebar_device_busy(self):
        return self.file_job_active or self.transfer_queue.unfinished or bool(self.active_processes)

    def _remove_sidebar_mount(self, mount):
        uri = mount.get_root().get_uri()
        if uri in self.sidebar_mount_operations:
            return
        if self._sidebar_device_busy():
            self._show_error('Device is in use', 'Finish or cancel file operations and transfers before disconnecting a device.')
            return
        eject = mount.can_eject()
        if not eject and not mount.can_unmount():
            return
        root = mount.get_root().get_path()
        cancel = Gio.Cancellable()
        self.sidebar_mount_operations[uri] = cancel
        # No force flags or force-unmount prompt: busy devices report an error.
        def complete(source, result):
            self.sidebar_mount_operations.pop(uri, None)
            try:
                finish = source.eject_with_operation_finish if eject else source.unmount_with_operation_finish
                finish(result)
            except GLib.Error as error:
                if self.get_visible() and not cancel.is_cancelled():
                    self._show_error('Could not ' + self._sidebar_mount_action(mount).lower() + ' device', error.message)
                return
            if not self.get_visible() or cancel.is_cancelled():
                return
            self._mount_open_generation = getattr(self, '_mount_open_generation', 0) + 1
            if root and self.special_mode is None and self.current_dir.is_relative_to(Path(root)):
                self.quicklook.close()
                self.navigate(Path.home())
            self._refresh_sidebar()
        try:
            remove = mount.eject_with_operation if eject else mount.unmount_with_operation
            remove(Gio.MountUnmountFlags.NONE, None, cancel, complete)
        except GLib.Error as error:
            self.sidebar_mount_operations.pop(uri, None)
            self._show_error('Could not disconnect device', error.message)

    def _cancel_sidebar_operations(self, *_args):
        for cancel in tuple(self.sidebar_mount_operations.values()):
            cancel.cancel()
