"""Shared nonblocking checks and a quiet, owner-bound browser notice."""
import threading
import weakref
from gi.repository import GLib, Gtk, Pango

from . import updates
from .update_state import UpdateState


class UpdateChecks:
    def __init__(self):
        self.state = UpdateState()
        self.running = False
        self.result = None
        self.force_requested = False
        self.observers = []

    def request(self, *, force=False):
        if self.running:
            self.force_requested = self.force_requested or force
            return
        self.force_requested = force
        self.running = True

        def worker():
            result = self.state.check(force=force)
            GLib.idle_add(self._complete, result)

        threading.Thread(target=worker, name='gudfiles-update-check', daemon=True).start()

    def _complete(self, result):
        self.running = False
        # A manual click racing a cached startup reply must still reach GitHub.
        if self.force_requested and self.state.used_cache:
            self.request(force=True)
            return GLib.SOURCE_REMOVE
        self.result = result
        self.observers = [ref for ref in self.observers if ref() is not None]
        for reference in self.observers:
            callback = reference()
            if callback is not None:
                callback(result)
        return GLib.SOURCE_REMOVE


def checks_for(app):
    if not hasattr(app, 'update_checks'):
        app.update_checks = UpdateChecks()
    return app.update_checks


class UpdateNotice(Gtk.Box):
    def __init__(self, owner):
        super().__init__(spacing=8)
        self.owner = weakref.ref(owner)
        self.checks = checks_for(owner.get_application())
        self.checks.observers.append(weakref.WeakMethod(self._complete))
        self.result = None
        self.started = False
        self.closed = False
        self.add_css_class('update-notice')
        self.set_visible(False)
        self.label = Gtk.Label(xalign=0, hexpand=True, max_width_chars=1, ellipsize=Pango.EllipsizeMode.END)
        self.append(self.label)
        self.link = Gtk.LinkButton(label='View download', uri=updates.releases_url())
        self.link.add_css_class('flat')
        self.append(self.link)
        self.dismiss_button = Gtk.Button.new_from_icon_name('window-close-symbolic')
        self.dismiss_button.add_css_class('flat')
        self.dismiss_button.update_property([Gtk.AccessibleProperty.LABEL], ['Dismiss this update'])
        self.dismiss_button.connect('clicked', self._dismiss)
        self.append(self.dismiss_button)
        owner.connect('map', self._launch)
        owner.connect('unrealize', self._close)

    def _launch(self, *_):
        if not self.started:
            self.started = True
            # Let the first frame and normal browsing initialize first.
            GLib.idle_add(self._request)

    def _request(self):
        if not self.closed:
            self.checks.request()
        return GLib.SOURCE_REMOVE

    def _close(self, *_):
        self.closed = True

    def _complete(self, result):
        owner = self.owner()
        if self.closed or owner is None or not owner.get_mapped():
            return
        version = updates.available_version(result)
        if not version:
            self.set_visible(False)
            return
        if self.get_visible() and self.result.url == result.url:
            return
        self.set_visible(False)
        if self.checks.state.claim_notice(result):
            self.result = result
            self.label.set_text(f'Gudfiles {version} is available')
            self.link.set_uri(result.url)
            self.set_visible(True)

    def _dismiss(self, *_):
        self.set_visible(False)
        self.checks.state.dismiss(self.result)
