"""Small creative controls shared by the file browser and its preview strip."""
import sqlite3

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, GLib, Gtk, Pango
from .ratings import COLORS, RatingStore, matches
from .list_metadata import ANNOTATION_COLUMNS


class CreativeTools:
    def _init_creative(self):
        self.ratings = RatingStore()
        self.rating_badges = {}
        self.creative_filter = ('all', 0, '')

    def _creative_entries(self, entries):
        try:
            self.ratings.refresh(entries)
        except (OSError, sqlite3.Error):
            self.ratings.cache = {}
        if self.creative_filter == ('all', 0, ''):
            return entries
        return [p for p in entries if self._entry_is_dir(p) or matches(self.ratings.get(p), *self.creative_filter)]

    def _rating_badge(self, path):
        badge = Gtk.Label()
        badge.add_css_class('rating-badge')
        badge.set_can_target(False)
        self.rating_badges[path] = badge
        self._update_rating_badge(path)
        return badge

    def _update_rating_badge(self, path):
        badge = self.rating_badges.get(path)
        if badge is None:
            return
        stars, color, rejected = self.ratings.get(path)
        for name in COLORS:
            badge.remove_css_class('label-' + name)
        badge.remove_css_class('rejected')
        columns = set(self.list_details.columns()) if self.view_mode == 'list' else set()
        text = ('×' if 'rejected' not in columns else '') if rejected else (
            f'★ {stars}' if stars and 'rating' not in columns else '')
        if color and 'color' not in columns:
            text = ('● ' + text).strip()
            badge.add_css_class('label-' + color)
        if rejected:
            badge.add_css_class('rejected')
        badge.set_text(text)
        badge.set_visible(bool(text))
        badge.set_tooltip_text(f'{stars} stars · {color or "No color"}' + (' · Rejected' if rejected else ''))

    def _apply_annotation(self, paths, **change):
        if not paths:
            return
        try:
            self.ratings.set_many(paths, **change)
        except (OSError, sqlite3.Error, ValueError) as error:
            self._show_error('Could not save labels', str(error))
            return
        for path in paths:
            self._update_rating_badge(path)
        self.list_details.refresh_annotations(paths)
        def update():
            if self.quicklook.get_visible() and self.quicklook.path in paths:
                self.quicklook.refresh_ratings()
            if self.creative_filter != ('all', 0, ''):
                previous = list(self.entries)
                previewed = self.quicklook.path if self.quicklook.get_visible() else None
                self._refresh_files(paths)
                if previewed and previewed not in self.entries:
                    index = previous.index(previewed) if previewed in previous else -1
                    neighbors = previous[index + 1:] + list(reversed(previous[:max(0, index)]))
                    target = next((p for p in neighbors if p in self.entries and p.is_file()), None)
                    if target:
                        self.flow.unselect_all()
                        self.flow.select_child(self.children_by_path[target])
                        self.quicklook.show_file(target)
                    else:
                        self.quicklook.close()
            else:
                if self.file_preferences['sort_key'] in ANNOTATION_COLUMNS:
                    self.list_details.apply_sort()
                if self._selected_paths():
                    self._update_metadata(self._selected_paths()[0])
            return False
        GLib.idle_add(update)

    def _creative_transfer_paths_renamed(self, mapping, receipt):
        return self._creative_paths_renamed(mapping, receipt=receipt)

    def _creative_paths_renamed(self, mapping, *, receipt=None):
        try:
            self.ratings.move(mapping, receipt=receipt)
            return True
        except (OSError, sqlite3.Error) as error:
            self._show_error('Files renamed; labels could not follow', str(error))
            return False

    def _rating_controls(self, paths):
        row = Gtk.Box(spacing=2, halign=Gtk.Align.START)
        row.add_css_class('rating-controls')
        values = [self.ratings.get(path) for path in paths]
        same_stars = values[0][0] if values and all(v[0] == values[0][0] for v in values) else 0
        for number in range(1, 6):
            button = Gtk.Button(label='★' if number <= same_stars else '☆')
            button.add_css_class('rating-star')
            if number <= same_stars:
                button.add_css_class('active')
            button.set_tooltip_text(f'{number} stars · Press {number}; 0 clears rating')
            button.connect('clicked', lambda _b, n=number: self._apply_annotation(paths, stars=n))
            row.append(button)
        color = values[0][1] if values and all(v[1] == values[0][1] for v in values) else ''
        palette = Gtk.MenuButton(label='●')
        palette.add_css_class('rating-color')
        if color:
            palette.add_css_class('label-' + color)
        palette.set_tooltip_text('Color label · applies to selected files')
        popover = Gtk.Popover()
        popover.add_css_class('creative-popover')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        heading = Gtk.Label(label='Color label', xalign=0)
        heading.add_css_class('creative-heading')
        box.append(heading)
        swatches = Gtk.Box(spacing=6)
        for name in ('', *COLORS):
            button = Gtk.Button(label='○' if not name else '●')
            button.add_css_class('color-swatch')
            if name:
                button.add_css_class('label-' + name)
            button.set_tooltip_text(name.title() if name else 'Clear color')
            def choose(_button, value=name):
                popover.popdown()
                self._apply_annotation(paths, color=value)
            button.connect('clicked', choose)
            swatches.append(button)
        box.append(swatches)
        popover.set_child(box)
        palette.set_popover(popover)
        row.append(palette)
        rejected = bool(values) and all(v[2] for v in values)
        reject = Gtk.Button.new_from_icon_name('edit-clear-symbolic')
        reject.add_css_class('rating-reject')
        if rejected:
            reject.add_css_class('active')
        reject.set_tooltip_text('Unmark rejected (X)' if rejected else 'Mark rejected (X) · does not delete files')
        reject.connect('clicked', lambda _b: self._apply_annotation(paths, rejected=not rejected))
        row.append(reject)
        return row

    def _creative_shortcut(self, keyval, state, paths):
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK):
            return False
        if not paths:
            return False
        if Gdk.KEY_0 <= keyval <= Gdk.KEY_5:
            self._apply_annotation(paths, stars=keyval - Gdk.KEY_0)
            return True
        if keyval in (Gdk.KEY_x, Gdk.KEY_X):
            self._apply_annotation(paths, rejected=not all(self.ratings.get(p)[2] for p in paths))
            return True
        return False

    def _creative_filter_button(self):
        button = Gtk.MenuButton(icon_name='starred-symbolic')
        button.set_tooltip_text('Filter by rating and color')
        button.add_css_class('creative-filter')
        popover = Gtk.Popover()
        popover.add_css_class('creative-popover')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        heading = Gtk.Label(label='Find your selects', xalign=0)
        heading.add_css_class('creative-heading')
        box.append(heading)
        modes = Gtk.Box(spacing=4)
        mode_buttons = []
        stars = Gtk.Box(spacing=4)
        star_buttons = []
        colors = Gtk.Box(spacing=5)
        color_buttons = []
        def refresh_controls():
            mode, minimum, color = self.creative_filter
            for group, chosen in ((mode_buttons, mode), (star_buttons, minimum), (color_buttons, color)):
                for item, value in group:
                    (item.add_css_class if value == chosen else item.remove_css_class)('active')
            (button.add_css_class if self.creative_filter != ('all', 0, '') else button.remove_css_class)('active')
        def change(index, value):
            current = list(self.creative_filter)
            current[index] = value
            self.creative_filter = tuple(current)
            refresh_controls()
            self._refresh_files()
        for title, value in [('All', 'all'), ('Rated', 'rated'), ('Rejected', 'rejected')]:
            item = Gtk.Button(label=title)
            item.add_css_class('creative-choice')
            item.connect('clicked', lambda _b, v=value: change(0, v))
            mode_buttons.append((item, value))
            modes.append(item)
        box.append(modes)
        box.append(Gtk.Label(label='Minimum rating', xalign=0, css_classes=['muted']))
        for number in range(6):
            item = Gtk.Button(label='Any' if number == 0 else f'{number}★')
            item.add_css_class('creative-choice')
            item.connect('clicked', lambda _b, v=number: change(1, v))
            star_buttons.append((item, number))
            stars.append(item)
        box.append(stars)
        box.append(Gtk.Label(label='Color', xalign=0, css_classes=['muted']))
        for name in ('', *COLORS):
            item = Gtk.Button(label='○' if not name else '●')
            item.set_tooltip_text(name.title() if name else 'Any color')
            item.add_css_class('color-swatch')
            if name:
                item.add_css_class('label-' + name)
            item.connect('clicked', lambda _b, v=name: change(2, v))
            color_buttons.append((item, name))
            colors.append(item)
        box.append(colors)
        reset = Gtk.Button(label='Clear filters', css_classes=['creative-choice'])
        def clear(_button):
            self.creative_filter = ('all', 0, '')
            refresh_controls()
            self._refresh_files()
        reset.connect('clicked', clear)
        box.append(reset)
        popover.set_child(box)
        button.set_popover(popover)
        self._refresh_creative_filter_controls = refresh_controls
        refresh_controls()
        return button

    def _build_active_filters(self):
        self.active_filters = Gtk.Box(spacing=8)
        self.active_filters.add_css_class('active-filters')
        self.active_filter_chips = Gtk.Box(spacing=6)
        scroller = Gtk.ScrolledWindow(hexpand=True)
        scroller.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        scroller.set_min_content_width(1)
        scroller.set_propagate_natural_width(False)
        scroller.set_child(self.active_filter_chips)
        self.active_filters.append(scroller)
        clear = Gtk.Button(label='Clear all')
        clear.add_css_class('clear-active-filters')
        clear.set_tooltip_text('Clear search, file type, rating and color filters; hide hidden files')
        clear.connect('clicked', lambda *_: self._clear_active_filter('all'))
        self.active_filters.append(clear)
        self.active_filters.set_visible(False)
        return self.active_filters

    def _update_active_filters(self):
        self._refresh_creative_filter_controls()
        self.hidden_button.set_icon_name('view-reveal-symbolic' if self.show_hidden else 'view-conceal-symbolic')
        self.hidden_button.set_tooltip_text(('Hide' if self.show_hidden else 'Show') + ' hidden files (Ctrl+H)')
        (self.hidden_button.add_css_class if self.show_hidden else self.hidden_button.remove_css_class)('active')
        while child := self.active_filter_chips.get_first_child():
            self.active_filter_chips.remove(child)
        mode, minimum, color = self.creative_filter
        items = []
        query = self.search.get_text()
        search_toggle = self.search_button.get_first_child()
        (search_toggle.add_css_class if query else search_toggle.remove_css_class)('active')
        self.search_button.set_tooltip_text('Search active · Edit search (Ctrl+F)' if query else 'Search (Ctrl+F)')
        if query:
            scope = 'Whole computer' if self.search_scope == 'computer' else 'This folder'
            items.append(('search', scope + ': ' + query))
        file_filter = self._active_filter() if hasattr(self, 'filter_combo') else None
        if file_filter:
            items.append(('type', 'Type: ' + file_filter.name))
        if mode != 'all':
            items.append(('mode', 'Rated' if mode == 'rated' else 'Rejected'))
        if minimum:
            items.append(('minimum', f'{minimum}★ & up'))
        if color:
            items.append(('color', color.title() + ' label'))
        if self.show_hidden:
            items.append(('hidden', 'Hidden files'))
        for key, text in items:
            chip = Gtk.Button()
            chip.filter_key = key
            chip.add_css_class('active-filter-chip')
            row = Gtk.Box(spacing=6)
            title = Gtk.Label(label=text, ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
            title.set_single_line_mode(True)
            if key == 'color':
                title.add_css_class('label-' + color)
            row.append(title)
            row.append(Gtk.Image.new_from_icon_name('window-close-symbolic'))
            chip.set_child(row)
            chip.set_tooltip_text(text + ' · Remove filter')
            # Rebuilding the strip must not destroy the current event target.
            chip.connect('clicked', lambda _button, k=key: GLib.idle_add(self._clear_active_filter, k))
            self.active_filter_chips.append(chip)
        self.active_filters.set_visible(bool(items))

    def _clear_active_filter(self, key):
        mode, minimum, color = self.creative_filter
        self.creative_filter = ('all' if key in ('all', 'mode') else mode,
                                0 if key in ('all', 'minimum') else minimum,
                                '' if key in ('all', 'color') else color)
        if key in ('all', 'search'):
            self.search.set_text('')
        if key in ('all', 'hidden'):
            self.show_hidden = False
        if key in ('all', 'type'):
            self.filter_combo.set_active(0)
        self._refresh_files()
        return False
