from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from .actions import (
    IMAGE_SIZE_PIXELS,
    ActionError,
    image_convert_command,
    image_resize_command,
    normalize_nas_uri,
    video_convert_command,
)
from .model import PickerRequest, file_type, format_size, list_directory, recent_files, safe_uri
from .theme import build_css, load_colors


IMAGE_TYPES = {".avif", ".bmp", ".gif", ".heic", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
VIDEO_TYPES = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}


def icon_for(path: Path) -> Gio.Icon:
    try:
        info = Gio.File.new_for_path(str(path)).query_info(
            "standard::icon", Gio.FileQueryInfoFlags.NONE, None
        )
        icon = info.get_icon()
        if icon:
            return icon
    except GLib.Error:
        pass
    return Gio.ThemedIcon.new("folder-symbolic" if path.is_dir() else "text-x-generic-symbolic")


def thumbnail_file(path: Path) -> Path | None:
    if path.suffix.casefold() in IMAGE_TYPES:
        return path
    if path.suffix.casefold() not in VIDEO_TYPES:
        return None
    uri = safe_uri(path)
    digest = hashlib.md5(uri.encode(), usedforsecurity=False).hexdigest()
    for size in ("xx-large", "x-large", "large", "normal"):
        candidate = Path.home() / ".cache/thumbnails" / size / f"{digest}.png"
        if candidate.exists():
            return candidate
    cache = Path.home() / ".cache/omarchy-file-picker/thumbnails" / f"{digest}.jpg"
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        return cache
    if not GLib.find_program_in_path("ffmpegthumbnailer"):
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["ffmpegthumbnailer", "-i", str(path), "-o", str(cache), "-s", "360", "-q", "8"],
            check=True,
            timeout=8,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return cache
    except (OSError, subprocess.SubprocessError):
        return None


def picture_for(path: Path, width: int, height: int, *, crop: bool = True) -> Gtk.Widget:
    source = thumbnail_file(path)
    if source:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(source), width, height, True)
            picture = Gtk.Picture.new_for_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
            picture.set_content_fit(Gtk.ContentFit.COVER if crop else Gtk.ContentFit.CONTAIN)
            picture.set_size_request(width, height)
            picture.set_can_shrink(True)
            return picture
        except GLib.Error:
            pass
    image = Gtk.Image.new_from_gicon(icon_for(path))
    image.set_pixel_size(min(64, height - 18))
    image.set_size_request(width, height)
    image.add_css_class("muted")
    return image


def label(text: str, css_class: str | None = None, *, xalign: float = 0.0) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=xalign)
    if css_class:
        widget.add_css_class(css_class)
    return widget


class PickerWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, request: PickerRequest, result_path: Path | None):
        super().__init__(application=app, title=request.title)
        self.request = request
        self.result_path = result_path
        self.current_dir = request.current_folder
        self.special_mode: str | None = None
        self.history = [self.current_dir]
        self.history_index = 0
        self.show_hidden = False
        self.view_mode = "grid"
        self.entries: list[Path] = []
        self.children_by_path: dict[Path, Gtk.FlowBoxChild] = {}
        self.location_buttons: list[Gtk.Button] = []
        self.choice_widgets: dict[str, Gtk.Widget] = {}
        self.active_processes: set[Gio.Subprocess] = set()
        self.context_popover: Gtk.Popover | None = None
        self.volume_monitor = Gio.VolumeMonitor.get()

        self.set_default_size(1200, 800)
        self.set_size_request(820, 560)
        self.add_css_class("picker-root")
        self._install_theme()
        self._build_header()
        self._build_content()
        self.volume_monitor.connect("mount-added", lambda *_args: self._refresh_sidebar())
        self.volume_monitor.connect("mount-removed", lambda *_args: self._refresh_sidebar())
        self._install_shortcuts()
        self._load()
        if os.environ.get("OMARCHY_FILE_PICKER_DEMO_SELECT_FIRST") == "1":
            GLib.idle_add(self._select_first_file)
        automation = os.environ.get("OMARCHY_FILE_PICKER_AUTOMATION")
        if automation == "cancel":
            GLib.timeout_add(150, lambda: self._automation_cancel())
        elif automation == "select-first":
            GLib.timeout_add(150, lambda: self._automation_select_first())
        elif automation == "accept":
            GLib.timeout_add(150, lambda: self._automation_accept())
        elif automation == "context-menu":
            GLib.timeout_add(250, lambda: self._automation_context_menu())

    def _install_theme(self) -> None:
        colors = load_colors()
        provider = Gtk.CssProvider()
        provider.load_from_string(build_css(colors))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-application-prefer-dark-theme", colors.get("mode") == "dark")

    def _build_header(self) -> None:
        header = Gtk.HeaderBar()
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_label = label(self.request.title, "metadata-title", xalign=0.5)
        subtitle_text = "Choose a folder" if self.request.directory else (
            "Choose where to save" if self.request.mode.startswith("save") else "Choose files to open"
        )
        subtitle = label(subtitle_text, "muted", xalign=0.5)
        title_box.append(title_label)
        title_box.append(subtitle)
        header.set_title_widget(title_box)
        self.set_titlebar(header)

    def _build_content(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.set_vexpand(True)
        root.append(body)

        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.sidebar.add_css_class("sidebar")
        self.sidebar.set_size_request(205, -1)
        body.append(self.sidebar)
        self._build_sidebar()

        browser = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        browser.set_hexpand(True)
        browser.set_vexpand(True)
        body.append(browser)

        self.toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.toolbar.add_css_class("toolbar")
        browser.append(self.toolbar)
        self._build_toolbar()

        self.browser_stack = Gtk.Stack()
        self.browser_stack.set_vexpand(True)
        self.browser_stack.set_hexpand(True)
        browser.append(self.browser_stack)

        self.flow = Gtk.FlowBox()
        self.flow.set_activate_on_single_click(False)
        self.flow.set_selection_mode(
            Gtk.SelectionMode.MULTIPLE if self.request.multiple else Gtk.SelectionMode.SINGLE
        )
        self.flow.set_row_spacing(12)
        self.flow.set_column_spacing(12)
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_min_children_per_line(1)
        self.flow.set_max_children_per_line(6)
        self.flow.set_homogeneous(False)
        self.flow.connect("child-activated", self._on_child_activated)
        self.flow.connect("selected-children-changed", self._on_selection_changed)
        context_click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        context_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        context_click.connect("pressed", self._on_context_pressed)
        self.flow.add_controller(context_click)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.flow)
        self.browser_stack.add_named(scroller, "files")

        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        empty.set_halign(Gtk.Align.CENTER)
        empty.set_valign(Gtk.Align.CENTER)
        empty.append(Gtk.Image.new_from_icon_name("folder-open-symbolic"))
        empty.append(label("Nothing here", "empty-title", xalign=0.5))
        self.empty_detail = label("Try another folder or search.", "muted", xalign=0.5)
        empty.append(self.empty_detail)
        self.browser_stack.add_named(empty, "empty")

        self.metadata = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.metadata.add_css_class("metadata-strip")
        browser.append(self.metadata)

        self.footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.footer.add_css_class("footer")
        root.append(self.footer)
        self._build_footer()

    def _sidebar_button(self, text: str, icon_name: str, callback) -> Gtk.Button:
        button = Gtk.Button()
        button.add_css_class("location-button")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(18)
        row.append(icon)
        item_label = label(text)
        item_label.set_hexpand(True)
        row.append(item_label)
        button.set_child(row)
        button.connect("clicked", callback)
        self.location_buttons.append(button)
        return button

    def _build_sidebar(self) -> None:
        self.sidebar.append(label("LOCATIONS", "sidebar-heading"))
        home = Path.home()
        locations = [
            ("Home", "user-home-symbolic", home),
            ("Recent", "document-open-recent-symbolic", None),
            ("Documents", "folder-documents-symbolic", home / "Documents"),
            ("Downloads", "folder-download-symbolic", home / "Downloads"),
            ("Pictures", "folder-pictures-symbolic", home / "Pictures"),
            ("Videos", "folder-videos-symbolic", home / "Videos"),
            ("Projects", "folder-symbolic", home / "Documents/Omarchy"),
        ]
        for name, icon, path in locations:
            if path is not None and not path.exists():
                continue
            if name == "Recent":
                button = self._sidebar_button(name, icon, lambda _b: self._open_recent())
            else:
                button = self._sidebar_button(name, icon, lambda _b, p=path: self.navigate(p))
                button._picker_path = path  # type: ignore[attr-defined]
            self.sidebar.append(button)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(10)
        separator.set_margin_bottom(6)
        self.sidebar.append(separator)
        self.sidebar.append(label("DEVICES", "sidebar-heading"))

        seen: set[str] = set()
        for mount in self.volume_monitor.get_mounts():
            root = mount.get_root().get_path()
            if not root or root in seen:
                continue
            seen.add(root)
            path = Path(root)
            button = self._sidebar_button(
                mount.get_name(), "drive-harddisk-symbolic", lambda _b, p=path: self.navigate(p)
            )
            button._picker_path = path  # type: ignore[attr-defined]
            self.sidebar.append(button)

        connect = self._sidebar_button("Connect to NAS…", "network-server-symbolic", self._show_nas_dialog)
        connect.add_css_class("nas-button")
        self.sidebar.append(connect)

    def _refresh_sidebar(self) -> None:
        if not hasattr(self, "sidebar"):
            return
        while child := self.sidebar.get_first_child():
            self.sidebar.remove(child)
        self.location_buttons.clear()
        self._build_sidebar()
        self._update_active_location()

    def _icon_button(self, icon_name: str, tooltip: str, callback) -> Gtk.Button:
        button = Gtk.Button.new_from_icon_name(icon_name)
        button.set_tooltip_text(tooltip)
        button.connect("clicked", callback)
        return button

    def _build_toolbar(self) -> None:
        self.back_button = self._icon_button("go-previous-symbolic", "Back (Alt+Left)", self._go_back)
        self.forward_button = self._icon_button("go-next-symbolic", "Forward (Alt+Right)", self._go_forward)
        self.toolbar.append(self.back_button)
        self.toolbar.append(self.forward_button)

        self.path_stack = Gtk.Stack()
        self.path_stack.set_hexpand(True)
        self.path_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=1)
        self.path_box.set_hexpand(True)
        self.path_stack.add_named(self.path_box, "crumbs")
        self.path_entry = Gtk.Entry()
        self.path_entry.connect("activate", self._on_path_activate)
        self.path_stack.add_named(self.path_entry, "entry")
        self.path_stack.set_visible_child_name("crumbs")
        self.toolbar.append(self.path_stack)

        location_button = self._icon_button("document-edit-symbolic", "Type a location (Ctrl+L)", self._toggle_path_entry)
        self.toolbar.append(location_button)

        self.search = Gtk.SearchEntry(placeholder_text="Search this folder")
        self.search.set_size_request(290, -1)
        self.search.connect("search-changed", lambda _entry: self._load())
        self.toolbar.append(self.search)

        self.hidden_button = self._icon_button("view-more-symbolic", "Show hidden files (Ctrl+H)", self._toggle_hidden)
        self.toolbar.append(self.hidden_button)
        self.list_button = self._icon_button("view-list-symbolic", "List view", lambda _b: self._set_view("list"))
        self.grid_button = self._icon_button("view-grid-symbolic", "Grid view", lambda _b: self._set_view("grid"))
        self.toolbar.append(self.list_button)
        self.toolbar.append(self.grid_button)

    def _build_footer(self) -> None:
        if self.request.choices:
            choices_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            for choice in self.request.choices:
                values = choice.get("values", [])
                if not values:
                    widget = Gtk.CheckButton(label=choice["label"])
                    widget.set_active(choice.get("selected") == "true")
                else:
                    item = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                    item.append(label(choice["label"], "muted"))
                    combo = Gtk.ComboBoxText()
                    active = 0
                    for index, (value_id, value_label) in enumerate(values):
                        combo.append(str(value_id), str(value_label))
                        if value_id == choice.get("selected"):
                            active = index
                    combo.set_active(active)
                    item.append(combo)
                    widget = combo
                    choices_row.append(item)
                    self.choice_widgets[choice["id"]] = widget
                    continue
                choices_row.append(widget)
                self.choice_widgets[choice["id"]] = widget
            self.footer.append(choices_row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.footer.append(row)

        self.filter_combo = Gtk.ComboBoxText()
        self.filter_combo.append_text("All files")
        for file_filter in self.request.filters:
            self.filter_combo.append_text(file_filter.name)
        requested = min(self.request.current_filter + 1, len(self.request.filters)) if self.request.filters else 0
        self.filter_combo.set_active(requested)
        self.filter_combo.connect("changed", lambda _combo: self._load())
        self.filter_combo.set_size_request(210, -1)
        row.append(self.filter_combo)

        if self.request.mode == "save":
            self.filename_entry = Gtk.Entry(placeholder_text="File name")
            self.filename_entry.set_text(self.request.current_name)
            self.filename_entry.set_hexpand(True)
            self.filename_entry.connect("changed", lambda _entry: self._update_accept_state())
            self.filename_entry.connect("activate", lambda _entry: self._accept())
            row.append(self.filename_entry)
        else:
            self.selection_label = label("No file selected", "muted")
            self.selection_label.set_hexpand(True)
            row.append(self.selection_label)

        hints = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hints.append(label("Ctrl+F Search", "key-hint"))
        hints.append(label("Ctrl+H Hidden", "key-hint"))
        hints.append(label("Enter Open", "key-hint"))
        row.append(hints)

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _button: self._finish(cancelled=True))
        row.append(cancel)
        self.accept_button = Gtk.Button(label=self.request.accept_label)
        self.accept_button.add_css_class("suggested-action")
        self.accept_button.connect("clicked", lambda _button: self._accept())
        row.append(self.accept_button)

    def _install_shortcuts(self) -> None:
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

    def _on_key_pressed(self, _controller, keyval, _keycode, state):
        control = bool(state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        if keyval == Gdk.KEY_Escape:
            if self.path_stack.get_visible_child_name() == "entry":
                self.path_stack.set_visible_child_name("crumbs")
            elif self.search.get_text():
                self.search.set_text("")
            else:
                self._finish(cancelled=True)
            return Gdk.EVENT_STOP
        if control and keyval in (Gdk.KEY_l, Gdk.KEY_L):
            self._toggle_path_entry(None)
            return Gdk.EVENT_STOP
        if control and keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.search.grab_focus()
            return Gdk.EVENT_STOP
        if control and keyval in (Gdk.KEY_h, Gdk.KEY_H):
            self._toggle_hidden(None)
            return Gdk.EVENT_STOP
        if alt and keyval == Gdk.KEY_Left:
            self._go_back(None)
            return Gdk.EVENT_STOP
        if alt and keyval == Gdk.KEY_Right:
            self._go_forward(None)
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def _active_filter(self):
        index = self.filter_combo.get_active() - 1
        if 0 <= index < len(self.request.filters):
            return self.request.filters[index]
        return None

    def _load(self) -> None:
        query = self.search.get_text() if hasattr(self, "search") else ""
        if self.special_mode == "recent":
            entries = recent_files()
            if query:
                entries = [item for item in entries if query.casefold() in item.name.casefold()]
            active_filter = self._active_filter() if hasattr(self, "filter_combo") else None
            if active_filter:
                entries = [item for item in entries if active_filter.matches(item)]
            if self.request.directory:
                entries = [item for item in entries if item.is_dir()]
            self.entries = entries
        else:
            self.entries = list_directory(
                self.current_dir,
                show_hidden=self.show_hidden,
                active_filter=self._active_filter() if hasattr(self, "filter_combo") else None,
                query=query,
                directories_only=self.request.directory,
            )
        self._rebuild_pathbar()
        self._rebuild_files()
        self._update_nav_state()
        self._update_active_location()

    def _rebuild_files(self) -> None:
        while child := self.flow.get_first_child():
            self.flow.remove(child)
        self.children_by_path.clear()
        for path in self.entries:
            child = Gtk.FlowBoxChild()
            child._picker_path = path  # type: ignore[attr-defined]
            child.set_tooltip_text(str(path))
            child.set_child(self._grid_item(path) if self.view_mode == "grid" else self._list_item(path))
            self.flow.append(child)
            self.children_by_path[path] = child
        self.browser_stack.set_visible_child_name("files" if self.entries else "empty")
        self.empty_detail.set_text(
            "No matching files." if self.search.get_text() else "This folder is empty."
        )
        self._clear_metadata()
        self._update_accept_state()

    def _grid_item(self, path: Path) -> Gtk.Widget:
        item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        item.set_size_request(160, 138)
        item.set_hexpand(False)
        frame = Gtk.Box()
        frame.add_css_class("thumbnail-frame")
        frame.set_halign(Gtk.Align.CENTER)
        frame.set_valign(Gtk.Align.CENTER)
        frame.append(picture_for(path, 156, 98))
        item.append(frame)
        name = label(path.name, "filename", xalign=0.5)
        name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        name.set_width_chars(18)
        name.set_max_width_chars(18)
        item.append(name)
        detail = ""
        try:
            if path.is_dir():
                detail = f"{len(list(path.iterdir()))} items"
            elif path.suffix.casefold() in IMAGE_TYPES:
                _format, width, height = GdkPixbuf.Pixbuf.get_file_info(str(path))
                detail = f"{width} × {height}" if width and height else format_size(path.stat().st_size)
            else:
                detail = format_size(path.stat().st_size)
        except OSError:
            detail = file_type(path)
        item.append(label(detail, "muted", xalign=0.5))
        return item

    def _list_item(self, path: Path) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_size_request(-1, 42)
        image = Gtk.Image.new_from_gicon(icon_for(path))
        image.set_pixel_size(24)
        row.append(image)
        name = label(path.name, "filename")
        name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        name.set_hexpand(True)
        row.append(name)
        kind = label(file_type(path), "muted")
        kind.set_size_request(150, -1)
        row.append(kind)
        try:
            size_text = "—" if path.is_dir() else format_size(path.stat().st_size)
            modified_text = datetime.fromtimestamp(path.stat().st_mtime).strftime("%b %-d, %H:%M")
        except OSError:
            size_text, modified_text = "—", "—"
        size = label(size_text, "muted")
        size.set_size_request(95, -1)
        row.append(size)
        modified = label(modified_text, "muted")
        modified.set_size_request(125, -1)
        row.append(modified)
        return row

    def _rebuild_pathbar(self) -> None:
        while child := self.path_box.get_first_child():
            self.path_box.remove(child)
        if self.special_mode == "recent":
            button = Gtk.Button(label="Recent")
            button.add_css_class("path-segment")
            self.path_box.append(button)
            return
        path = self.current_dir.resolve()
        home = Path.home().resolve()
        if path == home or home in path.parents:
            current = home
            parts = path.relative_to(home).parts
            root = Gtk.Button(label="Home")
            root.add_css_class("path-segment")
            root.connect("clicked", lambda _b: self.navigate(home))
            self.path_box.append(root)
        else:
            parts = path.parts[1:]
            current = Path("/")
            root = Gtk.Button(label="/")
            root.add_css_class("path-segment")
            root.connect("clicked", lambda _b: self.navigate(Path("/")))
            self.path_box.append(root)
        for part in parts:
            current = current / part
            button = Gtk.Button(label=part)
            button.add_css_class("path-segment")
            button.connect("clicked", lambda _b, p=current: self.navigate(p))
            self.path_box.append(button)
        self.path_entry.set_text(str(path))

    def _clear_metadata(self) -> None:
        while child := self.metadata.get_first_child():
            self.metadata.remove(child)
        image = Gtk.Image.new_from_icon_name("document-open-symbolic")
        image.set_pixel_size(32)
        self.metadata.append(image)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        copy.append(label("Select a file to preview", "metadata-title"))
        copy.append(label("Images and cached video thumbnails appear here.", "muted"))
        self.metadata.append(copy)

    def _update_metadata(self, path: Path) -> None:
        while child := self.metadata.get_first_child():
            self.metadata.remove(child)
        self.metadata.append(picture_for(path, 132, 76, crop=True))
        primary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        primary.set_size_request(240, -1)
        title = label(path.name, "metadata-title")
        title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        primary.append(title)
        primary.append(label(file_type(path), "muted"))
        primary.append(label(str(path.parent), "muted"))
        self.metadata.append(primary)
        try:
            stat = path.stat()
            size = "—" if path.is_dir() else format_size(stat.st_size)
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%B %-d, %Y at %-I:%M %p")
        except OSError:
            size, modified = "—", "—"
        facts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        facts.set_hexpand(True)
        facts.append(label(f"Size    {size}", "muted"))
        facts.append(label(f"Modified    {modified}", "muted"))
        if path.suffix.casefold() in IMAGE_TYPES:
            try:
                _format, width, height = GdkPixbuf.Pixbuf.get_file_info(str(path))
                if width and height:
                    facts.append(label(f"Dimensions    {width} × {height}", "muted"))
            except (GLib.Error, TypeError):
                pass
        self.metadata.append(facts)

    def _on_selection_changed(self, flow: Gtk.FlowBox) -> None:
        selected = flow.get_selected_children()
        if selected:
            path = selected[0]._picker_path  # type: ignore[attr-defined]
            self._update_metadata(path)
            if self.request.mode == "save" and not path.is_dir():
                self.filename_entry.set_text(path.name)
        else:
            self._clear_metadata()
        if hasattr(self, "selection_label"):
            count = len(selected)
            if count:
                total = 0
                for child in selected:
                    path = child._picker_path  # type: ignore[attr-defined]
                    if path.is_file():
                        try:
                            total += path.stat().st_size
                        except OSError:
                            pass
                noun = "item" if count == 1 else "items"
                suffix = f" ({format_size(total)})" if total else ""
                self.selection_label.set_text(f"{count} {noun} selected{suffix}")
            elif self.request.directory:
                self.selection_label.set_text(f"Current folder: {self.current_dir.name or '/'}")
            else:
                self.selection_label.set_text("No file selected")
        self._update_accept_state()

    def _on_child_activated(self, _flow: Gtk.FlowBox, child: Gtk.FlowBoxChild) -> None:
        path = child._picker_path  # type: ignore[attr-defined]
        if path.is_dir():
            self.navigate(path)
        else:
            self._accept()

    def _on_context_pressed(self, _gesture: Gtk.GestureClick, _presses: int, x: float, y: float) -> None:
        picked = self.flow.pick(x, y, Gtk.PickFlags.DEFAULT)
        child: Gtk.Widget | None = picked
        while child and child is not self.flow and not isinstance(child, Gtk.FlowBoxChild):
            child = child.get_parent()
        path = getattr(child, "_picker_path", None) if isinstance(child, Gtk.FlowBoxChild) else None
        if isinstance(child, Gtk.FlowBoxChild) and not child.is_selected():
            self.flow.unselect_all()
            self.flow.select_child(child)
        self._show_context_menu(x, y, path)

    def _menu_button(self, text: str, callback) -> Gtk.Button:
        button = Gtk.Button(label=text)
        button.add_css_class("context-action")
        button.set_halign(Gtk.Align.FILL)
        button.connect("clicked", lambda _button: (self._close_context_menu(), callback()))
        return button

    def _show_context_menu(self, x: float, y: float, path: Path | None = None) -> None:
        self._close_context_menu()
        keep_open_for_qa = os.environ.get("OMARCHY_FILE_PICKER_AUTOMATION") == "context-menu"
        popover = Gtk.Popover(autohide=not keep_open_for_qa, has_arrow=True)
        popover.add_css_class("file-context-menu")
        anchor = self.children_by_path.get(path, self.flow) if path else self.flow
        popover.set_parent(anchor)
        popover.connect("closed", self._on_context_closed)
        rectangle = Gdk.Rectangle()
        if anchor is self.flow:
            rectangle.x = int(x)
            rectangle.y = int(y)
        else:
            allocation = anchor.get_allocation()
            rectangle.x = allocation.width // 2
            rectangle.y = allocation.height // 2
        rectangle.width = 1
        rectangle.height = 1
        popover.set_pointing_to(rectangle)

        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        menu.set_margin_top(8)
        menu.set_margin_bottom(8)
        menu.set_margin_start(8)
        menu.set_margin_end(8)
        popover.set_child(menu)

        create_heading = label("CREATE", "context-heading")
        menu.append(create_heading)
        new_folder = self._menu_button("New Folder…", lambda: self._show_create_dialog("folder"))
        new_text = self._menu_button("New Text File…", lambda: self._show_create_dialog("text"))
        can_create = self.special_mode is None and os.access(self.current_dir, os.W_OK)
        new_folder.set_sensitive(can_create)
        new_text.set_sensitive(can_create)
        menu.append(new_folder)
        menu.append(new_text)

        if path and path.is_file() and path.suffix.casefold() in IMAGE_TYPES:
            menu.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            menu.append(label("RESIZE IMAGE", "context-heading"))
            sizes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            for size, pixels in IMAGE_SIZE_PIXELS.items():
                sizes.append(self._menu_button(
                    f"{size.title()}\n{pixels}px",
                    lambda p=path, s=size: self._resize_image(p, s),
                ))
            menu.append(sizes)
            menu.append(label("CONVERT IMAGE", "context-heading"))
            formats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            for image_format in ("jpeg", "png", "webp", "avif"):
                formats.append(self._menu_button(
                    image_format.upper(),
                    lambda p=path, f=image_format: self._convert_image(p, f),
                ))
            menu.append(formats)

        if path and path.is_file() and path.suffix.casefold() in VIDEO_TYPES:
            menu.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            menu.append(label("CONVERT VIDEO", "context-heading"))
            formats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            for video_format in ("mp4", "webm", "mov", "gif"):
                formats.append(self._menu_button(
                    video_format.upper(),
                    lambda p=path, f=video_format: self._convert_video(p, f),
                ))
            menu.append(formats)

        menu.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        menu.append(self._menu_button("Connect to NAS…", lambda: self._show_nas_dialog(None)))
        self.context_popover = popover
        popover.popup()

    def _close_context_menu(self) -> None:
        if self.context_popover:
            self.context_popover.popdown()

    def _on_context_closed(self, popover: Gtk.Popover) -> None:
        if self.context_popover is popover:
            self.context_popover = None
        GLib.idle_add(self._unparent_popover, popover)

    @staticmethod
    def _unparent_popover(popover: Gtk.Popover) -> bool:
        if popover.get_parent() is not None:
            popover.unparent()
        return GLib.SOURCE_REMOVE

    def _show_create_dialog(self, kind: str) -> None:
        noun = "Folder" if kind == "folder" else "Text File"
        dialog = Gtk.Dialog(title=f"New {noun}", transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Create", Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.append(label(f"Create in {self.current_dir}", "muted"))
        entry = Gtk.Entry(placeholder_text="Folder name" if kind == "folder" else "File name")
        entry.set_activates_default(True)
        content.append(entry)

        def on_response(_dialog: Gtk.Dialog, response: int) -> None:
            if response != Gtk.ResponseType.ACCEPT:
                dialog.destroy()
                return
            name = entry.get_text().strip()
            if not name or name in {".", ".."} or Path(name).name != name:
                entry.add_css_class("error")
                return
            if kind == "text" and not Path(name).suffix:
                name += ".txt"
            destination = self.current_dir / name
            try:
                if kind == "folder":
                    destination.mkdir()
                else:
                    destination.touch(exist_ok=False)
            except OSError as error:
                entry.add_css_class("error")
                entry.set_tooltip_text(str(error))
                return
            dialog.destroy()
            self._load()
            child = self.children_by_path.get(destination)
            if child:
                self.flow.select_child(child)
                child.grab_focus()

        dialog.connect("response", on_response)
        dialog.present()
        entry.grab_focus()

    def _resize_image(self, path: Path, size: str) -> None:
        try:
            command, output = image_resize_command(path, size)
        except ActionError as error:
            self._show_error("Could not resize image", str(error))
            return
        self._run_conversion(command, output, f"Resize {path.name}")

    def _convert_image(self, path: Path, image_format: str) -> None:
        try:
            command, output = image_convert_command(path, image_format)
        except ActionError as error:
            self._show_error("Could not convert image", str(error))
            return
        self._run_conversion(command, output, f"Convert {path.name} to {image_format.upper()}")

    def _convert_video(self, path: Path, video_format: str) -> None:
        try:
            command, output = video_convert_command(path, video_format)
        except ActionError as error:
            self._show_error("Could not convert video", str(error))
            return
        self._run_conversion(command, output, f"Convert {path.name} to {video_format.upper()}")

    def _run_conversion(self, command: list[str], output: Path, description: str) -> None:
        if not GLib.find_program_in_path(command[0]):
            self._show_error("Converter unavailable", f"{command[0]} is not installed")
            return
        try:
            process = Gio.Subprocess.new(
                command,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
            )
        except GLib.Error as error:
            self._show_error("Could not start conversion", error.message)
            return
        self.active_processes.add(process)
        self.set_title(f"Working… — {self.request.title}")
        self._notify("Conversion started", description)

        def on_finished(proc: Gio.Subprocess, result) -> None:
            try:
                successful, _stdout, stderr = proc.communicate_utf8_finish(result)
            except GLib.Error as error:
                successful, stderr = False, error.message
            self.active_processes.discard(proc)
            if not self.active_processes:
                self.set_title(self.request.title)
            if successful and output.exists():
                self._load()
                child = self.children_by_path.get(output)
                if child:
                    self.flow.unselect_all()
                    self.flow.select_child(child)
                    child.grab_focus()
                self._notify("Conversion complete", output.name)
                alert = Gtk.AlertDialog(message="Conversion complete", detail=f"Created {output.name}")
                alert.show(self)
            else:
                detail = (stderr or "The converter exited without creating a file.").strip()[-800:]
                self._show_error("Conversion failed", detail)

        process.communicate_utf8_async(None, None, on_finished)

    def _notify(self, headline: str, detail: str) -> None:
        notifier = GLib.find_program_in_path("omarchy-notification-send")
        if notifier:
            try:
                Gio.Subprocess.new(
                    [notifier, "--app-name", "Omarchy File Picker", headline, detail],
                    Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
                )
            except GLib.Error:
                pass

    def _show_error(self, message: str, detail: str) -> None:
        alert = Gtk.AlertDialog(message=message, detail=detail)
        alert.show(self)

    def _show_nas_dialog(self, _button) -> None:
        dialog = Gtk.Dialog(title="Connect to NAS", transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Connect", Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.append(label("SMB or NFS address", "metadata-title"))
        content.append(label("Examples: smb://nas/media or nfs://nas.local/archive", "muted"))
        entry = Gtk.Entry(placeholder_text="smb://server/share")
        entry.set_width_chars(44)
        entry.set_activates_default(True)
        content.append(entry)

        def on_response(_dialog: Gtk.Dialog, response: int) -> None:
            if response != Gtk.ResponseType.ACCEPT:
                dialog.destroy()
                return
            try:
                uri = normalize_nas_uri(entry.get_text())
            except ActionError as error:
                entry.add_css_class("error")
                entry.set_tooltip_text(str(error))
                return
            dialog.set_sensitive(False)
            target = Gio.File.new_for_uri(uri)
            mount_operation = Gtk.MountOperation.new(self)

            def on_mounted(source: Gio.File, result) -> None:
                mounted = True
                try:
                    source.mount_enclosing_volume_finish(result)
                except GLib.Error as error:
                    if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                        mounted = True
                    else:
                        mounted = False
                        dialog.set_sensitive(True)
                        entry.add_css_class("error")
                        entry.set_tooltip_text(error.message)
                        self._show_error("Could not connect to NAS", error.message)
                if not mounted:
                    return
                dialog.destroy()
                self._refresh_sidebar()
                mounted_path = self._path_for_mount_uri(uri)
                if mounted_path:
                    self.navigate(mounted_path)
                self._notify("NAS connected", uri)

            target.mount_enclosing_volume(
                Gio.MountMountFlags.NONE,
                mount_operation,
                None,
                on_mounted,
            )

        dialog.connect("response", on_response)
        dialog.present()
        entry.grab_focus()

    def _path_for_mount_uri(self, uri: str) -> Path | None:
        for mount in self.volume_monitor.get_mounts():
            root = mount.get_root()
            root_uri = root.get_uri().rstrip("/")
            if uri.rstrip("/").startswith(root_uri) or root_uri.startswith(uri.rstrip("/")):
                local_path = root.get_path()
                if local_path:
                    return Path(local_path)
        return None

    def _selected_paths(self) -> list[Path]:
        return [child._picker_path for child in self.flow.get_selected_children()]  # type: ignore[attr-defined]

    def _update_accept_state(self) -> None:
        if not hasattr(self, "accept_button"):
            return
        if self.request.mode == "save":
            enabled = bool(self.filename_entry.get_text().strip())
        elif self.request.directory:
            enabled = True
        else:
            enabled = any(path.is_file() for path in self._selected_paths())
        self.accept_button.set_sensitive(enabled)

    def _accept(self) -> None:
        selected = self._selected_paths()
        if self.request.mode == "save":
            name = self.filename_entry.get_text().strip()
            if not name or "/" in name or name in (".", ".."):
                self.filename_entry.add_css_class("error")
                return
            path = self.current_dir / name
            if path.exists() and path.is_file():
                dialog = Gtk.AlertDialog(message=f"Replace “{path.name}”?", detail="A file with this name already exists.")
                dialog.set_buttons(["Cancel", "Replace"])
                dialog.set_cancel_button(0)
                dialog.set_default_button(1)
                dialog.choose(self, None, lambda alert, result: self._replace_chosen(alert, result, path))
                return
            self._finish(paths=[path])
            return
        if self.request.directory:
            dirs = [path for path in selected if path.is_dir()]
            self._finish(paths=dirs or [self.current_dir])
            return
        paths = [path for path in selected if path.is_file()]
        if paths:
            self._finish(paths=paths)

    def _replace_chosen(self, dialog: Gtk.AlertDialog, result, path: Path) -> None:
        try:
            if dialog.choose_finish(result) == 1:
                self._finish(paths=[path])
        except GLib.Error:
            pass

    def _choice_results(self) -> dict[str, str]:
        results = {}
        for choice in self.request.choices:
            widget = self.choice_widgets.get(choice["id"])
            if isinstance(widget, Gtk.CheckButton):
                results[choice["id"]] = "true" if widget.get_active() else "false"
            elif isinstance(widget, Gtk.ComboBoxText):
                results[choice["id"]] = widget.get_active_id() or ""
        return results

    def _finish(self, *, cancelled: bool = False, paths: list[Path] | None = None) -> None:
        paths = paths or []
        active_filter = self._active_filter()
        payload: dict[str, Any] = {
            "response": "cancel" if cancelled else "ok",
            "uris": [] if cancelled else [safe_uri(path) for path in paths],
            "choices": self._choice_results(),
        }
        if active_filter:
            payload["current_filter"] = [active_filter.name, [list(rule) for rule in active_filter.rules]]
        encoded = json.dumps(payload)
        if self.result_path:
            self.result_path.write_text(encoded, encoding="utf-8")
        else:
            print(encoded, flush=True)
        self.get_application().quit()

    def navigate(self, path: Path, *, record: bool = True) -> None:
        path = path.expanduser()
        if not path.is_dir():
            return
        self.special_mode = None
        self.current_dir = path.resolve()
        self.search.set_text("")
        if record:
            self.history = self.history[: self.history_index + 1]
            if not self.history or self.history[-1] != self.current_dir:
                self.history.append(self.current_dir)
                self.history_index = len(self.history) - 1
        self._load()

    def _open_recent(self) -> None:
        self.special_mode = "recent"
        self.search.set_text("")
        self._load()

    def _go_back(self, _button) -> None:
        if self.history_index > 0:
            self.history_index -= 1
            self.current_dir = self.history[self.history_index]
            self.special_mode = None
            self._load()

    def _go_forward(self, _button) -> None:
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.current_dir = self.history[self.history_index]
            self.special_mode = None
            self._load()

    def _update_nav_state(self) -> None:
        self.back_button.set_sensitive(self.history_index > 0)
        self.forward_button.set_sensitive(self.history_index < len(self.history) - 1)

    def _update_active_location(self) -> None:
        for button in self.location_buttons:
            active = getattr(button, "_picker_path", None) == self.current_dir and self.special_mode is None
            if active:
                button.add_css_class("active")
            else:
                button.remove_css_class("active")

    def _toggle_hidden(self, _button) -> None:
        self.show_hidden = not self.show_hidden
        if self.show_hidden:
            self.hidden_button.add_css_class("active")
        else:
            self.hidden_button.remove_css_class("active")
        self._load()

    def _set_view(self, mode: str) -> None:
        if self.view_mode == mode:
            return
        self.view_mode = mode
        self.flow.set_homogeneous(False)
        self.flow.set_max_children_per_line(6 if mode == "grid" else 1)
        self._rebuild_files()

    def _select_first_file(self) -> bool:
        for path in self.entries:
            if path.is_file():
                child = self.children_by_path.get(path)
                if child:
                    self.flow.select_child(child)
                    child.grab_focus()
                break
        return GLib.SOURCE_REMOVE

    def _automation_cancel(self) -> bool:
        self._finish(cancelled=True)
        return GLib.SOURCE_REMOVE

    def _automation_select_first(self) -> bool:
        self._select_first_file()
        self._accept()
        return GLib.SOURCE_REMOVE

    def _automation_accept(self) -> bool:
        self._accept()
        return GLib.SOURCE_REMOVE

    def _automation_context_menu(self) -> bool:
        for path in self.entries:
            if path.is_file() and path.suffix.casefold() in IMAGE_TYPES:
                child = self.children_by_path.get(path)
                if child:
                    self.flow.select_child(child)
                    self._show_context_menu(280, 170, path)
                break
        return GLib.SOURCE_REMOVE

    def _toggle_path_entry(self, _button) -> None:
        if self.path_stack.get_visible_child_name() == "entry":
            self.path_stack.set_visible_child_name("crumbs")
        else:
            self.path_entry.set_text(str(self.current_dir))
            self.path_stack.set_visible_child_name("entry")
            self.path_entry.grab_focus()
            self.path_entry.select_region(0, -1)

    def _on_path_activate(self, entry: Gtk.Entry) -> None:
        path = Path(entry.get_text()).expanduser()
        if path.is_file():
            self.navigate(path.parent)
            child = self.children_by_path.get(path.resolve())
            if child:
                self.flow.select_child(child)
        elif path.is_dir():
            self.navigate(path)
        else:
            entry.add_css_class("error")
            return
        entry.remove_css_class("error")
        self.path_stack.set_visible_child_name("crumbs")

    def close_request(self) -> None:
        self._finish(cancelled=True)


class PickerApplication(Gtk.Application):
    def __init__(self, request: PickerRequest, result_path: Path | None):
        super().__init__(application_id="org.omarchy.FilePicker", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.request = request
        self.result_path = result_path

    def do_activate(self) -> None:
        window = PickerWindow(self, self.request, self.result_path)
        window.present()


def parse_args(argv: list[str]) -> tuple[PickerRequest, Path | None]:
    parser = argparse.ArgumentParser(description="Omarchy visual file picker")
    parser.add_argument("--request", type=Path, help="JSON portal request")
    parser.add_argument("--result", type=Path, help="JSON result destination")
    parser.add_argument("--demo", nargs="?", const=str(Path.home() / "Pictures"), help="Open standalone demo")
    parser.add_argument("--mode", choices=("open", "save", "save_files"), default="open")
    parser.add_argument("--multiple", action="store_true")
    parser.add_argument("--directory", action="store_true")
    args = parser.parse_args(argv)
    if args.request:
        request = PickerRequest.from_dict(json.loads(args.request.read_text(encoding="utf-8")))
    else:
        folder = Path(args.demo or Path.cwd()).expanduser()
        request = PickerRequest(
            mode=args.mode,
            title="Save File" if args.mode == "save" else "Open File",
            accept_label="Save" if args.mode == "save" else ("Select Folder" if args.directory else "Open"),
            current_folder=folder if folder.is_dir() else folder.parent,
            current_name="untitled.txt" if args.mode == "save" else "",
            multiple=args.multiple,
            directory=args.directory or args.mode == "save_files",
        )
    return request, args.result


def main(argv: list[str] | None = None) -> int:
    request, result_path = parse_args(argv if argv is not None else sys.argv[1:])
    return PickerApplication(request, result_path).run([])


if __name__ == "__main__":
    raise SystemExit(main())
