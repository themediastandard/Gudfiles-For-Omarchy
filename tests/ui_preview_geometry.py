"""Preview selection and animation must not resize or move the native window."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

import cairo
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow


def settle(milliseconds=120):
    loop = GLib.MainLoop()
    GLib.timeout_add(milliseconds, lambda: loop.quit() or False)
    loop.run()


def native_window():
    clients = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
    return next(c for c in clients if c['pid'] == os.getpid() and c['class'] == 'org.omarchy.FilePicker')


with tempfile.TemporaryDirectory(prefix='picker-preview-size-') as temp:
    root = Path(temp)
    for name, width, height in [('portrait', 100, 1600), ('landscape', 1600, 100), ('square', 500, 500)]:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = cairo.Context(surface)
        context.set_source_rgb(.2, .4, .7)
        context.paint()
        surface.write_to_png(str(root / (name + '.png')))
    (root / ('long-name-' * 20 + '.txt')).write_text('Long line ' * 300)
    request = PickerRequest(current_folder=root)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window._set_view('list')
    window.present()
    settle()
    try:
        client = native_window()
        selector = json.dumps('address:' + client['address'])
        if not client['floating']:
            subprocess.run(['hyprctl', 'dispatch',
                            'hl.dsp.window.float({action="toggle",window=' + selector + '})'], check=True)
            settle(350)
        subprocess.run(['hyprctl', 'dispatch',
                        'hl.dsp.window.resize({x=1040,y=680,relative=false,window=' + selector + '})'], check=True)
        settle(350)
        baseline = native_window()
        geometry = (baseline['at'], baseline['size'])
        assert baseline['size'] == [1040, 680], baseline['size']
        measure = lambda: (window.measure(Gtk.Orientation.HORIZONTAL, -1)[:2],
                           window.measure(Gtk.Orientation.VERTICAL, window.get_width())[:2])
        initial_measure = measure()
        preview_height = window.metadata_viewport.get_height()
        browser_height = window.browser_stack.get_height()
        def check(stage):
            client = native_window()
            actual = (client['at'], client['size'])
            assert actual == geometry, (stage, geometry, actual)
            assert measure() == initial_measure, (stage, initial_measure, measure())
            assert window.metadata_viewport.get_height() == preview_height
            assert window.browser_stack.get_height() == browser_height
        for mode in ('list', 'grid'):
            window._set_view(mode)
            settle()
            initial_measure = measure()
            check(mode)
            for path in window.entries:
                window.flow.unselect_all()
                window.flow.select_child(window.children_by_path[path])
                settle()
                check(mode + ' selected ' + path.suffix)
                if mode == 'list' and path.stem == 'portrait' and os.environ.get('PREVIEW_QA_SCREENSHOT'):
                    snapshot = Gtk.Snapshot.new()
                    Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                    texture = window.get_renderer().render_texture(snapshot.to_node(), None)
                    texture.save_to_png(os.environ['PREVIEW_QA_SCREENSHOT'])
                window.quicklook.show_file(path)
                for _ in range(5):
                    settle(70)
                    check('preview opening/loaded')
                assert window.quicklook.kind != 'loading'
                if window.quicklook.kind == 'image':
                    image = window.quicklook.content.get_first_child()
                    image.scroll.emit('scroll', 0.0, -20.0)
                    settle()
                    check('image zoomed')
                    image.click.emit('pressed', 2, 0.0, 0.0)
                    settle()
                    check('image reset to fit')
                window.quicklook.close()
                for _ in range(4):
                    settle(70)
                    check('preview closing')
                print('PASS:', mode, path.suffix, 'selection/open/close preserves geometry and size requests', flush=True)
            window.flow.unselect_all()
            settle()
            check('deselected')
        print('PASS: portrait/landscape/square/text selection and Quick Look preserve native size and position')
    finally:
        window.destroy()
