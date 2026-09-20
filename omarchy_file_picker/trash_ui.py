"""A native Trash browser with explicit selection and safe restoration."""
from pathlib import Path
import threading

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from .trash import list_trash, restore_item


class TrashPage(Gtk.Box):
    def __init__(self, owner):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self.add_css_class('trash-page')
        self.owner = owner
        self.alive, self.active = True, False
        self.busy = self.restoring = False
        self.generation = 0
        self.query = ''
        self.cancellable = Gio.Cancellable()
        self.operation_cancel = Gio.Cancellable()
        self.receipt = ''
        self.restore_error = ''
        self.refresh_after_restore = False
        self.pending_state = None
        self.status = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.status.add_css_class('muted')
        bar = Gtk.Box(spacing=8)
        bar.add_css_class('trash-actions')
        bar.append(self.status)
        self.refresh_button = Gtk.Button.new_from_icon_name('view-refresh-symbolic')
        self.refresh_button.set_tooltip_text('Refresh Trash (F5)')
        self.refresh_button.update_property([Gtk.AccessibleProperty.LABEL], ['Refresh Trash'])
        self.refresh_button.connect('clicked', lambda *_: self.refresh())
        bar.append(self.refresh_button)
        self.restore_button = Gtk.Button(label='Restore Selected')
        self.restore_button.connect('clicked', lambda *_: self.restore_selected())
        bar.append(self.restore_button)
        self.append(bar)
        self.error_label = Gtk.Label(xalign=0, wrap=True)
        self.error_label.add_css_class('trash-error')
        self.error_label.set_visible(False)
        self.append(self.error_label)
        self.rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.MULTIPLE)
        self.rows.add_css_class('trash-list')
        self.rows.connect('selected-rows-changed', lambda *_: self._actions())
        self.empty = Gtk.Label(label='Loading Trash…', vexpand=True, valign=Gtk.Align.CENTER)
        self.empty.add_css_class('muted')
        self.rows.set_placeholder(self.empty)
        self.scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroll.set_child(self.rows)
        self.append(self.scroll)
        owner.connect('unrealize', self._unrealized)
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
        return dict(selected=[row.item.uri for row in self.rows.get_selected_rows()],
                    scroll=self.scroll.get_vadjustment().get_value())

    def set_error(self, message):
        self.error_label.set_text(message)
        self.error_label.set_visible(bool(message))

    def clear_error(self):
        self.set_error('')

    def _actions(self):
        self.refresh_button.set_sensitive(not self.busy)
        self.restore_button.set_sensitive(not self.busy and bool(self.rows.get_selected_rows()))
        self.rows.set_sensitive(not self.busy)

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

    def show_menu(self, x, y):
        self.owner._close_context_menu()
        popover = Gtk.Popover(has_arrow=False, autohide=True)
        popover.add_css_class('file-context-menu')
        popover.set_parent(self)
        popover.connect('closed', self.owner._on_context_closed)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        for edge in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_' + edge)(4)
        restore = self.owner._menu_button('Restore Selected', self.restore_selected,
                                         icon_name='edit-undo-symbolic')
        restore.set_sensitive(self.restore_button.get_sensitive())
        box.append(restore)
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
        self.status.set_text(receipt + ('\n' if receipt else '') + 'Loading Trash…')
        def finished(items, error):
            if error:
                self.status.set_text(receipt + ('\n' if receipt else '') + 'Trash could not be refreshed.')
                self.set_error(self._message(error))
                self.empty.set_text('Trash unavailable')
                return
            while row := self.rows.get_first_child():
                self.rows.remove(row)
            visible = [item for item in items if not self.query or self.query in item.name.casefold() or self.query in item.original.casefold()]
            for item in visible:
                row = Gtk.ListBoxRow()
                row.item = item
                box = Gtk.Box(spacing=8)
                icon = Gtk.Image.new_from_icon_name('folder-symbolic' if item.directory else 'text-x-generic-symbolic')
                icon.set_pixel_size(16)
                box.append(icon)
                copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
                name = Gtk.Label(label=item.name, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
                name.set_tooltip_text(item.name)
                copy.append(name)
                location = Gtk.Label(label=str(Path(item.original).parent) if item.original else 'Original location unavailable',
                                     xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
                location.set_tooltip_text(item.original)
                location.add_css_class('dialog-description')
                copy.append(location)
                box.append(copy)
                date = Gtk.Label(label=item.deleted.replace('T', ' '), xalign=1)
                date.set_tooltip_text('Deleted ' + item.deleted.replace('T', ' ') if item.deleted else 'Deletion date unavailable')
                date.add_css_class('dialog-description')
                box.append(date)
                row.set_child(box)
                self.rows.append(row)
                if item.uri in state.get('selected', []):
                    self.rows.select_row(row)
            count = len(visible)
            self.empty.set_text('No matching items' if items else 'Trash is empty')
            generation = self.generation
            def restore_scroll():
                if self.active and generation == self.generation:
                    self.scroll.get_vadjustment().set_value(state.get('scroll', 0))
                return False
            GLib.timeout_add(40, restore_scroll)
            self.status.set_text(receipt + ('\n' if receipt else '') +
                                 (f'{count} item' + ('s' if count != 1 else '') if count else
                                  'No matching items.' if items else 'Trash is empty.'))
        self._work(lambda: list_trash(cancel), finished)

    def restore_selected(self):
        if self.busy or not self.active:
            return
        selected = [row.item for row in self.rows.get_selected_rows()]
        if not selected:
            return
        if self.owner.file_job_active:
            self.set_error('Wait for the current file operation to finish before restoring.')
            return
        self.clear_error()
        self.restore_error = ''
        self.restoring = True
        self.owner.file_job_active = True
        self.status.set_text(f'Restoring {len(selected)} item' + ('s…' if len(selected) != 1 else '…'))
        def work():
            restored, failures = [], []
            for item in selected:
                try:
                    restored.append((item.uri, restore_item(item, self.operation_cancel)))
                except Exception as error:
                    failures.append(f'{item.name}: {self._message(error)}')
            return restored, failures
        def finished(result, error):
            restored, failures = result if result else ([], [self._message(error)])
            restored_uris = {uri for uri, _path in restored}
            row = self.rows.get_first_child()
            while row:
                following = row.get_next_sibling()
                if row.item.uri in restored_uris:
                    self.rows.remove(row)
                row = following
            self.receipt = (f'Restored {len(restored)} of {len(selected)} items.' if failures else
                            f'Restored {len(restored)} item' + ('s.' if len(restored) != 1 else '.'))
            self.status.set_text(self.receipt)
            self.empty.set_text('Trash is empty')
            if failures:
                self.restore_error = '\n'.join(failures[:5]) + (f'\n…and {len(failures)-5} more.' if len(failures) > 5 else '')
                self.set_error(self.restore_error)
            if (restored and self.owner.get_realized() and self.owner.special_mode != 'trash'
                    and self.owner.current_dir in {path.parent for _uri, path in restored}):
                self.owner._refresh_files([path for _uri, path in restored])
        self._work(work, finished, operation=True)
