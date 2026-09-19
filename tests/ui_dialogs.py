"""Native dialog behavior and bounded layout with disposable files and palettes.

DIALOG_QA_SCREENSHOTS=/tmp/dialogs PYTHONPATH=. python tests/ui_dialogs.py
"""
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import DEFAULT_COLORS, load_colors


def settle(seconds=.12):
    loop = GLib.MainLoop()
    GLib.timeout_add(int(seconds * 1000), lambda: loop.quit() or False)
    loop.run()


def children(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from children(child)
        child = child.get_next_sibling()


def labels(widget):
    return [w.get_text() for w in children(widget) if isinstance(w, Gtk.Label)]


def entry(dialog):
    return next(w for w in children(dialog) if isinstance(w, Gtk.Entry))


def bounded(dialog, width, height=700):
    settle()
    assert 0 < dialog.get_width() <= width, (dialog.get_title(), dialog.get_width())
    assert 0 < dialog.get_height() <= height, (dialog.get_title(), dialog.get_height())
    ok, bounds = dialog.footer.compute_bounds(dialog)
    assert ok and bounds.get_y() + bounds.get_height() <= dialog.get_height()


def capture(dialog, palette, name):
    directory = os.environ.get('DIALOG_QA_SCREENSHOTS')
    if not directory:
        return
    settle()
    snapshot = Gtk.Snapshot.new()
    Gtk.WidgetPaintable.new(dialog).snapshot(snapshot, dialog.get_width(), dialog.get_height())
    node = snapshot.to_node()
    assert node is not None, (name, 'Dialog must be visible to capture')
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    dialog.get_renderer().render_texture(node, None).save_to_png(str(target / f'{palette}-{name}.png'))


def dismiss(dialog):
    dialog.response(Gtk.ResponseType.CANCEL)
    settle()
    assert not dialog.get_visible()


palettes = [('active', load_colors()), ('light', DEFAULT_COLORS),
            ('dark', {**DEFAULT_COLORS, 'background': '#17191f', 'foreground': '#d7dce4',
                      'bright_foreground': '#ffffff', 'accent': '#86a6f4'})]
with tempfile.TemporaryDirectory(prefix='dialog-qa-') as directory:
    root = Path(directory)
    app = PickerApplication(PickerRequest(current_folder=root), None)
    app.register(None)
    for palette, colors in palettes:
        folder = root / palette / 'Mountain drive'
        folder.mkdir(parents=True)
        source = folder / 'Mountain drive — final edit.mov'
        source.write_bytes(b'x' * 4096)
        source.chmod(0o640)
        collision = folder / 'Existing.mov'
        collision.write_text('Keep this original')
        zero = folder / 'Empty.txt'
        zero.touch()
        link = folder / 'Shortcut'
        link.symlink_to(folder / 'Missing target')
        nested = folder
        for index in range(9):
            nested /= f'Archive {index} ' + 'long location ' * 4
        nested.mkdir(parents=True)
        long_path = nested / ('Very long filename ' * 11 + '.txt')
        long_path.write_text('Long name')
        request = PickerRequest(current_folder=folder, mode='save', current_name=source.name)
        with patch.object(Path, 'home', return_value=root), \
             patch('omarchy_file_picker.picker.load_colors', return_value=colors), \
             patch('omarchy_file_picker.picker.thumbnail_file', return_value=None):
            window = PickerWindow(app, request, None)
            window.present()
            settle()
            dialog = window._show_rename_dialog(source)
            bounded(dialog, 510)
            assert entry(dialog).get_selection_bounds() == (0, len(source.stem))
            entry(dialog).set_text(collision.name)
            dialog.response(Gtk.ResponseType.ACCEPT)
            assert source.exists() and collision.read_text() == 'Keep this original'
            assert dialog.error_label.get_visible() and dialog.get_visible()
            capture(dialog, palette, 'rename-error')
            entry(dialog).set_text('Mountain drive — approved.mov')
            assert not dialog.error_label.get_visible()
            capture(dialog, palette, 'rename')
            # Gtk.Entry forwards Gtk.Text's signal. Exercise the native text
            # action, including its default-widget handling, like Return does.
            entry(dialog).get_first_child().emit('activate')
            settle(.3)
            renamed = source.with_name('Mountain drive — approved.mov')
            assert renamed.read_bytes() == b'x' * 4096 and not source.exists()
            assert not dialog.get_visible()

            dialog = window._show_create_dialog('folder')
            entry(dialog).set_text('Existing.mov')
            dialog.response(Gtk.ResponseType.ACCEPT)
            assert dialog.error_label.get_visible()
            entry(dialog).set_text('New project')
            bounded(dialog, 510)
            capture(dialog, palette, 'new-folder')
            entry(dialog).get_first_child().emit('activate')
            settle(.3)
            assert (folder / 'New project').is_dir()

            for name, paths in [('properties', [renamed]), ('empty', [zero]),
                                ('folder-properties', [folder]), ('link', [link]),
                                ('long-properties', [long_path]),
                                ('selection', [renamed, zero, folder / 'New project', link])]:
                dialog = window._show_properties(paths)
                bounded(dialog, 570)
                values = labels(dialog)
                assert not any('True /' in value for value in values)
                if name == 'properties':
                    assert '4.0 KB  ·  4,096 bytes' in values
                    assert 'rw-r-----  ·  0640' in values
                    copied = []
                    with patch.object(window, '_copy_location', side_effect=lambda paths: copied.extend(paths)):
                        dialog.response(Gtk.ResponseType.APPLY)
                    assert copied == paths and dialog.get_visible()
                if name == 'empty': assert '0 B' in values
                if name == 'folder-properties': assert 'Size' not in values
                if name == 'link': assert str(folder / 'Missing target') in values
                if name == 'long-properties': assert str(nested) in values
                if name == 'selection':
                    assert any('Folder contents excluded' in value and 'unavailable' in value for value in values)
                capture(dialog, palette, name)
                dismiss(dialog)

            dialog = window._show_rename_dialog(long_path)
            bounded(dialog, 510)
            assert entry(dialog).get_text() == long_path.name
            assert dialog._key_pressed(None, Gdk.KEY_Escape)
            settle()
            assert long_path.exists() and not dialog.get_visible()

            dialog = window._confirm_remove([renamed], permanent=True)
            bounded(dialog, 510)
            assert dialog.get_default_widget().get_label() == 'Cancel'
            capture(dialog, palette, 'delete')
            dialog.emit('activate-default')
            settle(.3)
            assert renamed.exists() and not window.file_job_active
            dialog = window._confirm_remove([renamed], permanent=False)
            capture(dialog, palette, 'trash')
            dialog.close_button.emit('clicked')
            settle()
            assert renamed.exists() and not window.file_job_active
            disposable = folder / 'Delete only this fixture.txt'
            disposable.write_text('Delete fixture')
            dialog = window._confirm_remove([disposable], permanent=True)
            dialog.response(Gtk.ResponseType.ACCEPT)
            deadline = time.monotonic() + 5
            while window.file_job_active and time.monotonic() < deadline:
                settle(.05)
            assert not disposable.exists() and not window.file_job_active

            results = []
            with patch.object(window, '_finish', side_effect=lambda **kw: results.append(kw)):
                for accept in (False, True):
                    window.filename_entry.set_text(collision.name)
                    window._accept()
                    dialog = next(w for w in Gtk.Window.get_toplevels()
                                  if w.get_title() == 'Replace existing file?' and w.get_visible())
                    bounded(dialog, 510)
                    assert dialog.get_default_widget().get_label() == 'Cancel'
                    capture(dialog, palette, 'replace')
                    dialog.response(Gtk.ResponseType.ACCEPT if accept else Gtk.ResponseType.CANCEL)
                    settle()
                    assert len(results) == int(accept)
                    assert collision.read_text() == 'Keep this original'
            assert results == [{'paths': [collision]}]

            detail = 'Could not access this location.\n' + str(nested) * 8
            dialog = window._show_error('Could not open the folder', detail)
            bounded(dialog, 530)
            assert detail in labels(dialog)
            capture(dialog, palette, 'error')
            dismiss(dialog)
            window.destroy()
            settle()
print('PASS: active/light/dark dialog geometry; long names/paths; name selection, inline collisions and Enter; properties, links and totals; Escape/close/cancel; confirmed fixture deletion; Save replacement protocol')
