"""Preview-first batch naming with atomic, no-overwrite Linux renames."""
from __future__ import annotations

import ctypes
import errno
import os
import stat
import string
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class RenameOptions:
    mode: str = 'pattern'
    pattern: str = '{name}_{n}'
    find: str = ''
    replace: str = ''
    start: int = 1
    padding: int = 3


@dataclass(frozen=True)
class RenameItem:
    source: Path
    target: Path
    identity: tuple[int, int]


@dataclass
class RenameResult:
    completed: dict[Path, Path] = field(default_factory=dict)
    error: str | None = None
    cancelled: bool = False


def _identity(path):
    info = path.lstat()
    return info.st_dev, info.st_ino


def _preflight(plan):
    sources = [item.source for item in plan]
    targets = [item.target for item in plan]
    if len(set(sources)) != len(sources):
        raise ValueError('The selection contains the same item twice.')
    if len(set(targets)) != len(targets):
        raise ValueError('Two items would have the same name. Include {n} in your pattern.')
    for item in plan:
        if _identity(item.source) != item.identity:
            raise ValueError(f'{item.source.name} changed since the preview. Review it again.')
        if any(parent in sources for parent in item.source.parents):
            raise ValueError('Rename folders and their contents in separate batches.')
        if item.source != item.target and os.path.lexists(item.target):
            raise FileExistsError(f'“{item.target.name}” already exists. Nothing will be overwritten.')


def plan_rename(paths, options: RenameOptions) -> list[RenameItem]:
    """Preserve selection order/extensions; {date} is modification date, not capture date."""
    if options.mode not in {'pattern', 'replace'}:
        raise ValueError('Choose Pattern or Find & replace.')
    if not 0 <= options.start <= 999999999 or not 1 <= options.padding <= 9:
        raise ValueError('Use a non-negative start and between 1 and 9 digits.')
    if options.mode == 'pattern':
        try:
            fields = list(string.Formatter().parse(options.pattern))
        except ValueError as error:
            raise ValueError('Check the braces in your naming pattern.') from error
        if any(name is not None and (name not in {'name', 'n', 'date'} or spec or conv)
               for _, name, spec, conv in fields):
            raise ValueError('Supported tokens are {name}, {n}, and {date}.')
    elif not options.find:
        raise ValueError('Enter the text to find in the original names.')
    result = []
    for index, path in enumerate(paths):
        path = Path(path).absolute()
        info = path.lstat()
        # lstat intentionally does not follow symlinks; rename only the directory entry.
        extension = '' if stat.S_ISDIR(info.st_mode) else path.suffix
        stem = path.name[:-len(extension)] if extension else path.name
        if options.mode == 'pattern':
            name = options.pattern.format(name=stem, n=str(options.start + index).zfill(options.padding),
                                          date=datetime.fromtimestamp(info.st_mtime).strftime('%Y-%m-%d'))
        else:
            name = stem.replace(options.find, options.replace)
        if not name.strip() or name in {'.', '..'} or '/' in name or '\0' in name:
            raise ValueError('Names cannot be empty or contain a slash.')
        target = path.with_name(name + extension)
        if len(os.fsencode(target.name)) > os.pathconf(path.parent, 'PC_NAME_MAX'):
            raise ValueError(f'The new name for “{path.name}” is too long.')
        result.append(RenameItem(path, target, (info.st_dev, info.st_ino)))
    _preflight(result)
    return result


def _rename_no_replace(source, target):
    # POSIX rename/Path.rename can overwrite a destination created after preflight.
    # Linux renameat2 guarantees that even a racing destination is never replaced.
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, 'renameat2', None)
    if rename is None:
        raise OSError(errno.ENOTSUP, 'This system cannot guarantee a no-overwrite rename.')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def execute_rename(plan, cancelled=None) -> RenameResult:
    """Stop on failure/cancel; return every completed rename for truthful refresh/migration."""
    result = RenameResult()
    try:
        _preflight(plan)
        for item in plan:
            if cancelled is not None and cancelled.is_set():
                result.cancelled = True
                break
            if item.source == item.target:
                continue
            if _identity(item.source) != item.identity:
                raise ValueError(f'“{item.source.name}” changed since the preview. Stopped safely.')
            _rename_no_replace(item.source, item.target)
            result.completed[item.source] = item.target
    except (OSError, ValueError) as error:
        result.error = str(error)
    return result


# Keep GTK out of imports used by backend/unit tests.
def _dialog_class():
    from gi.repository import GLib, Gtk, Pango
    from .dialogs import PickerDialog, entry_field

    class BatchRenameDialog(PickerDialog):
        def __init__(self, owner, paths):
            super().__init__(owner, 'Batch Rename', subtitle=f'{len(paths):,} items selected · File extensions are preserved', width=680)
            self.owner, self.paths = owner, list(paths)
            self.active, self.plan, self.cancelled = False, [], threading.Event()
            self.alive, self.preview_running = True, False
            self.preview_generation, self.preview_timer, self.preview_pending = 0, 0, None
            self.set_default_size(680, 520)
            self.set_resizable(True)
            self.add_css_class('batch-rename-dialog')
            outer = self.body
            self.fields = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            self.fields.add_css_class('rename-fields')
            self.stack = Gtk.Stack()
            self.stack.set_vhomogeneous(False)
            self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            switcher = Gtk.StackSwitcher(stack=self.stack, halign=Gtk.Align.START)
            self.fields.append(switcher)
            pattern_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            self.pattern = Gtk.Entry(text='{name}_{n}', hexpand=True)
            self.pattern.set_placeholder_text('Project_{n}')
            self.pattern.set_tooltip_text('Example: Project_{n} → Project_001.jpg')
            pattern_box.append(entry_field('Naming pattern', self.pattern))
            hint = Gtk.Label(label='{name} Original name    {n} Sequence    {date} Modified date', xalign=0, wrap=True)
            hint.add_css_class('muted')
            pattern_box.append(hint)
            sequence = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            sequence.append(Gtk.Label(label='Start at'))
            self.start = Gtk.SpinButton.new_with_range(0, 999999999, 1)
            self.start.set_value(1)
            self.start.set_width_chars(5)
            sequence.append(self.start)
            sequence.append(Gtk.Label(label='Digits', margin_start=12))
            self.padding = Gtk.SpinButton.new_with_range(1, 9, 1)
            self.padding.set_value(3)
            self.padding.set_width_chars(2)
            sequence.append(self.padding)
            pattern_box.append(sequence)
            replace_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            self.find = Gtk.Entry(placeholder_text='Find in original names', hexpand=True)
            self.replace = Gtk.Entry(placeholder_text='Replace with (leave empty to remove)', hexpand=True)
            replace_box.append(entry_field('Find', self.find))
            replace_box.append(entry_field('Replace with', self.replace))
            note = Gtk.Label(label='Matches exact text, including capitalization. File extensions are excluded.',
                             xalign=0, wrap=True)
            note.add_css_class('muted')
            replace_box.append(note)
            self.stack.add_titled(pattern_box, 'pattern', 'Pattern')
            self.stack.add_titled(replace_box, 'replace', 'Find & replace')
            self.fields.append(self.stack)
            outer.append(self.fields)
            preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, vexpand=True)
            preview.add_css_class('rename-preview')
            heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, homogeneous=True)
            heading.add_css_class('rename-preview-heading')
            heading.append(Gtk.Label(label='CURRENT NAME', xalign=0))
            heading.append(Gtk.Label(label='NEW NAME', xalign=0))
            preview.append(heading)
            self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            scroller = Gtk.ScrolledWindow(vexpand=True)
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_min_content_height(140)
            scroller.set_child(self.rows)
            preview.append(scroller)
            outer.append(preview)
            self.status = Gtk.Label(xalign=0, wrap=True, max_width_chars=65)
            self.status.add_css_class('rename-status')
            outer.append(self.status)
            self.cancel_button = self.add_action('Cancel', Gtk.ResponseType.CANCEL)
            self.apply_button = self.add_action(f'Rename {len(paths)} items', Gtk.ResponseType.ACCEPT,
                                                role='suggested-action', default=True)
            self.connect('response', lambda _d, code: self._apply() if code == Gtk.ResponseType.ACCEPT else self._close())
            for entry in (self.pattern, self.find, self.replace):
                entry.set_activates_default(True)
                entry.connect('changed', lambda *_: self._update())
            for spin in (self.start, self.padding):
                spin.connect('value-changed', lambda *_: self._update())
            self.stack.connect('notify::visible-child-name', lambda *_: self._update())
            self._update()

        def _options(self):
            return RenameOptions(mode=self.stack.get_visible_child_name(), pattern=self.pattern.get_text(),
                                 find=self.find.get_text(), replace=self.replace.get_text(),
                                 start=self.start.get_value_as_int(), padding=self.padding.get_value_as_int())

        def _update(self):
            # One worker maximum, with only the latest request retained. Slow NAS
            # metadata must neither block typing nor build an unbounded job queue.
            self.preview_generation += 1
            self.preview_pending = (self.preview_generation, self._options())
            self.plan = []
            self.apply_button.set_sensitive(False)
            self.status.remove_css_class('error')
            self.status.set_text('Checking names…')
            if self.preview_timer:
                GLib.source_remove(self.preview_timer)
            self.preview_timer = GLib.timeout_add(140, self._start_preview)

        def _start_preview(self):
            self.preview_timer = 0
            if not self.alive or self.preview_running or self.preview_pending is None:
                return False
            generation, options = self.preview_pending
            self.preview_pending = None
            self.preview_running = True
            def worker():
                try:
                    plan, error = plan_rename(self.paths, options), None
                except (ValueError, OSError) as exception:
                    plan, error = [], str(exception)
                GLib.idle_add(self._preview_ready, generation, plan, error)
            threading.Thread(target=worker, daemon=True).start()
            return False

        def _preview_ready(self, generation, plan, error):
            self.preview_running = False
            if not self.alive:
                return False
            if generation != self.preview_generation:
                if not self.preview_timer:
                    self._start_preview()
                return False
            self.plan = plan
            changed = sum(item.source != item.target for item in plan)
            message = error or (f'{changed} of {len(self.paths)} items will be renamed.' if changed
                               else 'No names will change. Edit the pattern to continue.')
            if error:
                self.status.add_css_class('error')
            else:
                self.status.remove_css_class('error')
            self.status.set_text(message)
            self.apply_button.set_label(f'Rename {changed} item' + ('s' if changed != 1 else ''))
            self.apply_button.set_sensitive(changed > 0)
            while child := self.rows.get_first_child():
                self.rows.remove(child)
            # Bound widget creation even for very large selections; the whole plan is validated.
            targets = {item.source: item.target for item in self.plan}
            for path in self.paths[:200]:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, homogeneous=True)
                row.add_css_class('rename-preview-row')
                for value, css in ((path.name, 'rename-before'),
                                   (targets[path.absolute()].name if path.absolute() in targets else '—', 'rename-after')):
                    label = Gtk.Label(label=value, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
                    label.set_width_chars(1)
                    label.add_css_class(css)
                    label.set_tooltip_text(value)
                    row.append(label)
                self.rows.append(row)
            if len(self.paths) > 200:
                self.rows.append(Gtk.Label(label=f'… and {len(self.paths) - 200} more validated items'))
            return False

        def _close(self):
            if self.active:
                self.cancelled.set()
                self.cancel_button.set_sensitive(False)
                self.status.set_text('Stopping after the current item…')
            else:
                self.alive = False
                if self.preview_timer:
                    GLib.source_remove(self.preview_timer)
                    self.preview_timer = 0
                self.owner._dismiss_dialog(self)

        def _apply(self):
            if self.active or self.owner.file_job_active:
                return
            if not self.apply_button.get_sensitive():
                return
            self.active = self.owner.file_job_active = True
            self.fields.set_sensitive(False)
            self.apply_button.set_sensitive(False)
            self.cancel_button.set_label('Stop')
            self.status.set_text('Renaming…')
            plan = list(self.plan)
            def worker():
                result = execute_rename(plan, self.cancelled)
                GLib.idle_add(self._completed, result)
            threading.Thread(target=worker, daemon=True).start()

        def _completed(self, result):
            self.active = self.owner.file_job_active = False
            if result.completed:
                migrate = getattr(self.owner, '_creative_paths_renamed', None)
                if migrate:
                    migrate(result.completed)
                self.owner._refresh_files([result.completed.get(path.absolute(), path) for path in self.paths])
            if result.error or result.cancelled:
                self.status.add_css_class('error') if result.error else None
                self.status.set_text(f'{len(result.completed)} items renamed. ' +
                                     (result.error or 'Stopped. Remaining items were not changed.'))
                self.cancel_button.set_label('Close')
                self.cancel_button.set_sensitive(True)
            else:
                self._close()
            return False

    return BatchRenameDialog


def BatchRenameDialog(owner, paths):
    """Construct the native dialog lazily so backend tools need no GTK initialization."""
    return _dialog_class()(owner, paths)
