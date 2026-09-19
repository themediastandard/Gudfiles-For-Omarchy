"""The desktop Trash, including mounted volumes, through GIO."""
from dataclasses import dataclass
from pathlib import Path

from gi.repository import Gio


ATTRIBUTES = 'standard::name,standard::display-name,standard::type,trash::orig-path,trash::deletion-date'


@dataclass(frozen=True)
class TrashItem:
    uri: str
    name: str
    original: str
    deleted: str
    directory: bool = False


def list_trash(cancellable=None):
    root = Gio.File.new_for_uri('trash:///')
    result = []
    listing = root.enumerate_children(ATTRIBUTES, Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancellable)
    try:
        while info := listing.next_file(cancellable):
            result.append(TrashItem(
                listing.get_child(info).get_uri(), info.get_display_name(),
                info.get_attribute_byte_string('trash::orig-path') or '',
                info.get_attribute_string('trash::deletion-date') or '',
                info.get_file_type() == Gio.FileType.DIRECTORY,
            ))
    finally:
        listing.close(None)
    return sorted(result, key=lambda item: (item.deleted, item.name.casefold()), reverse=True)


def restore_item(item, cancellable=None):
    source = Gio.File.new_for_uri(item.uri)
    if not source.has_parent(Gio.File.new_for_uri('trash:///')):
        raise ValueError('This item is no longer in Trash.')
    info = source.query_info(ATTRIBUTES, Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancellable)
    original = info.get_attribute_byte_string('trash::orig-path') or ''
    deleted = info.get_attribute_string('trash::deletion-date') or ''
    if (original, deleted) != (item.original, item.deleted):
        raise ValueError('This item changed. Refresh Trash and select it again.')
    if not original or not Path(original).is_absolute():
        raise ValueError('The original location is unavailable.')
    # GIO refuses existing targets, including directories and symlinks. Never
    # overwrite a replacement file or guess another restoration destination.
    target = Gio.File.new_for_path(original)
    if not source.move(target, Gio.FileCopyFlags.NOFOLLOW_SYMLINKS, cancellable, None, None):
        raise OSError('The item could not be restored.')
    return Path(original)
