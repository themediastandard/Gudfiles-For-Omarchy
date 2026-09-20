from __future__ import annotations

import fnmatch
import mimetypes
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class FileFilter:
    name: str
    rules: tuple[tuple[int, str], ...] = ()

    @classmethod
    def from_portal(cls, value: Any) -> "FileFilter":
        name, rules = value
        return cls(str(name), tuple((int(kind), str(pattern)) for kind, pattern in rules))

    def matches(self, path: Path) -> bool:
        if path.is_dir() or not self.rules:
            return True
        mime, _ = mimetypes.guess_type(path.name)
        for kind, pattern in self.rules:
            if kind == 0 and fnmatch.fnmatchcase(path.name, pattern):
                return True
            if kind == 1 and mime:
                if pattern.endswith("/*") and mime.startswith(pattern[:-1]):
                    return True
                if mime == pattern:
                    return True
        return False


@dataclass
class PickerRequest:
    mode: str = "open"
    explorer: bool = False
    title: str = "Open File"
    accept_label: str = "Open"
    current_folder: Path = field(default_factory=Path.home)
    current_name: str = ""
    multiple: bool = False
    directory: bool = False
    filters: list[FileFilter] = field(default_factory=list)
    current_filter: int = 0
    choices: list[dict[str, Any]] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    app_id: str = ""
    external: bool = False
    selected_paths: list[Path] = field(default_factory=list)
    # Destination prompts show surrounding files while accepting folders only.
    show_files_in_directory: bool = False

    @property
    def directories_only(self) -> bool:
        return self.directory and not self.show_files_in_directory

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PickerRequest":
        folder = Path(data.get("current_folder") or Path.home()).expanduser()
        if not folder.is_dir():
            folder = folder.parent if folder.parent.is_dir() else Path.home()
        filters = [FileFilter.from_portal(item) for item in data.get("filters", [])]
        return cls(
            mode=str(data.get("mode", "open")),
            title=str(data.get("title") or "Open File"),
            accept_label=str(data.get("accept_label") or ("Save" if data.get("mode") == "save" else "Open")),
            current_folder=folder,
            current_name=str(data.get("current_name") or ""),
            multiple=bool(data.get("multiple", False)),
            directory=bool(data.get("directory", False)),
            filters=filters,
            current_filter=max(0, int(data.get("current_filter", 0))),
            choices=list(data.get("choices", [])),
            files=[str(item) for item in data.get("files", [])],
            app_id=str(data.get("app_id") or ""),
        )


def decode_portal_path(value: Any, fallback: Path | None = None) -> Path:
    fallback = fallback or Path.home()
    if value is None:
        return fallback
    if isinstance(value, str):
        raw = value
    elif isinstance(value, (bytes, bytearray)):
        raw = bytes(value).rstrip(b"\0").decode(errors="surrogateescape")
    elif isinstance(value, (list, tuple)):
        raw = bytes(value).rstrip(b"\0").decode(errors="surrogateescape")
    else:
        return fallback
    path = Path(raw).expanduser()
    return path if path.exists() else fallback


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def file_type(path: Path) -> str:
    if path.is_dir():
        return "Folder"
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        return path.suffix[1:].upper() + " file" if path.suffix else "File"
    major, subtype = mime.split("/", 1)
    if major == "image":
        return f"{subtype.upper()} image"
    if major == "video":
        return f"{subtype.upper()} video"
    if major == "audio":
        return f"{subtype.upper()} audio"
    if major == "text":
        return "Text document"
    return subtype.replace("-", " ").title()


def recent_files(limit: int = 80) -> list[Path]:
    source = Path.home() / ".local/share/recently-used.xbel"
    try:
        root = ET.parse(source).getroot()
    except (OSError, ET.ParseError):
        return []
    items: list[tuple[str, Path]] = []
    for bookmark in root.iter():
        if not bookmark.tag.endswith("bookmark"):
            continue
        href = bookmark.attrib.get("href", "")
        parsed = urlparse(href)
        if parsed.scheme != "file":
            continue
        path = Path(unquote(parsed.path))
        if path.exists():
            items.append((bookmark.attrib.get("modified", ""), path))
    items.sort(key=lambda item: item[0], reverse=True)
    seen: set[Path] = set()
    result: list[Path] = []
    for _, path in items:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(path)
        if len(result) >= limit:
            break
    return result


def list_directory(
    directory: Path,
    *,
    show_hidden: bool = False,
    active_filter: FileFilter | None = None,
    query: str = "",
    directories_only: bool = False,
) -> list[Path]:
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    needle = query.casefold().strip()
    result = []
    for path in entries:
        if not show_hidden and path.name.startswith("."):
            continue
        if needle and needle not in path.name.casefold():
            continue
        if directories_only and not path.is_dir():
            continue
        if active_filter and not active_filter.matches(path):
            continue
        result.append(path)
    return sorted(result, key=lambda item: (not item.is_dir(), item.name.casefold()))


def safe_uri(path: Path) -> str:
    return path.expanduser().resolve().as_uri()


def suggested_folder(options: dict[str, Any]) -> Path:
    current_file = options.get("current_file")
    if current_file is not None:
        path = decode_portal_path(current_file)
        return path.parent if path.is_file() else path
    return decode_portal_path(options.get("current_folder"), Path.home())


def portal_request(method: str, app_id: str, title: str, options: dict[str, Any]) -> PickerRequest:
    mode = {"OpenFile": "open", "SaveFile": "save", "SaveFiles": "save_files"}[method]
    filters = options.get("filters", [])
    current_filter = options.get("current_filter")
    current_filter_index = 0
    if current_filter:
        try:
            current_filter_index = list(filters).index(current_filter)
        except ValueError:
            if not filters:
                filters = [current_filter]
    choices = []
    for choice_id, label, values, selected in options.get("choices", []):
        choices.append({
            "id": choice_id,
            "label": label,
            "values": list(values),
            "selected": selected,
        })
    current_name = options.get("current_name", "")
    if not current_name and options.get("current_file"):
        current_name = decode_portal_path(options["current_file"]).name
    return PickerRequest(
        mode=mode,
        title=title or ("Save File" if mode == "save" else "Open File"),
        accept_label=str(options.get("accept_label") or ("Save" if mode.startswith("save") else "Open")).replace("_", ""),
        current_folder=suggested_folder(options),
        current_name=str(current_name),
        multiple=bool(options.get("multiple", False)),
        directory=bool(options.get("directory", False) or mode == "save_files"),
        filters=[FileFilter.from_portal(item) for item in filters],
        current_filter=current_filter_index,
        choices=choices,
        files=[decode_portal_path(item).name for item in options.get("files", [])],
        app_id=app_id,
    )
