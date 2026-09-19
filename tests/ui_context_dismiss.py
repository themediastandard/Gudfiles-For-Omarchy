"""Real outside-click dismissal before/after cascading-menu transitions.
Run on an isolated Xvfb display with POINTER_QA_ISOLATED=1.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkX11', '4.0')
from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import DEFAULT_COLORS, load_colors

assert os.environ.get('POINTER_QA_ISOLATED') == '1'
errors = []
def exception(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = exception


def settle(ms=200):
    loop = GLib.MainLoop()
    GLib.timeout_add(max(1, ms), lambda: loop.quit() or False)
    loop.run()
    assert not errors


def send(*args, delay=60):
    subprocess.run([os.environ.get('XDOTOOL', 'xdotool'), *map(str, args)], check=True)
    settle(delay)


def move(widget, delay=200):
    native = widget.get_native()
    valid, bounds = widget.compute_bounds(native)
    assert valid
    dx, dy = native.get_surface_transform()
    send('mousemove', '--window', native.get_surface().get_xid(),
         round(bounds.get_x()+bounds.get_width()/2+dx),
         round(bounds.get_y()+bounds.get_height()/2+dy), delay=delay)


def children(widget):
    child = widget.get_first_child()
    while child:
        yield child
        child = child.get_next_sibling()


with tempfile.TemporaryDirectory(prefix='gudfiles-dismiss-') as temp:
    root = Path(temp)
    fixture = root/'Example.txt'
    fixture.write_text('fixture')
    request = PickerRequest(current_folder=root, explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    active = load_colors()
    dark = {**active, 'mode':'dark', 'background':'#17191f', 'foreground':'#d7dce4',
            'light_foreground':'#b3bdcf', 'dark_foreground':'#9ba5b5'}
    for theme, colors in [('active',active), ('light',DEFAULT_COLORS), ('dark',dark)]:
        with patch.object(Path, 'home', return_value=root/theme), \
             patch.object(Gio.VolumeMonitor,'get_mounts',return_value=[]), \
             patch('omarchy_file_picker.picker.load_colors',return_value=colors):
            window=PickerWindow(app,request,None)
            window.set_default_size(1000,700)
            window.present()
            settle()
            send('windowfocus',window.get_surface().get_xid())
            try:
                for view in ('grid','list','columns'):
                    window._set_view(view)
                    settle()
                    for mode in ('root','child','switch','hover-close','escape','toggle'):
                        for pause in (1,160,450):
                            move(window.search_button,delay=20)
                            window._show_context_menu(40,80,fixture)
                            settle()
                            popover=window.context_popover
                            rows=list(children(popover.get_child()))
                            menus=[w for w in rows if isinstance(w,Gtk.MenuButton)]
                            plain=next(w for w in rows if isinstance(w,Gtk.Button))
                            if mode != 'root':
                                move(menus[-2])
                                assert menus[-2].get_popover().get_mapped()
                            if mode=='switch':
                                move(menus[-1])
                            elif mode=='hover-close':
                                move(plain,delay=450)
                            elif mode=='escape':
                                send('key','Escape',delay=300)
                            elif mode=='toggle':
                                send('click',1,delay=300)
                            # A click outside the whole cascade must dismiss it
                            # even after a hover timer closed the child already.
                            move(window.search_button,delay=pause)
                            send('click',1,delay=350)
                            assert not popover.get_mapped(), (theme,view,mode,pause,'root stranded')
                            assert window.context_popover is None, (theme,view,mode,pause,'stale owner')
                            assert not any(menu.get_popover().get_mapped() for menu in menus)
                            assert not window.search_popover.get_mapped(), 'Dismissal clicked through to Search'
                            settle(50)
                        print('PASS:',theme,view,mode,flush=True)
                    # Click outside the owner window after the child has closed.
                    move(window.search_button, delay=20)
                    window._show_context_menu(40, 80, fixture)
                    settle()
                    popover = window.context_popover
                    menus = [w for w in children(popover.get_child()) if isinstance(w, Gtk.MenuButton)]
                    move(menus[-2])
                    send('mousemove', 1500, 1000, delay=450)
                    send('click', 1, delay=350)
                    assert not popover.get_mapped(), (theme, view, 'desktop click')
                    assert window.context_popover is None

            finally:
                window.destroy()
                settle()
    print('PASS: outside-click dismissal across all views, themes, child states and click timing')
