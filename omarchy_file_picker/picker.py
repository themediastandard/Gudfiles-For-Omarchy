from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import subprocess
import sys
import threading
from urllib.parse import urlsplit
from datetime import datetime
from pathlib import Path
from typing import Any

# GTK's Vulkan renderer can crash on video textures on this desktop. Keep the
# fallback app-local, before GTK initialization, and respect explicit overrides.
os.environ.setdefault("GSK_RENDERER", "gl")

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
from .file_management import FileManagement, SIDEBAR_MIN_WIDTH
from .file_actions import create_untitled_text, sort_entries
from .dialogs import PickerDialog, confirmation, entry_field, file_summary, text_label
from .quicklook import QuickLook
from .drag_selection import BackgroundSelection
from .network_ui import NetworkBrowser
from .network import NetworkLocation, safe_network_uri, mounted_local_path
from .creative import CreativeTools
from .hover_scrub import HoverScrub
from .media_details import MediaDetailsService, make_details_widget
from .breadcrumbs import BreadcrumbButton, BreadcrumbTrail, scroll_breadcrumbs
from .columns import ColumnBrowser
from .selection_summary import show_selection_summary


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


class PickerWindow(CreativeTools, FileManagement, Gtk.ApplicationWindow):
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
        self._init_file_management()
        self._init_creative()
        self.media_details = MediaDetailsService()
        self.connect('unrealize', lambda *_: self.media_details.close())
        self.active_processes: set[Gio.Subprocess] = set()
        self.context_popover: Gtk.Popover | None = None
        self.context_submenus: list[Gtk.Popover] = []
        self.qa_submenu_button: Gtk.MenuButton | None = None
        self.volume_monitor = Gio.VolumeMonitor.get()

        self.set_default_size(1200, 800)
        self.set_size_request(820, 560)
        self.add_css_class("picker-root")
        self._install_theme()
        self._build_header()
        self._build_content()
        self.quicklook = QuickLook(self)
        self.preview_overlay.add_overlay(self.quicklook)
        self.preview_overlay.set_measure_overlay(self.quicklook, False)
        self.preview_overlay.set_clip_overlay(self.quicklook, True)
        self.volume_monitor.connect("mount-added", lambda *_args: self._refresh_sidebar())
        self.volume_monitor.connect("mount-removed", lambda *_args: self._refresh_sidebar())
        self._install_shortcuts()
        self.connect('close-request', self._on_close_requested)
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
        elif automation in {"context-menu", "context-submenu"}:
            GLib.timeout_add(250, lambda: self._automation_context_menu())
        elif automation == 'context-background':
            GLib.timeout_add(250, lambda: self._show_context_menu(300, 180) or False)
        elif automation == 'quicklook':
            GLib.timeout_add(350, self._automation_quicklook)
        elif automation == 'nas-dialog':
            GLib.timeout_add(350, lambda: self._show_nas_dialog(None) or False)

    def _automation_quicklook(self):
        self._select_first_file()
        paths = self._selected_paths()
        if paths:
            self.quicklook.show_file(paths[0])
        return False

    def _install_theme(self) -> None:
        colors = load_colors()
        self.colors = colors
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
        if self.request.explorer:
            subtitle_text = "Browse files and folders"
        subtitle = label(subtitle_text, "muted", xalign=0.5)
        title_box.append(title_label)
        title_box.append(subtitle)
        header.set_title_widget(title_box)
        header.pack_end(self._build_transfer_button())
        self.set_titlebar(header)

    def _build_content(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.preview_overlay = Gtk.Overlay()
        self.preview_overlay.set_child(root)
        self.set_child(self.preview_overlay)

        body = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        body.add_css_class('sidebar-split')
        body.set_wide_handle(True)
        body.set_resize_start_child(False)
        body.set_resize_end_child(True)
        body.set_shrink_start_child(False)
        body.set_shrink_end_child(False)
        self.sidebar_split = body
        self.sidebar_save_timer = 0
        body.set_vexpand(True)
        root.append(body)

        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.sidebar.add_css_class("sidebar")
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_min_content_width(SIDEBAR_MIN_WIDTH)
        sidebar_scroll.set_size_request(SIDEBAR_MIN_WIDTH, -1)
        sidebar_scroll.set_child(self.sidebar)
        body.set_start_child(sidebar_scroll)
        self._build_sidebar()

        browser = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        browser.set_hexpand(True)
        browser.set_vexpand(True)
        body.set_end_child(browser)
        body.set_position(self.file_preferences['sidebar_width'])
        body.connect('notify::position', self._sidebar_resized)

        self.toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.toolbar.add_css_class("toolbar")
        browser.append(self.toolbar)
        self._build_toolbar()
        browser.append(self._build_active_filters())

        self.browser_stack = Gtk.Stack()
        self.browser_stack.set_hhomogeneous(False)
        self.browser_stack.set_vhomogeneous(False)
        self.browser_stack.set_vexpand(True)
        self.browser_stack.set_hexpand(True)
        self.browser_overlay = Gtk.Overlay()
        self.browser_overlay.set_child(self.browser_stack)
        browser.append(self.browser_overlay)

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
        self.selection_changed_handler = self.flow.connect("selected-children-changed", self._on_selection_changed)
        context_click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        context_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        context_click.connect("pressed", self._on_context_pressed)
        self.browser_stack.add_controller(context_click)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.flow)
        self.file_scroller = scroller
        self.browser_stack.add_named(scroller, "files")
        self.standard_flow = self.flow
        self.standard_scroller = scroller
        self.standard_selection_handler = self.selection_changed_handler
        self.columns = ColumnBrowser(self)
        self.browser_stack.add_named(self.columns, 'columns')
        self.drag_selection = BackgroundSelection(self)
        self.browser_overlay.add_overlay(self.drag_selection)
        self.browser_overlay.set_measure_overlay(self.drag_selection, False)
        self.browser_overlay.set_clip_overlay(self.drag_selection, True)

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
        # Preview content must never contribute a new minimum/natural window
        # size. Reserve the same strip even when selection or image shape changes.
        self.metadata_viewport = Gtk.Overlay()
        reserved_strip = Gtk.Box()
        reserved_strip.set_size_request(-1, 113)  # 92 content + padding and border.
        self.metadata_viewport.set_child(reserved_strip)
        self.metadata_viewport.add_overlay(self.metadata)
        self.metadata_viewport.set_measure_overlay(self.metadata, False)
        self.metadata_viewport.set_clip_overlay(self.metadata, True)
        browser.append(self.metadata_viewport)

        self.footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.footer.add_css_class("footer")
        root.append(self.footer)
        self._build_footer()
        self.footer.set_visible(not self.request.explorer)

    def _sidebar_resized(self, split, _property) -> None:
        if not self.get_mapped():
            return
        if self.sidebar_save_timer:
            GLib.source_remove(self.sidebar_save_timer)
        self.sidebar_save_timer = GLib.timeout_add(400, self._save_sidebar_width)

    def _save_sidebar_width(self) -> bool:
        if self.sidebar_save_timer:
            GLib.source_remove(self.sidebar_save_timer)
            self.sidebar_save_timer = 0
        width = max(SIDEBAR_MIN_WIDTH, self.sidebar_split.get_position())
        if width != self.file_preferences['sidebar_width']:
            self._set_file_preference('sidebar_width', width, reload=False)
        return False

    def _sidebar_button(self, text: str, icon_name: str, callback) -> Gtk.Button:
        button = Gtk.Button()
        button.add_css_class("location-button")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(18)
        row.append(icon)
        item_label = label(text)
        item_label.set_hexpand(True)
        item_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        item_label.set_max_width_chars(20)
        button.set_tooltip_text(text)
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
        existing_locations = {getattr(button, '_picker_path', None) for button in self.location_buttons}
        extra_bookmarks = [(path, name) for path, name in self._bookmarks() if path not in existing_locations]
        if extra_bookmarks:
            self.sidebar.append(label('BOOKMARKS', 'sidebar-heading'))
        for path, name in extra_bookmarks:
            button = self._sidebar_button(name, 'folder-symbolic', lambda _b, p=path: self.navigate(p))
            button._picker_path = path
            self.sidebar.append(button)
        self.sidebar.append(label("DEVICES", "sidebar-heading"))

        seen: set[str] = set()
        for mount in self.volume_monitor.get_mounts():
            root = mount.get_root().get_path()
            if not root or root in seen:
                continue
            seen.add(root)
            path = Path(root)
            button = self._sidebar_button(
                mount.get_name(), "drive-harddisk-symbolic",
                lambda _b, uri=mount.get_root().get_uri(): self._open_mounted_location(uri)
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
        self.path_box = BreadcrumbTrail()
        # Keep all ancestors reachable without growing the window's minimum
        # width every time the user enters another folder.
        self.path_scroll = Gtk.ScrolledWindow()
        self.path_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.path_scroll.set_min_content_width(80)
        self.path_scroll.set_propagate_natural_width(False)
        self.path_scroll.set_child(self.path_box)
        self.path_scroll.get_hadjustment().connect('changed', self._scroll_path_to_current)
        self.path_wheel = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.BOTH_AXES)
        self.path_wheel.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.path_wheel.connect('scroll', lambda controller, dx, dy:
                                scroll_breadcrumbs(controller, dx, dy, self.path_scroll.get_hadjustment()))
        self.path_scroll.add_controller(self.path_wheel)
        self.path_stack.add_named(self.path_scroll, "crumbs")
        self.path_entry = Gtk.Entry()
        self.path_entry.connect("activate", self._on_path_activate)
        self.path_stack.add_named(self.path_entry, "entry")
        self.path_stack.set_visible_child_name("crumbs")
        self.toolbar.append(self.path_stack)

        location_button = self._icon_button("document-edit-symbolic", "Type a location (Ctrl+L)", self._toggle_path_entry)
        self.toolbar.append(location_button)

        self.search = Gtk.SearchEntry(placeholder_text="Search this folder")
        self.search.set_size_request(240, -1)
        self.search.connect("search-changed", lambda _entry: self._refresh_files())
        self.toolbar.append(self.search)
        self.toolbar.append(self._creative_filter_button())

        self.hidden_button = self._icon_button("view-conceal-symbolic", "Show hidden files (Ctrl+H)", self._toggle_hidden)
        self.hidden_button.add_css_class('hidden-toggle')
        self.toolbar.append(self.hidden_button)
        self.list_button = self._icon_button("view-list-symbolic", "List view", lambda _b: self._set_view("list"))
        self.grid_button = self._icon_button("view-grid-symbolic", "Grid view", lambda _b: self._set_view("grid"))
        self.columns_button = self._icon_button('view-dual-symbolic', 'Column view', lambda _b: self._set_view('columns'))
        views = Gtk.Box()
        views.add_css_class('view-switcher')
        for button in (self.grid_button, self.list_button, self.columns_button):
            views.append(button)
        self.toolbar.append(views)
        self.grid_button.add_css_class('active')

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
        self.filter_combo.connect("changed", lambda _combo: self._refresh_files())
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
            self.selection_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            self.selection_label.set_max_width_chars(36)
            row.append(self.selection_label)

        hints = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hints.append(label("Ctrl+F Search", "key-hint"))
        hints.append(label("Ctrl+H Hidden", "key-hint"))
        hints.append(label("Space Preview", "key-hint"))
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
        preview_keys = Gtk.EventControllerKey()
        preview_keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        preview_keys.connect('key-pressed', self._on_preview_key)
        self.add_controller(preview_keys)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

    def _on_preview_key(self, _controller, keyval, _keycode, state):
        if self.view_mode == 'columns' and not self.quicklook.get_visible():
            self.columns.activate_focused()
        if self.drag_selection.active:
            if keyval == Gdk.KEY_Escape:
                self.drag_selection.cancel()
            return Gdk.EVENT_STOP
        if self.quicklook.get_visible():
            editing = isinstance(self.get_focus(), (Gtk.Editable, Gtk.TextView))
            if not editing and self._creative_shortcut(keyval, state, [self.quicklook.path]):
                return Gdk.EVENT_STOP
            if keyval in (Gdk.KEY_space, Gdk.KEY_Escape):
                if self.quicklook.target == 0:
                    self.quicklook.show_file(self.quicklook.path)
                else:
                    self.quicklook.close()
                return Gdk.EVENT_STOP
            if keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
                self.quicklook.step(-1 if keyval == Gdk.KEY_Left else 1)
                return Gdk.EVENT_STOP
            # Preview must not accept/delete/rename a file behind the overlay.
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_Delete, Gdk.KEY_F2):
                return Gdk.EVENT_STOP
            return Gdk.EVENT_PROPAGATE
        editing = isinstance(self.get_focus(), (Gtk.Editable, Gtk.TextView))
        modifiers = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK)
        if keyval == Gdk.KEY_space and not editing and not modifiers:
            paths = self._selected_paths()
            if paths and paths[0].is_file():
                self.quicklook.show_file(paths[0])
                return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def _on_key_pressed(self, _controller, keyval, _keycode, state):
        if self.quicklook.get_visible():
            return Gdk.EVENT_PROPAGATE
        control = bool(state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        focus = self.get_focus()
        editing = isinstance(focus, (Gtk.Editable, Gtk.TextView))
        if keyval == Gdk.KEY_Escape and self.context_popover:
            self._close_context_menu()
            return Gdk.EVENT_STOP
        if not editing:
            selected = self._selected_paths()
            if self.file_job_active and (keyval in (Gdk.KEY_F2, Gdk.KEY_Delete) or
                    (control and keyval in (Gdk.KEY_v, Gdk.KEY_V, Gdk.KEY_n, Gdk.KEY_N))):
                return Gdk.EVENT_STOP
            if keyval == Gdk.KEY_F2 and selected:
                if len(selected) == 1:
                    self._show_rename_dialog(selected[0])
                else:
                    self._show_batch_rename_dialog(selected)
                return Gdk.EVENT_STOP
            if self._creative_shortcut(keyval, state, selected):
                return Gdk.EVENT_STOP
            if keyval == Gdk.KEY_Delete and selected:
                self._confirm_remove(selected, permanent=shift)
                return Gdk.EVENT_STOP
            if keyval == Gdk.KEY_F5:
                self._refresh_files()
                return Gdk.EVENT_STOP
            if control and keyval in (Gdk.KEY_a, Gdk.KEY_A) and self.request.multiple:
                self.flow.select_all()
                return Gdk.EVENT_STOP
            if control and keyval in (Gdk.KEY_c, Gdk.KEY_C, Gdk.KEY_x, Gdk.KEY_X):
                if shift and keyval in (Gdk.KEY_c, Gdk.KEY_C):
                    self._copy_location(selected or [self.current_dir])
                else:
                    self._copy_files(selected, cut=keyval in (Gdk.KEY_x, Gdk.KEY_X))
                return Gdk.EVENT_STOP
            if control and keyval in (Gdk.KEY_v, Gdk.KEY_V):
                self._paste_files(queued=shift)
                return Gdk.EVENT_STOP
            if control and shift and keyval in (Gdk.KEY_n, Gdk.KEY_N):
                if self.special_mode is None: self._show_create_dialog('folder')
                return Gdk.EVENT_STOP
            if alt and keyval == Gdk.KEY_Up:
                self.navigate(self.current_dir.parent)
                return Gdk.EVENT_STOP
            if alt and keyval == Gdk.KEY_Return:
                self._show_properties(selected or [self.current_dir])
                return Gdk.EVENT_STOP
            if keyval == Gdk.KEY_Menu or (shift and keyval == Gdk.KEY_F10):
                self._show_context_menu(24, 24, selected[0] if selected else None, keyboard=True)
                return Gdk.EVENT_STOP
        if keyval == Gdk.KEY_Escape:
            if self.path_stack.get_visible_child_name() == "entry":
                self.path_stack.set_visible_child_name("crumbs")
            elif self.search.get_text():
                self.search.set_text("")
            elif self.request.explorer:
                self.flow.unselect_all()
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

    def _directory_entries(self, path):
        entries = list_directory(path, show_hidden=self.show_hidden,
            active_filter=self._active_filter(), query=self.search.get_text(),
            directories_only=self.request.directory)
        return sort_entries(self._creative_entries(entries), self.file_preferences['sort_key'],
                            self.file_preferences['descending'], self.file_preferences['folders_first'])

    def _load(self) -> None:
        self._update_active_filters()
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
        self.entries = self._creative_entries(self.entries)
        self.entries = sort_entries(self.entries, self.file_preferences['sort_key'],
                                    self.file_preferences['descending'], self.file_preferences['folders_first'])
        self._rebuild_pathbar()
        self._rebuild_files()
        self._update_nav_state()
        self._update_active_location()

    def _rebuild_files(self) -> None:
        self.drag_selection.cancel()
        self._close_context_menu()
        if self.view_mode == 'columns':
            self.columns.rebuild()
            self.browser_stack.set_visible_child_name('columns')
            self._clear_metadata()
            self._update_accept_state()
            return
        for child in list(self.children_by_path.values()):
            self.flow.remove(child)
        self.children_by_path.clear()
        self.rating_badges.clear()
        for path in self.entries:
            child = Gtk.FlowBoxChild()
            child._picker_path = path  # type: ignore[attr-defined]
            child.set_child(self._grid_item(path) if self.view_mode == "grid" else self._list_item(path))
            self.flow.append(child)
            self.children_by_path[path] = child
        self.browser_stack.set_visible_child_name("files" if self.entries else "empty")
        self.empty_detail.set_text(
            "No matching files." if self.search.get_text() or self.creative_filter != ('all', 0, '') else "This folder is empty."
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
        thumbnail = Gtk.Overlay()
        poster = picture_for(path, 156, 98)
        thumbnail.set_child(HoverScrub(path, poster) if path.suffix.casefold() in VIDEO_TYPES else poster)
        badge = self._rating_badge(path)
        badge.set_halign(Gtk.Align.END)
        badge.set_valign(Gtk.Align.START)
        thumbnail.add_overlay(badge)
        thumbnail.set_measure_overlay(badge, False)
        frame.append(thumbnail)
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
        detail_label = label(detail, "muted", xalign=0.5)
        detail_label.set_ellipsize(Pango.EllipsizeMode.END)
        detail_label.set_max_width_chars(18)
        detail_label.set_tooltip_text(detail)
        item.append(detail_label)
        return item

    def _list_item(self, path: Path) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_size_request(-1, 28)
        image = Gtk.Image.new_from_gicon(icon_for(path))
        image.set_pixel_size(18)
        row.append(image)
        name = label(path.name, "filename")
        name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        name.set_hexpand(True)
        row.append(name)
        row.append(self._rating_badge(path))
        kind = label(file_type(path), "muted")
        kind.set_size_request(150, -1)
        kind.set_ellipsize(Pango.EllipsizeMode.END)
        kind.set_max_width_chars(20)
        kind.set_tooltip_text(file_type(path))
        if self.file_preferences['show_type']: row.append(kind)
        try:
            size_text = "—" if path.is_dir() else format_size(path.stat().st_size)
            date_format = "%b %-d, %H:%M" if self.file_preferences['show_time'] else "%b %-d, %Y"
            modified_text = datetime.fromtimestamp(path.stat().st_mtime).strftime(date_format)
        except OSError:
            size_text, modified_text = "—", "—"
        size = label(size_text, "muted")
        size.set_size_request(95, -1)
        if self.file_preferences['show_size']: row.append(size)
        modified = label(modified_text, "muted")
        modified.set_size_request(125, -1)
        row.append(modified)
        return row

    def _scroll_path_to_current(self, adjustment) -> None:
        adjustment.set_value(max(adjustment.get_lower(), adjustment.get_upper() - adjustment.get_page_size()))

    def _rebuild_pathbar(self) -> None:
        while child := self.path_box.get_first_child():
            self.path_box.remove(child)
        if self.special_mode == "recent":
            button = BreadcrumbButton('Recent', self.colors, first=True, current=True)
            self.path_box.append(button)
            return
        path = self.current_dir.resolve()
        home = Path.home().resolve()
        if path == home or home in path.parents:
            current = home
            parts = path.relative_to(home).parts
            root = BreadcrumbButton('Home', self.colors, first=True, current=not parts)
            root.connect("clicked", lambda _b: self.navigate(home))
            self.path_box.append(root)
        else:
            parts = path.parts[1:]
            current = Path("/")
            root = BreadcrumbButton('/', self.colors, first=True, current=not parts)
            root.connect("clicked", lambda _b: self.navigate(Path("/")))
            self.path_box.append(root)
        for part in parts:
            current = current / part
            button = BreadcrumbButton(part, self.colors, current=current == path)
            button.connect("clicked", lambda _b, p=current: self.navigate(p))
            self.path_box.append(button)
        self.path_entry.set_text(str(path))

    def _clear_metadata(self) -> None:
        self.media_details.cancel()
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
        self.media_details.cancel()
        while child := self.metadata.get_first_child():
            self.metadata.remove(child)
        paths = self._selected_paths() or [path]
        if len(paths) > 1:
            show_selection_summary(self, paths)
            return
        poster = picture_for(path, 132, 76, crop=True)
        self.metadata.append(HoverScrub(path, poster) if path.suffix.casefold() in VIDEO_TYPES else poster)
        primary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        primary.set_size_request(140, -1)
        primary.set_hexpand(True)
        title = label(path.name, "metadata-title")
        title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        title.set_max_width_chars(32)
        title.set_tooltip_text(path.name)
        primary.append(title)
        for detail in (f'{file_type(path)} · {path.parent}',):
            detail_label = label(detail, "muted")
            detail_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            detail_label.set_max_width_chars(36)
            primary.append(detail_label)
        primary.append(self._rating_controls(paths))
        self.metadata.append(primary)
        try:
            stat = path.stat()
            size = "—" if path.is_dir() else format_size(stat.st_size)
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%B %-d, %Y at %-I:%M %p")
        except OSError:
            size, modified = "—", "—"
        facts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        facts.set_hexpand(True)
        def append_fact(text):
            fact = label(text, 'muted')
            fact.set_ellipsize(Pango.EllipsizeMode.END)
            fact.set_max_width_chars(28)
            fact.set_tooltip_text(text)
            facts.append(fact)
        append_fact(f"Size    {size}")
        append_fact(f"Modified    {modified}")
        facts.append(make_details_widget(self.media_details, path))
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
        if self.view_mode == 'columns':
            self.columns.activate_at(self.browser_stack, x, y)
            self.columns.cancel_pending()
        picked = self.browser_stack.pick(x, y, Gtk.PickFlags.DEFAULT)
        child: Gtk.Widget | None = picked
        while child and child is not self.browser_stack and not isinstance(child, Gtk.FlowBoxChild):
            if isinstance(child, Gtk.Popover): return
            child = child.get_parent()
        path = getattr(child, "_picker_path", None) if isinstance(child, Gtk.FlowBoxChild) else None
        if isinstance(child, Gtk.FlowBoxChild) and not child.is_selected():
            self.flow.unselect_all()
            self.flow.select_child(child)
        if path is None: self.flow.unselect_all()
        _gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._show_context_menu(x, y, path)

    def _context_row(
        self,
        text: str,
        icon_name: str,
        *,
        detail: str = "",
        end_icon: str = "",
    ) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_hexpand(True)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(17)
        icon.add_css_class("context-icon")
        row.append(icon)

        copy = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        copy.set_hexpand(True)
        copy.set_valign(Gtk.Align.CENTER)
        title = label(text, "context-label")
        title.set_hexpand(True)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        copy.append(title)
        if detail:
            copy.append(label(detail, "context-detail"))
        row.append(copy)

        if end_icon:
            arrow = Gtk.Image.new_from_icon_name(end_icon)
            arrow.set_pixel_size(14)
            arrow.add_css_class("context-arrow")
            row.append(arrow)
        return row

    def _menu_button(
        self,
        text: str,
        callback,
        *,
        icon_name: str = "document-open-symbolic",
        detail: str = "",
    ) -> Gtk.Button:
        button = Gtk.Button()
        button.add_css_class("context-action")
        button.set_halign(Gtk.Align.FILL)
        button.set_hexpand(True)
        button.set_child(self._context_row(text, icon_name, detail=detail))

        def on_clicked(_button: Gtk.Button) -> None:
            self._close_context_menu()
            callback()

        button.connect("clicked", on_clicked)
        return button

    def _submenu_button(
        self,
        text: str,
        icon_name: str,
        items: list[tuple[str, str, str, Any]],
        *,
        keep_open_for_qa: bool,
    ) -> Gtk.MenuButton:
        menu_button = Gtk.MenuButton()
        menu_button.add_css_class("context-action")
        menu_button.set_halign(Gtk.Align.FILL)
        menu_button.set_hexpand(True)
        menu_button.set_direction(self.context_submenu_direction)
        menu_button.set_child(
            self._context_row(
                text,
                icon_name,
                end_icon="go-previous-symbolic" if self.context_submenu_direction == Gtk.ArrowType.LEFT else "go-next-symbolic",
            )
        )

        submenu = Gtk.Popover(autohide=not keep_open_for_qa, has_arrow=False)
        submenu.add_css_class("file-context-menu")
        submenu.add_css_class("file-submenu")
        submenu.set_position(Gtk.PositionType.RIGHT)
        submenu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        submenu_box.set_margin_top(7)
        submenu_box.set_margin_bottom(7)
        submenu_box.set_margin_start(7)
        submenu_box.set_margin_end(7)
        for item_text, detail, item_icon, callback in items:
            item_button = self._menu_button(
                    item_text,
                    callback,
                    icon_name=item_icon,
                    detail=detail,
            )
            if detail.endswith(" px"):
                item_button.set_tooltip_text("Maximum longest edge; smaller images are not enlarged.")
            submenu_box.append(item_button)
        submenu.set_child(submenu_box)
        menu_button.set_popover(submenu)
        self.context_submenus.append(submenu)
        if self.qa_submenu_button is None:
            self.qa_submenu_button = menu_button
        return menu_button

    def _show_context_menu(self, x: float, y: float, path: Path | None = None, *, keyboard=False) -> None:
        self._close_context_menu()
        automation = os.environ.get("OMARCHY_FILE_PICKER_AUTOMATION")
        keep_open_for_qa = automation in {"context-menu", "context-submenu", "context-background"}
        popover = Gtk.Popover(autohide=not keep_open_for_qa, has_arrow=True)
        popover.add_css_class("file-context-menu")
        # Search, view changes, and refresh rebuild tiles. Keep the popup on the
        # stable browser surface, never on a tile that can be destroyed.
        anchor = self.browser_stack
        tile = self.children_by_path.get(path) if path else None
        if keyboard and tile:
            valid_tile_bounds, tile_bounds = tile.compute_bounds(anchor)
            if valid_tile_bounds:
                x = tile_bounds.get_x() + tile_bounds.get_width() / 2
                y = tile_bounds.get_y() + tile_bounds.get_height() / 2
        valid_bounds, bounds = anchor.compute_bounds(self)
        anchor_x = bounds.get_x() + x if valid_bounds else x
        # Keep cascading choices inside the chooser when the anchor is near its right edge.
        self.context_submenu_direction = (
            Gtk.ArrowType.LEFT if anchor_x + 370 > self.get_width() else Gtk.ArrowType.RIGHT
        )
        popover.set_parent(anchor)
        popover.connect("closed", self._on_context_closed)
        rectangle = Gdk.Rectangle()
        rectangle.x = int(x)
        rectangle.y = int(y)
        rectangle.width = 1
        rectangle.height = 1
        popover.set_pointing_to(rectangle)

        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        menu.set_margin_top(5)
        menu.set_margin_bottom(5)
        menu.set_margin_start(5)
        menu.set_margin_end(5)
        popover.set_child(menu)

        self.context_submenus.clear()
        self.qa_submenu_button = None
        new_folder = self._menu_button(
            "New Folder…",
            lambda: self._show_create_dialog("folder"),
            icon_name="folder-new-symbolic",
        )
        new_text = self._menu_button(
            "New Text File",
            lambda: self._show_create_dialog("text"),
            icon_name="document-new-symbolic",
        )
        can_create = not self.file_job_active and self.special_mode is None and os.access(self.current_dir, os.W_OK)
        new_folder.set_sensitive(can_create)
        new_text.set_sensitive(can_create)
        if path is None:
            menu.append(new_folder)
            menu.append(new_text)
            menu.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        paths = self._selected_paths() if path else []
        if path and path not in paths: paths = [path]
        self._append_common_context(menu, paths, background=path is None, qa=keep_open_for_qa)

        if path and len(paths) == 1 and path.is_file() and path.suffix.casefold() in IMAGE_TYPES:
            menu.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            resize_items = [
                (
                    size.title(),
                    f"{pixels} px",
                    "image-x-generic-symbolic",
                    lambda p=path, s=size: self._resize_image(p, s),
                )
                for size, pixels in IMAGE_SIZE_PIXELS.items()
            ]
            menu.append(self._submenu_button(
                "Resize Image",
                "image-x-generic-symbolic",
                resize_items,
                keep_open_for_qa=keep_open_for_qa,
            ))
            format_items = [
                (
                    image_format.upper(),
                    "",
                    "image-x-generic-symbolic",
                    lambda p=path, f=image_format: self._convert_image(p, f),
                )
                for image_format in ("jpeg", "png", "webp", "avif")
            ]
            menu.append(self._submenu_button(
                "Convert Image",
                "view-refresh-symbolic",
                format_items,
                keep_open_for_qa=keep_open_for_qa,
            ))

        if path and len(paths) == 1 and path.is_file() and path.suffix.casefold() in VIDEO_TYPES:
            menu.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            video_items = [
                (
                    video_format.upper(),
                    "",
                    "video-x-generic-symbolic",
                    lambda p=path, f=video_format: self._convert_video(p, f),
                )
                for video_format in ("mp4", "webm", "mov", "gif")
            ]
            menu.append(self._submenu_button(
                "Convert Video",
                "video-x-generic-symbolic",
                video_items,
                keep_open_for_qa=keep_open_for_qa,
            ))

        self.context_popover = popover
        popover.popup()
        if automation == "context-submenu" and self.qa_submenu_button:
            GLib.timeout_add(150, self._open_qa_submenu)

    def _open_qa_submenu(self) -> bool:
        if self.qa_submenu_button:
            self.qa_submenu_button.popup()
        return GLib.SOURCE_REMOVE

    def _close_context_menu(self) -> None:
        for submenu in list(self.context_submenus):
            submenu.popdown()
        if self.context_popover:
            self.context_popover.popdown()

    def _on_context_closed(self, popover: Gtk.Popover) -> None:
        if self.context_popover is popover:
            if self.view_mode == 'columns' and self.columns.active:
                self.columns.focus_column(self.columns.active)
            self.context_popover = None
        GLib.idle_add(self._unparent_popover, popover)

    @staticmethod
    def _unparent_popover(popover: Gtk.Popover) -> bool:
        if popover.get_parent() is not None:
            popover.unparent()
        return GLib.SOURCE_REMOVE

    def _show_create_dialog(self, kind: str) -> None:
        if kind == "text":
            try:
                destination = create_untitled_text(self.current_dir)
            except OSError as error:
                self._show_error("Could not create text file", str(error))
                return
            self._refresh_files([destination])
            child = self.children_by_path.get(destination)
            if child:
                child.grab_focus()
            return
        directory = self.current_dir
        dialog = PickerDialog(self, 'New Folder', subtitle='Create a folder in the current location.')
        dialog.body.append(file_summary(directory, detail='Create inside this folder'))
        entry = Gtk.Entry(placeholder_text="Folder name")
        entry.set_activates_default(True)
        dialog.body.append(entry_field('Folder name', entry))
        dialog.add_action('Cancel', Gtk.ResponseType.CANCEL)
        create = dialog.add_action('Create folder', Gtk.ResponseType.ACCEPT, role='suggested-action', default=True)
        create.set_sensitive(False)
        def changed(*_):
            dialog.clear_error()
            create.set_sensitive(bool(entry.get_text().strip()))
        entry.connect('changed', changed)

        def on_response(_dialog: Gtk.Dialog, response: int) -> None:
            if response != Gtk.ResponseType.ACCEPT:
                self._dismiss_dialog(dialog)
                return
            name = entry.get_text().strip()
            if not name or name in {".", ".."} or '/' in name or '\0' in name:
                dialog.set_error('Enter a folder name without slashes.', entry)
                return
            destination = directory / name
            try:
                destination.mkdir()
            except OSError as error:
                message = 'An item with this name already exists.' if isinstance(error, FileExistsError) else str(error)
                dialog.set_error(message, entry)
                return
            self._dismiss_dialog(dialog)
            self._load()
            child = self.children_by_path.get(destination)
            if child:
                self.flow.select_child(child)
                child.grab_focus()

        dialog.connect("response", on_response)
        dialog.present()
        entry.grab_focus()
        return dialog

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
                self._show_conversion_notice(output)
            else:
                detail = (stderr or "The converter exited without creating a file.").strip()[-800:]
                self._show_error("Conversion failed", detail)

        process.communicate_utf8_async(None, None, on_finished)

    def _show_conversion_notice(self, output: Path) -> None:
        if not hasattr(self, 'conversion_notice'):
            notice = Gtk.Revealer(halign=Gtk.Align.END, valign=Gtk.Align.END)
            notice.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
            notice.set_transition_duration(180)
            notice.set_margin_end(16)
            notice.set_margin_bottom(16)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.add_css_class('conversion-notice')
            icon = Gtk.Image.new_from_icon_name('emblem-ok-symbolic')
            icon.add_css_class('conversion-success')
            row.append(icon)
            copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            copy.append(label('Conversion complete', 'metadata-title'))
            self.conversion_notice_filename = label('', 'muted')
            self.conversion_notice_filename.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            self.conversion_notice_filename.set_max_width_chars(36)
            copy.append(self.conversion_notice_filename)
            row.append(copy)
            close = self._icon_button('window-close-symbolic', 'Dismiss notification',
                                      lambda *_: self._dismiss_conversion_notice())
            close.add_css_class('flat')
            row.append(close)
            notice.set_child(row)
            self.browser_overlay.add_overlay(notice)
            self.browser_overlay.set_measure_overlay(notice, False)
            self.browser_overlay.set_clip_overlay(notice, True)
            self.conversion_notice = notice
            self.conversion_notice_timer = 0
        self._dismiss_conversion_notice()
        self.conversion_notice_filename.set_text(output.name)
        self.conversion_notice_filename.set_tooltip_text(str(output))
        self.conversion_notice.set_reveal_child(True)
        def expire():
            self.conversion_notice_timer = 0
            self.conversion_notice.set_reveal_child(False)
            return False
        self.conversion_notice_timer = GLib.timeout_add_seconds(8, expire)

    def _dismiss_conversion_notice(self) -> None:
        if self.conversion_notice_timer:
            GLib.source_remove(self.conversion_notice_timer)
            self.conversion_notice_timer = 0
        self.conversion_notice.set_reveal_child(False)

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
        dialog = PickerDialog(self, message, width=520)
        detail_label = text_label(detail, 'error-detail', selectable=True)
        card = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                  vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                  propagate_natural_height=True, max_content_height=240)
        card.add_css_class('dialog-detail-card')
        card.set_child(detail_label)
        dialog.body.append(card)
        done = dialog.add_action('Close', Gtk.ResponseType.CLOSE, role='suggested-action', default=True)
        dialog.connect('response', lambda *_: self._dismiss_dialog(dialog))
        dialog.present()
        done.grab_focus()
        return dialog

    def _show_nas_dialog(self, _button) -> None:
        dialog = PickerDialog(self, 'Connect to NAS', subtitle='Browse shared folders on your network.', width=560)
        content = dialog.body
        entry = Gtk.Entry(placeholder_text="smb://server/share")
        discovery = NetworkBrowser(self, dialog, entry)
        content.append(discovery)
        entry.set_activates_default(True)
        content.append(entry_field('Server or share address', entry,
                                   'SMB  smb://nas/media     ·     NFS  nfs://nas/archive'))
        error_label = dialog.error_label
        cancel = dialog.add_action('Cancel', Gtk.ResponseType.CANCEL)
        connect = dialog.add_action('Connect', Gtk.ResponseType.ACCEPT, role='suggested-action', default=True)
        def changed(*_):
            dialog.clear_error()
            entry.remove_css_class('error')
            connect.set_sensitive(bool(entry.get_text().strip()))
        entry.connect('changed', changed)
        connect.set_sensitive(False)
        mount_cancel = Gio.Cancellable()
        mounting = False

        def on_response(_dialog: Gtk.Dialog, response: int) -> None:
            nonlocal mounting
            if response != Gtk.ResponseType.ACCEPT:
                mount_cancel.cancel()
                self._dismiss_dialog(dialog)
                return
            if mounting:
                return
            try:
                raw = entry.get_text().strip()
                parsed = urlsplit(raw if '://' in raw else 'smb://' + raw)
                if parsed.scheme in {'smb', 'smbs'} and parsed.hostname and not parsed.path.strip('/'):
                    discovery.browse(NetworkLocation(parsed.hostname, safe_network_uri(parsed.geturl()), 'SMB server', True))
                    return
                uri = normalize_nas_uri(entry.get_text())
            except (ActionError, ValueError) as error:
                entry.add_css_class("error")
                error_label.set_text(str(error))
                error_label.set_visible(True)
                return
            error_label.set_visible(False)
            entry.remove_css_class('error')
            connect.set_label('Connecting…')
            mounting = True
            connect.set_sensitive(False)
            entry.set_sensitive(False)
            discovery.set_sensitive(False)
            target = Gio.File.new_for_uri(uri)
            mount_operation = Gtk.MountOperation.new(dialog)

            def on_mounted(source: Gio.File, result) -> None:
                nonlocal mounting
                mounted = True
                try:
                    source.mount_enclosing_volume_finish(result)
                except GLib.Error as error:
                    if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                        mounted = True
                    else:
                        mounted = False
                        mounting = False
                        if not dialog.get_visible():
                            return
                        connect.set_sensitive(True)
                        entry.set_sensitive(True)
                        discovery.set_sensitive(True)
                        connect.set_label('Connect')
                        entry.add_css_class("error")
                        error_label.set_text(error.message)
                        error_label.set_visible(True)
                if not mounted or not dialog.get_visible():
                    return
                self._dismiss_dialog(dialog)
                self._refresh_sidebar()
                self._open_mounted_location(uri)
                self._notify("NAS connected", uri)

            target.mount_enclosing_volume(
                Gio.MountMountFlags.NONE,
                mount_operation,
                mount_cancel,
                on_mounted,
            )

        dialog.connect("response", on_response)
        dialog.present()
        entry.grab_focus()
        return dialog

    def _open_mounted_location(self, uri: str) -> None:
        # Repair the local bridge off the GTK thread; a GFile path alone does
        # not prove that GVfs has exposed the share to ordinary filesystem APIs.
        token = getattr(self, '_mount_open_generation', 0) + 1
        self._mount_open_generation = token
        def complete(path, error):
            if not self.get_visible() or token != self._mount_open_generation:
                return False
            if error:
                self._show_error('Could not open mounted folder', error)
            else:
                self.navigate(path)
            return False
        def worker():
            try:
                path, error = mounted_local_path(uri), None
            except (OSError, RuntimeError, GLib.Error) as exc:
                path, error = None, str(exc)
            GLib.idle_add(complete, path, error)
        threading.Thread(target=worker, daemon=True).start()

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
        if self.request.explorer:
            if len(selected) == 1 and selected[0].is_dir():
                self.navigate(selected[0])
                return
            for path in selected:
                if path.is_file():
                    try:
                        Gio.AppInfo.launch_default_for_uri(safe_uri(path), None)
                    except GLib.Error as error:
                        self._show_error(f'Could not open {path.name}', error.message)
            return
        if self.request.mode == "save":
            name = self.filename_entry.get_text().strip()
            if not name or "/" in name or name in (".", ".."):
                self.filename_entry.add_css_class("error")
                return
            path = self.current_dir / name
            if path.exists() and path.is_file():
                confirmation(self, 'Replace existing file?',
                             'Saving will replace this file’s current contents.', 'Replace', [path],
                             lambda: self._finish(paths=[path]), destructive=True)
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
        if self._guard_transfer_close(lambda: self._finish(cancelled=cancelled, paths=paths)):
            return
        if self.file_job_active:
            self._show_error('File operation in progress', 'Wait for the operation to finish before closing the picker.')
            return
        if self.sidebar_save_timer:
            self._save_sidebar_width()
        self.media_details.close()
        if self.request.explorer:
            self.get_application().quit()
            return
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
        self._mount_open_generation = getattr(self, '_mount_open_generation', 0) + 1
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
        self._refresh_files()

    def _set_view(self, mode: str) -> None:
        if self.view_mode == mode or mode not in ('grid', 'list', 'columns'):
            return
        selected = self._selected_paths()
        self.drag_selection.cancel()
        if self.view_mode == 'columns':
            self.columns.reset()
            self.flow = self.standard_flow
            self.file_scroller = self.standard_scroller
            self.selection_changed_handler = self.standard_selection_handler
            self.children_by_path = {}
        self.view_mode = mode
        for name, button in (('grid', self.grid_button), ('list', self.list_button), ('columns', self.columns_button)):
            (button.add_css_class if name == mode else button.remove_css_class)('active')
        if mode == 'columns':
            # Hidden standard rows must not retain stale selections or badges.
            self.flow.remove_all()
            self.children_by_path = {}
            self._refresh_files(selected)
            return
        self.flow.remove_all()
        self.children_by_path = {}
        self.flow.set_homogeneous(False)
        self.flow.set_max_children_per_line(6 if mode == "grid" else 1)
        self.flow.set_row_spacing(12 if mode == "grid" else 0)
        self.flow.set_column_spacing(12 if mode == "grid" else 0)
        if mode == "list":
            self.flow.add_css_class('file-list')
        else:
            self.flow.remove_css_class('file-list')
        self._refresh_files(selected)

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

    def _on_close_requested(self, _window):
        self._finish(cancelled=True)
        return True


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
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--multiple", dest="multiple", action="store_true", default=None,
                           help="Allow multiple selections (default for standalone Open)")
    selection.add_argument("--single", dest="multiple", action="store_false",
                           help="Restrict standalone Open to one selection")
    parser.add_argument("--directory", action="store_true")
    args = parser.parse_args(argv)
    if args.request:
        request = PickerRequest.from_dict(json.loads(args.request.read_text(encoding="utf-8")))
    else:
        folder = Path(args.demo or Path.cwd()).expanduser()
        explorer = args.mode == 'open' and not args.directory and args.result is None
        request = PickerRequest(
            mode=args.mode,
            explorer=explorer,
            title="Files" if explorer else ("Save File" if args.mode == "save" else "Open File"),
            accept_label="Save" if args.mode == "save" else ("Select Folder" if args.directory else "Open"),
            current_folder=folder if folder.is_dir() else folder.parent,
            current_name="untitled.txt" if args.mode == "save" else "",
            multiple=args.mode == "open" and args.multiple is not False,
            directory=args.directory or args.mode == "save_files",
        )
    return request, args.result


def main(argv: list[str] | None = None) -> int:
    request, result_path = parse_args(argv if argv is not None else sys.argv[1:])
    return PickerApplication(request, result_path).run([])


if __name__ == "__main__":
    raise SystemExit(main())
