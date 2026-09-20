"""Search scope controls and latest-only computer results for the native picker."""
import os
from pathlib import Path

from gi.repository import Gtk, GLib, Gio, Pango

from .search import SearchService


class SearchTools:
    def _init_search(self):
        self.search_scope = 'folder'
        self.search_generation = 0
        self.search_key = None
        self.search_result = None
        self.search_pending = False
        self.search_service = SearchService()
        self.connect('unrealize', lambda *_: self._close_search())

    def _build_search_controls(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(content, 'set_margin_' + side)(10)
        self.search = Gtk.SearchEntry(placeholder_text='Search this folder')
        self.search.set_size_request(310, -1)
        content.append(self.search)
        choices = Gtk.Box(spacing=4, homogeneous=True)
        choices.add_css_class('view-switcher')
        self.search_scope_buttons = {}
        for scope, title in (('folder', 'This folder'), ('computer', 'Whole computer')):
            button = Gtk.ToggleButton(label=title)
            if self.search_scope_buttons:
                button.set_group(self.search_scope_buttons['folder'])
            button.connect('toggled', lambda b, value=scope:
                           self._set_search_scope(value) if b.get_active() else None)
            self.search_scope_buttons[scope] = button
            choices.append(button)
        content.append(choices)
        self.search_hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=40)
        self.search_hint.add_css_class('muted')
        content.append(self.search_hint)
        self.search_scope_buttons['folder'].set_active(True)
        self._update_search_scope()
        self._last_search = ''
        self.search.connect('changed', lambda *_: self._cancel_computer_search())
        self.search.connect('search-changed', self._search_changed)
        self.search.connect('stop-search', lambda *_: self.search_button.popdown())
        self.search.connect('activate', self._search_activated)
        self.search_popover.set_child(content)

    def _build_search_status(self):
        self.search_status = Gtk.Box(spacing=8)
        self.search_status.set_margin_start(12)
        self.search_status.set_margin_end(12)
        self.search_status.set_margin_bottom(6)
        self.search_spinner = Gtk.Spinner()
        self.search_status.append(self.search_spinner)
        self.search_status_label = Gtk.Label(xalign=0, hexpand=True,
                                            ellipsize=Pango.EllipsizeMode.END)
        self.search_status_label.add_css_class('muted')
        self.search_status.append(self.search_status_label)
        self.search_status.set_visible(False)
        return self.search_status

    def _set_search_scope(self, scope):
        if scope not in ('folder', 'computer') or scope == self.search_scope:
            return
        self.search_scope = scope
        self._cancel_computer_search()
        self._update_search_scope()
        if hasattr(self, 'browser_stack') and not getattr(self, '_restoring_tab', False):
            self._refresh_files()

    def _update_search_scope(self):
        self.search_scope_buttons[self.search_scope].set_active(True)
        for scope, button in self.search_scope_buttons.items():
            (button.add_css_class if scope == self.search_scope else button.remove_css_class)('active')
        trash = self.special_mode == 'trash'
        computer = self.search_scope == 'computer' and not trash
        self.search.set_property('placeholder-text', 'Search Trash' if trash else 'Search whole computer' if computer else 'Search this folder')
        self.search_hint.set_text('Search deleted names and original locations.' if trash else 'Search accessible files and mounted drives by name.' if computer
                                  else 'Search names in this folder, without subfolders.')

    def _computer_search_active(self):
        return self.special_mode != 'trash' and self.search_scope == 'computer' and bool(self.search.get_text().strip())

    def _cancel_computer_search(self):
        self.search_generation += 1
        self.search_service.cancel()
        self.search_pending = False
        self.search_key = self.search_result = None
        self._search_restore_selection = []
        if hasattr(self, 'search_status'):
            self.search_spinner.stop()
            self.search_status.set_visible(False)

    def _close_search(self):
        self._cancel_computer_search()
        self.search_service.close()

    def _computer_search_roots(self):
        # /run is excluded from the system walk; only exposed file mounts belong
        # in the search. Never initiate a network connection or request credentials.
        roots = [Path.home(), Path('/'), Path('/run/media')]
        for mount in self.volume_monitor.get_mounts():
            path = mount.get_root().get_path()
            if path:
                roots.append(Path(path))
        gvfs = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'gvfs'
        roots.append(gvfs)
        return list(dict.fromkeys(str(path) for path in roots))

    def _load_computer_search(self):
        active_filter = self._active_filter()
        options = dict(query=self.search.get_text(), roots=self._computer_search_roots(),
                       hidden=self.show_hidden, directories_only=self.request.directories_only,
                       filter=[active_filter.name, active_filter.rules] if active_filter else None)
        key = (str(self.current_dir), repr(options))
        if key == self.search_key:
            if self.search_result is not None:
                self._show_computer_results(self.search_result)
            else:
                self.entries = []
                self._rebuild_files()
                self._search_status_message('Searching whole computer…', working=True)
            return
        selected = getattr(self, '_search_restore_selection', [])
        self._cancel_computer_search()
        self._search_restore_selection = selected
        self.search_key = key
        self.search_pending = True
        self.entries = []
        self._rebuild_files()
        self._search_status_message('Searching whole computer…', working=True)
        self._rebuild_pathbar()
        self._update_nav_state()
        self._update_active_location()
        generation = self.search_generation

        def complete(result):
            if generation != self.search_generation or not self._computer_search_active():
                return False
            self.search_pending = False
            self.search_result = result
            self._show_computer_results(result)
            return False

        self.search_service.submit(options, lambda result: GLib.idle_add(complete, result))

    def _search_status_message(self, message, *, working=False):
        self.search_status_label.set_text(message)
        self.search_status_label.set_tooltip_text(message)
        self.search_status.set_visible(True)
        self.search_spinner.set_visible(working)
        (self.search_spinner.start if working else self.search_spinner.stop)()
        if not self.entries:
            self.empty_title.set_text('Searching…' if working else 'No results')
            self.empty_detail.set_text(message)
            if self.view_mode == 'columns' and self.columns.active:
                self.columns.active.empty.set_text('Searching…' if working else message)

    def _show_computer_results(self, result):
        selected = self._selected_paths() or getattr(self, '_search_restore_selection', [])
        self._search_restore_selection = []
        self.entries = self._sort_entries(self._creative_entries(result.paths), metadata=result.metadata)
        self._rebuild_files()
        for path in selected:
            if path in self.children_by_path:
                self.flow.select_child(self.children_by_path[path])
        message = f'{len(self.entries)} results · Whole computer'
        if result.limited:
            message += ' · Result limit reached; narrow your search'
        if result.timed_out:
            message += ' · Time limit reached; results may be incomplete'
        if result.skipped:
            message += ' · Some folders could not be read'
        if result.error:
            message += ' · ' + result.error
        self._search_status_message(message)

    def _entry_is_dir(self, path):
        if self._computer_search_active() and self.search_result is not None:
            return self.search_result.metadata.get(path, {}).get('directory', False)
        return path.is_dir()

    def _search_result_icon(self, path):
        content_type = 'inode/directory' if self._entry_is_dir(path) else Gio.content_type_guess(path.name, None)[0]
        return Gio.content_type_get_icon(content_type)

    def _search_location_label(self, path):
        location = Gtk.Label(label=str(path.parent), xalign=0,
                             ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=30)
        location.add_css_class('muted')
        return location
