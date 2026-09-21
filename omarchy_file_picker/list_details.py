"""Aligned list headings, customizable cells, and asynchronous media sorting."""
from gi.repository import Gdk, GLib, Gtk, Pango
from .list_metadata import (ANNOTATION_COLUMNS, COLUMNS, DEFAULT_COLUMNS, EXTRA_SORTS, MEDIA_COLUMNS,
                            ListMetadataWorker, annotation_values, format_value, normalize_columns)
from .ratings import COLORS
from .thumbnail_widgets import Thumbnail
from .thumbnails import thumbnail_file


class ListDetails:
    def __init__(self, owner):
        self.owner = owner
        self.data, self.rows, self.buttons = {}, {}, {}
        self.name_labels = {}
        self.resize_start = None
        self.name_width = owner.file_preferences['list_name_width']
        self.busy = False
        self.scope = None
        self.applied = False
        self.dragged_column = None
        self.drag_candidate = None
        self.drag_position = None
        self.drag_scroll = 0
        self.drag_timer = 0
        self.display_columns = []
        self.drag_valid = False
        self.drag_offset = 0
        self.worker = ListMetadataWorker(GLib.idle_add)
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.header_scroll = Gtk.ScrolledWindow(hexpand=True)
        self.header_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.header_scroll.set_min_content_width(1)
        self.header_scroll.set_hadjustment(owner.standard_scroller.get_hadjustment())
        self.header = Gtk.Box()
        self.header.add_css_class('list-heading')
        self.header_scroll.set_child(self.header)
        self.header_scroll.get_child().set_scroll_to_focus(False)
        self.header_overlay = Gtk.Overlay()
        self.header_overlay.set_child(self.header_scroll)
        self.drag_layer = Gtk.Fixed(can_target=False)
        self.header_overlay.add_overlay(self.drag_layer)
        self.header_overlay.set_measure_overlay(self.drag_layer, False)
        self.header_overlay.set_clip_overlay(self.drag_layer, True)
        self.drag_ghost = Gtk.Box(spacing=6, can_target=False)
        self.drag_ghost.add_css_class('column-drag-ghost')
        grip = Gtk.Label(label='⠿')
        grip.add_css_class('column-drag-grip')
        self.drag_ghost.append(grip)
        self.drag_title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True)
        self.drag_ghost.append(self.drag_title)
        self.drag_layer.put(self.drag_ghost, 0, 0)
        self.drag_ghost.set_visible(False)
        self.widget.append(self.header_overlay)
        self._install_column_drag()
        self.status = Gtk.Label(xalign=0)
        self.status.add_css_class('list-sort-status')
        self.widget.append(self.status)
        self.popover = Gtk.Popover()
        self.popover.add_css_class('compact-popover')
        self.popover.add_css_class('columns-popover')
        self.popover.set_parent(self.header)
        gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesture.connect('pressed', self.show_menu)
        self.header.add_controller(gesture)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self.menu_key)
        self.header.add_controller(keys)
        self.timer = GLib.timeout_add(120, self.tick)
        owner.connect('unrealize', self.close)

    def close(self, *_):
        self._end_name_resize()
        self._end_column_drag()
        self.worker.close()
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        if self.popover.get_parent():
            self.popover.unparent()

    def columns(self):
        return normalize_columns(self.owner.file_preferences['list_columns'])

    def reset(self):
        self._end_name_resize()
        self._end_column_drag()
        self.worker.cancel()
        self.busy = self.applied = False
        self.scope = None
        self.data.clear()
        self.rows.clear()
        self.name_labels.clear()
        self.owner.standard_flow.set_sort_func(None)
        self.configure()

    def configure(self):
        self._end_name_resize()
        self._end_column_drag()
        self.popover.popdown()
        while child := self.header.get_first_child():
            if child is self.popover:
                child = child.get_next_sibling()
                if child is None:
                    break
            self.header.remove(child)
        self.buttons.clear()
        columns = self.columns()
        self.display_columns = list(columns)
        for key in columns:
            button = Gtk.Button()
            button.add_css_class('list-heading-button')
            button.set_size_request((self.name_width or COLUMNS[key][1]) if key == 'name' else COLUMNS[key][1], -1)
            button.set_hexpand(False)
            if key == 'name':
                button.add_css_class('name-heading')
            text = Gtk.Label(xalign=1 if key == columns[-1] and key != 'name' else 0,
                             ellipsize=Pango.EllipsizeMode.END)
            text.set_margin_start(0 if key == 'name' else 8)
            text.set_margin_end(0 if key == columns[-1] else 8)
            button.set_child(text)
            button.connect('clicked', lambda _, key=key: self.sort(key))
            self._column_keys(button, key)
            self.header.append(button)
            self.buttons[key] = button
        listing = self.owner.view_mode == 'list'
        self.header_scroll.set_visible(listing)
        self.header_overlay.set_visible(listing)
        self.owner.standard_scroller.set_policy(Gtk.PolicyType.AUTOMATIC if listing else Gtk.PolicyType.NEVER,
                                                Gtk.PolicyType.AUTOMATIC)
        self.owner.standard_flow.set_hexpand(True)
        self.update_header()

    def update_header(self):
        prefs = self.owner.file_preferences
        for key, button in self.buttons.items():
            title = COLUMNS[key][0]
            active = key == prefs['sort_key']
            (button.add_css_class if active else button.remove_css_class)('active')
            button.get_child().set_text(title + (' ↓' if prefs['descending'] else ' ↑') if active else title)
            movement = ('Drag the right edge to resize; double-click it to fit filenames. Name stays first.'
                        if key == 'name' else 'Drag or Alt+Left/Right to reorder.')
            button.set_tooltip_text(f'Sort by {title}. Click again to reverse. {movement} Right-click to choose columns.')
            button.update_property([Gtk.AccessibleProperty.LABEL],
                [title + (', descending' if prefs['descending'] else ', ascending') if active else title])
        pending = prefs['sort_key'] in EXTRA_SORTS and not self.applied and bool(self.owner.entries)
        self.status.set_visible(pending)
        if pending:
            self.status.set_text(f'Reading {COLUMNS[prefs["sort_key"]][0]} for sorting… {len(self.data)}/{len(self.owner.entries)}')
        self.widget.set_visible(self.owner.special_mode != 'trash' and (self.owner.view_mode == 'list' or pending))

    def sort(self, key):
        if self.dragged_column is not None or self.resize_start is not None:
            return
        prefs = self.owner.file_preferences
        descending = not prefs['descending'] if prefs['sort_key'] == key else key not in {'name', 'type', 'codec', 'color'}
        self.owner._set_sort(key, descending)

    def _column_cells(self):
        for child in self.owner.children_by_path.values():
            row = child.get_child()
            cell = row.get_first_child() if row else None
            while cell:
                key = getattr(cell, '_list_column', None)
                if key is not None:
                    yield key, cell
                cell = cell.get_next_sibling()

    def _shade_column(self):
        for key, widget in [*self.buttons.items(), *self._column_cells()]:
            (widget.add_css_class if key == self.dragged_column else
             widget.remove_css_class)('column-drag-slot')

    def _end_column_drag(self, *_, commit=False):
        if self.dragged_column is not None and not commit:
            self._reorder_widgets(self.columns())
        self.dragged_column = None
        self.drag_candidate = None
        self.drag_position = None
        self.drag_scroll = 0
        self.drag_valid = False
        if self.drag_timer:
            GLib.source_remove(self.drag_timer)
            self.drag_timer = 0
        self.drag_ghost.set_visible(False)
        self.header_scroll.set_cursor_from_name(None)
        self._shade_column()

    def _mark_column_target(self, x, y):
        width, height = self.header_scroll.get_width(), self.header_scroll.get_height()
        self.drag_valid = 0 <= x <= width and 0 <= y <= height
        ghost_width = self.drag_ghost.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        self.drag_layer.move(self.drag_ghost, max(0, min(width - ghost_width, x - self.drag_offset)), 0)
        self.drag_ghost.set_opacity(1 if self.drag_valid else .45)
        if not self.drag_valid:
            self.drag_scroll = 0
            return
        self.drag_scroll = -1 if x < 28 else 1 if x > width - 28 else 0
        # Keep Name anchored. The other columns move aside as their midpoint
        # is crossed. Using their live bounds gives the source slot hysteresis
        # instead of repeatedly swapping back under a stationary pointer.
        order = [key for key in self.display_columns if key != self.dragged_column]
        index = 1
        for key in order[1:]:
            valid, bounds = self.buttons[key].compute_bounds(self.header_scroll)
            if valid and x >= bounds.get_x() + bounds.get_width() / 2:
                index += 1
        order.insert(index, self.dragged_column)
        if order != self.display_columns:
            self._reorder_widgets(order)

    def _scroll_drag(self):
        if self.dragged_column is None:
            self.drag_timer = 0
            return False
        adjustment = self.header_scroll.get_hadjustment()
        maximum = max(0, adjustment.get_upper() - adjustment.get_page_size())
        adjustment.set_value(max(0, min(maximum, adjustment.get_value() + self.drag_scroll * 16)))
        if self.drag_position:
            self._mark_column_target(*self.drag_position)
        return True

    def _name_edge(self, x, y):
        button = self.buttons.get('name')
        if button is None:
            return False
        valid, bounds = button.compute_bounds(self.header_scroll)
        return (valid and 0 <= y <= self.header_scroll.get_height()
                and abs(x - bounds.get_x() - bounds.get_width()) <= 6)

    def _set_name_width(self, width, *, save=False):
        self.name_width = max(96, min(32768, round(width))) if width else 0
        for key, widget in [*self.buttons.items(), *self._column_cells()]:
            if key == 'name':
                widget.set_size_request(self.name_width or COLUMNS['name'][1], -1)
                widget.set_hexpand(False)
        if save:
            self.owner._set_file_preference('list_name_width', self.name_width, reload=False)

    def _end_name_resize(self, *, commit=False):
        if self.resize_start is None:
            return
        _, previous = self.resize_start
        self.resize_start = None
        self._set_name_width(self.name_width if commit else previous, save=commit)
        self.header_scroll.set_cursor_from_name(None)

    def fit_name(self):
        # Measure every displayed row, including offscreen names, using its actual
        # font. Copy the layout so measuring never changes the live ellipsized text.
        width = COLUMNS['name'][1]
        for label, cell in self.name_labels.values():
            layout = label.get_layout().copy()
            layout.set_width(-1)
            layout.set_ellipsize(Pango.EllipsizeMode.NONE)
            needed = layout.get_pixel_size()[0] + cell.get_margin_start() + cell.get_margin_end()
            child = cell.get_first_child()
            while child:
                # Search wraps the filename with its parent-location label.
                if child is not label and child is not label.get_parent() and child.get_visible():
                    needed += child.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
                child = child.get_next_sibling()
            width = max(width, needed + 2)
        self.resize_start = None
        # Fitting is an explicit action for this window, not a new-window default.
        self._set_name_width(width)

    def _install_column_drag(self):
        # The viewport stays in place while headings reorder beneath it, so
        # drag coordinates never jump with the dragged button's allocation.
        gesture = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        start = [0., 0.]
        def begin(_gesture, x, y):
            start[:] = [x, y]
            self.drag_candidate = None
            if self._name_edge(x, y):
                self.resize_start = (self.buttons['name'].get_width(), self.name_width)
                self.buttons['name'].grab_focus()
                _gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                return
            picked = self.header_scroll.pick(x, y, Gtk.PickFlags.DEFAULT)
            while picked and picked not in self.buttons.values():
                picked = picked.get_parent()
            if picked:
                self.drag_candidate = next(key for key, button in self.buttons.items() if button is picked)
                valid, bounds = picked.compute_bounds(self.header_scroll)
                self.drag_offset = x - bounds.get_x() if valid else 0
        def update(source, dx, dy):
            if self.resize_start is not None:
                self._set_name_width(self.resize_start[0] + dx)
                self.header_scroll.set_cursor_from_name('col-resize')
                return
            key = self.drag_candidate
            if key is None:
                return
            if self.dragged_column is None:
                if max(abs(dx), abs(dy)) <= self.header_scroll.get_settings().get_property('gtk-dnd-drag-threshold'):
                    return
                source.set_state(Gtk.EventSequenceState.CLAIMED)
                if key == 'name':
                    self.drag_candidate = None
                    return
                self.dragged_column = key
                self.buttons[key].grab_focus()
                self.drag_title.set_text(self.buttons[key].get_child().get_text())
                self.drag_ghost.set_size_request(max(1, self.buttons[key].get_width() - 16),
                                                 max(1, self.header_scroll.get_height() - 2))
                self.drag_ghost.set_visible(True)
                self.header_scroll.set_cursor_from_name('grabbing')
                self._shade_column()
                self.drag_timer = GLib.timeout_add(40, self._scroll_drag)
            self.drag_position = (start[0] + dx, start[1] + dy)
            self._mark_column_target(*self.drag_position)
        def end(_gesture, _dx, _dy):
            if self.resize_start is not None:
                # A single edge click must not turn an automatic width into a
                # fixed width. Only a drag or double-click changes preferences.
                self._end_name_resize(commit=abs(_dx) >= 1)
                return
            key = self.dragged_column
            commit = key is not None and self.drag_valid
            order = list(self.display_columns)
            self._end_column_drag(commit=commit)
            self.drag_candidate = None
            if commit:
                self._save_column_order(order, key)
        gesture.connect('drag-begin', begin)
        gesture.connect('drag-update', update)
        gesture.connect('drag-end', end)
        def cancel(*_):
            self._end_name_resize()
            self.drag_candidate = None
            self._end_column_drag()
        gesture.connect('cancel', cancel)
        self.header_scroll.add_controller(gesture)
        click = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.header_scroll.add_controller(click)
        click.group(gesture)
        def pressed(source, count, x, y):
            if self._name_edge(x, y):
                source.set_state(Gtk.EventSequenceState.CLAIMED)
                if count == 2:
                    self.fit_name()
        click.connect('pressed', pressed)
        motion = Gtk.EventControllerMotion()
        def moved(_controller, x, y):
            if self.dragged_column is None:
                self.header_scroll.set_cursor_from_name(
                    'col-resize' if self.resize_start is not None or self._name_edge(x, y) else None)
        motion.connect('motion', moved)
        motion.connect('leave', lambda *_: self.header_scroll.set_cursor_from_name(None)
                       if self.resize_start is None and self.dragged_column is None else None)
        self.header_scroll.add_controller(motion)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        def key_pressed(_controller, value, *_):
            if value == Gdk.KEY_Escape and (self.dragged_column is not None or self.resize_start is not None):
                cancel()
                return True
            return False
        keys.connect('key-pressed', key_pressed)
        self.header_scroll.add_controller(keys)

    def _column_keys(self, button, key):
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', lambda _controller, value, _code, state:
                     self.column_key(key, value, state))
        button.add_controller(keys)

    def _reorder_widgets(self, columns):
        if set(columns) != set(self.buttons):
            return
        before = None
        for key in columns:
            button = self.buttons[key]
            self.header.reorder_child_after(button, before)
            text = button.get_child()
            text.set_margin_end(0 if key == columns[-1] else 8)
            text.set_xalign(1 if key == columns[-1] and key != 'name' else 0)
            before = button
        for path, child in self.owner.children_by_path.items():
            row = child.get_child()
            cells, cell = {}, row.get_first_child() if row else None
            while cell:
                cells[getattr(cell, '_list_column', None)] = cell
                cell = cell.get_next_sibling()
            if not all(key in cells for key in columns):
                continue
            before = None
            for key in columns:
                cell = cells[key]
                row.reorder_child_after(cell, before)
                cell.get_first_child().set_margin_end(0 if key == columns[-1] else 8)
                if label := self.rows.get(path, {}).get(key):
                    label.set_xalign(1 if key == columns[-1] else 0)
                before = cell
        self.display_columns = list(columns)

    def _save_column_order(self, columns, key):
        previous = self.columns()
        def apply():
            if (not self.owner.get_realized() or self.owner.view_mode != 'list'
                    or self.dragged_column is not None or self.columns() != previous):
                return False
            if columns != previous:
                self.owner._set_file_preferences({'list_columns': columns}, reload=False)
            self._reorder_widgets(columns)
            self.buttons[key].grab_focus()
            GLib.timeout_add(40, self._reveal_column, key)
            return False
        GLib.idle_add(apply)

    def move_column(self, key, target, after):
        columns = self.columns()
        if (key == 'name' or key == target or key not in columns or target not in columns
                or self.dragged_column is not None):
            return
        columns.remove(key)
        columns.insert(max(1, columns.index(target) + int(after)), key)
        self._save_column_order(columns, key)

    def _reveal_column(self, key):
        button = self.buttons.get(key)
        if button is None or not button.get_mapped():
            return False
        valid, bounds = button.compute_bounds(self.header_scroll)
        if valid:
            adjustment = self.header_scroll.get_hadjustment()
            right = bounds.get_x() + bounds.get_width()
            offset = (bounds.get_x() if bounds.get_x() < 0 else
                      max(0, right - self.header_scroll.get_width()))
            maximum = max(0, adjustment.get_upper() - adjustment.get_page_size())
            adjustment.set_value(max(0, min(maximum, adjustment.get_value() + offset)))
        return False

    def column_key(self, key, value, state):
        if not state & Gdk.ModifierType.ALT_MASK or value not in (Gdk.KEY_Left, Gdk.KEY_Right):
            return False
        columns = self.columns()
        index = columns.index(key) + (-1 if value == Gdk.KEY_Left else 1)
        if key != 'name' and self.dragged_column is None and 1 <= index < len(columns):
            self.move_column(key, columns[index], value == Gdk.KEY_Right)
        return True

    def choose(self, key, active):
        selected = self.columns()
        if active and key not in selected:
            selected.append(key)
        elif not active and key in selected and key != 'name':
            selected.remove(key)
        self.set_columns(selected)

    def set_columns(self, columns):
        columns = normalize_columns(columns)
        self.popover.popdown()
        self.owner._set_file_preferences(dict(list_columns=columns, show_size='size' in columns,
                                             show_type='type' in columns), reload=False)
        self.owner._refresh_files(rescan=False)

    def reset_columns(self):
        self._end_name_resize()
        self._set_name_width(0, save=True)
        self.set_columns(DEFAULT_COLUMNS)

    def menu_key(self, _controller, key, _code, modifiers):
        if key == Gdk.KEY_Menu or (key == Gdk.KEY_F10 and modifiers & Gdk.ModifierType.SHIFT_MASK):
            self.show_menu(None, 1, 12, 12)
            return True
        return False

    def show_menu(self, gesture, _count, x, y):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        content.set_size_request(160, -1)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(content, 'set_margin_' + side)(8)
        heading = Gtk.Label(label='Show columns', xalign=0)
        heading.add_css_class('columns-heading')
        content.append(heading)
        order = self.columns() + [key for key in COLUMNS if key not in self.columns()]
        for key in order:
            title = COLUMNS[key][0]
            check = Gtk.CheckButton(label=title)
            check.set_active(key in self.columns())
            check.set_sensitive(key != 'name')
            check.connect('toggled', lambda button, key=key: self.choose(key, button.get_active()))
            content.append(check)
        hint = Gtk.Label(label='Drag headers or use Alt+← / →\nName stays first', xalign=0)
        hint.add_css_class('muted')
        content.append(hint)
        reset = Gtk.Button(label='Reset columns')
        reset.add_css_class('columns-reset')
        reset.connect('clicked', lambda *_: self.reset_columns())
        content.append(reset)
        self.popover.set_child(content)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self.popover.set_pointing_to(rect)
        self.popover.popup()
        if gesture:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def row(self, path):
        owner = self.owner
        row = Gtk.Box(height_request=24)
        row.set_hexpand(True)
        cells = {}
        columns = self.columns()
        for key in columns:
            cell = Gtk.Box(width_request=(self.name_width or COLUMNS[key][1]) if key == 'name' else COLUMNS[key][1],
                           hexpand=False)
            cell.add_css_class('list-cell')
            outer = cell
            outer._list_column = key
            cell = Gtk.Box(hexpand=True)
            cell.set_margin_start(0 if key == 'name' else 8)
            cell.set_margin_end(0 if key == columns[-1] else 8)
            outer.append(cell)
            if key == 'name':
                icon = owner._search_result_icon(path)
                if not owner._computer_search_active() and not owner._entry_is_dir(path):
                    image = Thumbnail(path, 24, 20, icon, thumbnail_file, crop=False)
                else:
                    image = Gtk.Image.new_from_gicon(icon)
                    image.set_pixel_size(14)
                    image.set_size_request(24, 20)
                image.set_valign(Gtk.Align.CENTER)
                image.set_margin_end(6)
                cell.append(image)
                name = Gtk.Label(label=path.name, xalign=0, hexpand=True,
                                 ellipsize=Pango.EllipsizeMode.MIDDLE, width_chars=1, max_width_chars=1)
                # size_request is only a minimum. Bound the label's natural
                # width too, or Gtk.Box grants each row its full filename width
                # when the window has spare space, ignoring the header divider.
                self.name_labels[path] = (name, cell)
                if owner._computer_search_active():
                    title = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
                    title.append(name)
                    location = owner._search_location_label(path)
                    location.set_max_width_chars(1)
                    title.append(location)
                    cell.append(title)
                else:
                    cell.append(name)
                cell.append(owner._rating_badge(path))
            else:
                text = path.suffix[1:].upper() if key == 'type' else '…'
                if key == 'type' and owner._entry_is_dir(path):
                    text = 'Folder'
                value = Gtk.Label(label=text or 'File', xalign=1 if key == columns[-1] else 0, hexpand=True,
                                  ellipsize=Pango.EllipsizeMode.END, width_chars=1, max_width_chars=1)
                value.add_css_class('muted')
                cell.append(value)
                cells[key] = value
            row.append(outer)
        self.rows[path] = cells
        self.refresh_annotations([path])
        return row

    def refresh_annotations(self, paths):
        for path in paths:
            values = annotation_values(self.owner.ratings.get(path))
            for key in ANNOTATION_COLUMNS:
                label = self.rows.get(path, {}).get(key)
                if label is None:
                    continue
                label.set_text(format_value(key, values))
                if key == 'rating':
                    description = f'{values[key]} of 5 stars' if values[key] else 'Unrated'
                elif key == 'color':
                    description = values[key].title() if values[key] else 'No color label'
                    for color in COLORS:
                        label.remove_css_class('label-' + color)
                    if values[key]:
                        label.add_css_class('label-' + values[key])
                else:
                    description = 'Rejected' if values[key] else 'Not rejected'
                label.update_property([Gtk.AccessibleProperty.LABEL], [description])

    def tick(self):
        owner = self.owner
        if owner.special_mode == 'trash':
            return True
        scope = (id(owner.flow), frozenset(owner.entries), owner.view_mode)
        if scope != self.scope:
            self.worker.cancel()
            self.scope = scope
            self.busy = self.applied = False
            self.data.clear()
        self.update_header()
        if self.busy:
            return True
        key = owner.file_preferences['sort_key']
        sorting = key in EXTRA_SORTS and not self.applied
        media = key in MEDIA_COLUMNS if sorting else bool(set(self.columns()) & MEDIA_COLUMNS)
        if sorting:
            candidates = owner.entries
        elif owner.view_mode == 'list' and owner.get_mapped():
            candidates = []
            scroller = owner.standard_scroller
            for path, child in owner.children_by_path.items():
                valid, bounds = child.compute_bounds(scroller)
                if valid and bounds.get_y() + bounds.get_height() > 0 and bounds.get_y() < scroller.get_height():
                    candidates.append(path)
        else:
            return True
        missing = [p for p in candidates if p not in self.data or (media and not self.data[p].get('_media'))]
        if not missing:
            if sorting:
                self.apply_sort()
            return True
        self.busy = True
        self.worker.submit(missing[:16], media, self.ready)
        return True

    def ready(self, path, values, last):
        self.data[path] = values
        for key, label in self.rows.get(path, {}).items():
            if key != 'type' and key not in ANNOTATION_COLUMNS:
                text = format_value(key, values, show_time=self.owner.file_preferences['show_time'])
                label.set_text(text)
                label.update_property([Gtk.AccessibleProperty.LABEL],
                                      ['Unavailable or not applicable' if text == '—' else text])
        if last:
            self.busy = False
        self.update_header()

    def apply_sort(self):
        owner = self.owner
        ordered = owner._sort_entries(owner.entries, metadata=self.data)
        rank = {path: index for index, path in enumerate(ordered)}
        owner.flow.set_sort_func(lambda a, b: rank.get(a._picker_path, 0) - rank.get(b._picker_path, 0))
        owner.entries = ordered
        if owner.view_mode == 'columns' and owner.columns.active:
            owner.columns.active.entries = ordered
        self.applied = True
        self.update_header()
