from __future__ import annotations

import json
import os
import stat as stat_module
import threading
from datetime import datetime
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk

from .dialogs import PickerDialog, confirmation, detail_card, entry_field, file_summary, path_list, section

from .file_actions import (RemovalError, TrashUnavailable, delete_after_trash_failure,
                          parse_file_clipboard, remove_items, rename_item, transfer_items)
from .transfer_ui import TransferUI
from .sound_effects import ActionSounds
from .list_metadata import ANNOTATION_COLUMNS, COLUMNS, DEFAULT_COLUMNS, EXTRA_SORTS, normalize_columns

SIDEBAR_MIN_WIDTH = 180
SIDEBAR_DEFAULT_WIDTH = 220
from .model import file_type, format_size

SORT_OPTIONS = (
    ('modified', True, 'Newest first'),
    ('modified', False, 'Oldest first'),
    ('name', False, 'Name A–Z'),
    ('name', True, 'Name Z–A'),
    ('size', True, 'Largest first'),
    ('size', False, 'Smallest first'),
    ('type', False, 'Type A–Z'),
    ('type', True, 'Type Z–A'),
)


class FileManagement(TransferUI):
    """Native dialogs and actions shared by keyboard and context menus."""

    @staticmethod
    def _dismiss_dialog(dialog):
        # Release input focus while the entry still exists; destroy after queued
        # Wayland input-method notifications have had a chance to run.
        dialog.set_focus(None)
        dialog.set_visible(False)
        GLib.idle_add(lambda: dialog.destroy() or False)

    def _init_file_management(self):
        self.file_job_active = False
        self._init_transfers()
        self.preferences_path = Path.home() / '.config/omarchy-file-picker/preferences.json'
        self.bookmarks_path = Path.home() / '.config/gtk-3.0/bookmarks'
        defaults = dict(sort_key='name', descending=False, folders_first=True,
                        show_size=True, show_type=True, show_time=True, sidebar_width=SIDEBAR_DEFAULT_WIDTH,
                        transfer_mode='queue', hidden_locations=[], view_mode='grid', sound_effects=True,
                        list_columns=list(DEFAULT_COLUMNS))
        saved = {}
        try:
            saved = json.loads(self.preferences_path.read_text())
            if not isinstance(saved, dict):
                saved = {}
            for key, default in defaults.items():
                if isinstance(saved.get(key), type(default)):
                    defaults[key] = saved[key]
        except (OSError, ValueError, TypeError):
            pass
        defaults['list_columns'] = normalize_columns(defaults['list_columns'])
        if 'list_columns' not in saved and not defaults['show_size']:
            defaults['list_columns'].remove('size')
        defaults['show_size'] = 'size' in defaults['list_columns']
        defaults['show_type'] = 'type' in defaults['list_columns']
        if defaults['sort_key'] not in {'name', 'modified', 'size', 'type'} | EXTRA_SORTS | ANNOTATION_COLUMNS:
            defaults['sort_key'] = 'name'
        if defaults['transfer_mode'] not in {'queue', 'all'}:
            defaults['transfer_mode'] = 'queue'
        if defaults['view_mode'] not in {'grid', 'list', 'columns'}:
            defaults['view_mode'] = 'grid'
        defaults['hidden_locations'] = [key for key in defaults['hidden_locations'] if isinstance(key, str)]
        defaults['sidebar_width'] = max(SIDEBAR_MIN_WIDTH, defaults['sidebar_width'])
        self.file_preferences = defaults
        self.action_sounds = ActionSounds(self.preferences_path)
        self.connect('unrealize', self.action_sounds.close)

    def _play_sound(self, cue):
        self.action_sounds.play(cue)

    def _toggle_sound_effects(self):
        enabled = not self.action_sounds.enabled
        self._set_file_preference('sound_effects', enabled, reload=False)
        if not enabled:
            self.action_sounds.stop()

    def _set_file_preference(self, key, value, *, reload=True):
        changes = {key: value}
        if key in {'show_size', 'show_type'}:
            column = key.removeprefix('show_')
            columns = list(self.file_preferences['list_columns'])
            if value and column not in columns:
                columns.append(column)
            elif not value and column in columns:
                columns.remove(column)
            changes['list_columns'] = normalize_columns(columns)
        self._set_file_preferences(changes, reload=reload)

    def _set_file_preferences(self, changes, *, reload=True):
        self.file_preferences.update(changes)
        try:
            self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
            file = Gio.File.new_for_path(str(self.preferences_path))
            try:
                _, content, etag = file.load_contents(None)
                try:
                    saved = json.loads(content)
                except (UnicodeError, ValueError):
                    saved = {}
                if not isinstance(saved, dict):
                    saved = {}
            except GLib.Error as error:
                if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_FOUND):
                    raise
                saved, etag = {}, None
            # Other Files windows may have saved newer choices. Change only this
            # requested keys on disk; keep this window's display settings in memory.
            updated = {**self.file_preferences, **saved, **changes}
            file.replace_contents(
                json.dumps(updated).encode(), etag, False,
                Gio.FileCreateFlags.PRIVATE, None,
            )
        except (OSError, GLib.Error) as error:
            self._show_error('Could not save display preferences', str(error))
        if hasattr(self, 'sort_button'):
            self._update_sort_button()
        if reload:
            self._load()

    def _build_sort_button(self):
        self.sort_button = Gtk.MenuButton(label='Sort')
        self.sort_button.update_property([Gtk.AccessibleProperty.LABEL], ['Sort files'])
        self.sort_popover = Gtk.Popover()
        self.sort_popover.add_css_class('file-context-menu')
        self.sort_popover.connect('show', self._populate_sort_menu)
        self.sort_button.set_popover(self.sort_popover)
        self._update_sort_button()
        return self.sort_button

    def _update_sort_button(self):
        prefs = self.file_preferences
        title = next((title for key, descending, title in SORT_OPTIONS
                      if (key, descending) == (prefs['sort_key'], prefs['descending'])),
                     COLUMNS.get(prefs['sort_key'], ('Name', 0))[0] +
                     (' descending' if prefs['descending'] else ' ascending'))
        detail = ' · Date modified' if prefs['sort_key'] == 'modified' else ''
        self.sort_button.set_tooltip_text(f'Sort: {title}{detail}')
        if hasattr(self, 'list_details'):
            self.list_details.update_header()

    def _sort_menu_entries(self):
        prefs = self.file_preferences
        entries = []
        options = list(SORT_OPTIONS)
        if prefs['sort_key'] in EXTRA_SORTS | ANNOTATION_COLUMNS:
            key = prefs['sort_key']
            options.extend((key, descending, COLUMNS[key][0] + (' descending' if descending else ' ascending'))
                           for descending in (False, True))
        for key, descending, title in options:
            selected = (key, descending) == (prefs['sort_key'], prefs['descending'])
            entries.append((title, 'Date modified' if key == 'modified' else '',
                            'object-select-symbolic' if selected else
                            ('view-sort-descending-symbolic' if descending else 'view-sort-ascending-symbolic'),
                            lambda k=key, d=descending: self._set_sort(k, d)))
        entries.append(('Folders first', 'On' if prefs['folders_first'] else 'Off',
                        'folder-symbolic', self._toggle_folders_first))
        return entries

    def _populate_sort_menu(self, popover):
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(menu, 'set_margin_' + side)(7)
        entries = self._sort_menu_entries()
        for index, (title, detail, icon, callback) in enumerate(entries):
            if index == len(entries) - 1:
                menu.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            menu.append(self._menu_button(title, callback, icon_name=icon, detail=detail))
        popover.set_child(menu)

    def _set_sort(self, key, descending):
        self.sort_popover.popdown()
        # Save criterion and direction together so another window cannot restore
        # half of the previous choice. Refresh once and keep the selected files.
        self._set_file_preferences({'sort_key': key, 'descending': descending}, reload=False)
        self._refresh_files(rescan=False)

    def _toggle_folders_first(self):
        self.sort_popover.popdown()
        self._set_file_preference('folders_first', not self.file_preferences['folders_first'], reload=False)
        self._refresh_files(rescan=False)

    def _bookmarks(self):
        result = []
        try:
            for line in self.bookmarks_path.read_text().splitlines():
                uri, _, name = line.partition(' ')
                path = Gio.File.new_for_uri(uri).get_path()
                if path and Path(path).is_dir():
                    result.append((Path(path), name or Path(path).name))
        except OSError:
            pass
        return result

    def _toggle_bookmark(self, path):
        self._set_bookmark(path, None)

    def _set_bookmark(self, path, present):
        """Update one URI against the latest file; explicit removal never re-adds it."""
        uri = path.absolute().as_uri()
        try:
            self.bookmarks_path.parent.mkdir(parents=True, exist_ok=True)
            file = Gio.File.new_for_path(str(self.bookmarks_path))
            try:
                _, content, etag = file.load_contents(None)
                lines = content.decode().splitlines()
            except GLib.Error as error:
                if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_FOUND): raise
                lines, etag = [], None
            exists = any(line.split(' ', 1)[0] == uri for line in lines)
            if present is not None and exists == present:
                self._refresh_sidebar()
                return
            lines = [line for line in lines if line.split(' ', 1)[0] != uri]
            if present is True or (present is None and not exists): lines.append(uri)
            file.replace_contents(('\n'.join(lines) + '\n').encode(), etag, False,
                                  Gio.FileCreateFlags.PRIVATE, None)
            self._refresh_sidebar()
        except (OSError, UnicodeError, GLib.Error) as error:
            self._show_error('Could not update bookmarks', str(error))

    def _run_file_job(self, title, work, finished=None, *, refresh=None, failed=None):
        if self.file_job_active:
            self._show_error('File operation in progress', 'Wait for it to finish before starting another.')
            return
        self.file_job_active = True
        self.set_title(title)
        def worker():
            try:
                paths, error = work(), None
            except Exception as exc:
                paths, error = [], exc
            GLib.idle_add(complete, paths, error)
        def complete(paths, error):
            self.file_job_active = False
            self.set_title(self.request.title)
            if refresh:
                refresh(paths or [])
            else:
                self._refresh_files(paths or [])
            if error:
                if not failed or not failed(error):
                    self._show_error(title + ' failed', str(error) + '\nAny completed items remain in their new location.')
            elif finished:
                finished()
            return False
        threading.Thread(target=worker, daemon=True).start()

    def _extract_zip(self, path):
        from .archives import extract_zip
        if self.file_job_active:
            self._show_error('File operation in progress', 'Wait for it to finish before starting another.')
            return
        outputs = []

        def work():
            outputs.append(extract_zip(path))
            return outputs

        def refresh(paths):
            self._dismiss_conversion_notice()
            if not paths:
                return
            # Browsing remains available while extracting. Refresh only visible
            # destinations, without taking the user back from another folder/tab.
            if self.view_mode == 'columns':
                self.columns.refresh_paths({path.parent})
            elif self._computer_search_active() or self.current_dir == path.parent or self.special_mode == 'recent':
                self._refresh_files()

        def finished():
            self._show_conversion_notice(outputs[0], headline='Extraction complete')
            self._play_sound('complete')

        self._show_conversion_notice(path, headline='Extracting ZIP…', working=True)
        self._run_file_job('ZIP extraction', work, finished, refresh=refresh)

    def _refresh_files(self, selected=None, *, rescan=True):
        if getattr(self, "_restoring_tab", False):
            return
        selected = self._selected_paths() if selected is None else selected
        if rescan and self._computer_search_active():
            self._cancel_computer_search()
        self._search_restore_selection = list(selected)
        self._close_context_menu()
        self._load()
        for path in selected:
            child = self.children_by_path.get(path)
            if child: self.flow.select_child(child)

    def _show_rename_dialog(self, path):
        dialog = PickerDialog(self, 'Rename', subtitle='Choose a new name for this item.')
        dialog.body.append(file_summary(path))
        entry = Gtk.Entry(text=path.name, activates_default=True)
        hint = f'Keep {path.suffix} to preserve the file type.' if path.is_file() and path.suffix else ''
        dialog.body.append(entry_field('New name', entry, hint))
        dialog.add_action('Cancel', Gtk.ResponseType.CANCEL)
        rename = dialog.add_action('Rename', Gtk.ResponseType.ACCEPT, role='suggested-action', default=True)
        rename.set_sensitive(False)
        def changed(*_):
            dialog.clear_error()
            rename.set_sensitive(bool(entry.get_text().strip()) and entry.get_text().strip() != path.name)
        entry.connect('changed', changed)
        def response(_dialog, code):
            if code != Gtk.ResponseType.ACCEPT:
                self._dismiss_dialog(dialog)
                return
            try:
                target = rename_item(path, entry.get_text())
            except (ValueError, OSError, GLib.Error) as error:
                message = str(error)
                if isinstance(error, GLib.Error):
                    message = error.message
                    if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.EXISTS):
                        message = f'An item named “{entry.get_text().strip()}” already exists in this folder.'
                    elif error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.PERMISSION_DENIED):
                        message = 'You don’t have permission to rename this item.'
                    elif error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_FOUND):
                        message = 'This item is no longer in this folder.'
                dialog.set_error(message, entry)
                return
            self._dismiss_dialog(dialog)
            migrate = getattr(self, '_creative_paths_renamed', None)
            if migrate and target != path:
                migrate({path: target})
            self._refresh_files([target])
        dialog.connect('response', response)
        dialog.present()
        entry.grab_focus()
        entry.select_region(0, len(path.stem) if path.is_file() else -1)
        return dialog

    def _show_batch_rename_dialog(self, paths):
        if not paths or self.file_job_active:
            return
        from .batch_rename import BatchRenameDialog
        dialog = BatchRenameDialog(self, paths)
        dialog.present()
        dialog.pattern.grab_focus()
        return dialog

    def _confirm_remove(self, paths, permanent=False):
        if not paths: return
        action = 'Delete permanently' if permanent else 'Move to Trash'
        detail = ('This cannot be undone.' if permanent else
                  'Items moved to Trash can be restored. If a location does not support Trash, Gudfiles will ask before deleting permanently.')
        return confirmation(self, f'{action}?', detail, action, paths,
                            lambda: self._run_file_job(action, lambda: remove_items(paths, permanent),
                                lambda: self._play_sound('delete' if permanent else 'trash'),
                                refresh=lambda _: self._refresh_removed(paths),
                                failed=lambda error: self._remove_failed(error, permanent)),
                            destructive=permanent)

    def _refresh_removed(self, paths):
        if self.view_mode == 'columns':
            self.columns.refresh_paths({path.parent for path in paths})
        elif self._computer_search_active() or self.current_dir in {path.parent for path in paths} or self.special_mode == 'recent':
            self._refresh_files()

    def _remove_failed(self, error, permanent=False):
        if isinstance(error, TrashUnavailable) and not permanent:
            detail = ('This location does not support Trash. You can delete the listed items permanently instead. '
                      'This cannot be undone. Cancel keeps them in place.')
            if error.completed:
                count = len(error.completed)
                detail += f' {count} other item{"s were" if count != 1 else " was"} already moved to Trash.'
            confirmation(self, 'Trash is not available', detail, 'Delete permanently',
                         list(error.remaining),
                         lambda: self._run_file_job('Delete permanently',
                             lambda: delete_after_trash_failure(error), lambda: self._play_sound('delete'),
                             refresh=lambda _: self._refresh_removed(error.remaining),
                             failed=lambda failure: self._remove_failed(failure, True)),
                         destructive=True)
            return True
        if isinstance(error, RemovalError):
            action = 'Permanently deleted' if permanent else 'Moved to Trash'
            detail = f'{error}\n\n{action}: {len(error.completed)}. Not completed: {len(error.remaining)}.'
            self._show_error('Delete failed' if permanent else 'Move to Trash failed', detail)
            return True
        return False

    def _copy_location(self, paths):
        self.get_clipboard().set('\n'.join(str(p.absolute()) for p in paths))

    def _copy_files(self, paths, cut=False):
        if not paths: return
        uris = [p.absolute().as_uri() for p in paths]
        providers = [
            Gdk.ContentProvider.new_for_bytes('x-special/gnome-copied-files',
                GLib.Bytes.new((('cut' if cut else 'copy') + '\n' + '\n'.join(uris)).encode())),
            Gdk.ContentProvider.new_for_bytes('text/uri-list',
                GLib.Bytes.new(('\r\n'.join(uris) + '\r\n').encode())),
        ]
        self.get_clipboard().set_content(Gdk.ContentProvider.new_union(providers))

    def _can_paste(self):
        formats = self.get_clipboard().get_formats()
        return not self._computer_search_active() and self.special_mode is None and os.access(self.current_dir, os.W_OK) and any(
            formats.contain_mime_type(m) for m in ('x-special/gnome-copied-files', 'text/uri-list'))

    def _choose_transfer_destination(self, paths, *, cut=False):
        """Keep the source selection fixed while a Gudfiles folder picker is open."""
        from .model import PickerRequest
        from .picker import PickerWindow

        sources = tuple(paths)
        if not sources or self.file_job_active:
            return None
        existing = getattr(self, 'destination_picker', None)
        if existing is not None:
            existing.present()
            return existing
        verb = 'Move' if cut else 'Copy'
        start = sources[0].parent if self.special_mode or self._computer_search_active() else self.current_dir

        def chosen(destinations):
            if not destinations or not self.get_visible():
                return
            try:
                job = self.transfer_queue.add(sources, destinations[0], cut,
                                              start=True, duplicate=not cut)
                self._show_transfers(automatic_job=job)
            except ValueError as error:
                self._show_error(f'Could not {verb.lower()}', str(error))

        request = PickerRequest(current_folder=start, directory=True,
                                title=f'{verb} {len(sources)} item{"s" if len(sources) != 1 else ""} to…',
                                accept_label=f'{verb} here')
        chooser = PickerWindow(self.get_application(), request, None, on_result=chosen)
        chooser.set_default_size(960, 640)
        self.destination_picker = chooser
        chooser.set_transient_for(self)
        chooser.set_modal(True)
        chooser.set_destroy_with_parent(True)
        # Gtk.Window.destroy() can unrealize an owner before its destroy signal
        # is emitted when Python still holds it. Close the prompt at that point.
        owner_closed = self.connect('unrealize', lambda *_: chooser.destroy())

        def released(*_):
            self.destination_picker = None
            self.disconnect(owner_closed)
            chooser.on_result = None
            chooser.finished = True

        chooser.connect('unrealize', released)
        chooser.present()
        return chooser

    def _paste_files(self, *, queued=False):
        if not self._can_paste(): return
        destination = self.current_dir
        clipboard = self.get_clipboard()
        original_provider = clipboard.get_content()
        def read(clip, result):
            try: stream, mime = clip.read_finish(result)
            except GLib.Error as error:
                self._show_error('Could not paste', str(error)); return
            chunks = bytearray()
            def data_ready(source, res):
                try:
                    chunk = source.read_bytes_finish(res).get_data()
                    chunks.extend(chunk)
                    if len(chunks) > 1024 * 1024: raise ValueError('Clipboard file list is too large.')
                    if chunk:
                        source.read_bytes_async(8192, GLib.PRIORITY_DEFAULT, None, data_ready)
                        return
                    source.close(None)
                    paths, cut = parse_file_clipboard(chunks.decode(), mime)
                    if not paths: raise ValueError('The clipboard does not contain local files.')
                    job = self.transfer_queue.add(paths, destination, cut, start=not queued)
                    # Track our provider through partial moves too. Never alter
                    # newer clipboard contents, including copies made elsewhere.
                    provider = [original_provider]
                    def moved(mapping):
                        if not cut or provider[0] is None or clip.get_content() != provider[0]:
                            return
                        remaining = [p for p in paths if p not in mapping]
                        self._copy_files(remaining or list(mapping.values()), cut=bool(remaining))
                        provider[0] = clip.get_content()
                    self.transfer_callbacks[job.id] = moved
                    self._show_transfers(automatic_job=None if queued else job)
                except (GLib.Error, ValueError) as error:
                    source.close(None)
                    self._show_error('Could not paste', str(error))
            stream.read_bytes_async(8192, GLib.PRIORITY_DEFAULT, None, data_ready)
        clipboard.read_async(['x-special/gnome-copied-files', 'text/uri-list'],
                             GLib.PRIORITY_DEFAULT, None, read)

    def _transfer_files(self, paths, destination, cut):
        """Run on the file-job worker; preserve confirmed moves even after a later failure."""
        mapping = {}
        try:
            return transfer_items(paths, destination, cut, moved=lambda source, target: mapping.__setitem__(source, target))
        finally:
            if mapping:
                def migrate():
                    callback = getattr(self, '_creative_paths_renamed', None)
                    if callback:
                        callback(mapping)
                    return False
                # Enqueued before _run_file_job's completion/refresh, on the same
                # main-loop priority; never mutate the visible ratings cache here.
                GLib.idle_add(migrate)

    def _open_file_manager(self, path):
        try:
            Gio.AppInfo.launch_default_for_uri(path.absolute().as_uri(), None)
        except GLib.Error as error:
            self._show_error('Could not open file manager', str(error))

    def _visit_file(self, path):
        self.navigate(path if path.is_dir() else path.parent)
        child = self.children_by_path.get(path)
        if child: self.flow.select_child(child)

    def _show_properties(self, paths):
        if not paths: return
        if len(paths) == 1:
            try:
                stat = paths[0].lstat()
                link_target = os.readlink(paths[0]) if paths[0].is_symlink() else None
            except OSError as error:
                self._show_error('Could not read properties', str(error))
                return
        dialog = PickerDialog(self, 'Properties', width=560)
        general, access = [], []
        if len(paths) == 1:
            p = paths[0]
            kind = 'Symbolic link' if p.is_symlink() else file_type(p)
            dialog.body.append(file_summary(p, detail=kind))
            general.append(('Location', str(p.parent)))
            if not stat_module.S_ISDIR(stat.st_mode):
                size = format_size(stat.st_size)
                if stat.st_size >= 1024: size += f'  ·  {stat.st_size:,} bytes'
                general.append(('Size', size))
            general.append(('Modified', datetime.fromtimestamp(stat.st_mtime).strftime('%b %-d, %Y at %-I:%M %p')))
            readable, writable = os.access(p, os.R_OK), os.access(p, os.W_OK)
            access_text = ('Read and write' if readable and writable else 'Read only' if readable
                           else 'Write only' if writable else 'No access')
            access = [('Your access', access_text),
                      ('Permissions', f'{stat_module.filemode(stat.st_mode)[1:]}  ·  {stat.st_mode & 0o7777:04o}')]
            if link_target is not None: general.append(('Link target', link_target))
        else:
            from .selection_summary import selection_totals
            folders, files, total, unavailable = selection_totals(paths)
            parts = []
            if folders: parts.append(f'{folders:,} ' + ('folder' if folders == 1 else 'folders'))
            if files: parts.append(f'{files:,} ' + ('file' if files == 1 else 'files'))
            dialog.body.append(file_summary(title=f'{len(paths):,} items selected', detail=' · '.join(parts)))
            parents = {str(p.parent) for p in paths}
            general = [('Location', next(iter(parents)) if len(parents) == 1 else 'Multiple locations')]
            if files:
                size = 'Unavailable' if unavailable == files else format_size(total) + (' known' if unavailable else '')
                if folders: size += ' · Folder contents excluded'
                if unavailable: size += f' · {unavailable:,} unavailable'
                general.append(('Combined size', size))
        dialog.body.append(section('GENERAL', detail_card(general)))
        if access:
            dialog.body.append(section('ACCESS', detail_card(access)))
        if len(paths) > 1:
            dialog.body.append(section('SELECTED ITEMS', path_list(paths)))
        dialog.scroll_body()
        copy = dialog.add_action('Copy location' if len(paths) == 1 else 'Copy locations', Gtk.ResponseType.APPLY)
        close = dialog.add_action('Done', Gtk.ResponseType.CLOSE, role='suggested-action', default=True)
        def response(_dialog, code):
            if code == Gtk.ResponseType.APPLY:
                self._copy_location(paths)
                copy.set_label('Copied')
            else:
                self._dismiss_dialog(dialog)
        dialog.connect('response', response)
        dialog.present()
        close.grab_focus()
        return dialog

    def _append_common_context(self, menu, paths, *, background, qa):
        def action(text, callback, icon, enabled=True, detail=''):
            button = self._menu_button(text, callback, icon_name=icon, detail=detail)
            button.set_sensitive(enabled and not self.file_job_active)
            menu.append(button)
        def submenu(title, icon, entries):
            button = self._submenu_button(title, icon, entries, keep_open_for_qa=qa)
            button.set_sensitive(not self.file_job_active)
            menu.append(button)
        def separator(): menu.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        if paths and not background:
            action('Open Folder' if len(paths) == 1 and paths[0].is_dir() else self.request.accept_label,
                   lambda: self.navigate(paths[0]) if len(paths) == 1 and paths[0].is_dir() else self._accept(),
                   'document-open-symbolic')
            if (self.special_mode == 'recent' or self._computer_search_active()) and len(paths) == 1:
                action('Visit File', lambda: self._visit_file(paths[0]), 'go-jump-symbolic')
            action('Batch Rename…' if len(paths) > 1 else 'Rename…',
                   lambda: self._show_batch_rename_dialog(paths) if len(paths) > 1 else self._show_rename_dialog(paths[0]),
                   'document-edit-symbolic', enabled=all(os.access(path.parent, os.W_OK) for path in paths), detail='F2')
            separator()
            action('Cut', lambda: self._copy_files(paths, True), 'edit-cut-symbolic', detail='Ctrl+X')
            action('Copy', lambda: self._copy_files(paths), 'edit-copy-symbolic', detail='Ctrl+C')
            action('Copy to…', lambda: self._choose_transfer_destination(paths), 'edit-copy-symbolic')
            action('Move to…', lambda: self._choose_transfer_destination(paths, cut=True), 'go-jump-symbolic')
        action('Paste', self._paste_files, 'edit-paste-symbolic', self._can_paste(), 'Ctrl+V')
        action('Add to Transfer Queue', lambda: self._paste_files(queued=True),
               'folder-download-symbolic', self._can_paste(), 'Ctrl+Shift+V')
        if not background:
            action('Copy Location', lambda: self._copy_location(paths), 'edit-copy-symbolic')
            action('Properties', lambda: self._show_properties(paths), 'dialog-information-symbolic')
            separator()
            action('Move to Trash…', lambda: self._confirm_remove(paths), 'user-trash-symbolic', detail='Del')
        else:
            action('Select All', self.flow.select_all, 'edit-select-all-symbolic', self.request.multiple, 'Ctrl+A')
            action('Refresh', self._refresh_files, 'view-refresh-symbolic', detail='F5')
            folder = self.current_dir
            submenu('Folder', 'folder-symbolic', [
                ('Open With File Manager', '', 'folder-open-symbolic', lambda: self._open_file_manager(folder)),
                ('Copy Location', '', 'edit-copy-symbolic', lambda: self._copy_location([folder])),
                ('Remove Bookmark' if folder in [p for p, _ in self._bookmarks()] else 'Add to Bookmarks', '',
                 'bookmark-new-symbolic', lambda: self._toggle_bookmark(folder)),
                ('Properties', '', 'dialog-information-symbolic', lambda: self._show_properties([folder])),
            ])
        separator()
        prefs = self.file_preferences
        options = [
            ('Grid View', '', 'view-grid-symbolic', lambda: self._set_view('grid')),
            ('List View', '', 'view-list-symbolic', lambda: self._set_view('list')),
            ('Column View', '', 'view-dual-symbolic', lambda: self._set_view('columns')),
            ('Hide Hidden Files' if self.show_hidden else 'Show Hidden Files', 'Ctrl+H',
             'view-reveal-symbolic', lambda: self._toggle_hidden(None)),
        ]
        for key, title in [('show_size', 'Size Column'), ('show_type', 'Type Column'), ('show_time', 'Time')]:
            options.append((('Hide ' if prefs[key] else 'Show ') + title, '', 'view-list-symbolic',
                            lambda k=key: self._set_file_preference(k, not prefs[k])))
        enabled = self.action_sounds.enabled
        options.append(('Sound Effects', 'On' if enabled else 'Off',
                        'audio-volume-low-symbolic' if enabled else 'audio-volume-muted-symbolic',
                        self._toggle_sound_effects))
        submenu('View', 'view-grid-symbolic', options)
        submenu('Sort By', 'view-sort-ascending-symbolic', self._sort_menu_entries())
