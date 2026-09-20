"""Real FFmpeg/GTK hover frame QA, using controller signals, not physical input."""
import os
os.environ.setdefault('GSK_RENDERER', 'gl')
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk
from omarchy_file_picker.hover_scrub import HoverScrub, SCRUB_STEPS, ScrubFrame, scrub_step


errors = []
def report_error(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = report_error


def until(predicate, timeout=8):
    loop = GLib.MainLoop()
    done = False
    def poll():
        nonlocal done
        done = bool(predicate())
        if done:
            loop.quit()
        return not done
    source = GLib.timeout_add(20, poll)
    deadline = GLib.timeout_add(int(timeout * 1000), lambda: loop.quit() or False)
    loop.run()
    GLib.source_remove(deadline if done else source)
    assert not errors, 'GTK callback failed'
    assert done, 'Timed out waiting for thumbnail state'


def settle(milliseconds=280):
    loop = GLib.MainLoop()
    GLib.timeout_add(milliseconds, lambda: loop.quit() or False)
    loop.run()
    assert not errors, 'GTK callback failed'


with tempfile.TemporaryDirectory(prefix='hover-scrub-qa-') as directory:
    path = Path(directory) / 'silent-colors.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=12',
                    '-t', '3', '-c:v', 'libx264', '-threads', '1', '-preset', 'ultrafast', str(path)],
                   check=True, timeout=20)
    before = path.read_bytes()
    app = Gtk.Application(application_id='org.omarchy.HoverScrubQA')
    app.register(None)
    window = Gtk.ApplicationWindow(application=app, default_width=440, default_height=280)
    flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.MULTIPLE)
    tile = Gtk.FlowBoxChild()
    base = Gtk.Image(icon_name='video-x-generic-symbolic', width_request=156, height_request=98)
    scrub = HoverScrub(path, base)
    tile.set_child(scrub)
    flow.append(tile)
    window.set_child(flow)
    window.present()
    until(lambda: scrub.get_mapped() and scrub.get_width() > 0)
    flow.select_child(tile)
    measured = (window.get_width(), window.get_height(), scrub.measure(Gtk.Orientation.HORIZONTAL, -1),
                scrub.measure(Gtk.Orientation.VERTICAL, -1))
    try:
        assert not scrub.get_has_tooltip()
        # A fast pass across the tile does not start extraction.
        scrub.motion.emit('enter', 5.0, 5.0)
        scrub.motion.emit('leave')
        settle()
        assert not scrub._busy and scrub.frame is None

        scrub.motion.emit('enter', float(scrub.get_width() * .1), 8.0)
        until(lambda: scrub.frame is not None)
        assert scrub.picture.get_visible() and scrub.track.get_visible()
        first = scrub.frame
        assert 0 <= first.seconds < .5
        assert first.duration == 3
        for fraction in [.9, .2, .7, .95]:
            scrub.motion.emit('motion', scrub.get_width() * fraction, 8.0)
        until(lambda: scrub.displayed_step == scrub_step(.95))
        assert scrub.frame.seconds > 2.3
        assert first.data != scrub.frame.data
        assert scrub.picture.get_paintable().get_intrinsic_width() <= 320
        assert scrub.picture.get_paintable().get_intrinsic_height() <= 180
        assert flow.get_selected_children() == [tile]
        assert measured == (window.get_width(), window.get_height(), scrub.measure(Gtk.Orientation.HORIZONTAL, -1),
                            scrub.measure(Gtk.Orientation.VERTICAL, -1))

        # Leaving while a frame is requested never brings its overlay back.
        scrub.motion.emit('motion', scrub.get_width() * .4, 8.0)
        scrub._tick()
        scrub.motion.emit('leave')
        until(lambda: not scrub._busy)
        assert scrub.frame is None and not scrub.picture.get_visible()
        assert not scrub.track.get_visible() and scrub.get_child() is base

        # A decoder slower than pointer motion must still advance the preview.
        # Control replies so every completion arrives after another mouse move.
        class DelayedWorker:
            def __init__(self):
                self.requests = []

            def request(self, path, step, callback):
                self.requests.append((step, callback))
                return True

            def finish(self):
                step, callback = self.requests.pop(0)
                callback(ScrubFrame(first.data, step / (SCRUB_STEPS - 1) * 3, 3, step))
                return step

        delayed = DelayedWorker()
        real_worker, scrub.worker = scrub.worker, delayed
        scrub.motion.emit('enter', scrub.get_width() * .1, 8.0)
        until(lambda: bool(delayed.requests))
        for fraction in [.3, .5, .7, .9]:
            scrub.motion.emit('motion', scrub.get_width() * fraction, 8.0)
            completed = delayed.finish()
            assert scrub.picture.get_visible(), 'Continuous motion starved the preview'
            assert scrub.displayed_step == completed
            assert len(delayed.requests) == 1, 'Latest position was not requested immediately'
            assert delayed.requests[0][0] == scrub_step(fraction)
        delayed.finish()
        assert scrub.displayed_step == scrub_step(.9)
        assert not delayed.requests

        # A reply from a previous hover cannot replace the poster on re-entry.
        scrub.motion.emit('motion', scrub.get_width() * .6, 8.0)
        scrub.motion.emit('leave')
        scrub.motion.emit('enter', scrub.get_width() * .2, 8.0)
        delayed.finish()
        assert scrub.frame is None and not scrub.picture.get_visible()
        until(lambda: bool(delayed.requests))
        delayed.finish()
        assert scrub.displayed_step == scrub_step(.2)
        scrub.motion.emit('leave')
        scrub.worker = real_worker

        # Native motion observes held buttons without claiming click sequences.
        class DraggingPointer:
            def get_current_event_state(self):
                return Gdk.ModifierType.BUTTON1_MASK
        scrub.motion.emit('enter', 5.0, 5.0)
        scrub._motion(DraggingPointer(), 20, 5)
        assert not scrub.active and not scrub.picture.get_visible()
        assert flow.get_selected_children() == [tile]
        scrub._enter(DraggingPointer(), 20, 5)
        assert not scrub.active and scrub._timer == 0

        # Broken media stays a quiet original poster, never a fake error icon.
        scrub.motion.emit('enter', 5.0, 5.0)
        scrub._complete(scrub._generation, scrub_step(scrub.fraction), None)
        assert not scrub.active and scrub.get_child() is base
        assert not scrub.picture.get_visible() and scrub._timer == 0
        assert path.read_bytes() == before
        print('PASS: real frames, continuous motion with slow decoding, immediate catch-up, re-entry/drag cancellation, no skim tooltip, bounded textures, selection/geometry, quiet failure, unchanged source')
    finally:
        window.destroy()
        settle(100)

    # Actual grid ancestors must not reintroduce the file-path tooltip over video.
    from omarchy_file_picker.model import PickerRequest
    from omarchy_file_picker.picker import PickerWindow

    def walk(widget):
        yield widget
        child = widget.get_first_child()
        while child:
            yield from walk(child)
            child = child.get_next_sibling()

    with patch.object(Path, 'home', return_value=Path(directory) / 'home'):
        request = PickerRequest(current_folder=Path(directory), explorer=True)
        browser = PickerWindow(app, request, None)
        browser._set_view('grid')
        browser.present()
        try:
            until(lambda: path in browser.children_by_path)
            tile = browser.children_by_path[path]
            video = next(w for w in walk(tile) if isinstance(w, HoverScrub))
            ancestor = video
            while ancestor:
                assert not ancestor.get_has_tooltip(), type(ancestor)
                ancestor = ancestor.get_parent()
            name = next(w for w in walk(tile) if isinstance(w, Gtk.Label) and w.get_text() == path.name)
            assert not name.get_has_tooltip()
            if os.environ.get('POINTER_QA_ISOLATED') == '1':
                # Real pointer motion through the composed grid widget, including
                # its poster/overlay children, must keep producing video frames.
                gi.require_version('GdkX11', '4.0')
                from gi.repository import GdkX11
                until(lambda: video.get_mapped() and video.get_width() > 0)
                settle()
                valid, bounds = video.compute_bounds(browser)
                assert valid
                dx, dy = browser.get_surface_transform()
                def point(fraction):
                    subprocess.run([os.environ.get('XDOTOOL', 'xdotool'), 'mousemove',
                        '--window', str(browser.get_surface().get_xid()),
                        str(round(dx + bounds.get_x() + video.get_width() * fraction)),
                        str(round(dy + bounds.get_y() + video.get_height() / 2))], check=True)
                point(.1)
                until(lambda: video.frame is not None)
                shown = set()
                for step in range(40):
                    point(.1 + .8 * step / 39)
                    settle(30)
                    shown.add(video.displayed_step)
                assert len(shown - {None}) >= 3, shown
                until(lambda: video.displayed_step == scrub_step(video.fraction))
                settle(900)  # Remain over video beyond the normal tooltip delay.
                assert video.active and not video.get_has_tooltip()
                assert not browser.flow.get_selected_children()
                subprocess.run([os.environ.get('XDOTOOL', 'xdotool'), 'mousemove', '0', '0'], check=True)
                until(lambda: not video.active and video.frame is None)
                print(f'PASS: physical grid skimming displayed {len(shown - {None})} positions during motion; leave restored poster')
            browser._set_view('list')
            settle(500)  # Include asynchronously populated metadata cells.
            assert all(not widget.get_has_tooltip() for widget in walk(browser.children_by_path[path]))
            browser._set_view('columns')
            for column in browser.columns.columns:
                for widget in walk(column.flow):
                    assert not widget.get_has_tooltip(), type(widget)
            print('PASS: video, filename, list cells and column rows have no hover tooltips')
        finally:
            browser.destroy()
            settle(100)
