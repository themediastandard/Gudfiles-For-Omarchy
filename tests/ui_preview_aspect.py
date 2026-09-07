"""Native image/video aspect fitting, chrome bounds and live window resizing."""
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch

import cairo
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from gi.repository import GLib, Gtk

GLib.set_application_name('Omarchy File Picker Aspect QA')


def settle(ms=50):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'GTK condition timed out'


def native_window():
    clients = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
    return next((c for c in clients if c['pid'] == os.getpid()
                 and c['class'] == 'org.omarchy.FilePicker'), None)


def capture(window, name):
    directory = os.environ.get('ASPECT_QA_SCREENSHOTS')
    if not directory:
        return
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    for _ in range(20):
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
        node = snapshot.to_node()
        if node:
            window.get_renderer().render_texture(node, None).save_to_png(str(path / (name + '.png')))
            return
        settle()
    raise AssertionError('No drawable snapshot')


with tempfile.TemporaryDirectory(prefix='picker-aspect-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)):
    root = Path(temp)
    cases = []
    for name, width, height in [('portrait', 180, 320), ('landscape', 320, 180), ('square', 240, 240)]:
        picture = root / (name + '.png')
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(surface)
        gradient = cairo.LinearGradient(0, 0, width, height)
        gradient.add_color_stop_rgb(0, .12, .24, .45)
        gradient.add_color_stop_rgb(1, .7, .4, .2)
        cr.set_source(gradient)
        cr.paint()
        surface.write_to_png(str(picture))
        video = root / (name + '.mp4')
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
                        '-f', 'lavfi', '-i', f'testsrc2=size={width}x{height}:rate=30',
                        '-t', '3', '-an', '-c:v', 'libx264', '-preset', 'ultrafast',
                        '-threads', '2', str(video)], check=True, timeout=20)
        cases.extend([(picture, width / height), (video, width / height)])
    text = root / 'notes.txt'
    text.write_text('A bounded read-only preview.\n' * 10)
    request = PickerRequest(current_folder=root, explorer=True, title='Preview sizing QA')
    app = PickerApplication(request, None)
    app.register(None)
    with patch('omarchy_file_picker.picker.thumbnail_file', return_value=None):
        window = PickerWindow(app, request, None)
    window.present()
    until(window.get_mapped)
    until(lambda: native_window() is not None)
    preview = window.quicklook
    try:
        client = native_window()
        selector = json.dumps('address:' + client['address'])
        if not client['floating']:
            subprocess.run(['hyprctl', 'dispatch',
                            'hl.dsp.window.float({action="toggle",window=' + selector + '})'], check=True)
        def resize(width, height):
            subprocess.run(['hyprctl', 'dispatch',
                            f'hl.dsp.window.resize({{x={width},y={height},relative=false,window=' + selector + '})'], check=True)
            until(lambda: native_window()['size'] == [width, height])
            settle(200)
        resize(1200, 820)
        geometry = (native_window()['at'], native_window()['size'])
        original = (window.get_width(), window.get_height(), window.browser_stack.get_height())
        shapes = {}
        old_media = None
        for path, ratio in cases:
            preview.show_file(path)
            until(lambda: preview.kind != 'loading' and preview.progress == 1
                  and preview.aspect_ratio > 0)
            settle(120)
            view = preview.content.get_first_child()
            assert math.isclose(preview.aspect_ratio, ratio, abs_tol=.002), (path.name, preview.aspect_ratio)
            assert abs(view.get_width() - view.get_height() * ratio) <= 1.1, (
                path.name, view.get_width(), view.get_height(), ratio)
            assert (window.get_width(), window.get_height(), window.browser_stack.get_height()) == original
            assert (native_window()['at'], native_window()['size']) == geometry
            for control in preview.header_items:
                valid, bounds = control.compute_bounds(preview.card)
                assert valid and bounds.get_x() >= 0 and bounds.get_y() >= 0
                assert bounds.get_x() + bounds.get_width() <= preview.card.get_width() + 1
                assert bounds.get_y() + bounds.get_height() <= preview.card.get_height() + 1
            shapes[path.name] = preview.rect[2:]
            capture(window, path.name)
            if preview.media:
                old_media = preview.media
            preview.close()
            until(lambda: not preview.get_visible())
            assert preview.aspect_ratio == 0
            print('PASS:', path.name, 'fitted content, attached controls, stable Files geometry', flush=True)
        assert shapes['portrait.png'][0] < shapes['portrait.png'][1]
        assert shapes['landscape.png'][0] > shapes['landscape.png'][1]
        assert shapes['portrait.mp4'] == shapes['portrait.png']
        preview.show_file(root / 'portrait.png')
        until(lambda: preview.kind == 'image' and preview.progress == 1)
        old_media.emit('invalidate-size')
        assert math.isclose(preview.aspect_ratio, 9 / 16, abs_tol=.002)
        for width, height in [(820, 560), (1400, 900), (1200, 820)]:
            resize(width, height)
            x, y, w, h = preview.rect
            assert x >= 0 and y >= 0
            assert x + w <= preview.get_width() and y + h <= preview.get_height()
            image = preview.content.get_first_child()
            iw, ih = image.image_size()
            assert iw <= image.get_width() + .01 and ih <= image.get_height() + .01
            assert math.isclose(iw / ih, 9 / 16, abs_tol=.002)
        preview.show_file(text)
        until(lambda: preview.kind == 'text')
        old_media.emit('invalidate-size')
        settle()
        assert preview.aspect_ratio == 0 and not preview.compact_header
        preview.close()
        until(lambda: not preview.get_visible())
        print('PASS: window resizing, stale decoder signals and text fallback', flush=True)
    finally:
        window.destroy()
