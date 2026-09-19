"""A native Trash browser with explicit selection and safe restoration."""
from pathlib import Path
import threading

from gi.repository import Gio, GLib, Gtk, Pango

from .dialogs import PickerDialog
from .trash import list_trash, restore_item


class TrashDialog(PickerDialog):
    def __init__(self, owner):
        super().__init__(owner, 'Trash', subtitle='Restore deleted items to their original folders.', width=720)
        self.owner = owner
        self.alive = True
        self.busy = False
        self.restoring = False
        self.cancellable = Gio.Cancellable()
        self.set_default_size(720, 500)
        self.set_resizable(True)
        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.add_css_class('dialog-description')
        self.body.append(self.status)
        self.rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.MULTIPLE)
        self.rows.add_css_class('trash-list')
        self.rows.connect('selected-rows-changed', lambda *_: self._actions())
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                   min_content_height=220)
        scroll.set_child(self.rows)
        self.body.append(scroll)
        self.refresh_button = self.add_action('Refresh', 1)
        self.restore_button = self.add_action('Restore Selected', 2, role='suggested-action')
        self.done_button = self.add_action('Done', Gtk.ResponseType.CLOSE)
        self.connect('response', self._response)
        self.connect('unrealize', self._unrealized)
        self.refresh()

    def _unrealized(self, *_):
        self.alive = False
        self.cancellable.cancel()
        if getattr(self.owner, 'trash_dialog', None) is self:
            self.owner.trash_dialog = None

    def _actions(self):
        self.refresh_button.set_sensitive(not self.busy)
        self.restore_button.set_sensitive(not self.busy and bool(self.rows.get_selected_rows()))
        self.rows.set_sensitive(not self.busy)
        self.done_button.set_sensitive(not self.restoring)
        self.close_button.set_sensitive(not self.restoring)

    def _response(self, _dialog, response):
        if response == 1 and not self.busy:
            self.refresh()
        elif response == 2 and not self.busy:
            self.restore_selected()
        elif response in (Gtk.ResponseType.CLOSE, Gtk.ResponseType.CANCEL, Gtk.ResponseType.DELETE_EVENT):
            if not self.restoring:
                self.cancellable.cancel()
                self.owner._dismiss_dialog(self)

    def _work(self, work, finished):
        self.busy = True
        self._actions()
        def complete(result, error):
            self.busy = False
            if self.restoring:
                self.restoring = False
                self.owner.file_job_active = False
            if self.alive:
                finished(result, error)
                self._actions()
            return GLib.SOURCE_REMOVE
        def worker():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, exc
            GLib.idle_add(complete, result, error)
        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _message(error):
        if isinstance(error, GLib.Error):
            if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.EXISTS):
                return 'An item already exists in the original location. Rename or move it before restoring.'
            return error.message
        return str(error)

    def refresh(self, receipt=''):
        self.clear_error()
        self.status.set_text(receipt + ('\n' if receipt else '') + 'Loading Trash…')
        def finished(items, error):
            if error:
                self.status.set_text(receipt + ('\n' if receipt else '') + 'Trash could not be refreshed.')
                self.set_error(self._message(error))
                return
            while row := self.rows.get_first_child():
                self.rows.remove(row)
            for item in items:
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
            count = len(items)
            self.status.set_text(receipt + ('\n' if receipt else '') +
                                 (f'{count} item' + ('s' if count != 1 else '') if count else 'Trash is empty.'))
        self._work(lambda: list_trash(self.cancellable), finished)

    def restore_selected(self):
        selected = [row.item for row in self.rows.get_selected_rows()]
        if not selected:
            return
        if self.owner.file_job_active:
            self.set_error('Wait for the current file operation to finish before restoring.')
            return
        self.clear_error()
        self.restoring = True
        self.owner.file_job_active = True
        self.status.set_text(f'Restoring {len(selected)} item' + ('s…' if len(selected) != 1 else '…'))
        def work():
            restored, failures = [], []
            for item in selected:
                try:
                    restored.append((item.uri, restore_item(item, self.cancellable)))
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
            self.status.set_text(f'Restored {len(restored)} of {len(selected)} items.' if failures else
                                 f'Restored {len(restored)} item' + ('s.' if len(restored) != 1 else '.'))
            if failures:
                self.set_error('\n'.join(failures[:5]) + (f'\n…and {len(failures)-5} more.' if len(failures) > 5 else ''))
            if restored and self.owner.get_realized():
                self.owner._refresh_files([path for _uri, path in restored])
        self._work(work, finished)
