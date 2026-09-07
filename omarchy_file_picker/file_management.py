from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk

from .file_actions import parse_file_clipboard, remove_items, rename_item, transfer_items

SIDEBAR_MIN_WIDTH = 280
SIDEBAR_DEFAULT_WIDTH = 300
from .model import file_type, format_size


class FileManagement:
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
        self.preferences_path = Path.home() / '.config/omarchy-file-picker/preferences.json'
        self.bookmarks_path = Path.home() / '.config/gtk-3.0/bookmarks'
        defaults = dict(sort_key='name', descending=False, folders_first=True,
                        show_size=True, show_type=True, show_time=True, sidebar_width=SIDEBAR_DEFAULT_WIDTH)
        try:
            saved = json.loads(self.preferences_path.read_text())
            if not isinstance(saved, dict):
                saved = {}
            for key, default in defaults.items():
                if isinstance(saved.get(key), type(default)):
                    defaults[key] = saved[key]
        except (OSError, ValueError, TypeError):
            pass
        if defaults['sort_key'] not in {'name', 'modified', 'size', 'type'}:
            defaults['sort_key'] = 'name'
        defaults['sidebar_width'] = max(SIDEBAR_MIN_WIDTH, defaults['sidebar_width'])
        self.file_preferences = defaults

    def _set_file_preference(self, key, value, *, reload=True):
        self.file_preferences[key] = value
        try:
            self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
            Gio.File.new_for_path(str(self.preferences_path)).replace_contents(
                json.dumps(self.file_preferences).encode(), None, False,
                Gio.FileCreateFlags.PRIVATE, None,
            )
        except (OSError, GLib.Error) as error:
            self._show_error('Could not save display preferences', str(error))
        if reload:
            self._load()

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
            lines = [line for line in lines if line.split(' ', 1)[0] != uri]
            if not exists: lines.append(uri)
            file.replace_contents(('\n'.join(lines) + '\n').encode(), etag, False,
                                  Gio.FileCreateFlags.PRIVATE, None)
            self._refresh_sidebar()
        except (OSError, GLib.Error) as error:
            self._show_error('Could not update bookmarks', str(error))

    def _run_file_job(self, title, work, finished=None):
        if self.file_job_active:
            self._show_error('File operation in progress', 'Wait for it to finish before starting another.')
            return
        self.file_job_active = True
        self.set_title(title)
        def worker():
            try:
                paths, error = work(), None
            except Exception as exc:
                paths, error = [], str(exc)
            GLib.idle_add(complete, paths, error)
        def complete(paths, error):
            self.file_job_active = False
            self.set_title(self.request.title)
            self._refresh_files(paths or [])
            if error:
                self._show_error(title + ' failed', error + '\nAny completed items remain in their new location.')
            elif finished:
                finished()
            return False
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_files(self, selected=None):
        selected = self._selected_paths() if selected is None else selected
        self._close_context_menu()
        self._load()
        for path in selected:
            child = self.children_by_path.get(path)
            if child: self.flow.select_child(child)

    def _show_rename_dialog(self, path):
        dialog = Gtk.Dialog(title='Rename', transient_for=self, modal=True)
        dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
        dialog.add_button('Rename', Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        box = dialog.get_content_area()
        for edge in ('top', 'bottom', 'start', 'end'): getattr(box, 'set_margin_' + edge)(18)
        box.set_spacing(8)
        entry = Gtk.Entry(text=path.name, activates_default=True, width_chars=38)
        error_label = Gtk.Label(xalign=0, wrap=True)
        error_label.add_css_class('error')
        box.append(entry)
        box.append(error_label)
        def response(_dialog, code):
            if code != Gtk.ResponseType.ACCEPT:
                self._dismiss_dialog(dialog)
                return
            try:
                target = rename_item(path, entry.get_text())
            except (ValueError, OSError, GLib.Error) as error:
                error_label.set_text(str(error))
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
        names = '\n'.join(p.name for p in paths[:6])
        if len(paths) > 6: names += f'\n…and {len(paths) - 6} more'
        detail = ('This cannot be undone.' if permanent else 'You can restore these items from Trash.')
        dialog = Gtk.AlertDialog(message=f'{action}?', detail=f'{names}\n\n{detail}')
        dialog.set_buttons(['Cancel', action])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)
        def chosen(alert, result):
            try:
                if alert.choose_finish(result) == 1:
                    self._run_file_job(action, lambda: remove_items(paths, permanent))
            except GLib.Error: pass
        dialog.choose(self, None, chosen)

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
        return self.special_mode is None and os.access(self.current_dir, os.W_OK) and any(
            formats.contain_mime_type(m) for m in ('x-special/gnome-copied-files', 'text/uri-list'))

    def _paste_files(self):
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
                    self._run_file_job('Moving files' if cut else 'Copying files',
                        lambda: self._transfer_files(paths, destination, cut),
                        # Convert a completed cut to copy without clearing unrelated newer clipboard data.
                        lambda: self._copy_files([destination / p.name for p in paths])
                        if cut and original_provider is not None and clip.get_content() == original_provider else None)
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
        rows = [('Name', paths[0].name), ('Location', str(paths[0].parent))]
        if len(paths) == 1:
            p = paths[0]
            try:
                stat = p.lstat()
                rows.extend([('Type', 'Symbolic link' if p.is_symlink() else file_type(p)),
                    ('Size', format_size(stat.st_size)),
                    ('Modified', datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')),
                    ('Permissions', oct(stat.st_mode & 0o777)),
                    ('Readable / writable', f'{os.access(p, os.R_OK)} / {os.access(p, os.W_OK)}')])
                if p.is_symlink(): rows.append(('Target', os.readlink(p)))
            except OSError as error:
                self._show_error('Could not read properties', str(error)); return
        else:
            names = '\n'.join(p.name for p in paths[:20])
            if len(paths) > 20:
                names += f'\n…and {len(paths) - 20} more'
            rows = [('Selection', f'{len(paths)} items'), ('Names', names)]
        dialog = Gtk.Dialog(title='Properties', transient_for=self, modal=True)
        dialog.add_button('Close', Gtk.ResponseType.CLOSE)
        box = dialog.get_content_area()
        for edge in ('top', 'bottom', 'start', 'end'): getattr(box, 'set_margin_' + edge)(18)
        box.set_spacing(10)
        for title, value in rows:
            text = Gtk.Label(label=f'{title}\n{value}', xalign=0, selectable=True, wrap=True)
            text.set_max_width_chars(65)
            box.append(text)
        dialog.connect('response', lambda *_: dialog.destroy())
        dialog.present()

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
            if self.special_mode == 'recent' and len(paths) == 1:
                action('Visit File', lambda: self._visit_file(paths[0]), 'go-jump-symbolic')
            action('Batch Rename…' if len(paths) > 1 else 'Rename…',
                   lambda: self._show_batch_rename_dialog(paths) if len(paths) > 1 else self._show_rename_dialog(paths[0]),
                   'document-edit-symbolic', enabled=all(os.access(path.parent, os.W_OK) for path in paths), detail='F2')
            separator()
            action('Cut', lambda: self._copy_files(paths, True), 'edit-cut-symbolic', detail='Ctrl+X')
            action('Copy', lambda: self._copy_files(paths), 'edit-copy-symbolic', detail='Ctrl+C')
        action('Paste', self._paste_files, 'edit-paste-symbolic', self._can_paste(), 'Ctrl+V')
        if not background:
            action('Copy Location', lambda: self._copy_location(paths), 'edit-copy-symbolic')
            folder = paths[0] if len(paths) == 1 and paths[0].is_dir() else paths[0].parent
            entries = [
                ('Open With File Manager', '', 'folder-open-symbolic', lambda: self._open_file_manager(folder)),
                ('Delete Permanently…', 'Shift+Del', 'edit-delete-symbolic', lambda: self._confirm_remove(paths, True)),
            ]
            if len(paths) == 1 and paths[0].is_dir():
                bookmarked = paths[0] in [p for p, _ in self._bookmarks()]
                entries.insert(0, ('Remove Bookmark' if bookmarked else 'Add to Bookmarks', '',
                    'bookmark-new-symbolic', lambda: self._toggle_bookmark(paths[0])))
            submenu('More', 'view-more-symbolic', entries)
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
        submenu('View', 'view-grid-symbolic', options)
        sorts = [(title, 'Selected' if prefs['sort_key'] == key else '', 'view-sort-ascending-symbolic',
                  lambda k=key: self._set_file_preference('sort_key', k))
                 for key, title in [('name', 'Name'), ('modified', 'Modified'), ('size', 'Size'), ('type', 'Type')]]
        sorts.extend([
            ('Ascending' if prefs['descending'] else 'Descending', '', 'view-sort-descending-symbolic',
             lambda: self._set_file_preference('descending', not prefs['descending'])),
            ('Mix Folders and Files' if prefs['folders_first'] else 'Folders First', '', 'folder-symbolic',
             lambda: self._set_file_preference('folders_first', not prefs['folders_first'])),
        ])
        submenu('Sort By', 'view-sort-ascending-symbolic', sorts)
