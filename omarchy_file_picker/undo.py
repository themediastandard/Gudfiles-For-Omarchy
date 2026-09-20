"""Session-only, identity-checked inverse renames. No copies or deletion undo."""
from __future__ import annotations

import os
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .batch_rename import _rename_no_replace

MAX_ENTRIES = 10000


def _identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _snapshot(path):
    """Read links themselves, never their targets; bound retained history size."""
    entries = {}
    pending = [Path('.')]
    while pending:
        relative = pending.pop()
        current = path / relative
        info = current.lstat()
        entries[relative] = _stamp(info)
        if len(entries) > MAX_ENTRIES:
            raise ValueError('This folder is too large for safe Undo.')
        if stat.S_ISDIR(info.st_mode):
            with os.scandir(current) as children:
                for child in children:
                    pending.append(relative / child.name)
                    if len(entries) + len(pending) > MAX_ENTRIES:
                        raise ValueError('This folder is too large for safe Undo.')
    return entries


@dataclass
class UndoItem:
    original: Path
    current: Path
    original_parent: tuple
    current_parent: tuple
    entries: dict


@dataclass
class UndoReceipt:
    label: str
    items: list[UndoItem]


@dataclass
class UndoResult:
    completed: dict[Path, Path] = field(default_factory=dict)
    error: str | None = None


def capture_receipt(mapping, label='Move', expected_identity=None):
    """Called on the operation worker immediately after confirmed publication.

    Failure to establish an exact baseline never turns a successful rename into
    an apparent failure; it simply makes that operation unavailable for Undo.
    """
    items = []
    try:
        for original, current in mapping.items():
            original, current = Path(original).absolute(), Path(current).absolute()
            if original == current:
                continue
            entries = _snapshot(current)
            root = entries[Path('.')]
            expected = (expected_identity.get(original) if isinstance(expected_identity, dict)
                        else expected_identity)
            if expected and (root[0], root[1], stat.S_IFMT(root[2]))[:len(expected)] != tuple(expected):
                return None
            original_parent, current_parent = _identity(original.parent), _identity(current.parent)
            if root[0] != original_parent[0] or original_parent[0] != current_parent[0]:
                return None
            items.append(UndoItem(original, current, original_parent, current_parent, entries))
        return UndoReceipt(label, items) if items else None
    except (OSError, ValueError):
        return None


class UndoHistory:
    def __init__(self, limit=20):
        self._receipts = []
        self._lock = threading.RLock()
        self.limit = limit

    def record(self, receipt):
        if receipt and receipt.items:
            with self._lock:
                self._receipts.append(receipt)
                del self._receipts[:-self.limit]

    def peek(self):
        with self._lock:
            return self._receipts[-1] if self._receipts else None

    @staticmethod
    def _validate(item):
        if (_identity(item.original.parent) != item.original_parent or
                _identity(item.current.parent) != item.current_parent):
            raise ValueError('A containing folder changed. Undo stopped safely.')
        if os.path.lexists(item.original):
            raise FileExistsError(f'“{item.original.name}” already exists. Undo will not overwrite it.')
        if _snapshot(item.current) != item.entries:
            raise ValueError(f'“{item.current.name}” changed since this operation. Undo stopped safely.')

    def undo(self):
        """Run on a worker; retain failures for retry and return only actual inverses."""
        result = UndoResult()
        with self._lock:
            receipt = self.peek()
            if receipt is None:
                return result
            try:
                # Preflight every target first so ordinary collisions cause no
                # partial work. Racing failures still return exact receipts.
                for item in receipt.items:
                    self._validate(item)
                for item in list(reversed(receipt.items)):
                    self._validate(item)
                    _rename_no_replace(item.current, item.original)
                    result.completed[item.current] = item.original
                    receipt.items.remove(item)
                    # Our own inverse changes root ctime. Update only matching
                    # earlier baselines so A→B→C can be undone twice.
                    stamp = _stamp(item.original.lstat())
                    for prior in self._receipts[:-1]:
                        for previous in prior.items:
                            if (previous.current == item.original and
                                    previous.entries[Path('.')][:5] == stamp[:5]):
                                previous.entries[Path('.')] = stamp
            except (OSError, ValueError) as error:
                result.error = str(error)
            if not receipt.items:
                self._receipts.pop()
        return result
