"""Route list arrows to GTK's native row cursor and selection engine."""
from gi.repository import Gdk, Gtk


def _reveal_row(owner):
    row = owner.flow.get_focus_child()
    if row is not None:
        valid, bounds = row.compute_bounds(owner.file_scroller)
        if valid:
            adjustment = owner.file_scroller.get_vadjustment()
            top = adjustment.get_value() + bounds.get_y()
            adjustment.clamp_page(top, top + bounds.get_height())


def navigate_list(owner, key, state):
    if owner.view_mode != 'list' or key not in (Gdk.KEY_Up, Gdk.KEY_Down):
        return False
    if state & (Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK):
        return False
    focus = owner.get_focus()
    if isinstance(focus, (Gtk.Editable, Gtk.TextView)):
        return False
    # Sidebar, filename/search fields and other controls retain their own keys.
    # The view button is included so changing views does not swallow a first arrow.
    if focus is not None and focus is not owner.list_button and focus is not owner.flow \
            and not focus.is_ancestor(owner.browser_stack):
        return False
    step = 1 if key == Gdk.KEY_Down else -1
    shift = bool(state & Gdk.ModifierType.SHIFT_MASK) and owner.request.multiple
    control = bool(state & Gdk.ModifierType.CONTROL_MASK)
    row = focus
    while row is not None and row is not owner.flow and not isinstance(row, Gtk.FlowBoxChild):
        row = row.get_parent()
    if not isinstance(row, Gtk.FlowBoxChild) or row.get_parent() is not owner.flow:
        selected = owner.flow.get_selected_children()
        # Enter through FlowBox's focus implementation, which initializes its
        # private cursor after a rebuild. Focusing a child directly can leave
        # the old cursor invalid even though GTK reports the new child focused.
        owner.flow.child_focus(Gtk.DirectionType.TAB_FORWARD if step > 0 else Gtk.DirectionType.TAB_BACKWARD)
        row = owner.flow.get_focus_child()
        if row is None or not selected:
            _reveal_row(owner)
            return True
    # Keep arrows at the first/last row in the list, not on neighboring controls.
    if (step < 0 and row is owner.flow.get_first_child()) or \
            (step > 0 and row is owner.flow.get_last_child()):
        return True
    owner.flow.emit('move-cursor', Gtk.MovementStep.DISPLAY_LINES, step, shift, control)
    _reveal_row(owner)
    return True
