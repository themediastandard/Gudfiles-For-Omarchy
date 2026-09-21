"""A folder-like desktop Trash with safe restore and permanent emptying."""
from pathlib import Path
import threading

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from .dialogs import PickerDialog, file_summary
from .filename_display import display_filename
from .trash import delete_item, list_trash, restore_item


class TrashPage(Gtk.Box):
    """Render Trash like the other file views without pretending its URIs are Paths."""

    def __init__(self, owner):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self.add_css_class('trash-page')
        self.owner = owner
        self.alive, self.active, self.available = True, False, False
        self.busy = self.restoring = False
        self.generation = 0
        self.query = ''
        self.items = []
        self.cancellable = Gio.Cancellable()
        self.operation_cancel = Gio.Cancellable()
        self.receipt = ''
        self.restore_error = ''
        self.refresh_after_restore = False
        self.pending_state = None

        bar = Gtk.Box(spacing=8)
        bar.add_css_class('trash-actions')
        self.status = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.status.add_css_class('muted')
        bar.append(self.status)
        self.restore_button = Gtk.Button(label='Restore')
        self.restore_button.connect('clicked', lambda *_: self.restore_selected())
        bar.append(self.restore_button)
        self.empty_button = Gtk.Button(label='Empty Trash…')
        self.empty_button.add_css_class('destructive-action')
        self.empty_button.connect('clicked', lambda *_: self.confirm_empty())
        bar.append(self.empty_button)
        self.append(bar)

        self.error_label = Gtk.Label(xalign=0, wrap=True)
        self.error_label.add_css_class('trash-error')
        self.error_label.set_visible(False)
        self.append(self.error_label)

        self.list_header = Gtk.Box(spacing=8)
        self.list_header.add_css_class('trash-list-heading')
        for title, expand, width in (('Name', True, -1), ('Original location', True, -1),
                                     ('Date deleted', False, 150)):
            heading = Gtk.Label(label=title, xalign=0, hexpand=expand)
            if width > 0:
                heading.set_size_request(width, -1)
            self.list_header.append(heading)
        self.append(self.list_header)

        self.rows = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.MULTIPLE,
                                activate_on_single_click=False, valign=Gtk.Align.START)
        self.rows.add_css_class('trash-list')
        self.rows.set_min_children_per_line(1)
        self.rows.connect('selected-children-changed', lambda *_: self._actions())
        self.empty = Gtk.Label(label='Loading Trash…', valign=Gtk.Align.CENTER,
                               halign=Gtk.Align.CENTER, can_target=False)
        self.empty.add_css_class('muted')
        self.scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroll.set_child(self.rows)
        self.content = Gtk.Overlay(vexpand=True)
        self.content.set_child(self.scroll)
        self.content.add_overlay(self.empty)
        self.content.set_measure_overlay(self.empty, False)
        self.append(self.content)
        owner.connect('unrealize', self._unrealized)
        self._configure_view()
        self._actions()

    def _unrealized(self, *_):
        self.alive = False
        self.deactivate()
        self.operation_cancel.cancel()

    def activate(self, state=None):
        self.active = True
        self.query = self.owner.search.get_text().strip().casefold()
        if self.restoring:
            self.refresh_after_restore = True
            self.pending_state = state
        else:
            self.refresh(state=state)

    def deactivate(self):
        self.active = False
        self.refresh_after_restore = False
        self.generation += 1
        self.cancellable.cancel()
        if not self.restoring:
            self.busy = False
        self._actions()

    def capture(self):
        return dict(selected=[child.item.uri for child in self.rows.get_selected_children()],
                    scroll=self.scroll.get_vadjustment().get_value())

    def set_error(self, message):
        self.error_label.set_text(message)
        self.error_label.set_visible(bool(message))

    def clear_error(self):
        self.set_error('')

    def _selected_items(self):
        return [child.item for child in self.rows.get_selected_children()]

    def _actions(self):
        selected = self._selected_items()
        self.restore_button.set_sensitive(self.available and not self.busy and bool(selected))
        self.empty_button.set_sensitive(self.available and not self.busy and bool(self.items))
        self.rows.set_sensitive(not self.busy)
        if (self.active and self.owner.special_mode == 'trash'
                and hasattr(self.owner, 'view_status')):
            status = self.owner.view_status
            status.scale.set_sensitive(self.owner.view_mode == 'grid' and not self.busy)
            status.summary.set_text(
                f'{len(selected):,} ' + ('item' if len(selected) == 1 else 'items') + ' selected'
                if selected else '')

    def _work(self, work, finished, *, operation=False):
        generation = self.generation
        self.busy = True
        self._actions()

        def complete(result, error):
            if operation:
                self.restoring = False
                self.owner.file_job_active = False
            elif generation != self.generation or not self.active:
                return GLib.SOURCE_REMOVE
            self.busy = False
            if self.alive:
                finished(result, error)
                if operation and self.active and self.refresh_after_restore:
                    self.refresh_after_restore = False
                    self.refresh(state=self.pending_state)
                self._actions()
            return GLib.SOURCE_REMOVE

        def worker():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, exc
            GLib.idle_add(complete, result, error)

        threading.Thread(target=worker, daemon=True).start()

    def set_view(self, _mode):
        state = self.capture()
        self._configure_view()
        self._rebuild(state)

    def resize_tiles(self, width):
        for child in self._children():
            self.owner.view_status.size_tile(child.get_child(), width)

    def _configure_view(self):
        grid = self.owner.view_mode == 'grid'
        self.list_header.set_visible(self.owner.view_mode == 'list')
        self.rows.set_max_children_per_line(100 if grid else 1)
        self.rows.set_row_spacing(12 if grid else 2)
        self.rows.set_column_spacing(12 if grid else 0)
        if grid:
            self.rows.remove_css_class('file-list')
        else:
            self.rows.add_css_class('file-list')

    def _children(self):
        child = self.rows.get_first_child()
        while child:
            yield child
            child = child.get_next_sibling()

    def _ordered(self, items):
        prefs = self.owner.file_preferences
        key = prefs['sort_key']
        if key == 'modified':
            value = lambda item: (item.deleted, item.name.casefold())
        elif key == 'type':
            value = lambda item: ('' if item.directory else Path(item.name).suffix.casefold(), item.name.casefold())
        else:
            value = lambda item: item.name.casefold()
        ordered = sorted(items, key=value, reverse=prefs['descending'])
        if prefs['folders_first']:
            ordered.sort(key=lambda item: not item.directory)
        return ordered

    def _rebuild(self, state=None):
        state = state or {}
        while child := self.rows.get_first_child():
            self.rows.remove(child)
        visible = [item for item in self._ordered(self.items)
                   if not self.query or self.query in item.name.casefold()
                   or self.query in item.original.casefold()]
        selected = set(state.get('selected', []))
        for item in visible:
            child = Gtk.FlowBoxChild()
            child.item = item
            child.set_child(self._grid_item(item) if self.owner.view_mode == 'grid' else self._list_item(item))
            self.rows.append(child)
            if item.uri in selected:
                self.rows.select_child(child)
        self.empty.set_text('No matching items' if self.items else 'Trash is empty')
        self.empty.set_visible(not visible)
        generation = self.generation

        def restore_scroll():
            if self.active and generation == self.generation:
                self.scroll.get_vadjustment().set_value(state.get('scroll', 0))
            return False

        GLib.timeout_add(40, restore_scroll)
        self._actions()
        return len(visible)

    def _grid_item(self, item):
        tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        tile.set_hexpand(False)
        image = Gtk.Image.new_from_icon_name('folder-symbolic' if item.directory else 'text-x-generic-symbolic')
        image.set_pixel_size(48)
        name = Gtk.Label(label=display_filename(item.name), xalign=.5,
                         ellipsize=Pango.EllipsizeMode.MIDDLE)
        location = Gtk.Label(label=display_filename(Path(item.original).parent.name) if item.original else 'Unknown location',
                             xalign=.5, ellipsize=Pango.EllipsizeMode.END)
        location.add_css_class('muted')
        tile.append(image)
        tile.append(name)
        tile.append(location)
        tile._grid_size_parts = (image, name, location)
        self.owner.view_status.size_tile(tile, self.owner.file_preferences['thumbnail_size'])
        return tile

    def _list_item(self, item):
        row = Gtk.Box(spacing=8, height_request=28)
        icon = Gtk.Image.new_from_icon_name('folder-symbolic' if item.directory else 'text-x-generic-symbolic')
        icon.set_pixel_size(14)
        row.append(icon)
        name = Gtk.Label(label=display_filename(item.name), xalign=0, hexpand=True,
                         ellipsize=Pango.EllipsizeMode.MIDDLE, width_chars=8)
        row.append(name)
        location = Gtk.Label(label=display_filename(str(Path(item.original).parent)) if item.original else 'Original location unavailable',
                             xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE,
                             width_chars=8)
        location.add_css_class('muted')
        row.append(location)
        deleted = Gtk.Label(label=item.deleted.replace('T', ' '), xalign=0,
                            ellipsize=Pango.EllipsizeMode.END, width_chars=18)
        deleted.set_size_request(150, -1)
        deleted.add_css_class('muted')
        row.append(deleted)
        return row

    def show_menu(self, x, y):
        self.owner._close_context_menu()
        popover = Gtk.Popover(has_arrow=False, autohide=True)
        popover.add_css_class('file-context-menu')
        popover.set_parent(self)
        popover.connect('closed', self.owner._on_context_closed)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        for edge in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_' + edge)(4)
        restore = self.owner._menu_button('Restore', self.restore_selected,
                                         icon_name='edit-undo-symbolic')
        restore.set_sensitive(self.restore_button.get_sensitive())
        box.append(restore)
        empty = self.owner._menu_button('Empty Trash…', self.confirm_empty,
                                       icon_name='user-trash-symbolic')
        empty.set_sensitive(self.empty_button.get_sensitive())
        box.append(empty)
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        refresh = self.owner._menu_button('Refresh', self.refresh, icon_name='view-refresh-symbolic')
        refresh.set_sensitive(not self.busy)
        box.append(refresh)
        popover.set_child(box)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        self.owner.context_popover = popover
        self.owner.context_submenus.clear()
        popover.popup()

    @staticmethod
    def _message(error):
        if isinstance(error, GLib.Error):
            if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.EXISTS):
                return 'An item already exists in the original location. Rename or move it before restoring.'
            return error.message
        return str(error)

    def refresh(self, *, state=None):
        if self.restoring or not self.active:
            return
        self.generation += 1
        self.cancellable.cancel()
        self.cancellable = Gio.Cancellable()
        cancel = self.cancellable
        state = self.capture() if state is None else state
        receipt = self.receipt
        self.set_error(self.restore_error)
        self.status.set_text(receipt + ('  ·  ' if receipt else '') + 'Loading Trash…')

        def finished(items, error):
            if error:
                self.available = False
                self.status.set_text(receipt + ('  ·  ' if receipt else '') + 'Trash could not be refreshed.')
                self.set_error(self._message(error))
                self.empty.set_text('Trash unavailable')
                return
            self.available = True
            self.items = items
            count = self._rebuild(state)
            self.status.set_text(receipt + ('  ·  ' if receipt else '') +
                                 (f'{count} item' + ('s' if count != 1 else '') if count else
                                  'No matching items.' if items else 'Trash is empty.'))

        self._work(lambda: list_trash(cancel), finished)

    def restore_selected(self):
        selected = self._selected_items()
        if not selected:
            return
        self._operate(selected, restoring=True)

    def confirm_empty(self):
        if self.busy or not self.active or not self.items:
            return
        snapshot = list(self.items)
        count = len(snapshot)
        detail = (f'Permanently delete all {count:,} items in Trash? '
                  'This cannot be undone. Items added after this confirmation will be kept.')
        dialog = PickerDialog(self.owner, 'Empty Trash?', subtitle=detail)
        dialog.body.append(file_summary(title=f'{count:,} ' + ('item' if count == 1 else 'items'),
                                        detail='All current items in Trash', icon='user-trash-symbolic'))
        cancel = dialog.add_action('Cancel', Gtk.ResponseType.CANCEL, default=True)
        dialog.add_action('Empty Trash', Gtk.ResponseType.ACCEPT, role='destructive-action')

        def response(_dialog, code):
            self.owner._dismiss_dialog(dialog)
            if code == Gtk.ResponseType.ACCEPT:
                self._operate(snapshot, restoring=False)

        dialog.connect('response', response)
        dialog.present()
        cancel.grab_focus()
        return dialog

    def _operate(self, selected, *, restoring):
        if self.busy or not self.active:
            return
        if self.owner.file_job_active:
            self.set_error('Wait for the current file operation to finish before changing Trash.')
            return
        self.clear_error()
        self.restore_error = ''
        self.restoring = True
        self.owner.file_job_active = True
        verb = 'Restoring' if restoring else 'Permanently deleting'
        self.status.set_text(f'{verb} {len(selected):,} item' + ('s…' if len(selected) != 1 else '…'))

        def work():
            completed, failures = [], []
            for item in selected:
                try:
                    if restoring:
                        completed.append((item.uri, restore_item(item, self.operation_cancel)))
                    else:
                        delete_item(item, self.operation_cancel)
                        completed.append((item.uri, None))
                except Exception as error:
                    failures.append(f'{item.name}: {self._message(error)}')
            return completed, failures

        def finished(result, error):
            completed, failures = result if result else ([], [self._message(error)])
            completed_uris = {uri for uri, _path in completed}
            self.items = [item for item in self.items if item.uri not in completed_uris]
            selected_uris = [item.uri for item in selected if item.uri not in completed_uris]
            self._rebuild({'selected': selected_uris, 'scroll': self.scroll.get_vadjustment().get_value()})
            if restoring:
                self.receipt = (f'Restored {len(completed):,} of {len(selected):,} items.' if failures else
                                f'Restored {len(completed):,} item' + ('s.' if len(completed) != 1 else '.'))
            else:
                self.receipt = (f'Permanently deleted {len(completed):,} of {len(selected):,} items.' if failures else
                                f'Emptied {len(completed):,} item' + ('s from Trash.' if len(completed) != 1 else ' from Trash.'))
                if completed:
                    self.owner._play_sound('delete')
            self.status.set_text(self.receipt)
            if failures:
                self.restore_error = '\n'.join(failures[:5]) + (f'\n…and {len(failures)-5} more.' if len(failures) > 5 else '')
                self.set_error(self.restore_error)
            else:
                self.clear_error()
            restored_paths = [path for _uri, path in completed if path is not None]
            if (restored_paths and self.owner.get_realized() and self.owner.special_mode != 'trash'
                    and self.owner.current_dir in {path.parent for path in restored_paths}):
                self.owner._refresh_files(restored_paths)

        self._work(work, finished, operation=True)
