"""Desktop smoke test: automatic live discovery; never mounts a share."""
import os
import tempfile
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.network_ui import NetworkBrowser
from omarchy_file_picker.network import NetworkLocation


def children(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from children(child)
        child = child.get_next_sibling()


with tempfile.TemporaryDirectory(prefix='nas-ui-qa-') as temp:
    request = PickerRequest(current_folder=Path(temp))
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.bookmarks_path = Path(temp) / 'bookmarks'
    window.present()
    loop = GLib.MainLoop()
    passed = False
    def start():
        window._show_nas_dialog(None)
        return False
    def verify():
        global passed
        dialogs = [d for d in Gtk.Window.get_toplevels() if d.get_title() == 'Connect to NAS']
        if not dialogs:
            return True
        dialog = dialogs[0]
        browser = next(w for w in children(dialog) if isinstance(w, NetworkBrowser))
        if not browser.refresh.get_sensitive():
            return True
        if not getattr(browser, '_qa_rendered', False):
            browser._qa_rendered = True
            return True  # Let the discovered rows paint before capture.
        labels = [w.get_text() for w in children(browser.list) if isinstance(w, Gtk.Label)]
        print('App-discovered locations:', labels or '(none advertised)')
        assert dialog.has_css_class('picker-dialog')
        assert any(isinstance(w, Gtk.Button) and w.has_css_class('suggested-action') for w in children(dialog))
        capture = os.environ.get('NAS_QA_SCREENSHOT')
        if capture:
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(dialog).snapshot(snapshot, dialog.get_width(), dialog.get_height())
            texture = dialog.get_renderer().render_texture(snapshot.to_node(), None)
            texture.save_to_png(capture)
        entry = next(w for w in children(dialog) if isinstance(w, Gtk.Entry))
        browsed = []
        browser.browse = lambda location: browsed.append(location)
        entry.set_text('smb://example.local')
        dialog.response(Gtk.ResponseType.ACCEPT)
        assert browsed[-1].uri == 'smb://example.local/'
        browser.select(NetworkLocation('Media', 'smb://example.local/media', 'Share'))
        assert entry.get_text() == 'smb://example.local/media'
        entry.set_text('https://invalid.example')
        dialog.response(Gtk.ResponseType.ACCEPT)
        assert any(isinstance(w, Gtk.Label) and 'Use an smb://' in w.get_text() and w.get_visible() for w in children(dialog))
        assert dialog.get_visible()
        dialog.response(Gtk.ResponseType.CANCEL)
        assert not browser.alive
        passed = True
        loop.quit()
        return False
    GLib.timeout_add(200, start)
    GLib.timeout_add(500, verify)
    GLib.timeout_add_seconds(14, lambda: loop.quit() or False)
    loop.run()
    window.destroy()
    assert passed
    print('PASS: automatic discovery, themed controls, validation, cancellation')
