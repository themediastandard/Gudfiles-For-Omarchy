"""Discovery and explicit share browsing embedded in the connection dialog."""
import threading
from pathlib import Path
from urllib.parse import urlsplit

from gi.repository import Gio, GLib, Gtk, Pango
from .network import NetworkLocation, discover_network, safe_network_uri


class NetworkBrowser(Gtk.Box):
    def __init__(self, owner, dialog, address_entry):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.owner, self.dialog, self.entry = owner, dialog, address_entry
        self.generation = 0
        self.cancel = None
        self.alive = True
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label='Discovered on your network', xalign=0, hexpand=True)
        title.add_css_class('network-heading')
        row.append(title)
        self.refresh = Gtk.Button.new_from_icon_name('view-refresh-symbolic')
        self.refresh.add_css_class('flat')
        self.refresh.set_tooltip_text('Refresh discovered servers')
        self.refresh.connect('clicked', lambda *_: self.scan())
        row.append(self.refresh)
        self.append(row)
        self.status = Gtk.Label(xalign=0, wrap=True, max_width_chars=54)
        self.status.add_css_class('muted')
        self.append(self.status)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.list.add_css_class('network-locations')
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(74)
        scroller.set_max_content_height(210)
        scroller.set_propagate_natural_height(True)
        scroller.set_child(self.list)
        self.append(scroller)
        dialog.connect('notify::visible', self._visibility)
        self.scan()

    def _visibility(self, dialog, _property):
        if not dialog.get_visible():
            self.alive = False
            self.generation += 1
            if self.cancel:
                self.cancel.cancel()

    def _clear(self):
        while child := self.list.get_first_child():
            self.list.remove(child)

    def _known(self):
        known = []
        for mount in self.owner.volume_monitor.get_mounts():
            uri = mount.get_root().get_uri()
            if urlsplit(uri).scheme in {'smb', 'smbs', 'nfs'}:
                known.append(NetworkLocation(mount.get_name(), uri, 'Mounted share'))
        try:
            for line in self.owner.bookmarks_path.read_text().splitlines():
                uri, _, name = line.partition(' ')
                parsed = urlsplit(uri)
                if parsed.scheme in {'smb', 'smbs', 'nfs'}:
                    known.append(NetworkLocation(name or parsed.hostname or 'Saved NAS', uri, 'Saved network location',
                        server=parsed.scheme.startswith('smb') and not parsed.path.strip('/')))
        except OSError:
            pass
        return known

    def scan(self):
        self.generation += 1
        token = self.generation
        if self.cancel:
            self.cancel.cancel()
        self.refresh.set_sensitive(False)
        self._clear()
        self.status.set_text('Looking for SMB and NFS servers…')
        known = self._known()
        def worker():
            locations, notes = discover_network(known)
            GLib.idle_add(self._found, token, locations, notes)
        threading.Thread(target=worker, daemon=True).start()

    def _found(self, token, locations, notes):
        if not self.alive or token != self.generation:
            return False
        self.refresh.set_sensitive(True)
        self._clear()
        for location in locations:
            self._row(location)
        self.status.set_text(('Select a server to browse its shares.' if locations else
            'No advertised NAS found. Wake it up, check your network, or enter an address below.') +
            (' ' + ' '.join(notes) if notes else ''))
        return False

    def _row(self, location):
        button = Gtk.Button()
        button.add_css_class('network-location')
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.append(Gtk.Image.new_from_icon_name('network-server-symbolic' if location.server else 'folder-remote-symbolic'))
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        copy.append(Gtk.Label(label=location.name, xalign=0, ellipsize=Pango.EllipsizeMode.END))
        subtitle = Gtk.Label(label=location.detail, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        subtitle.add_css_class('muted')
        copy.append(subtitle)
        row.append(copy)
        row.append(Gtk.Image.new_from_icon_name('go-next-symbolic'))
        button.set_child(row)
        button.set_tooltip_text(location.uri)
        button.connect('clicked', lambda *_: self.browse(location) if location.server else self.select(location))
        self.list.append(button)

    def select(self, location):
        self.entry.set_text(location.uri)
        self.entry.grab_focus()
        self.status.set_text(f'{location.name} selected. Press Connect to mount it.')

    def browse(self, location):
        # Browsing a selected SMB server may ask for credentials via GTK/GVfs.
        self.generation += 1
        token = self.generation
        if self.cancel:
            self.cancel.cancel()
        self.cancel = Gio.Cancellable()
        cancel = self.cancel
        self.entry.set_text(location.uri)
        self.status.set_text(f'Browsing shares on {location.name}…')
        file = Gio.File.new_for_uri(location.uri)
        operation = Gtk.MountOperation.new(self.dialog)
        # Keep the mount operation alive through the asynchronous request.
        self.operation = operation
        def mounted(source, result):
            try:
                source.mount_enclosing_volume_finish(result)
            except GLib.Error as error:
                if not self.alive or token != self.generation:
                    return
                if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                    self.status.set_text(f'Could not browse this server: {error.message}')
                    return
            if not self.alive or token != self.generation:
                return
            threading.Thread(target=enumerate_shares, daemon=True).start()
        def enumerate_shares():
            shares, error = [], None
            timer = GLib.timeout_add_seconds(10, lambda: cancel.cancel() or False)
            try:
                iterator = file.enumerate_children('standard::name,standard::display-name,standard::target-uri',
                    Gio.FileQueryInfoFlags.NONE, cancel)
                try:
                    while info := iterator.next_file(cancel):
                        uri = safe_network_uri(info.get_attribute_string('standard::target-uri') or
                                               file.get_child(info.get_name()).get_uri())
                        if uri:
                            shares.append(NetworkLocation(info.get_display_name(), uri, f'Share on {location.name}'))
                finally:
                    iterator.close(None)
            except (GLib.Error, ValueError) as exc:
                error = str(exc)
            GLib.idle_add(finished, shares, error, timer)
        def finished(shares, error, timer):
            # Cancelled timers may already have fired; find before removing.
            if GLib.MainContext.default().find_source_by_id(timer):
                GLib.source_remove(timer)
            if not self.alive or token != self.generation:
                return False
            self._clear()
            for share in sorted(shares, key=lambda s: s.name.casefold()):
                self._row(share)
            self.status.set_text(f'Could not list shares: {error}' if error else
                ('Choose a share, then press Connect.' if shares else 'No shares were advertised for this login. Enter a share address below.'))
            return False
        file.mount_enclosing_volume(Gio.MountMountFlags.NONE, operation, cancel, mounted)
