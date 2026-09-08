"""Finder-style directory columns, sharing the picker's active selection contract."""
from types import SimpleNamespace

from gi.repository import Gdk, Gio, GLib, Gtk, Pango
from .drag_copy import disable_native_rubberband
from .list_navigation import focus_file


class ColumnBrowser(Gtk.ScrolledWindow):
    def __init__(self, owner):
        super().__init__(hexpand=True, vexpand=True)
        self.owner = owner
        self.columns = []
        self.active = None
        self.busy = False
        self.pending = 0
        self.focus_restore = None
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.set_min_content_width(1)
        self.set_propagate_natural_width(False)
        self.box = Gtk.Box()
        self.set_child(self.box)
        # The viewport otherwise follows the focused ancestor and undoes our
        # horizontal reveal as soon as the child column is allocated.
        self.get_child().set_scroll_to_focus(False)
        self.reveal_tick = 0
        click = Gtk.GestureClick(button=0)
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect('pressed', lambda g, _n, x, y: self.activate_at(
            self, x, y, reveal=g.get_current_button() == Gdk.BUTTON_PRIMARY))
        self.add_controller(click)

    def reveal_column(self, column):
        self.cancel_reveal()
        attempts, stable, previous = 0, 0, None

        def reveal(_widget, _clock):
            nonlocal attempts, stable, previous
            attempts += 1
            if column not in self.columns or attempts >= 60:
                self.reveal_tick = 0
                return False
            adjustment = self.get_hadjustment()
            valid, bounds = column.panel.compute_bounds(self.box)
            layout = (bounds.get_x(), bounds.get_width(), adjustment.get_upper(),
                      adjustment.get_page_size()) if valid else None
            stable = stable + 1 if layout == previous else 0
            previous = layout
            # Run after allocation and GTK's focus scrolling. Replacing a column
            # of the same width (including an empty folder) emits no size change.
            if not valid or bounds.get_width() <= 0 or adjustment.get_page_size() <= 0 or stable < 2:
                return True
            adjustment.clamp_page(bounds.get_x(), bounds.get_x() + bounds.get_width())
            self.reveal_tick = 0
            return False

        self.reveal_tick = self.add_tick_callback(reveal)

    def cancel_reveal(self):
        if self.reveal_tick:
            self.remove_tick_callback(self.reveal_tick)
            self.reveal_tick = 0

    def cancel_pending(self):
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending = 0

    def reset(self):
        self.cancel_pending()
        self.cancel_reveal()
        self.focus_restore = None
        self.busy = True
        for column in self.columns:
            self.box.remove(column.panel)
        self.columns.clear()
        self.active = None
        self.busy = False

    def rebuild(self):
        owner = self.owner
        focus = owner.get_focus()
        restore_focus = focus and focus.is_ancestor(self)
        # Keep the visible ancestors on refresh/history navigation. A new
        # sidebar/location destination starts a new trail rather than inventing
        # columns for every system ancestor.
        restore = getattr(self, 'restore_state', None)
        self.restore_state = None
        paths = [c.path for c in self.columns]
        if restore:
            paths = [path for path, _selected, _y in restore]
        elif owner.special_mode is None and owner.current_dir in paths:
            paths = paths[:paths.index(owner.current_dir) + 1]
        else:
            paths = [owner.current_dir]
        entries = owner.entries
        self.reset()
        owner.rating_badges.clear()
        self.busy = True
        for index, path in enumerate(paths):
            column = self.append(path, entries if path == owner.current_dir else None)
            if index:
                previous = self.columns[index - 1]
                child = previous.children.get(path)
                if child:
                    previous.flow.select_child(child)
        if restore:
            for column, (_path, selected, _y) in zip(self.columns, restore):
                column.flow.unselect_all()
                for path in selected:
                    if path in column.children:
                        column.flow.select_child(column.children[path])
            column = next((c for c in self.columns if c.path == owner.current_dir), self.columns[-1])
        self.activate(column, record=False)
        if restore_focus:
            self.focus_column(column)
        self.busy = False

    def focus_column(self, column, path=None):
        # Newly constructed flows are not mapped yet. GTK otherwise restores
        # focus into the first ancestor and emits a spurious selection there.
        self.focus_restore = column
        def restore(_widget, _clock):
            if self.focus_restore is column and column in self.columns:
                self.activate(column, record=False)
                selected = column.flow.get_selected_children()
                child = column.children.get(path) or (selected[0] if selected else None)
                if child:
                    focus_file(self.owner, child)
                else:
                    self.owner.set_focus(column.flow)
                valid, bounds = column.panel.compute_bounds(self.box)
                if valid:
                    adjustment = self.get_hadjustment()
                    left, right = bounds.get_x(), bounds.get_x() + bounds.get_width()
                    if left < adjustment.get_value():
                        adjustment.set_value(left)
                    elif right > adjustment.get_value() + adjustment.get_page_size():
                        adjustment.set_value(right - adjustment.get_page_size())
                self.focus_restore = None
            return False
        column.flow.add_tick_callback(restore)

    def append(self, path, entries=None):
        owner = self.owner
        cache = dict(owner.ratings.cache)
        entries = list(entries if entries is not None else owner._directory_entries(path))
        cache.update(owner.ratings.cache)
        owner.ratings.cache = cache
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.add_css_class('browser-column')
        panel.set_size_request(260, -1)
        title = Gtk.Label(label='Recent' if owner.special_mode == 'recent' else path.name or '/', xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        title.set_max_width_chars(26)
        title.add_css_class('column-heading')
        panel.append(title)
        flow = Gtk.FlowBox(valign=Gtk.Align.START)
        disable_native_rubberband(flow)
        flow.set_focusable(True)
        flow.add_css_class('file-list')
        flow.add_css_class('column-files')
        flow.set_selection_mode(Gtk.SelectionMode.MULTIPLE if owner.request.multiple else Gtk.SelectionMode.SINGLE)
        flow.set_activate_on_single_click(False)
        flow.set_min_children_per_line(1)
        flow.set_max_children_per_line(1)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(flow)
        panel.append(scroller)
        column = SimpleNamespace(path=path, panel=panel, flow=flow, scroller=scroller,
                                 entries=entries, children={})
        empty = Gtk.Label(label='No matching files' if owner.search.get_text() or owner.creative_filter != ('all', 0, '')
                          else 'Empty folder', valign=Gtk.Align.START, can_target=False)
        empty.add_css_class('column-empty')
        column.empty = empty
        panel.remove(scroller)
        overlay = Gtk.Overlay()
        overlay.set_child(scroller)
        overlay.add_overlay(empty)
        overlay.set_measure_overlay(empty, False)
        panel.append(overlay)
        self._populate(column)
        column.handler = flow.connect('selected-children-changed', self._selection, column)
        flow.connect('child-activated', owner._on_child_activated)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self._key, column)
        flow.add_controller(keys)
        self.columns.append(column)
        self.box.append(panel)
        self.reveal_column(column)
        return column

    def _populate(self, column):
        owner = self.owner
        for item in column.entries:
            child = Gtk.FlowBoxChild()
            child._picker_path = item
            child._picker_is_dir = item.is_dir()
            row = Gtk.Box(spacing=8, height_request=28)
            row.append(Gtk.Image.new_from_gicon(Gio.content_type_get_icon('inode/directory') if item.is_dir()
                       else Gio.content_type_get_icon(Gio.content_type_guess(str(item), None)[0])))
            name = Gtk.Label(label=item.name, xalign=0, hexpand=True)
            name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            name.set_width_chars(8)
            name.set_max_width_chars(22)
            row.append(name)
            row.append(owner._rating_badge(item))
            if item.is_dir():
                arrow = Gtk.Image.new_from_icon_name('go-next-symbolic')
                arrow.add_css_class('muted')
                arrow.set_pixel_size(12)
                row.append(arrow)
            child.set_child(row)
            column.flow.append(child)
            column.children[item] = child
        column.empty.set_visible(not column.entries)

    def refresh_paths(self, paths):
        """Refresh completed transfers in any visible column, preserving its trail."""
        owner = self.owner
        self.cancel_pending()
        self.busy = True
        try:
            for column in self.columns:
                if column.path not in paths:
                    continue
                selected = {c._picker_path for c in column.flow.get_selected_children()}
                focus = owner.get_focus()
                focused_path = getattr(focus, '_picker_path', None) if focus and focus.is_ancestor(column.flow) else None
                for path in column.children:
                    owner.rating_badges.pop(path, None)
                cache = dict(owner.ratings.cache)
                column.entries = owner._directory_entries(column.path)
                cache.update(owner.ratings.cache)
                owner.ratings.cache = cache
                column.flow.remove_all()
                column.children.clear()
                self._populate(column)
                for path in selected:
                    if path in column.children:
                        column.flow.select_child(column.children[path])
                if focused_path:
                    self.focus_column(column, focused_path)
            if self.active:
                self.activate(self.active, record=False)
                owner._on_selection_changed(self.active.flow)
        finally:
            self.busy = False

    def activate_focused(self):
        focus = self.owner.get_focus()
        if focus:
            for column in self.columns:
                if focus is column.flow or focus.is_ancestor(column.flow):
                    self.activate(column)
                    return

    def activate(self, column, *, record=True):
        owner = self.owner
        self.active = column
        owner.flow = column.flow
        owner.file_scroller = column.scroller
        owner.selection_changed_handler = column.handler
        owner.children_by_path = column.children
        owner.entries = column.entries
        for item in self.columns:
            (item.panel.add_css_class if item is column else item.panel.remove_css_class)('active-column')
        if owner.current_dir != column.path:
            owner.current_dir = column.path
            if record:
                owner.history = owner.history[:owner.history_index + 1]
                owner.history.append(column.path)
                owner.history_index = len(owner.history) - 1
            owner._rebuild_pathbar()
            owner._update_nav_state()
            owner._update_active_location()

    def activate_at(self, widget, x, y, *, reveal=False):
        picked = widget.pick(x, y, Gtk.PickFlags.DEFAULT)
        row = None
        while picked and not isinstance(picked, Gtk.Popover):
            if isinstance(picked, Gtk.FlowBoxChild):
                row = picked
            column = next((c for c in self.columns if c.panel is picked), None)
            if column:
                self.activate(column)
                # Leave file-row focus to GTK's native click handling. Focusing
                # the whole flow during capture can scroll to its old cursor
                # before the row receives the click.
                if row is None:
                    self.owner.set_focus(column.flow)
                elif reveal and row.is_selected() and len(column.flow.get_selected_children()) == 1:
                    index = self.columns.index(column) + 1
                    if index < len(self.columns) and self.columns[index].path == row._picker_path:
                        self.reveal_column(self.columns[index])
                self.owner._on_selection_changed(column.flow)
                return
            picked = picked.get_parent()

    def _selection(self, flow, column):
        if (self.busy or self.owner.view_mode != 'columns' or
                (self.focus_restore is not None and column is not self.focus_restore)):
            return
        self.activate(column)
        self.owner._on_selection_changed(flow)
        self.schedule_open()

    def schedule_open(self):
        self.cancel_pending()
        if not self.busy:
            self.pending = GLib.idle_add(self._open_selection)

    def _open_selection(self):
        self.pending = 0
        owner = self.owner
        if (owner.view_mode != 'columns' or not self.active or owner.drag_selection.active or
                owner.drag_copy.active or owner.context_popover):
            return False
        selected = owner._selected_paths()
        target = selected[0] if len(selected) == 1 and selected[0].is_dir() else None
        index = self.columns.index(self.active) + 1
        if index < len(self.columns) and self.columns[index].path == target:
            self.reveal_column(self.columns[index])
            return False
        self.busy = True
        try:
            for column in self.columns[index:]:
                self.box.remove(column.panel)
                for path in column.children:
                    owner.rating_badges.pop(path, None)
            del self.columns[index:]
        finally:
            self.busy = False
        if target:
            self.append(target)
        return False

    def enter_folder(self, column, path=None):
        """Enter the adjacent column without rebuilding scrolled ancestors."""
        self.activate(column)
        if path is not None:
            column.flow.handler_block(column.handler)
            try:
                column.flow.unselect_all()
                column.flow.select_child(column.children[path])
            finally:
                column.flow.handler_unblock(column.handler)
        self.cancel_pending()
        self._open_selection()
        index = self.columns.index(column) + 1
        if index < len(self.columns):
            destination = self.columns[index]
            self.activate(destination)
            self.focus_column(destination)
            if destination.children and not destination.flow.get_selected_children():
                destination.flow.select_child(next(iter(destination.children.values())))
            else:
                self.owner._on_selection_changed(destination.flow)

    def _key(self, _controller, keyval, _code, state, column):
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SHIFT_MASK):
            return False
        self.activate(column)
        if keyval == Gdk.KEY_Right:
            self.enter_folder(column)
            return True
        if keyval == Gdk.KEY_Left:
            index = self.columns.index(column)
            if index:
                destination = self.columns[index - 1]
                self.activate(destination)
                self.focus_column(destination)
                self.owner._on_selection_changed(destination.flow)
            return True
        return False
