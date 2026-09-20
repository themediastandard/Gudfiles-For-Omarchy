"""Event-driven refresh of the visible directories without disturbing navigation."""
from gi.repository import Gio, GLib, Gtk

from .list_navigation import focus_file
from .hover_scrub import HoverScrub


class FolderWatch:
    """One GIO monitor per visible directory; no recursive or periodic rescans.

    Navigation calls suspend before loading and sync afterwards. Column trail
    changes call sync as well. Old callbacks and layout restores are scoped to
    the current tab/view, and refresh waits for transient interactions to finish.
    """

    DELAY_MS = 400

    def __init__(self, owner):
        self.owner = owner
        self.monitors = {}
        self.pending = set()
        self.timer = 0
        self.retry_timer = 0
        self.missing = set()
        self.probes = {}
        self.generation = 0
        self.scope = None
        self.closed = False
        owner.connect('unrealize', self.close)
        self.sync()

    def _paths(self):
        owner = self.owner
        if owner.special_mode is not None or owner._computer_search_active():
            return ()
        if owner.view_mode == 'columns':
            return tuple(column.path for column in owner.columns.columns)
        return (owner.current_dir,)

    def suspend(self):
        self.generation += 1
        self.pending.clear()
        for probe in self.probes.values():
            probe['cancel'].cancel()
            if probe['deadline']:
                GLib.source_remove(probe['deadline'])
        self.probes.clear()
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0

    def sync(self):
        if self.closed:
            return
        paths = self._paths()
        self.missing.intersection_update(paths)
        if not self.missing and self.retry_timer:
            GLib.source_remove(self.retry_timer)
            self.retry_timer = 0
        owner = self.owner
        scope = (getattr(owner.tabs, 'generation', 0), owner.view_mode, paths)
        if scope != self.scope:
            self.suspend()
            self.scope = scope
        for path, monitor in list(self.monitors.items()):
            if path not in paths or monitor.is_cancelled():
                monitor.cancel()
                del self.monitors[path]
        for path in paths:
            if path in self.monitors or path in self.missing:
                continue
            try:
                monitor = Gio.File.new_for_path(str(path)).monitor_directory(
                    Gio.FileMonitorFlags.WATCH_MOVES, None)
            except GLib.Error:
                # Some remote backends cannot monitor. Manual refresh remains
                # available; navigation/reconnect retries monitor creation.
                continue
            monitor.set_rate_limit(self.DELAY_MS)
            monitor.connect('changed', self._changed, path)
            self.monitors[path] = monitor

    def _changed(self, monitor, file, other_file, event, path):
        if self.closed or self.monitors.get(path) is not monitor:
            return
        if event == Gio.FileMonitorEvent.PRE_UNMOUNT:
            return
        if (event == Gio.FileMonitorEvent.UNMOUNTED or
                (file.get_path() == str(path) and event in (
                    Gio.FileMonitorEvent.DELETED, Gio.FileMonitorEvent.MOVED_OUT))):
            # Linux inotify stops watching a deleted inode. Recreating the same
            # pathname does not revive that watch. Probe only that absent root
            # until it returns, then establish a fresh monitor and refresh once.
            monitor.cancel()
            del self.monitors[path]
            self.missing.add(path)
            if not self.retry_timer:
                self.retry_timer = GLib.timeout_add(1500, self._retry_missing)
        # Hidden staging/config writes must not continually rebuild an ordinary
        # directory. A hidden-to-visible rename still matters via other_file.
        names = [item.get_basename() for item in (file, other_file) if item]
        if (file.get_path() != str(path) and not self.owner.show_hidden and names and
                all(name and name.startswith('.') for name in names)):
            return
        self.pending.add(path)
        if not self.timer:
            self.timer = GLib.timeout_add(self.DELAY_MS, self._flush)

    def _retry_missing(self):
        if self.closed:
            self.retry_timer = 0
            return False
        self.missing.intersection_update(self._paths())
        for path in self.missing:
            if path in self.probes:
                continue
            probe = dict(cancel=Gio.Cancellable(), generation=self.generation, deadline=0)
            self.probes[path] = probe
            probe['deadline'] = GLib.timeout_add(4000, self._timeout_probe, path, probe)
            Gio.File.new_for_path(str(path)).query_info_async(
                'standard::type', Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT,
                probe['cancel'], self._probe_ready, (path, probe))
        if not self.missing:
            self.retry_timer = 0
        return bool(self.missing)

    def _timeout_probe(self, path, probe):
        probe['deadline'] = 0
        if self.probes.get(path) is probe:
            # Keep its slot until completion acknowledges cancellation. Even a
            # backend that ignores cancellation cannot accumulate new queries.
            probe['cancel'].cancel()
        return False

    def _probe_ready(self, file, result, data):
        path, probe = data
        try:
            info = file.query_info_finish(result)
        except GLib.Error:
            info = None
        if self.probes.get(path) is not probe:
            return
        del self.probes[path]
        if probe['deadline']:
            GLib.source_remove(probe['deadline'])
        if (self.closed or probe['generation'] != self.generation or
                probe['cancel'].is_cancelled() or path not in self.missing or
                info is None or info.get_file_type() != Gio.FileType.DIRECTORY):
            return
        self.missing.remove(path)
        self.sync()
        self.pending.add(path)
        if not self.timer:
            self.timer = GLib.timeout_add(self.DELAY_MS, self._flush)

    def _busy(self):
        owner = self.owner
        return (getattr(owner, '_restoring_tab', False) or owner.file_job_active or
                owner.drag_selection.active or owner.drag_copy.active or
                owner.context_popover is not None or owner.quicklook.get_visible() or
                HoverScrub.active_for(owner) or
                bool(owner.columns.pending) or owner.columns.busy or
                bool(owner.list_details.dragged_column) or
                owner.list_details.popover.get_visible() or
                any(getattr(owner, name, None) and getattr(owner, name).get_visible()
                    for name in ('sort_popover', 'search_popover')) or
                any(window is not owner and window.get_visible() and window.get_modal()
                    and window.get_transient_for() is owner
                    for window in Gtk.Window.list_toplevels()))

    def _flush(self):
        if self.closed:
            self.timer = 0
            return False
        if self._busy():
            return True
        self.timer = 0
        paths = self.pending.intersection(self._paths())
        self.pending.clear()
        if not paths:
            return False
        owner = self.owner
        owner._refreshing_folder = True
        try:
            if owner.view_mode == 'columns':
                owner.columns.refresh_paths(paths)
            else:
                self._refresh_standard()
        finally:
            owner._refreshing_folder = False
        return False

    def _refresh_standard(self):
        owner = self.owner
        selected = owner._selected_paths()
        focus = owner.get_focus()
        had_focus = focus is owner.flow or bool(focus and focus.is_ancestor(owner.flow))
        row = owner.flow.get_focus_child() if had_focus else None
        focused_path = getattr(row, '_picker_path', None)
        index = row.get_index() if row else 0
        scroll = owner.file_scroller.get_vadjustment().get_value()
        horizontal = owner.file_scroller.get_hadjustment().get_value()
        owner._refresh_files(selected)
        if not owner.current_dir.is_dir():
            owner.empty_title.set_text('Folder unavailable')
            owner.empty_detail.set_text('This folder was removed or its drive is disconnected. '
                                        'Reconnect the drive or choose another folder.')
        generation, flow = self.generation, owner.flow
        after_focus = owner.get_focus()
        frames = 0

        def restore(_widget, _clock):
            nonlocal frames
            if self.closed or generation != self.generation or owner.flow is not flow:
                return False
            frames += 1
            if had_focus and frames == 1 and owner.get_focus() is after_focus:
                child = owner.children_by_path.get(focused_path)
                if child is None and owner.entries:
                    child = owner.children_by_path[owner.entries[min(index, len(owner.entries) - 1)]]
                if child:
                    focus_file(owner, child)
                else:
                    owner.set_focus(flow)
            # Allocation and native focus scrolling can occur one frame later.
            owner.file_scroller.get_vadjustment().set_value(scroll)
            owner.file_scroller.get_hadjustment().set_value(horizontal)
            return frames < 3

        owner.browser_stack.add_tick_callback(restore)

    def close(self, *_):
        self.closed = True
        self.suspend()
        if self.retry_timer:
            GLib.source_remove(self.retry_timer)
            self.retry_timer = 0
        self.missing.clear()
        for monitor in self.monitors.values():
            monitor.cancel()
        self.monitors.clear()
