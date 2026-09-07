"""Select a launch target after GTK has allocated the browser's rows."""
from .list_navigation import focus_file


def reveal_initial_selection(owner):
    flow = owner.flow
    folder = owner.current_dir
    targets = tuple(owner.request.selected_paths)
    attempts = 0
    last_layout = None
    stable_frames = 0
    focused = False

    children = [owner.children_by_path[path] for path in targets if path in owner.children_by_path]
    if not children:
        return
    if not owner.request.multiple:
        children = children[:1]
    flow.handler_block(owner.selection_changed_handler)
    try:
        flow.unselect_all()
        for child in children:
            flow.select_child(child)
    finally:
        flow.handler_unblock(owner.selection_changed_handler)
    owner._on_selection_changed(flow)

    def reveal(_widget, _clock):
        nonlocal attempts, last_layout, stable_frames, focused
        attempts += 1
        # A startup callback must never override a later navigation or tab switch.
        if owner.flow is not flow or owner.current_dir != folder or any(
                owner.children_by_path.get(child._picker_path) is not child for child in children):
            return False
        if set(owner._selected_paths()) != {child._picker_path for child in children}:
            return False
        first = children[0]
        adjustment = owner.file_scroller.get_vadjustment()
        valid, bounds = first.compute_bounds(flow)
        if not valid or first.get_height() <= 0 or adjustment.get_page_size() <= 0:
            return attempts < 60
        layout = (flow.get_width(), bounds.get_y(), bounds.get_height(),
                  adjustment.get_upper(), adjustment.get_page_size(), owner.is_active())
        stable_frames = stable_frames + 1 if layout == last_layout else 0
        last_layout = layout
        # Compositor sizing and the selection strip both change the initial
        # layout. Wait for consecutive allocated frames, not a fixed timeout.
        if stable_frames < 2:
            return attempts < 60
        if not focused:
            focus_file(owner, first)
            focused = True
            # GTK's focus scroll runs after the cursor movement. Clamp the
            # complete row on the following frame, after that scroll is applied.
            return True
        valid, bounds = first.compute_bounds(owner.file_scroller)
        if valid:
            top = adjustment.get_value() + bounds.get_y()
            adjustment.clamp_page(top, top + bounds.get_height())
        owner.tabs.capture()
        return False

    flow.add_tick_callback(reveal)
