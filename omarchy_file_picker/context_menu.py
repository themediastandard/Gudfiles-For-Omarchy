"""Pointer navigation for the custom, native cascading context menus."""
from gi.repository import GLib, Gtk


class HoverSubmenus:
    OPEN_DELAY_MS = 140
    CLOSE_DELAY_MS = 280

    def __init__(self, popover: Gtk.Popover):
        self.popover = popover
        self.pending = 0
        self.active = None
        self.pointer_suspended = False
        popover.connect('closed', self._reset)
        popover.connect('unmap', self._reset)
        self._keys(popover)
        row = popover.get_child().get_first_child()
        while row:
            if isinstance(row, Gtk.MenuButton):
                submenu = row.get_popover()
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

    def _key_pressed(self, *_):
        # Dismissing a popup changes GTK's pointer grab and can emit enter for
        # the row under a stationary pointer. Do not reopen after Escape.
        self.pointer_suspended = True
        self._cancel()
        return False

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
            self.active.popdown()
        return GLib.SOURCE_REMOVE

    def _opened(self, submenu):
        self._cancel()
        previous = self.active
        self.active = submenu
        if previous and previous is not submenu:
            previous.popdown()

    def _closed(self, submenu):
        if self.active is submenu:
            self.active = None
            self._cancel()
            # Closing by click, Escape or a timer can all release a grab.
            # Require actual motion before another hover opens a popup.
            self.pointer_suspended = True

    def _reset(self, *_):
        self._cancel()
        self.active = None
