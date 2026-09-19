"""Aligned list headings, customizable cells, and asynchronous media sorting."""
from gi.repository import Gdk, GLib, Gtk, Pango
from .list_metadata import (COLUMNS, DEFAULT_COLUMNS, EXTRA_SORTS, MEDIA_COLUMNS,
                            ListMetadataWorker, format_value, normalize_columns)
from .file_actions import sort_entries


class ListDetails:
    def __init__(self, owner):
        self.owner = owner
        self.data, self.rows, self.buttons = {}, {}, {}
        self.busy = False
        self.scope = None
        self.applied = False
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
        self.widget.append(self.header_scroll)
        self.status = Gtk.Label(xalign=0)
        self.status.add_css_class('list-sort-status')
        self.widget.append(self.status)
        self.popover = Gtk.Popover()
        self.popover.add_css_class('compact-popover')
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
        self.worker.close()
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        if self.popover.get_parent():
            self.popover.unparent()

    def columns(self):
        return normalize_columns(self.owner.file_preferences['list_columns'])

    def reset(self):
        self.worker.cancel()
        self.busy = self.applied = False
        self.scope = None
        self.data.clear()
        self.rows.clear()
        self.owner.standard_flow.set_sort_func(None)
        self.configure()

    def configure(self):
        self.popover.popdown()
        while child := self.header.get_first_child():
            if child is self.popover:
                child = child.get_next_sibling()
                if child is None:
                    break
            self.header.remove(child)
        self.buttons.clear()
        columns = self.columns()
        for key in columns:
            button = Gtk.Button()
            button.add_css_class('list-heading-button')
            button.set_size_request(COLUMNS[key][1], -1)
            button.set_hexpand(key == 'name')
            text = Gtk.Label(xalign=1 if key == columns[-1] and key != 'name' else 0,
                             ellipsize=Pango.EllipsizeMode.END)
            text.set_margin_start(0 if key == 'name' else 8)
            text.set_margin_end(0 if key == columns[-1] else 8)
            button.set_child(text)
            button.connect('clicked', lambda _, key=key: self.sort(key))
            self.header.append(button)
            self.buttons[key] = button
        listing = self.owner.view_mode == 'list'
        self.header_scroll.set_visible(listing)
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
            button.set_tooltip_text(f'Sort by {title}. Click again to reverse. Right-click to choose columns.')
            button.update_property([Gtk.AccessibleProperty.LABEL],
                [title + (', descending' if prefs['descending'] else ', ascending') if active else title])
        pending = prefs['sort_key'] in EXTRA_SORTS and not self.applied and bool(self.owner.entries)
        self.status.set_visible(pending)
        if pending:
            self.status.set_text(f'Reading {COLUMNS[prefs["sort_key"]][0]} for sorting… {len(self.data)}/{len(self.owner.entries)}')
        self.widget.set_visible(self.owner.view_mode == 'list' or pending)

    def sort(self, key):
        prefs = self.owner.file_preferences
        descending = not prefs['descending'] if prefs['sort_key'] == key else key not in {'name', 'type', 'codec'}
        self.owner._set_sort(key, descending)

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

    def menu_key(self, _controller, key, _code, modifiers):
        if key == Gdk.KEY_Menu or (key == Gdk.KEY_F10 and modifiers & Gdk.ModifierType.SHIFT_MASK):
            self.show_menu(None, 1, 12, 12)
            return True
        return False

    def show_menu(self, gesture, _count, x, y):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(content, 'set_margin_' + side)(10)
        content.append(Gtk.Label(label='Show columns', xalign=0))
        for key, (title, _) in COLUMNS.items():
            check = Gtk.CheckButton(label=title)
            check.set_active(key in self.columns())
            check.set_sensitive(key != 'name')
            check.connect('toggled', lambda button, key=key: self.choose(key, button.get_active()))
            content.append(check)
        reset = Gtk.Button(label='Reset columns')
        reset.connect('clicked', lambda *_: self.set_columns(DEFAULT_COLUMNS))
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
            cell = Gtk.Box(width_request=COLUMNS[key][1], hexpand=key == 'name')
            cell.add_css_class('list-cell')
            outer = cell
            cell = Gtk.Box(hexpand=True)
            cell.set_margin_start(0 if key == 'name' else 8)
            cell.set_margin_end(0 if key == columns[-1] else 8)
            outer.append(cell)
            if key == 'name':
                image = Gtk.Image.new_from_gicon(owner._search_result_icon(path))
                image.set_pixel_size(14)
                image.set_margin_end(6)
                cell.append(image)
                name = Gtk.Label(label=path.name, xalign=0, hexpand=True,
                                 ellipsize=Pango.EllipsizeMode.MIDDLE, width_chars=1)
                if owner._computer_search_active():
                    title = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
                    title.append(name)
                    title.append(owner._search_location_label(path))
                    cell.append(title)
                else:
                    cell.append(name)
                cell.append(owner._rating_badge(path))
            else:
                text = path.suffix[1:].upper() if key == 'type' else '…'
                if key == 'type' and owner._entry_is_dir(path):
                    text = 'Folder'
                value = Gtk.Label(label=text or 'File', xalign=1 if key == columns[-1] else 0, hexpand=True,
                                  ellipsize=Pango.EllipsizeMode.END, width_chars=1)
                value.add_css_class('muted')
                cell.append(value)
                cells[key] = value
            row.append(outer)
        self.rows[path] = cells
        return row

    def tick(self):
        owner = self.owner
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
            if key != 'type':
                text = format_value(key, values, show_time=self.owner.file_preferences['show_time'])
                label.set_text(text)
                label.set_tooltip_text('Unavailable or not applicable' if text == '—' else text)
        if last:
            self.busy = False
        self.update_header()

    def apply_sort(self):
        owner = self.owner
        prefs = owner.file_preferences
        ordered = sort_entries(owner.entries, prefs['sort_key'], prefs['descending'],
                               prefs['folders_first'], metadata=self.data)
        rank = {path: index for index, path in enumerate(ordered)}
        owner.flow.set_sort_func(lambda a, b: rank.get(a._picker_path, 0) - rank.get(b._picker_path, 0))
        owner.entries = ordered
        if owner.view_mode == 'columns' and owner.columns.active:
            owner.columns.active.entries = ordered
        self.applied = True
        self.update_header()
