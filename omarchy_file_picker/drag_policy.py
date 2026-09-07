"""Filesystem policy for Finder-style drops. Call on a worker, never during GTK hit testing."""
from pathlib import Path


def plan_drop(paths, destination, *, force_copy=False):
    """Return (sources, cut) batches; a same-folder ordinary drop is a no-op.

    lstat identifies the volume holding a symlink itself. Resolving the parent
    also handles different sidebar/bookmark aliases for the same directory.
    The transfer engine revalidates identities and publishes without overwrite.
    """
    destination = Path(destination).resolve(strict=True)
    if not destination.is_dir():
        raise ValueError('Drop files onto a folder.')
    device = destination.stat().st_dev
    sources = list(dict.fromkeys(Path(p).parent.resolve(strict=True) / Path(p).name for p in paths))
    if any(p == destination or p in destination.parents for p in sources):
        raise ValueError('A folder cannot be transferred into itself.')
    if any(parent in sources for p in sources for parent in p.parents):
        raise ValueError('Drag a folder and its contents separately.')
    moves, copies = [], []
    for path in sources:
        same_disk = path.lstat().st_dev == device
        if force_copy or not same_disk:
            copies.append(path)
        elif path.parent != destination:
            moves.append(path)
    return [(group, cut) for group, cut in ((moves, True), (copies, False)) if group]
