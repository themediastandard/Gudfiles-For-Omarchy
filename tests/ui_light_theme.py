"""Native light-palette ink and surface review using disposable files.

LIGHT_THEME_QA_SCREENSHOTS=/tmp/gudfiles-light PYTHONPATH=. python tests/ui_light_theme.py
Captures three views, menus, Help, Transfers, Quick Look and a form for each palette.
"""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.theme import build_css, contrast_ratio
from tests.test_theme import LIGHT_PALETTES
from gi.repository import Gtk, Gio, GLib

GLib.set_application_name('Gudfiles Light Theme QA')


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(150, lambda: loop.quit() or False)
    loop.run()


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


def capture(widget, palette, name):
    directory = os.environ.get('LIGHT_THEME_QA_SCREENSHOTS')
    if not directory:
        return
    settle()
    snapshot = Gtk.Snapshot.new()
    Gtk.WidgetPaintable.new(widget).snapshot(snapshot, widget.get_width(), widget.get_height())
    node = snapshot.to_node()
    assert node is not None, (palette, name, 'Surface must be drawable')
    target = Path(directory) / palette
    target.mkdir(parents=True, exist_ok=True)
    widget.get_native().get_renderer().render_texture(node, None).save_to_png(str(target / (name + '.png')))


def verify_ink(widget, surface):
    color = widget.get_color()
    ink = '#%02x%02x%02x' % tuple(round(v * 255) for v in (color.red, color.green, color.blue))
    assert contrast_ratio(ink, surface) >= 4.5, (widget.get_css_classes(), ink, surface)


with tempfile.TemporaryDirectory(prefix='gudfiles-light-') as temp:
    root = Path(temp)
    folder = root / 'Projects'
    folder.mkdir()
    for name in ('Brand assets', 'Deliverables', 'Footage', 'Reference'):
        (folder / name).mkdir()
    source = folder / 'Project brief.txt'
    source.write_text('Gudfiles\n\nA clean workspace for your next project.\n')
    (folder / 'Shot list.txt').touch()
    app = PickerApplication(PickerRequest(current_folder=folder), None)
    app.register(None)
    for palette, colors in LIGHT_PALETTES.items():
        provider = Gtk.CssProvider()
        errors = []
        provider.connect('parsing-error', lambda _p, _section, error: errors.append(str(error)))
        provider.load_from_string(build_css(colors))
        assert not errors, errors
        with patch.object(Path, 'home', return_value=root), \
                patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
                patch('omarchy_file_picker.picker.load_colors', return_value=colors), \
                patch.dict(os.environ, {'OMARCHY_FILE_PICKER_AUTOMATION': 'context-menu'}):
            window = PickerWindow(app, PickerRequest(current_folder=folder, explorer=True,
                                  multiple=True, title='Gudfiles'), None)
            window.present()
            settle()
            try:
                for mode in ('grid', 'list', 'columns'):
                    window._set_view(mode)
                    settle()
                    window.flow.select_child(window.children_by_path[source])
                    settle()
                    for label in descendants(window):
                        if isinstance(label, Gtk.Label) and any(label.has_css_class(css) for css in
                                                                ('muted', 'key-hint', 'column-heading', 'sidebar-heading')):
                            verify_ink(label, window.colors['selection'])
                    capture(window, palette, mode)
                window._set_view('list')
                settle()
                window._show_context_menu(250, 80, source)
                settle()
                capture(window.context_popover, palette, 'file-menu')
                window._close_context_menu()
                filtering = next(w for w in descendants(window.toolbar)
                                 if isinstance(w, Gtk.MenuButton) and w.has_css_class('creative-filter'))
                filtering.get_popover().set_autohide(False)
                filtering.popup()
                capture(filtering.get_popover(), palette, 'filters')
                filtering.popdown()
                window._show_transfers()
                settle()
                capture(window.transfer_window, palette, 'transfers')
                window.transfer_window.set_visible(False)
                window.help_button.emit('clicked')
                settle()
                capture(window.help_window, palette, 'help')
                window.help_window.set_visible(False)
                window.quicklook.show_file(source)
                settle()
                capture(window, palette, 'quicklook')
                window.quicklook.close()
                settle()
                if palette == 'rose' and shutil.which('ffmpeg'):
                    video = root / 'Preview.mp4'
                    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
                                    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=12',
                                    '-t', '4', '-c:v', 'libx264', '-preset', 'ultrafast', '-an',
                                    str(video)], check=True, timeout=20)
                    window.quicklook.show_file(video)
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        media = window.quicklook.media
                        if media is not None and media.is_prepared():
                            break
                        settle()
                    assert media is not None and media.is_prepared()
                    media.pause()
                    for widget in descendants(window.quicklook.content):
                        if isinstance(widget, Gtk.Revealer):
                            widget.set_reveal_child(True)
                    settle()
                    controls = next(w for w in descendants(window.quicklook.content)
                                    if isinstance(w, Gtk.MediaControls))
                    for widget in descendants(controls):
                        if isinstance(widget, (Gtk.Button, Gtk.Label)):
                            verify_ink(widget, window.colors['background'])
                    capture(window, palette, 'video-controls')
                    window.quicklook.close()
                    settle()
                dialog = window._show_rename_dialog(source)
                settle()
                next(w for w in descendants(dialog) if isinstance(w, Gtk.Entry)).set_text('Project brief — final.txt')
                settle()
                action = next(w for w in descendants(dialog) if isinstance(w, Gtk.Button)
                              and w.has_css_class('suggested-action'))
                # Rose's pastel accent previously received unreadable white text.
                verify_ink(action.get_child(), window.colors['accent'])
                capture(dialog, palette, 'rename')
                dialog.response(Gtk.ResponseType.CANCEL)
                settle()
                assert source.read_text().startswith('Gudfiles')
                print('PASS:', palette, 'native ink, CSS, three views, popovers and auxiliary windows')
            finally:
                window.destroy()
                settle()
