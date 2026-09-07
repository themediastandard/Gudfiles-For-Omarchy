"""Real FFmpeg/GTK hover frame QA, using controller signals, not physical input."""
import os
os.environ.setdefault('GSK_RENDERER', 'gl')
import subprocess
import tempfile
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk
from omarchy_file_picker.hover_scrub import HoverScrub, scrub_step


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
    assert done, 'Timed out waiting for thumbnail state'


def settle(milliseconds=280):
    loop = GLib.MainLoop()
    GLib.timeout_add(milliseconds, lambda: loop.quit() or False)
    loop.run()


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

        # Native motion observes held buttons without claiming click sequences.
        class DraggingPointer:
            def get_current_event_state(self):
                return Gdk.ModifierType.BUTTON1_MASK
        scrub.motion.emit('enter', 5.0, 5.0)
        scrub._motion(DraggingPointer(), 20, 5)
        assert not scrub.active and not scrub.picture.get_visible()
        assert flow.get_selected_children() == [tile]

        # Broken media stays a quiet original poster, never a fake error icon.
        scrub.motion.emit('enter', 5.0, 5.0)
        scrub._complete(scrub._generation, scrub_step(scrub.fraction), None)
        assert not scrub.active and scrub.get_child() is base
        assert not scrub.picture.get_visible() and scrub._timer == 0
        assert path.read_bytes() == before
        print('PASS: delayed hover, real frame scrubbing, latest position, bounded textures, selection/geometry, leave/drag cancellation, quiet failure, unchanged source')
    finally:
        window.destroy()
        settle(100)
