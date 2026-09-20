"""Explorer tabs with independent navigation and shared session transfers."""
from dataclasses import dataclass, field
from pathlib import Path
import uuid

from gi.repository import Gdk, GLib, Gtk, Pango
from .tab_strip import AnimatedTabStrip


@dataclass(eq=False)
class Tab:
    path: Path
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: dict = field(default_factory=dict)


class BrowserTabs(Gtk.Box):
    def __init__(self, owner):
        super().__init__(spacing=0)
        self.owner = owner
        self.items = []
        self.current = None
        self.closed = []
        self.generation = 0
        self.hover_tab = None
        self.hover_timer = 0
        self.reveal_tick = 0
        self.add_css_class('browser-tabs')
        self.set_visible(owner.request.explorer)
        self.scroll = Gtk.ScrolledWindow(hexpand=True)
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.scroll.set_min_content_width(1)
        self.strip = AnimatedTabStrip()
        self.scroll.set_child(self.strip)
        self.scroll.get_child().set_scroll_to_focus(False)
        self.append(self.scroll)
        self.add_button = Gtk.Button.new_from_icon_name('list-add-symbolic')
        self.add_button.add_css_class('tab-new')
        self.add_button.set_valign(Gtk.Align.CENTER)
        self.add_button.set_tooltip_text('New Tab (Ctrl+T)')
        self.add_button.connect('clicked', lambda *_: self.new())
        self.append(self.add_button)
        self.connect('unrealize', self._stop_motion)

    def _stop_motion(self, *_):
        self.drag_hover(None)
        self.strip.finish()
        if self.reveal_tick:
            self.remove_tick_callback(self.reveal_tick)
            self.reveal_tick = 0

    def initialize(self):
        if self.owner.request.explorer:
            self.current = self._add(self.owner.current_dir)
            self.capture()
            self.update()
        for widget, callback in ((self.owner.browser_stack, self._middle_file),
                                 (self.owner.sidebar_scroll, self._middle_sidebar)):
            gesture = Gtk.GestureClick(button=Gdk.BUTTON_MIDDLE)
            gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            gesture.connect('pressed', callback)
            widget.add_controller(gesture)

    def _add(self, path):
        tab = Tab(path)
        tab.widget = Gtk.Box(spacing=2, valign=Gtk.Align.CENTER, hexpand=True)
        tab.widget.add_css_class('browser-tab')
        tab.button = Gtk.Button(hexpand=True)
        tab.button.add_css_class('tab-label')
        tab.label = Gtk.Label(ellipsize=Pango.EllipsizeMode.MIDDLE, width_chars=6, max_width_chars=20)
        tab.button.set_child(tab.label)
        tab.button.connect('clicked', lambda *_: self.select(tab))
        close = Gtk.Button.new_from_icon_name('window-close-symbolic')
        close.add_css_class('tab-close')
        close.set_valign(Gtk.Align.CENTER)
        close.set_tooltip_text('Close Tab (Ctrl+W)')
        close.connect('clicked', lambda *_: self.close(tab))
        tab.widget.append(close)
        tab.widget.append(tab.button)
        middle = Gtk.GestureClick(button=Gdk.BUTTON_MIDDLE)
        middle.connect('pressed', lambda gesture, *_: self._middle_close(gesture, tab))
        tab.widget.add_controller(middle)
        reorder = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        def prepare(*_):
            self.strip.finish()
            return Gdk.ContentProvider.new_for_value(tab.id)
        reorder.connect('prepare', prepare)
        tab.button.add_controller(reorder)
        target = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
        target.connect('drop', lambda _t, value, x, _y: self.reorder(value, tab, x))
        tab.widget.add_controller(target)
        self.owner.drag_copy._install_target(tab.widget, lambda _x, _y, _paths:
            (None, None, None) if tab.state.get('special_mode') else (tab.path, tab.widget, None))
        self.items.append(tab)
        self.strip.append(tab.widget)
        return tab

    def capture(self):
        if self.current is None:
            return
        owner = self.owner
        self.current.path = owner.current_dir
        self.current.state = dict(
            special_mode=owner.special_mode, history=list(owner.history), history_index=owner.history_index,
            query=owner.search.get_text(), view=owner.view_mode, hidden=owner.show_hidden,
            search_scope=owner.search_scope,
            creative=owner.creative_filter, filter=owner.filter_combo.get_active(),
            selected=owner._selected_paths(), scroll=owner.file_scroller.get_vadjustment().get_value(),
            columns=[(c.path, [r._picker_path for r in c.flow.get_selected_children()],
                      c.scroller.get_vadjustment().get_value()) for c in owner.columns.columns],
            horizontal=owner.columns.get_hadjustment().get_value(),
            trash=owner.trash_page.capture() if owner.special_mode == 'trash' else {},
        )

    def update(self):
        if self.current is None:
            return
        self.current.path = self.owner.current_dir
        self.current.state['special_mode'] = self.owner.special_mode
        for tab in self.items:
            mode = tab.state.get('special_mode')
            name = mode.title() if mode else tab.path.name or '/'
            tab.label.set_text(name)
            tab.button.set_tooltip_text(name if mode else str(tab.path))
            (tab.widget.add_css_class if tab is self.current else tab.widget.remove_css_class)('active')

    def new(self, path=None, *, background=False, special_mode=None):
        if not self.owner.request.explorer:
            return None
        self.capture()
        if path is None and self.owner.special_mode == 'trash' and special_mode is None:
            special_mode = 'trash'
        tab = self._add(Path(path) if path is not None else self.owner.current_dir)
        tab.state = dict(view=self.owner.view_mode, special_mode=special_mode,
                         history=[(special_mode, tab.path) if special_mode else tab.path], history_index=0)
        if not background:
            self.select(tab)
        self.update()
        return tab

    def select(self, tab):
        if tab not in self.items or tab is self.current:
            return
        owner = self.owner
        self.capture()
        owner._cancel_computer_search()
        owner.drag_selection.cancel()
        owner.columns.cancel_pending()
        owner.quicklook.close()
        owner._close_context_menu()
        owner._mount_open_generation = getattr(owner, '_mount_open_generation', 0) + 1
        owner.set_focus(None)
        self.current = tab
        self.generation += 1
        state = tab.state
        owner._restoring_tab = True
        try:
            owner.current_dir = tab.path
            owner.special_mode = state.get('special_mode')
            owner._trash_restore_state = state.get('trash', {})
            owner.history = list(state.get('history', [tab.path]))
            owner.history_index = state.get('history_index', len(owner.history) - 1)
            owner.show_hidden = state.get('hidden', False)
            owner.creative_filter = state.get('creative', ('all', 0, ''))
            owner._set_search_scope(state.get('search_scope', 'folder'))
            owner.search.set_text(state.get('query', ''))
            owner._last_search = owner.search.get_text()
            owner.filter_combo.set_active(state.get('filter', 0))
            owner.path_stack.set_visible_child_name('crumbs')
            owner._set_view(state.get('view', 'grid'), persist=False)
            owner.columns.reset()
            owner.columns.restore_state = state.get('columns')
        finally:
            owner._restoring_tab = False
        owner._load()
        owner._search_restore_selection = state.get('selected', [])
        generation = self.generation
        frames = 0
        def restore(_widget, _clock):
            nonlocal frames
            if generation != self.generation:
                return False
            if owner.special_mode == 'trash':
                return False
            frames += 1
            # GTK allocates rows and adjustment ranges on the next frame.
            owner.columns.busy = True
            try:
                owner.set_focus(owner.flow)
                owner.flow.handler_block(owner.selection_changed_handler)
                owner.flow.unselect_all()
                for path in state.get('selected', []):
                    child = owner.children_by_path.get(path)
                    if child:
                        owner.flow.select_child(child)
                owner.flow.handler_unblock(owner.selection_changed_handler)
                if owner.view_mode == 'columns':
                    owner.columns.cancel_reveal()
                    owner.columns.get_hadjustment().set_value(state.get('horizontal', 0))
                    positions = {p: y for p, _selected, y in state.get('columns', [])}
                    for column in owner.columns.columns:
                        column.scroller.get_vadjustment().set_value(positions.get(column.path, 0))
                else:
                    owner.file_scroller.get_vadjustment().set_value(state.get('scroll', 0))
                owner._on_selection_changed(owner.flow)
            finally:
                owner.columns.busy = False
            return frames < 2
        owner.browser_stack.add_tick_callback(restore)
        self.update()
        self._reveal(tab)

    def _reveal(self, tab):
        if self.reveal_tick:
            self.remove_tick_callback(self.reveal_tick)
        frames = 0
        def reveal(*_):
            nonlocal frames
            frames += 1
            # New pills receive their bounds after the first frame's layout.
            if frames < 2:
                return True
            if tab is self.current and tab in self.items:
                valid, bounds = tab.widget.get_parent().compute_bounds(self.strip)
                if valid:
                    adjustment = self.scroll.get_hadjustment()
                    left, right = bounds.get_x(), bounds.get_x() + bounds.get_width()
                    if left < adjustment.get_value():
                        adjustment.set_value(left)
                    elif right > adjustment.get_value() + adjustment.get_page_size():
                        adjustment.set_value(right - adjustment.get_page_size())
                if self.strip.tick_id:
                    return True
            self.reveal_tick = 0
            return False
        self.reveal_tick = self.add_tick_callback(reveal)

    def close(self, tab=None):
        tab = tab or self.current
        if tab not in self.items:
            return
        if len(self.items) == 1:
            self.owner._finish(cancelled=True)
            return
        self.capture()
        self.closed.append((tab.path, dict(tab.state)))
        self.closed = self.closed[-20:]
        if tab is self.current:
            index = self.items.index(tab)
            self.select(self.items[index - 1] if index else self.items[1])
        self.items.remove(tab)
        self.strip.remove(tab.widget)
        self.drag_hover(None)
        self._reveal(self.current)

    def reopen(self):
        if self.closed:
            path, state = self.closed.pop()
            tab = self._add(path)
            tab.state = state
            self.select(tab)

    def shortcut(self, key, state):
        if not self.items:
            return False
        control, shift = state & Gdk.ModifierType.CONTROL_MASK, state & Gdk.ModifierType.SHIFT_MASK
        if control and key in (Gdk.KEY_t, Gdk.KEY_T):
            self.reopen() if shift else self.new()
        elif control and key in (Gdk.KEY_w, Gdk.KEY_W):
            self.close()
        elif control and key in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab, Gdk.KEY_Page_Up, Gdk.KEY_Page_Down):
            step = -1 if shift or key in (Gdk.KEY_ISO_Left_Tab, Gdk.KEY_Page_Up) else 1
            self.select(self.items[(self.items.index(self.current) + step) % len(self.items)])
        elif state & Gdk.ModifierType.ALT_MASK and Gdk.KEY_1 <= key <= Gdk.KEY_9:
            index = len(self.items) - 1 if key == Gdk.KEY_9 else key - Gdk.KEY_1
            if index < len(self.items):
                self.select(self.items[index])
        else:
            return False
        return True

    def reorder(self, tab_id, target, x):
        source = next((t for t in self.items if t.id == tab_id), None)
        if source is None or source is target:
            return False
        self.items.remove(source)
        index = self.items.index(target) + (x > target.widget.get_width() / 2)
        self.items.insert(index, source)
        self.strip.reorder_child_after(source.widget, self.items[index - 1].widget if index else None)
        return True

    def drag_hover(self, surface):
        tab = next((t for t in self.items if t.widget is surface), None)
        if tab is self.hover_tab:
            return
        if self.hover_timer:
            GLib.source_remove(self.hover_timer)
            self.hover_timer = 0
        self.hover_tab = tab
        if tab and tab is not self.current:
            def switch():
                self.hover_timer = 0
                if tab in self.items:
                    self.select(tab)
                return False
            self.hover_timer = GLib.timeout_add(600, switch)

    def _middle_close(self, gesture, tab):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.close(tab)

    def _middle_file(self, gesture, _n, x, y):
        child, _column, valid = self.owner.drag_copy._hit(x, y)
        if self.items and valid and child and child._picker_is_dir:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.new(child._picker_path, background=True)

    def _middle_sidebar(self, gesture, _n, x, y):
        button = self.owner._sidebar_target(self.owner.sidebar_scroll.pick(x, y, Gtk.PickFlags.DEFAULT))
        if self.items and getattr(button, '_sidebar_key', None) == 'trash':
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.new(background=True, special_mode='trash')
            return
        path = getattr(button, '_picker_path', None)
        if self.items and path:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.new(path, background=True)
