"""Pointer navigation for the custom, native cascading context menus."""
from gi.repository import Gdk, GLib, Gtk


class HoverSubmenus:
    OPEN_DELAY_MS = 140
    CLOSE_DELAY_MS = 280

    def __init__(self, popover: Gtk.Popover):
        self.popover = popover
        self.pending = 0
        self.active = None
        self.pointer_suspended = False
        self.restore_cascade = 0
        # An outside click first dismisses the active modal submenu. Cascade
        # that dismissal through the root instead of leaving it stranded.
        popover.set_cascade_popdown(True)
        popover.connect('closed', self._reset)
        popover.connect('unmap', self._reset)
        self._keys(popover)
        row = popover.get_child().get_first_child()
        while row:
            if isinstance(row, Gtk.MenuButton):
                submenu = row.get_popover()
                row.set_create_popup_func(self._prepare_popup)
                self._keys(submenu)
                enter = lambda *_, b=row: self._enter_row(b)
                self._motion(row, enter, self._leave)
                self._motion(submenu, lambda *_, p=submenu: self._enter_submenu(p), self._leave)
                submenu.connect('map', self._opened)
                submenu.connect('unmap', self._closed)
            elif isinstance(row, Gtk.Button):
                self._motion(row, self._leave, None)
            row = row.get_next_sibling()

    def _keys(self, widget):
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self._key_pressed)
        widget.add_controller(keys)

    def _motion(self, widget, enter, leave):
        motion = Gtk.EventControllerMotion()
        motion.connect('enter', enter)
        motion.connect('motion', lambda *_: self._pointer_moved(motion, enter))
        if leave:
            motion.connect('leave', leave)
        widget.add_controller(motion)

    def _key_pressed(self, _controller, keyval, *_):
        # Dismissing a popup changes GTK's pointer grab and can emit enter for
        # the row under a stationary pointer. Do not reopen after Escape.
        self.pointer_suspended = True
        self._cancel()
        if keyval == Gdk.KEY_Escape and self.active:
            # Escape backs out of one submenu level. The default key handler
            # runs after this capture controller, so keep cascade disabled
            # through the rest of this event dispatch.
            self._suspend_cascade()
        return False

    def _suspend_cascade(self):
        self.popover.set_cascade_popdown(False)
        if not self.restore_cascade:
            self.restore_cascade = GLib.idle_add(self._restore_cascade)

    def _restore_cascade(self):
        self.restore_cascade = 0
        if self.popover.get_parent() is not None:
            self.popover.set_cascade_popdown(True)
        return GLib.SOURCE_REMOVE

    def _popdown_child(self, submenu):
        # Hover-closing or switching a submenu is internal navigation, not a
        # request to dismiss the root. GtkPopover otherwise cascades both.
        self.popover.set_cascade_popdown(False)
        try:
            submenu.popdown()
        finally:
            self.popover.set_cascade_popdown(True)

    def _pointer_moved(self, motion, resume):
        was_suspended = self.pointer_suspended
        self.pointer_suspended = False
        if was_suspended:
            if motion.contains_pointer():
                resume()
            else:
                # A grabbed popup also receives motion outside its surface.
                self._leave()

    def _cancel(self):
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending = 0

    def _enter_row(self, button):
        self._cancel()
        if self.pointer_suspended:
            return
        if not button.is_sensitive():
            self._leave()
            return
        if self.active is button.get_popover():
            return

        def open_submenu():
            self.pending = 0
            if self.popover.get_mapped() and button.get_mapped() and button.is_sensitive():
                button.popup()
            return GLib.SOURCE_REMOVE

        self.pending = GLib.timeout_add(self.OPEN_DELAY_MS, open_submenu)

    def _enter_submenu(self, submenu):
        if self.active is submenu:
            self._cancel()

    def _leave(self, *_):
        self._cancel()
        if self.active and not self.pointer_suspended:
            self.pending = GLib.timeout_add(self.CLOSE_DELAY_MS, self._close_active)

    def _close_active(self):
        self.pending = 0
        if self.active:
            self._popdown_child(self.active)
        return GLib.SOURCE_REMOVE

    def _prepare_popup(self, button, *_):
        # MenuButton calls this before mapping, for hover, click and keyboard
        # activation alike. Wayland requires the old grabbing popup to close
        # before a sibling can use their shared parent. Waiting for `map` is
        # too late: GDK refuses the new popup, so _opened never runs.
        self._cancel()
        previous = self.active
        if previous and previous is not button.get_popover():
            # This is a handoff, not dismissal. Its unmap must not suspend
            # hovering or cancel the incoming popup's native activation.
            self.active = None
            self._popdown_child(previous)

    def _opened(self, submenu):
        self._cancel()
        previous = self.active
        self.active = submenu
        if previous and previous is not submenu:
            self._popdown_child(previous)

    def _closed(self, submenu):
        if self.active is submenu:
            self.active = None
            self._cancel()
            # Closing by click, Escape or a timer can all release a grab.
            # Require actual motion before another hover opens a popup.
            self.pointer_suspended = True

    def _reset(self, *_):
        self._cancel()
        if self.restore_cascade:
            GLib.source_remove(self.restore_cascade)
            self.restore_cascade = 0
        self.active = None
