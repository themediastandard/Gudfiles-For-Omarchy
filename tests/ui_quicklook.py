"""Run with PYTHONPATH=. python tests/ui_quicklook.py on a GTK desktop."""
import tempfile
import wave
from pathlib import Path

import cairo
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.quicklook import read_preview

GLib.set_application_name('Gudfiles Quick Look QA')


def wait_for(predicate, timeout=5):
    loop = GLib.MainLoop()
    ready = False
    def poll():
        nonlocal ready
        ready = bool(predicate())
        if ready:
            loop.quit()
            return False
        return True
    timer = GLib.timeout_add(10, poll)
    deadline = GLib.timeout_add(int(timeout * 1000), lambda: loop.quit() or False)
    loop.run()
    if ready:
        GLib.source_remove(deadline)
    else:
        GLib.source_remove(timer)
    assert ready, 'Timed out waiting for GTK state'


with tempfile.TemporaryDirectory(prefix='quicklook-qa-') as directory:
    root = Path(directory)
    text = root / 'notes.txt'
    text.write_text('Quick Look\nA read-only preview.\n' * 20)
    picture = root / 'image.png'
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 800, 500)
    context = cairo.Context(surface)
    context.set_source_rgb(0.1, 0.4, 0.9)
    context.paint()
    surface.write_to_png(str(picture))
    pdf = root / 'document.pdf'
    surface = cairo.PDFSurface(str(pdf), 400, 600)
    context = cairo.Context(surface)
    context.move_to(40, 60)
    context.show_text('Preview fixture')
    context.show_page()
    surface.finish()
    sound = root / 'audio.wav'
    with wave.open(str(sound), 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
        wav.writeframes(b'\0\0' * 8000)
    binary = root / 'binary.bin'
    binary.write_bytes(b'\0\1\2')
    request = PickerRequest(current_folder=root)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    preview = window.quicklook
    wait_for(lambda: window.get_mapped())

    def key(value):
        return window._on_preview_key(None, value, 0, Gdk.ModifierType(0))

    try:
        window.flow.unselect_all()
        window.flow.select_child(window.children_by_path[picture])
        window.children_by_path[picture].grab_focus()
        assert key(Gdk.KEY_space) == Gdk.EVENT_STOP
        wait_for(lambda: 0 < preview.progress < 1)
        wait_for(lambda: preview.progress == 1 and preview.kind == 'image')
        assert not window.preview_overlay.get_child().get_sensitive()
        selected = window._selected_paths()
        assert key(Gdk.KEY_Return) == Gdk.EVENT_STOP
        assert key(Gdk.KEY_space) == Gdk.EVENT_STOP
        wait_for(lambda: 0 < preview.progress < 1)
        wait_for(lambda: not preview.get_visible())
        assert window._selected_paths() == selected
        assert window.preview_overlay.get_child().get_sensitive()
        assert window.get_focus() is window.children_by_path[picture]

        # Reversing an in-flight close never strands the overlay or focus.
        key(Gdk.KEY_space)
        wait_for(lambda: preview.progress > .1)
        key(Gdk.KEY_space)
        key(Gdk.KEY_space)
        wait_for(lambda: preview.progress == 1)
        key(Gdk.KEY_Escape)
        wait_for(lambda: not preview.get_visible())

        for path, kind in [(text, 'text'), (pdf, 'pdf'), (binary, 'info'), (sound, 'media')]:
            preview.show_file(path)
            wait_for(lambda: preview.kind != 'loading' and preview.progress == 1)
            if kind == 'media' and preview.kind == 'info':
                print('NOTE: media decoder unavailable; verified graceful codec message')
                preview.close()
                wait_for(lambda: not preview.get_visible())
                continue
            assert preview.kind == kind, (path.name, preview.kind)
            if kind == 'media':
                wait_for(lambda: preview.media is not None and preview.media.is_prepared())
                assert preview.media.get_error() is None
            preview.close()
            wait_for(lambda: not preview.get_visible())
            assert preview.media is None

        preview.show_file(picture)
        wait_for(lambda: preview.kind == 'image')
        key(Gdk.KEY_Right)
        wait_for(lambda: preview.path == text and preview.kind == 'text')
        preview.close()
        wait_for(lambda: not preview.get_visible())

        window.search.grab_focus()
        assert key(Gdk.KEY_space) == Gdk.EVENT_PROPAGATE
        settings = Gtk.Settings.get_default()
        animations = settings.get_property('gtk-enable-animations')
        settings.set_property('gtk-enable-animations', False)
        preview.show_file(picture)
        # Reduced motion still waits for decoded geometry, then reveals directly.
        wait_for(lambda: preview.kind == 'image')
        assert preview.progress == 1
        preview.close()
        assert not preview.get_visible()
        settings.set_property('gtk-enable-animations', animations)
        wait_for(lambda: True)
        assert read_preview(root / 'missing')[0] == 'info'
        print('PASS: animated Space open/close, reversal, Escape, focus/selection, read-only keys, images/text/PDF, media or graceful codec fallback, arrows, editable Space, reduced motion, missing file')
    finally:
        window.destroy()
