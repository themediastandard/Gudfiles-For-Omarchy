"""Native batch rename flow against disposable files and isolated preferences."""
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.batch_rename import plan_rename


def settle(seconds=0.18):
    loop = GLib.MainLoop()
    GLib.timeout_add(int(seconds * 1000), lambda: loop.quit() or False)
    loop.run()


def preview_ready(dialog):
    deadline = time.monotonic() + 6
    while (dialog.preview_timer or dialog.preview_running or dialog.preview_pending) and time.monotonic() < deadline:
        settle(0.05)
    assert not dialog.preview_running and not dialog.preview_pending


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    paths = [root / name for name in ('Camera_A_take01.mov', 'Camera_B_take02.mov', 'Camera_C_take03.mov')]
    for index, path in enumerate(paths):
        path.write_text(f'original {index}')
    with patch.object(Path, 'home', return_value=root):
        request = PickerRequest(current_folder=root, multiple=True, explorer=True)
        app = PickerApplication(request, None)
        app.register(None)
        with patch('omarchy_file_picker.picker.thumbnail_file', return_value=None):
            window = PickerWindow(app, request, None)
        window.present()
        settle()
        changes = []
        window._creative_paths_renamed = lambda mapping: changes.append(mapping)
        dialog = window._show_batch_rename_dialog(paths)
        settle()
        preview_ready(dialog)
        assert dialog.has_css_class('picker-dialog')
        assert dialog.apply_button.get_sensitive()
        dialog.pattern.set_text('Interview_{n}')
        dialog.start.set_value(12)
        preview_ready(dialog)
        assert [item.target.name for item in dialog.plan] == ['Interview_012.mov', 'Interview_013.mov', 'Interview_014.mov']
        dialog.pattern.set_text('same')
        preview_ready(dialog)
        assert not dialog.apply_button.get_sensitive()
        assert 'same name' in dialog.status.get_text()
        dialog.stack.set_visible_child_name('replace')
        dialog.find.set_text('Camera')
        dialog.replace.set_text('Scene')
        preview_ready(dialog)
        assert dialog.plan[0].target.name == 'Scene_A_take01.mov'
        # A slow NAS-like preview must not block GTK or replace newer input.
        def delayed_plan(paths, options):
            time.sleep(0.25)
            return plan_rename(paths, options)
        with patch('omarchy_file_picker.batch_rename.plan_rename', side_effect=delayed_plan):
            dialog.stack.set_visible_child_name('pattern')
            dialog.pattern.set_text('Old_{n}')
            settle(0.17)
            assert dialog.preview_running
            dialog.pattern.set_text('Latest_{n}')
            assert not dialog.apply_button.get_sensitive()
            preview_ready(dialog)
            assert dialog.plan[0].target.name == 'Latest_012.mov'
        dialog._close()
        settle()
        assert all(path.exists() for path in paths)
        assert not changes
        dialog = window._show_batch_rename_dialog(paths)
        dialog.pattern.set_text('Interview_{n}')
        settle()
        preview_ready(dialog)
        screenshot = os.environ.get('BATCH_RENAME_QA_SCREENSHOT')
        if screenshot:
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(dialog).snapshot(snapshot, dialog.get_width(), dialog.get_height())
            texture = dialog.get_renderer().render_texture(snapshot.to_node(), None)
            texture.save_to_png(screenshot)
        dialog.pattern.get_first_child().emit('activate')
        settle(.3)
        deadline = time.monotonic() + 6
        while dialog.active and time.monotonic() < deadline:
            settle(0.05)
        settle()
        assert not dialog.active and not dialog.get_visible()
        targets = [root / f'Interview_{index + 1:03d}.mov' for index in range(3)]
        assert [path.read_text() for path in targets] == [f'original {index}' for index in range(3)]
        assert changes == [dict(zip(paths, targets))]
        assert set(window._selected_paths()) == set(targets)
        assert not window.file_job_active
        window.destroy()
        settle()
print('PASS: native preview, validation, pattern/replace, cancellation, rename, selection and metadata migration hook')
