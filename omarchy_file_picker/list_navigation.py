"""Route spatial file arrows to GTK's native cursor and selection engine."""
from gi.repository import Gdk, Gtk


def focus_file(owner, child):
    """Restore both GTK's row focus and its private cursor without changing selection."""
    flow = child.get_parent()
    if owner.view_mode == 'columns':
        column = next(column for column in owner.columns.columns if column.flow is flow)
        owner.columns.activate(column, record=False)
    selected = flow.get_selected_children()
    flow.handler_block(owner.selection_changed_handler)
    try:
        owner.set_focus(None)
        child.child_focus(Gtk.DirectionType.TAB_FORWARD)
        flow.unselect_all()
        for row in selected:
            flow.select_child(row)
    finally:
        flow.handler_unblock(owner.selection_changed_handler)


def _reveal_row(owner):
    row = owner.flow.get_focus_child()
    if row is not None:
        valid, bounds = row.compute_bounds(owner.file_scroller)
        if valid:
            adjustment = owner.file_scroller.get_vadjustment()
            top = adjustment.get_value() + bounds.get_y()
            adjustment.clamp_page(top, top + bounds.get_height())


def navigate_files(owner, key, state):
    vertical = key in (Gdk.KEY_Up, Gdk.KEY_Down)
    if not vertical and not (owner.view_mode == 'grid' and key in (Gdk.KEY_Left, Gdk.KEY_Right)):
        return False
    if state & (Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK):
        return False
    focus = owner.get_focus()
    if isinstance(focus, (Gtk.Editable, Gtk.TextView)):
        return False
    # Menus, sidebar and editable controls retain their native keys. Returning
    # from a view/sort button must not spend the first arrow just entering files.
    ancestor = focus
    while ancestor is not None:
        if isinstance(ancestor, Gtk.Popover):
            return False
        ancestor = ancestor.get_parent()
    view_button = getattr(owner, owner.view_mode + '_button')
    sort_focus = focus is owner.sort_button or (focus and focus.is_ancestor(owner.sort_button))
    if focus is not None and focus is not view_button and not sort_focus and focus is not owner.flow \
            and not focus.is_ancestor(owner.browser_stack):
        return False
    step = 1 if key in (Gdk.KEY_Down, Gdk.KEY_Right) else -1
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
    # Stop at the visible edge instead of sending focus into toolbar controls.
    edge = owner.flow.get_first_child() if step < 0 else owner.flow.get_last_child()
    if row is edge or (vertical and row.get_allocation().y == edge.get_allocation().y):
        return True
    movement = Gtk.MovementStep.DISPLAY_LINES if vertical else Gtk.MovementStep.VISUAL_POSITIONS
    owner.flow.emit('move-cursor', movement, step, shift, control)
    _reveal_row(owner)
    return True
