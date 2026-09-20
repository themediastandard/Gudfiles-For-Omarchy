from pathlib import Path
import tempfile
import time
import traceback
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gdk
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.model import PickerRequest

temp = tempfile.TemporaryDirectory()
root = Path(temp.name)
source, dest = root/'source', root/'destination'
source.mkdir(); dest.mkdir()
(source/'a.txt').write_text('original')
(source/'b.txt').write_text('collision')
request = PickerRequest(current_folder=source, multiple=True)
app = PickerApplication(request, None)
app.register(None)
w = PickerWindow(app, request, None)
w.bookmarks_path = root/'bookmarks'
w.preferences_path = root/'preferences.json'
errors=[]
w._show_error = lambda *args: errors.append(args)
w.present()
loop = GLib.MainLoop()
passed = False

def labels(widget):
    result=[]
    if isinstance(widget, Gtk.Label): result.append(widget.get_text())
    child=widget.get_first_child()
    while child:
        result += labels(child)
        child=child.get_next_sibling()
    return result

def guarded(fn):
    def call():
        try: return fn()
        except Exception:
            traceback.print_exc(); loop.quit(); return False
    return call

def dialog(title):
    return next(x for x in Gtk.Window.get_toplevels() if x.get_title()==title)

def entry_in(widget):
    if isinstance(widget, Gtk.Entry): return widget
    child=widget.get_first_child()
    while child:
        found=entry_in(child)
        if found:return found
        child=child.get_next_sibling()

class Gesture:
    def set_state(self,state): assert state == Gtk.EventSequenceState.CLAIMED

def settle_rename():
    deadline = time.monotonic() + 3
    while w.file_job_active and time.monotonic() < deadline:
        GLib.MainContext.default().iteration(True)
    assert not w.file_job_active, 'rename did not finish'

def start():
    # Hit-test unoccupied space below the file tiles, not just the FlowBox.
    w._on_context_pressed(Gesture(),1,w.browser_stack.get_width()-30,w.browser_stack.get_height()-30)
    texts=labels(w.context_popover)
    assert 'New Folder…' in texts and 'Rename…' not in texts and 'Connect to NAS…' not in texts, texts
    assert 'New Text File' in texts and 'New Text File…' not in texts
    w._close_context_menu()
    for name in ('untitled.txt', 'untitled (1).txt'):
        w._show_create_dialog('text')
        assert (source/name).read_bytes() == b''
        assert w._selected_paths() == [source/name]
        assert not any(x.get_visible() and x is not w for x in Gtk.Window.get_toplevels())
    w._show_create_dialog('folder')
    d=dialog('New Folder'); entry_in(d).set_text('created'); d.response(Gtk.ResponseType.ACCEPT)
    assert (source/'created').is_dir()
    w._show_rename_dialog(source/'a.txt')
    d=dialog('Rename'); entry_in(d).set_text('b.txt'); d.response(Gtk.ResponseType.ACCEPT)
    settle_rename()
    assert (source/'a.txt').read_text()=='original'
    assert (source/'b.txt').read_text()=='collision'
    entry_in(d).set_text('renamed.txt'); d.response(Gtk.ResponseType.ACCEPT)
    settle_rename()
    assert (source/'renamed.txt').read_text()=='original'
    w._toggle_bookmark(source)
    assert w._bookmarks()==[(source,'source')]
    w._toggle_bookmark(source)
    assert not w._bookmarks()
    w._set_file_preference('sort_key','size')
    w._set_file_preference('show_size',False)
    w._set_view('list')
    w._set_view('grid')
    w._copy_files([source/'renamed.txt'])
    w.navigate(dest)
    # Entire empty-state surface also exposes the background menu.
    w._on_context_pressed(Gesture(),1,50,50)
    assert 'New Folder…' in labels(w.context_popover)
    w._close_context_menu()
    assert w._can_paste()
    w._paste_files()
    GLib.timeout_add(50, guarded(copied))
    return False

def copied():
    if dest/'renamed.txt' not in w.children_by_path or w.transfer_queue.active:return True
    assert not errors, errors
    assert (source/'renamed.txt').exists()
    w._copy_files([source/'b.txt'],cut=True)
    w._paste_files()
    GLib.timeout_add(50,guarded(moved))
    return False

def moved():
    if dest/'b.txt' not in w.children_by_path or w.transfer_queue.active:return True
    assert not errors, errors
    assert not (source/'b.txt').exists()
    w.flow.select_child(w.children_by_path[dest/'b.txt'])
    w._show_context_menu(24,24,dest/'b.txt')
    texts=labels(w.context_popover)
    assert all(t in texts for t in ['Rename…','Cut','Copy','Copy Location','Move to Trash…']), texts
    assert 'Connect to NAS…' not in texts
    assert w.context_popover.get_parent() is w.browser_stack
    w._refresh_files()
    w._show_properties([dest/'b.txt'])
    d=dialog('Properties'); assert 'Size' in labels(d) and '9 B' in labels(d),labels(d); d.response(Gtk.ResponseType.CLOSE)
    w.flow.grab_focus()
    w._on_key_pressed(None, Gdk.KEY_F2, 0, Gdk.ModifierType(0))
    dialog('Rename').response(Gtk.ResponseType.CANCEL)
    removal_shortcuts=[]
    confirm_remove=w._confirm_remove
    w._confirm_remove=lambda paths, permanent=False: removal_shortcuts.append((list(paths), permanent))
    assert w._on_key_pressed(None, Gdk.KEY_BackSpace, 0, Gdk.ModifierType(0)) == Gdk.EVENT_PROPAGATE
    assert w._on_key_pressed(None, Gdk.KEY_BackSpace, 0, Gdk.ModifierType.SUPER_MASK) == Gdk.EVENT_STOP
    assert w._on_key_pressed(None, Gdk.KEY_Delete, 0, Gdk.ModifierType.SUPER_MASK) == Gdk.EVENT_STOP
    assert w._on_key_pressed(None, Gdk.KEY_BackSpace, 0,
        Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.SHIFT_MASK) == Gdk.EVENT_STOP
    assert [permanent for _paths, permanent in removal_shortcuts] == [False, False, True]
    assert all(paths == [dest/'b.txt'] for paths, _permanent in removal_shortcuts)
    w._confirm_remove=confirm_remove
    w.flow.select_all()
    w._show_context_menu(24,24,dest/'b.txt')
    assert len(w._selected_paths()) == 2
    w._close_context_menu()
    w._confirm_remove([dest/'b.txt'], permanent=True)
    GLib.timeout_add(150,guarded(cancel_delete))
    return False

def cancel_delete():
    global passed
    def cancel_button(widget):
        if isinstance(widget,Gtk.Button) and widget.get_label()=='Cancel':return widget
        child=widget.get_first_child()
        while child:
            found=cancel_button(child)
            if found:return found
            child=child.get_next_sibling()
    alerts=[x for x in Gtk.Window.get_toplevels() if x is not w and x.get_visible()]
    alert=next(x for x in alerts if 'Delete permanently?' in labels(x))
    cancel_button(alert).emit('clicked')
    assert (dest/'b.txt').read_text()=='collision'
    assert not w.file_job_active
    passed=True
    print('PASS: background/empty hit tests; create; rename collision/F2; bookmarks; view/sort; clipboard copy/cut/paste; single/multi context; properties; delete shortcuts and confirmation cancellation')
    loop.quit()
    return False

GLib.timeout_add(350,guarded(start))
GLib.timeout_add_seconds(12,lambda: loop.quit() or False)
loop.run()
w.destroy()
temp.cleanup()
assert passed, errors
