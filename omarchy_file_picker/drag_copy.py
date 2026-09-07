"""Native file drags, folder targets and Finder-style disk-aware transfers."""
import threading
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from .drag_policy import plan_drop

FILE_DRAG_MIME = "application/x-omarchy-file-drag"


def disable_native_rubberband(flow):
    # FlowBox's own capture-phase rubber band can win before DragSource's
    # minimum hold time elapses. BackgroundSelection already owns blank drags;
    # leave FlowBox's separate click/range/keyboard controllers untouched.
    for controller in flow.observe_controllers():
        if isinstance(controller, Gtk.GestureDrag):
            controller.set_propagation_phase(Gtk.PropagationPhase.NONE)


class DragCopy:
    def __init__(self, owner):
        self.owner = owner
        self.paths = ()
        self.active = False
        self.highlight = None
        self.pointer = None
        self.drop_paths = ()
        self.scroller = None
        self.tick = 0
        self.armed = False
        self.hover_key = None
        self.hover_result = None
        self.hover_busy = False
        self.hover_pending = None
        self.icon_title = self.icon_image = None
        source = Gtk.DragSource(actions=Gdk.DragAction.COPY, button=Gdk.BUTTON_PRIMARY)
        source.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        source.connect('begin', self._begin)
        source.connect('end', self._gesture_end)
        source.connect('cancel', self._gesture_end)
        source.connect('prepare', self._prepare)
        source.connect('drag-begin', self._drag_begin)
        source.connect('drag-end', self._drag_end)
        owner.browser_stack.add_controller(source)
        self.source = source
        self.target = self._install_target(owner.browser_stack)
        self._install_target(owner.sidebar_scroll, self._sidebar_destination)
        owner.connect('unrealize', lambda *_: self.cancel())

    def _install_target(self, widget, destination=None):
        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        target.set_preload(True)
        target._destination = destination
        target.connect('enter', self._motion)
        target.connect('motion', self._motion)
        target.connect('leave', self._leave)
        target.connect('drop', self._drop)
        target.connect('notify::value', self._value_changed)
        widget.add_controller(target)
        return target

    def _sidebar_destination(self, x, y, paths):
        button = self.owner._sidebar_target(self.owner.sidebar_scroll.pick(x, y, Gtk.PickFlags.DEFAULT))
        path = getattr(button, '_picker_path', None)
        return path, button if path else None, None

    def _hit(self, x, y):
        widget = self.owner.browser_stack.pick(x, y, Gtk.PickFlags.DEFAULT)
        child = column = None
        while widget and widget is not self.owner.browser_stack:
            if isinstance(widget, (Gtk.Popover, Gtk.Scrollbar)):
                return None, None, False
            if isinstance(widget, Gtk.FlowBoxChild):
                child = widget
            if self.owner.view_mode == 'columns':
                column = column or next((c for c in self.owner.columns.columns if c.panel is widget), None)
            widget = widget.get_parent()
        return child, column, widget is self.owner.browser_stack

    def _begin(self, source, sequence):
        valid, x, y = source.get_point(sequence)
        if valid:
            self._arm(source, x, y)

    def _arm(self, source, x, y):
        self.paths, self.active, self.armed = (), False, False
        child, column, valid = self._hit(x, y)
        if not valid or child is None or self.owner.context_popover:
            source.set_state(Gtk.EventSequenceState.DENIED)
            return
        self.armed = True
        self.origin_child, self.origin_column = child, column
        flow = child.get_parent()
        self.paths = (tuple(item._picker_path for item in flow.get_selected_children())
                      if child.is_selected() else (child._picker_path,))
        # Ordinary clicks/ranges/double-clicks reach GTK unchanged. Claim their
        # sequence only after GTK's drag threshold. Alt presses retain the
        # existing copy-selection behavior.
        if source.get_current_event_state() & Gdk.ModifierType.ALT_MASK:
            self._claim(source)

    def _claim(self, source):
        self.active = True
        source.set_state(Gtk.EventSequenceState.CLAIMED)
        if self.origin_column:
            self.owner.columns.activate(self.origin_column)
            self.owner.columns.cancel_pending()
        flow = self.origin_child.get_parent()
        if {child._picker_path for child in flow.get_selected_children()} != set(self.paths):
            flow.unselect_all()
            for child in tuple(self.owner.children_by_path.values()):
                if child._picker_path in self.paths:
                    flow.select_child(child)
        if self.origin_column:
            self.owner.columns.cancel_pending()

    def _prepare(self, source, _x, _y):
        if not self.armed or not self.paths:
            return None
        self._claim(source)
        self.force_copy = bool(source.get_current_event_state() & Gdk.ModifierType.ALT_MASK)
        self.source.set_actions(Gdk.DragAction.COPY if self.force_copy else
                                Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        files = Gdk.FileList.new_from_list([Gio.File.new_for_path(str(p)) for p in self.paths])
        return Gdk.ContentProvider.new_union([
            Gdk.ContentProvider.new_for_value(files),
            Gdk.ContentProvider.new_for_bytes(FILE_DRAG_MIME, GLib.Bytes.new(b'files')),
        ])

    def _drag_begin(self, _source, drag):
        icon = Gtk.Box(spacing=8)
        icon.add_css_class('file-copy-drag')
        self.icon_image = Gtk.Image.new_from_icon_name('text-x-generic-symbolic')
        self.icon_title = Gtk.Label(ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=28)
        icon.append(self.icon_image)
        icon.append(self.icon_title)
        self.drag_name = self.paths[0].name if len(self.paths) == 1 else f'{len(self.paths)} items'
        self._update_icon(drag)
        drag.connect('notify::selected-action', lambda drag, _p: self._update_icon(drag))
        Gtk.DragIcon.get_for_drag(drag).set_child(icon)
        drag.set_hotspot(-12, -12)

    def _update_icon(self, drag):
        if self.icon_title is None:
            return
        copying = drag.get_selected_action() == Gdk.DragAction.COPY or self.force_copy
        self.icon_image.set_from_icon_name('list-add-symbolic' if copying else 'go-jump-symbolic')
        self.icon_title.set_text(('Copy ' if copying else 'Move ') + self.drag_name)

    def _drag_end(self, *_args):
        changed = {path.parent for path in self.paths}
        self._finish()
        # URI receivers perform file operations. Never delete paths merely on
        # GDK's delete-data flag: a queued or external transfer has no verified
        # receipt here. Our transfer engine owns every local move.
        def refresh():
            if self.owner.get_visible():
                if self.owner.view_mode == 'columns':
                    self.owner.columns.refresh_paths(changed)
                elif self.owner.current_dir in changed:
                    self.owner._refresh_files()
            return False
        GLib.idle_add(refresh)

    def _gesture_end(self, source, _sequence):
        # GTK resets gestures after creating GdkDrag, before drag-begin. Keep
        # the captured group across that reset, clearing it on the DND end.
        if source.get_drag() is None:
            self._finish()

    def _finish(self, *_args):
        self.paths, self.active, self.armed = (), False, False
        self.icon_title = self.icon_image = None
        self._leave()

    def cancel(self):
        self.source.drag_cancel()
        self.source.reset()
        self._finish()

    @staticmethod
    def _paths(value):
        if not isinstance(value, Gdk.FileList):
            return ()
        files = value.get_files()
        if not files or len(files) > 10_000:
            return ()
        paths = [file.get_path() for file in files]
        if any(path is None for path in paths):
            return ()
        return tuple(dict.fromkeys(Path(path) for path in paths))

    def _destination(self, x, y, paths):
        child, column, valid = self._hit(x, y)
        if not valid or (self.owner.view_mode == 'columns' and column is None):
            return None, None, None
        directory = column.path if column else self.owner.current_dir
        surface = column.panel if column else self.owner.browser_stack
        scroller = column.scroller if column else self.owner.standard_scroller
        if child and child._picker_path not in paths:
            if not child._picker_is_dir:
                return None, None, scroller
            directory, surface = child._picker_path, child
        elif self.owner.special_mode is not None:
            return None, None, scroller
        # Filesystem/alias checks happen again on the worker. Hover uses only
        # cached row kinds and path comparisons, never a potentially blocked NAS.
        if any(path == directory or path in directory.parents for path in paths):
            return None, None, scroller
        return directory, surface, scroller

    def _target_destination(self, target, x, y, paths):
        callback = getattr(target, '_destination', None) or self._destination
        directory, surface, scroller = callback(x, y, paths)
        if self.owner.file_job_active:
            return None, None, None
        if directory is None or any(p == directory or p in directory.parents for p in paths):
            return None, None, scroller
        return directory, surface, scroller

    def _copy_requested(self, target):
        drop = target.get_current_drop()
        return bool(target.get_current_event_state() & (Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.CONTROL_MASK)
                    or (drop and not drop.get_actions() & Gdk.DragAction.MOVE)
                    or (self.active and getattr(self, 'force_copy', False)))

    def _motion(self, target, x, y):
        paths = self._paths(target.get_value())
        self.drop_paths = paths
        directory, surface, self.scroller = self._target_destination(target, x, y, paths) if paths else (None, None, None)
        self._highlight(surface)
        self.pointer, self.motion_target = (x, y), target
        if self.scroller and not self.tick:
            self.tick = self.owner.browser_stack.add_tick_callback(self._scroll)
        if directory is None:
            return Gdk.DragAction(0)
        key = paths, directory, self._copy_requested(target)
        if key != self.hover_key:
            self.hover_key, self.hover_result = key, None
            self.hover_pending = key
            self._start_hover_check()
        action = Gdk.DragAction.COPY
        drop = target.get_current_drop()
        # Only our URI-transfer protocol negotiates MOVE. Other sources receive
        # COPY acknowledgement, so they cannot delete before our queued I/O.
        ours = drop is None or drop.get_formats().contain_mime_type(FILE_DRAG_MIME)
        if ours and self.hover_result and all(cut for _paths, cut in self.hover_result):
            action = Gdk.DragAction.MOVE
        tabs = getattr(self.owner, 'tabs', None)
        if tabs:
            tabs.drag_hover(surface)
        return action

    def _start_hover_check(self):
        if self.hover_busy or self.hover_pending is None:
            return
        key, self.hover_pending = self.hover_pending, None
        self.hover_busy = True
        def complete(result):
            self.hover_busy = False
            if self.hover_key == key and self.pointer and self.owner.get_visible():
                self.hover_result = result
                target = self.motion_target
                action = self._motion(target, *self.pointer)
                drop = target.get_current_drop()
                if drop:
                    drop.status(target.get_actions(), action)
            self._start_hover_check()
            return False
        def worker():
            try:
                result = plan_drop(key[0], key[1], force_copy=key[2])
            except (OSError, ValueError):
                result = None
            GLib.idle_add(complete, result)
        threading.Thread(target=worker, daemon=True).start()

    def _value_changed(self, target, _property):
        if self.pointer and target is self.motion_target:
            self._motion(target, *self.pointer)

    def _highlight(self, surface):
        if self.highlight is not surface:
            if self.highlight:
                self.highlight.remove_css_class('drop-copy-target')
            self.highlight = surface
            if surface:
                surface.add_css_class('drop-copy-target')

    def _leave(self, *_args):
        self._highlight(None)
        self.pointer = self.scroller = None
        self.drop_paths = ()
        self.hover_key = self.hover_result = self.hover_pending = None
        tabs = getattr(self.owner, 'tabs', None)
        if tabs:
            tabs.drag_hover(None)
        if self.tick:
            self.owner.browser_stack.remove_tick_callback(self.tick)
            self.tick = 0

    def _scroll(self, _widget, _clock):
        if self.pointer and self.scroller:
            x, y = self.pointer
            vertical = self.scroller.get_vadjustment()
            horizontal = self.owner.columns.get_hadjustment()
            previous = vertical.get_value(), horizontal.get_value()
            valid, bounds = self.scroller.compute_bounds(self.owner.browser_stack)
            if valid:
                self._step(vertical, y - bounds.get_y(), bounds.get_height())
            if self.owner.view_mode == 'columns':
                self._step(horizontal, x, self.owner.browser_stack.get_width())
            if previous != (vertical.get_value(), horizontal.get_value()):
                self._motion(self.motion_target, x, y)
        return True

    @staticmethod
    def _step(adjustment, position, size):
        speed = -10 if position < 24 else 10 if position > size - 24 else 0
        if speed:
            adjustment.set_value(max(adjustment.get_lower(), min(
                adjustment.get_upper() - adjustment.get_page_size(), adjustment.get_value() + speed)))

    def _drop(self, target, value, x, y):
        paths = self._paths(value)
        directory, _, _ = self._target_destination(target, x, y, paths) if paths else (None, None, None)
        force_copy = self._copy_requested(target)
        self._leave()
        if directory is None:
            return False
        return self.submit(paths, directory, force_copy=force_copy)

    def submit(self, paths, directory, *, force_copy=False):
        if self.owner.file_job_active:
            return False
        self.owner.file_job_active = True
        def complete(batches, error):
            owner = self.owner
            owner.file_job_active = False
            if error:
                owner._show_error('Could not transfer files', error)
                return False
            queue = owner.transfer_queue
            try:
                # Reserve the entire drop before any worker can finish; a full
                # queue must not accept just the moving half of a mixed drop.
                with queue.lock:
                    if len(queue.jobs) + len(batches) > 100:
                        raise ValueError('The queue is full. Clear finished transfers before adding more.')
                    jobs = [queue.add(group, directory, cut=cut, duplicate=not cut, start=True)
                            for group, cut in batches]
                for job in jobs:
                    owner._show_transfers(automatic_job=job)
            except ValueError as exc:
                owner._show_error('Could not transfer files', str(exc))
            return False
        def worker():
            try:
                batches, error = plan_drop(paths, directory, force_copy=force_copy), None
            except (OSError, ValueError) as exc:
                batches, error = [], str(exc)
            GLib.idle_add(complete, batches, error)
        threading.Thread(target=worker, daemon=True).start()
        return True
