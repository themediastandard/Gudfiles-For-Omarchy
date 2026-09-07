"""Actual pointer DND on an isolated X11 display (Xvfb + xdotool)."""
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import gi
gi.require_version('Gtk','4.0')
gi.require_version('GdkX11','4.0')
from gi.repository import Gtk, Gdk, Gio, GLib, GdkX11
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.theme import load_colors

def settle(ms=150):
    loop=GLib.MainLoop(); GLib.timeout_add(ms, lambda: loop.quit() or False); loop.run()

def until(fn):
    deadline=time.monotonic()+8
    while not fn() and time.monotonic()<deadline: settle(50)
    assert fn(), 'Timed out waiting for real input/transfer'

assert os.environ.get('POINTER_QA_ISOLATED') == '1', 'Run this test on a disposable Xvfb display.'
colors=load_colors()
with tempfile.TemporaryDirectory(prefix='native-drag-') as temp, patch.object(Path,'home',return_value=Path(temp)), patch.object(Gio.VolumeMonitor,'get_mounts',return_value=[]), patch('omarchy_file_picker.picker.load_colors',return_value=colors):
    root=Path(temp); folder=root/'Destination'; folder.mkdir()
    paths=[root/f'{i}-file.txt' for i in range(6)]
    for p in paths: p.write_text('data '+p.name)
    request=PickerRequest(current_folder=root, multiple=True, explorer=True, title='Pointer drag QA')
    app=PickerApplication(request,None); app.register(None)
    window=PickerWindow(app,request,None); window.present(); settle()
    xid=window.get_surface().get_xid()
    xdo=os.environ.get('XDOTOOL', 'xdotool')
    errors=[]; window._show_error=lambda *args: errors.append(args)
    events=[]
    window.drag_copy.source.connect('drag-begin', lambda *_: events.append('begin'))
    window.drag_copy.source.connect('drag-end', lambda *_: events.append('end'))
    def send(*args, delay=60):
        subprocess.run([xdo,*map(str,args)],check=True); settle(delay)
    def move(widget, delay=150):
        valid,bounds=widget.compute_bounds(window); assert valid
        native=window.get_surface_transform()
        x=round(bounds.get_x()+bounds.get_width()/2+native[0])
        y=round(bounds.get_y()+bounds.get_height()/2+native[1])
        send('mousemove','--window',xid,x,y,delay=delay)
    def click(widget, button=1):
        move(widget); send('mousedown',button); send('mouseup',button,delay=120)
    def drag(source,target):
        _, start = source.compute_bounds(window)
        _, end = target.compute_bounds(window)
        dx, dy = window.get_surface_transform()
        ax, ay = start.get_x()+start.get_width()/2+dx, start.get_y()+start.get_height()/2+dy
        bx, by = end.get_x()+end.get_width()/2+dx, end.get_y()+end.get_height()/2+dy
        move(source); send('mousedown',1,delay=40)
        for step in range(1,13):
            send('mousemove','--window',xid,round(ax+(bx-ax)*step/12),round(ay+(by-ay)*step/12),delay=35)
        settle(700)
        send('mouseup',1,delay=250)
    try:
        for mode in ('grid','list','columns'):
            window.navigate(root); window._set_view(mode); settle()
            print('testing',mode,flush=True)
            click(window.children_by_path[paths[0]])
            assert window._selected_paths()==[paths[0]], window._selected_paths()
            print('PASS actual plain click',flush=True)
            send('keydown','Shift_L')
            click(window.children_by_path[paths[2]])
            send('keyup','Shift_L')
            assert set(window._selected_paths())==set(paths[:3]), window._selected_paths()
            send('keydown','Control_L')
            click(window.children_by_path[paths[1]])
            send('keyup','Control_L')
            assert set(window._selected_paths())=={paths[0],paths[2]}, window._selected_paths()
            print('PASS actual Shift range and Ctrl toggle',flush=True)
            old=len(window.transfer_queue.jobs)
            drag(window.children_by_path[paths[0]],window.children_by_path[folder])
            until(lambda: len(window.transfer_queue.jobs)>old and not window.transfer_queue.unfinished)
            assert not paths[0].exists() and not paths[2].exists()
            assert (folder/paths[0].name).exists() and (folder/paths[2].name).exists()
            print('PASS actual grouped move to folder',mode,flush=True)
            for p in (paths[0],paths[2]): (folder/p.name).rename(p)
            window._refresh_files(); settle()
        assert not errors, errors
        window._set_view('grid'); settle()
        click(window.children_by_path[paths[1]])
        send('keydown', 'Alt_L')
        drag(window.children_by_path[paths[1]], window.children_by_path[folder])
        send('keyup', 'Alt_L')
        until(lambda: not window.file_job_active and not window.transfer_queue.unfinished)
        assert paths[1].exists() and (folder / paths[1].name).read_bytes() == paths[1].read_bytes()
        assert not window.transfer_queue.jobs[-1].cut
        print('PASS actual Alt-copy on the same disk', flush=True)
        # A directory double-click remains GTK's native activation.
        move(window.children_by_path[folder])
        send('click', '--repeat', 2, '--delay', 90, 1)
        assert window.current_dir == folder
        window.navigate(root); settle()
        window.flow.unselect_all(); window.flow.select_child(window.children_by_path[paths[0]])
        destination=window.tabs.new(folder, background=True); settle()
        drag(window.children_by_path[paths[0]],destination.button)
        until(lambda: not window.transfer_queue.unfinished and not paths[0].exists())
        assert window.tabs.current is destination
        print('PASS actual drag to tab and hover switch',flush=True)
        original = window.tabs.items[0]
        drag(destination.button, original.button)
        assert window.tabs.items[0] is destination
        print('PASS actual tab reorder', flush=True)
        window.tabs.select(original); settle()
        with tempfile.TemporaryDirectory(prefix='pointer-other-disk-', dir='/dev/shm') as remote:
            remote = Path(remote)
            assert root.stat().st_dev != remote.stat().st_dev
            other = window.tabs.new(remote, background=True); settle()
            drag(window.children_by_path[paths[3]], other.button)
            until(lambda: not window.file_job_active and not window.transfer_queue.unfinished and (remote / paths[3].name).exists())
            assert paths[3].exists() and (remote / paths[3].name).read_bytes() == paths[3].read_bytes()
            assert not window.transfer_queue.jobs[-1].cut
            window.tabs.select(original); settle()
            window.tabs.close(other)
        print('PASS actual cross-filesystem tab drop copies and preserves original', flush=True)
        window.tabs.select(destination); settle()
        if screenshot := os.environ.get('POINTER_QA_SCREENSHOT'):
            shot=Gtk.Snapshot(); Gtk.WidgetPaintable.new(window).snapshot(shot,window.get_width(),window.get_height())
            texture=window.get_renderer().render_texture(shot.to_node(),None)
            assert texture.save_to_png(screenshot)
    finally:
        send('mouseup',1)
        send('keyup','Shift_L','Control_L','Alt_L')
        window.destroy(); settle()
