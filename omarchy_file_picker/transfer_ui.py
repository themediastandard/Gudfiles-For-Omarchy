"""Compact native transfer window; filesystem work stays in transfers.py."""
from __future__ import annotations

import time
from itertools import groupby

from gi.repository import GLib, Gtk, Pango

from .model import format_size
from .transfers import BUSY, TERMINAL, TransferQueue

KEEP_OPEN_SECONDS = 5 * 60


def text_label(text='', css=None):
    label = Gtk.Label(label=text, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
    label.set_hexpand(True)
    label.set_max_width_chars(1)
    if css:
        label.add_css_class(css)
    return label


def button(text, callback, css='flat'):
    control = Gtk.Button(label=text)
    control.add_css_class(css)
    control.connect('clicked', lambda *_: callback())
    return control


class TransferRow(Gtk.Box):
    def __init__(self, owner, job):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.owner, self.job = owner, job
        self.add_css_class('transfer-row')
        heading = Gtk.Box(spacing=10)
        icon = Gtk.Image.new_from_icon_name('folder-download-symbolic' if not job.cut else 'go-jump-symbolic')
        icon.set_pixel_size(22)
        icon.add_css_class('transfer-icon')
        heading.append(icon)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        count = len(job.sources)
        name = job.sources[0].name if count == 1 else f'{count} items'
        self.title = text_label(('Move ' if job.cut else 'Copy ') + name, 'transfer-title')
        titles.append(self.title)
        destination = text_label('To ' + str(job.destination), 'transfer-subtitle')
        destination.set_tooltip_text(str(job.destination))
        titles.append(destination)
        heading.append(titles)
        self.status = Gtk.Label()
        self.status.add_css_class('transfer-status')
        heading.append(self.status)
        self.append(heading)
        self.progress = Gtk.ProgressBar()
        self.append(self.progress)
        self.detail = text_label('', 'transfer-subtitle')
        self.append(self.detail)
        self.error = text_label('', 'error')
        self.error.set_ellipsize(Pango.EllipsizeMode.END)
        self.error.set_wrap(True)
        self.error.set_lines(3)
        self.error.set_selectable(True)
        self.append(self.error)
        controls = Gtk.Box(spacing=6)
        self.stats = text_label('', 'transfer-subtitle')
        controls.append(self.stats)
        self.restart = button('Restart unfinished', self._restart)
        self.restart.set_tooltip_text('Discard this batch’s partial copies and copy unfinished sources from the beginning. Completed items stay.')
        controls.append(self.restart)
        self.primary = button('Start', self._primary, 'transfer-action')
        controls.append(self.primary)
        self.cancel = button('Cancel', lambda: owner.transfer_queue.cancel(job))
        controls.append(self.cancel)
        self.append(controls)
        self.update()

    def _primary(self):
        self.owner.transfer_auto_close = False
        if self.job.state == 'running':
            self.owner.transfer_queue.pause(self.job)
        else:
            self.owner.transfer_queue.start(self.job)
        self.owner._poll_transfers()

    def _restart(self):
        self.owner.transfer_auto_close = False
        self.owner.transfer_queue.restart(self.job)
        self.owner._poll_transfers()

    def update(self):
        job, queue = self.job, self.owner.transfer_queue
        state = job.state
        self.status.set_text({'queued': 'QUEUED', 'waiting': 'WAITING', 'running': 'TRANSFERRING',
                              'pausing': 'PAUSING', 'paused': 'PAUSED', 'failed': 'NEEDS ATTENTION',
                              'cancelling': 'CANCELLING', 'cancelled': 'CANCELLED', 'completed': 'COMPLETE'}[state])
        for name in ('failed', 'completed', 'running'):
            getattr(self.status, 'add_css_class' if state == name else 'remove_css_class')(name)
        fraction = job.done_bytes / job.total_bytes if job.total_bytes else 0
        if state == 'completed':
            fraction = 1
        self.progress.set_fraction(min(1, max(0, fraction)))
        self.progress.set_visible(state not in {'queued', 'cancelled'})
        if state in {'queued', 'waiting'}:
            detail = ('Not started · contents scanned when started' if state == 'queued' else
                      job.phase if job.phase != 'Waiting for its turn' else
                      'Waiting · one transfer at a time' if queue.mode == 'queue' else 'Waiting · up to 3 at a time')
        elif state == 'pausing':
            detail = 'Pausing after the current filesystem operation…'
        elif state == 'cancelling':
            detail = 'Stopping and removing owned partial copies…' if job in queue.active_jobs else job.phase
        elif state == 'failed':
            detail = f'{len(job.completed)} item(s) complete · ' + ('queue held' if queue.held else 'transfer stopped')
        else:
            detail = job.phase + (f' · {job.current_name}' if state == 'running' and job.current_name else '')
        self.detail.set_text(detail)
        self.error.set_text(job.error)
        self.error.set_tooltip_text(job.error or None)
        self.error.set_visible(bool(job.error))
        if job.total_bytes:
            stats = f'{format_size(min(job.done_bytes, job.total_bytes))} / {format_size(job.total_bytes)}'
            elapsed = time.monotonic() - job.started if job.started else 0
            if state == 'running' and job.phase == 'Copying' and elapsed > .8 and job.written_bytes:
                rate = job.written_bytes / elapsed
                stats += f' · {format_size(int(rate))}/s'
        else:
            stats = f'{len(job.completed)} complete' if job.completed else ''
        self.stats.set_text(stats)
        self.primary.set_label('Pause' if state == 'running' else
                               ('Resume' if job.stage_name and state in {'paused', 'failed'} else
                                'Continue' if state == 'paused' else 'Retry' if state == 'failed' else 'Start'))
        self.primary.set_visible(state in {'queued', 'waiting', 'running', 'paused', 'failed'} and
                                 (state != 'waiting' or queue.held) and not job.restart_required)
        self.primary.set_sensitive(state == 'running' or job not in queue.active_jobs)
        self.primary.set_tooltip_text('Retained bytes are compared with the unchanged source before continuing.'
                                     if job.stage_name else None)
        self.restart.set_visible(state in {'failed', 'paused'} and bool(job.items or job.stage_name))
        self.restart.set_sensitive(job not in queue.active_jobs)
        self.cancel.set_visible(state not in TERMINAL)
        self.cancel.set_sensitive(state != 'cancelling')
        if self.owner.transfer_cancel_close:
            self.primary.set_sensitive(False)
            self.restart.set_sensitive(False)
            self.cancel.set_sensitive(False)


class TransferUI:
    def _init_transfers(self):
        self.transfer_queue = TransferQueue()
        self.transfer_window = None
        self.transfer_rows = {}
        self.transfer_callbacks = {}
        self.transfer_seen_states = {}
        self.transfer_changed_dirs = {}
        self.transfer_closing = None
        self.transfer_cancel_close = False
        self.transfer_cleanup_blocked = False
        self.transfer_timer = 0
        self.transfer_auto_close = False
        self.transfer_auto_jobs = set()

    def _build_transfer_button(self):
        self.transfer_queue.set_mode(self.file_preferences.get('transfer_mode', 'queue'))
        self.transfer_button = Gtk.Button()
        self.transfer_button.set_valign(Gtk.Align.CENTER)
        icon = Gtk.Overlay()
        icon.set_child(Gtk.Image.new_from_icon_name('folder-download-symbolic'))
        self.transfer_count = Gtk.Label(halign=Gtk.Align.END, valign=Gtk.Align.START,
                                        visible=False, can_target=False)
        self.transfer_count.add_css_class('header-transfer-badge')
        icon.add_overlay(self.transfer_count)
        icon.set_measure_overlay(self.transfer_count, False)
        self.transfer_button.set_child(icon)
        self.transfer_button.add_css_class('header-utility')
        self.transfer_button.update_property([Gtk.AccessibleProperty.LABEL], ['Transfers'])
        self.transfer_button.set_tooltip_text('Transfers · Ctrl+Shift+V adds clipboard files to the queue')
        self.transfer_button.connect('clicked', lambda *_: self._show_transfers())
        self.transfer_timer = GLib.timeout_add(120, self._poll_transfers)
        self.connect('unrealize', self._dispose_transfers)
        return self.transfer_button

    def _show_transfers(self, *, automatic_job=None):
        visible = self.transfer_window is not None and self.transfer_window.get_visible()
        if automatic_job is None:
            # Explicitly opening Transfers always leaves the panel in the
            # user's hands, including when an automatic panel is already open.
            self.transfer_auto_close = False
            self.transfer_auto_jobs.clear()
        elif not visible:
            # A tiny copy may finish before GTK handles this request. Avoid
            # flashing an already-completed panel; history stays in Transfers.
            with self.transfer_queue.lock:
                quick_done = (automatic_job.state in TERMINAL and
                              automatic_job not in self.transfer_queue.active_jobs and
                              automatic_job.elapsed_seconds < KEEP_OPEN_SECONDS)
            if quick_done:
                self._poll_transfers()
                return self.transfer_window
            self.transfer_auto_close = True
            self.transfer_auto_jobs = {automatic_job}
        elif self.transfer_auto_close:
            self.transfer_auto_jobs.add(automatic_job)
        if self.transfer_window is None:
            window = Gtk.Window(title='Transfers', transient_for=self, application=self.get_application())
            window.add_css_class('transfer-window')
            window.set_default_size(660, 540)
            window.set_size_request(560, 370)
            window.set_hide_on_close(True)
            header = Gtk.HeaderBar()
            header.set_title_widget(Gtk.Label(label='Transfers'))
            modes = Gtk.Box(spacing=2)
            self.transfer_mode_buttons = {}
            for mode, title, hint in (
                    ('queue', 'Queue', 'Run transfers one at a time'),
                    ('all', 'All', 'Run independent transfers together, up to 3 at a time')):
                control = Gtk.ToggleButton(label=title)
                control.set_tooltip_text(hint)
                if self.transfer_mode_buttons:
                    control.set_group(self.transfer_mode_buttons['queue'])
                self.transfer_mode_buttons[mode] = control
                control.connect('toggled', lambda button, value=mode: self._set_transfer_mode(value)
                                if button.get_active() and value != self.transfer_queue.mode else None)
                modes.append(control)
            header.pack_start(modes)
            window.set_titlebar(header)
            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            window.set_child(root)
            toolbar = Gtk.Box(spacing=8)
            toolbar.add_css_class('transfer-toolbar')
            self.transfer_summary = text_label('Your queue is empty', 'transfer-title')
            toolbar.append(self.transfer_summary)
            self.transfer_start = button('Start queue', lambda: self.transfer_queue.start(), 'transfer-action')
            toolbar.append(self.transfer_start)
            self.transfer_pause = button('Pause', self._pause_transfers)
            toolbar.append(self.transfer_pause)
            root.append(toolbar)
            scroll = Gtk.ScrolledWindow(vexpand=True)
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.transfer_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            for edge in ('top', 'bottom', 'start', 'end'):
                getattr(self.transfer_list, 'set_margin_' + edge)(14)
            scroll.set_child(self.transfer_list)
            root.append(scroll)
            self.transfer_empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, vexpand=True, valign=Gtk.Align.CENTER)
            empty_icon = Gtk.Image.new_from_icon_name('folder-download-symbolic')
            empty_icon.set_pixel_size(40)
            empty_icon.add_css_class('muted')
            self.transfer_empty.append(empty_icon)
            self.transfer_empty.append(Gtk.Label(label='Move at your own pace', css_classes=['transfer-title']))
            self.transfer_empty.append(Gtk.Label(label='Copy or cut files, then add them to the queue\nfrom their destination with Ctrl+Shift+V.', justify=Gtk.Justification.CENTER))
            self.transfer_list.append(self.transfer_empty)
            self.transfer_close_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            self.transfer_close_box.add_css_class('transfer-close-box')
            self.transfer_close_label = Gtk.Label(xalign=0, wrap=True)
            self.transfer_close_box.append(self.transfer_close_label)
            close_controls = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            self.transfer_keep = button('Keep Files open', self._keep_transfers)
            close_controls.append(self.transfer_keep)
            self.transfer_close_confirm = button('Cancel unfinished & close', self._cancel_transfers_and_close, 'transfer-action')
            close_controls.append(self.transfer_close_confirm)
            self.transfer_leave = button('Leave partials & close', self._leave_partials_and_close)
            self.transfer_leave.set_tooltip_text('Close this session without deleting its hidden .omarchy-transfer-* folders. Sources and completed outputs stay.')
            close_controls.append(self.transfer_leave)
            self.transfer_close_box.append(close_controls)
            root.append(self.transfer_close_box)
            footer = Gtk.Box(spacing=12)
            footer.add_css_class('transfer-footer')
            note = text_label('Queue stays in this Files session. Closing this panel keeps transfers running.', 'transfer-subtitle')
            note.set_wrap(True)
            note.set_ellipsize(Pango.EllipsizeMode.NONE)
            note.set_lines(2)
            self.transfer_note = note
            footer.append(note)
            footer.append(button('Clear finished', self._clear_transfers))
            root.append(footer)
            self.transfer_window = window
            # A copy can finish while this window is being built. Realize its
            # surface even if the first poll hides it before presentation:
            # GTK's Wayland application teardown expects a valid surface.
            window.realize()
        self._poll_transfers()
        if not self._can_auto_hide_transfers():
            self.transfer_window.present()
        return self.transfer_window

    def _can_auto_hide_transfers(self):
        return (self.transfer_auto_close and self.transfer_closing is None and
                not self.transfer_queue.unfinished)

    def _update_transfer_visibility(self):
        if self.transfer_auto_close:
            with self.transfer_queue.lock:
                now = time.monotonic()
                keep_open = any(
                    job.state in {'paused', 'failed'} or
                    job.elapsed_seconds + (now - job.active_since if job.active_since else 0) >= KEEP_OPEN_SECONDS
                    for job in self.transfer_auto_jobs)
            if keep_open:
                self.transfer_auto_close = False
        self.transfer_note.set_text(
            'Closes when quick transfers finish. Transfers lasting 5 minutes stay open.'
            if self.transfer_auto_close else
            'Queue stays in this Files session. Closing this panel keeps transfers running.')
        if self._can_auto_hide_transfers():
            self.transfer_window.set_visible(False)

    def _clear_transfers(self):
        self.transfer_queue.clear_finished()
        self._poll_transfers()

    def _pause_transfers(self):
        self.transfer_auto_close = False
        self.transfer_queue.pause()
        self._poll_transfers()

    def _set_transfer_mode(self, mode):
        if self.transfer_cancel_close:
            return
        self.transfer_auto_close = False
        self.transfer_queue.set_mode(mode)
        self._set_file_preference('transfer_mode', mode, reload=False)
        self._poll_transfers()

    def _poll_transfers(self):
        queue = self.transfer_queue
        with queue.lock:
            jobs = list(queue.jobs)
            active_at_snapshot = set(queue.active_jobs)
            states = {job.id: ('running' if job in active_at_snapshot and job.state not in BUSY else job.state)
                      for job in jobs}
            completed_events = queue.completed_events()
        # Preserve actual commit order even when individual Start controls run
        # jobs in a different order from the visible list. No GTK on workers.
        for job, events in groupby(completed_events, key=lambda event: event[0]):
            mapping = {source: target for _, source, target in events}
            changed = self.transfer_changed_dirs.setdefault(job.id, set())
            changed.update(target.parent for target in mapping.values())
            if job.cut:
                changed.update(source.parent for source in mapping)
            if job.cut:
                callback = getattr(self, '_creative_paths_renamed', None)
                if callback:
                    callback(mapping)
                clipboard = self.transfer_callbacks.get(job.id)
                if clipboard:
                    clipboard(dict(job.completed))
        for job in jobs:
            previous = self.transfer_seen_states.get(job.id)
            state = states[job.id]
            if previous != state and state in TERMINAL | {'failed', 'paused'}:
                # A browsing user may have navigated away: don't select outputs
                # from a different directory or steal their current selection.
                changed = self.transfer_changed_dirs.pop(job.id, set())
                if (getattr(self, 'view_mode', None) == 'columns' and
                        any(column.path in changed for column in self.columns.columns)):
                    self.columns.refresh_paths(changed)
                elif self.current_dir in changed:
                    self._refresh_files()
                if state in TERMINAL:
                    self.transfer_callbacks.pop(job.id, None)
            self.transfer_seen_states[job.id] = state
        count = sum(job.state not in TERMINAL for job in jobs)
        if hasattr(self, 'transfer_count'):
            self.transfer_count.set_text(str(count) if count < 100 else '99+')
            self.transfer_count.set_visible(bool(count))
            self.transfer_button.update_property([Gtk.AccessibleProperty.LABEL],
                [f'Transfers, {count} unfinished' if count else 'Transfers'])
            getattr(self.transfer_button, 'add_css_class' if count else 'remove_css_class')('active')
        if self.transfer_window:
            self.transfer_empty.set_visible(not jobs)
            for job_id in list(self.transfer_rows):
                if not any(job.id == job_id for job in jobs):
                    self.transfer_list.remove(self.transfer_rows.pop(job_id))
                    self.transfer_callbacks.pop(job_id, None)
                    self.transfer_seen_states.pop(job_id, None)
                    self.transfer_changed_dirs.pop(job_id, None)
            for job in jobs:
                if job.id not in self.transfer_rows:
                    row = TransferRow(self, job)
                    self.transfer_rows[job.id] = row
                    self.transfer_list.append(row)
                self.transfer_rows[job.id].update()
            active = tuple(queue.active_jobs)
            if queue.held:
                summary = f'Scheduling paused · {len(active)} active' if active else 'Scheduling paused'
            elif queue.mode == 'queue' and len(active) > 1:
                summary = f'{len(active)} finishing · then one at a time'
            elif active:
                summary = f'{len(active)} running · up to 3 at once' if queue.mode == 'all' else 'One at a time'
            else:
                summary = f'{count} ready or waiting' if count else 'All finished' if jobs else 'Your queue is empty'
            self.transfer_summary.set_text(summary)
            self.transfer_summary.set_tooltip_text(summary)
            for mode, control in self.transfer_mode_buttons.items():
                control.set_active(mode == queue.mode)
                control.set_sensitive(not self.transfer_cancel_close)
                control.remove_css_class('flat' if mode == queue.mode else 'transfer-action')
                control.add_css_class('transfer-action' if mode == queue.mode else 'flat')
            self.transfer_start.set_label('Start queue' if queue.mode == 'queue' else 'Start all')
            self.transfer_start.set_tooltip_text('Start queued and waiting transfers. Paused or failed transfers keep their own controls.')
            self.transfer_start.set_sensitive(any(job.state == 'queued' or (queue.held and job.state == 'waiting')
                                                  for job in jobs) and not self.transfer_cancel_close)
            self.transfer_pause.set_label('Pause all' if queue.mode == 'all' or len(active) > 1 else 'Pause')
            self.transfer_pause.set_visible(bool(active))
            self.transfer_pause.set_sensitive(any(job.state == 'running' for job in active))
            self.transfer_close_box.set_visible(self.transfer_closing is not None)
            self.transfer_close_label.set_text(
                'Stopping transfers before closing. Waiting for the current filesystem operation and cleanup…'
                if self.transfer_cancel_close else
                'Cleanup could not finish. Keep Files open to retry, or leave the hidden partial folders and close this session. Sources and completed items stay.'
                if self.transfer_cleanup_blocked else
                'Files has unfinished transfers. Keep this session open to preserve the queue and saved bytes, or cancel unfinished work to close. Completed items stay.')
            self.transfer_close_confirm.set_sensitive(not self.transfer_cancel_close)
            self.transfer_keep.set_sensitive(not self.transfer_cancel_close)
            self.transfer_leave.set_visible(self.transfer_cleanup_blocked)
            self._update_transfer_visibility()
        if self.transfer_cancel_close and not active_at_snapshot and not queue.active_jobs:
            next_job = next((job for job in jobs if job.state not in TERMINAL), None)
            if next_job is not None:
                if next_job.state == 'failed' and self.transfer_seen_states.get('cleanup:' + next_job.id):
                    # A disconnected or externally changed partial cannot be
                    # silently abandoned. Keep the window and explain the error.
                    self.transfer_cancel_close = False
                    self.transfer_cleanup_blocked = True
                else:
                    self.transfer_seen_states['cleanup:' + next_job.id] = True
                    queue.cancel(next_job)
            else:
                callback = self.transfer_closing
                self.transfer_closing = None
                self.transfer_cancel_close = False
                if callback:
                    GLib.idle_add(lambda: callback() or False)
        return True

    def _guard_transfer_close(self, callback):
        # A last commit may have finished between GTK ticks. Apply its move
        # annotations/clipboard receipt before permitting the application to quit.
        self._poll_transfers()
        if not self.transfer_queue.unfinished:
            return False
        self.transfer_closing = callback
        self.transfer_queue.pause()
        self._show_transfers()
        return True

    def _keep_transfers(self):
        self.transfer_closing = None
        self.transfer_cancel_close = False
        self.transfer_cleanup_blocked = False
        self.transfer_seen_states = {k: v for k, v in self.transfer_seen_states.items() if not k.startswith('cleanup:')}
        self._poll_transfers()

    def _cancel_transfers_and_close(self):
        self.transfer_cleanup_blocked = False
        self.transfer_seen_states = {k: v for k, v in self.transfer_seen_states.items() if not k.startswith('cleanup:')}
        self.transfer_cancel_close = True
        self.transfer_queue.pause()
        for active in tuple(self.transfer_queue.active_jobs):
            self.transfer_seen_states['cleanup:' + active.id] = True
            self.transfer_queue.cancel(active)
        self._poll_transfers()

    def _leave_partials_and_close(self):
        if not self.transfer_cleanup_blocked or self.transfer_queue.active_jobs:
            return
        self.transfer_queue.held = True
        self.transfer_queue.pending.clear()
        self.transfer_queue.pending_cleanup.clear()
        self.transfer_queue.operations.clear()
        for job in self.transfer_queue.jobs:
            if job.state not in TERMINAL:
                job.state = 'cancelled'
        callback = self.transfer_closing
        self.transfer_closing = None
        self.transfer_cancel_close = False
        if callback:
            GLib.idle_add(lambda: callback() or False)

    def _dispose_transfers(self, *_):
        if self.transfer_timer:
            GLib.source_remove(self.transfer_timer)
            self.transfer_timer = 0
        if self.transfer_window:
            self.transfer_window.destroy()
            self.transfer_window = None
        # Normal application close is guarded above. Direct widget destruction
        # (e.g. a host teardown) still stops the worker at its next checkpoint.
        self.transfer_queue.pause()
