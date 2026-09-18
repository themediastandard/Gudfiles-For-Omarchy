from __future__ import annotations

import argparse
import json
import mimetypes
import os
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
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from .actions import (
    IMAGE_SIZE_PIXELS,
    ActionError,
    image_convert_command,
    image_resize_command,
    normalize_nas_uri,
    video_convert_command,
)
from .filename_display import display_filename
from .model import PickerRequest, file_type, format_size, list_directory, recent_files, safe_uri
from .theme import build_css, load_colors, prepare_colors
from .file_management import FileManagement, SIDEBAR_MIN_WIDTH
from .file_actions import create_untitled_text, sort_entries
from .dialogs import PickerDialog, confirmation, entry_field, file_summary, text_label
from .quicklook import QuickLook
from .drag_selection import BackgroundSelection
from .drag_copy import DragCopy, disable_native_rubberband
from .network_ui import NetworkBrowser
from .network import NetworkLocation, safe_network_uri, mounted_local_path, mount_display_name
from .creative import CreativeTools
from .hover_scrub import HoverScrub
from .folder_watch import FolderWatch
from .media_details import MediaDetailsService, make_details_widget
from .breadcrumbs import BreadcrumbButton, BreadcrumbTrail, scroll_breadcrumbs
from .columns import ColumnBrowser
from .view_status import ViewStatus
from .folder_size_ui import FolderSizes
from .sidebar import SidebarMenus
from .help_window import show_help
from .list_navigation import navigate_files
from .tabs import BrowserTabs
from .toolbar import AdaptiveToolbar
from .list_details import ListDetails
from .list_metadata import ANNOTATION_COLUMNS, EXTRA_SORTS, annotation_values
from .search_ui import SearchTools
from .context_menu import HoverSubmenus
from .thumbnails import IMAGE_TYPES, RAW_TYPES, VIDEO_TYPES, thumbnail_file
from .thumbnail_widgets import Thumbnail


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


def picture_for(path: Path, width: int, height: int, *, crop: bool = True, priority: int = 1) -> Gtk.Widget:
    # Guess from the name; synchronous GIO content probes can read entire RAWs.
    content_type, _ = Gio.content_type_guess(path.name, None)
    icon = Gio.content_type_get_icon(content_type) if content_type else Gio.ThemedIcon.new('text-x-generic-symbolic')
    if path.is_dir():
        icon = Gio.ThemedIcon.new('folder-symbolic')
    return Thumbnail(path, width, height, icon, thumbnail_file, crop=crop, priority=priority)


def label(text: str, css_class: str | None = None, *, xalign: float = 0.0) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=xalign)
    if css_class:
        widget.add_css_class(css_class)
    return widget


class PickerWindow(SearchTools, SidebarMenus, CreativeTools, FileManagement, Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, request: PickerRequest, result_path: Path | None,
                 *, on_result=None):
        title = 'Choose Folder' if request.directory and request.title == 'Open File' else request.title
        super().__init__(application=app, title=title)
        self.request = request
        self.result_path = result_path
        self.on_result = on_result
        self.finished = False
        self.current_dir = request.current_folder
        self.special_mode: str | None = None
        self.history = [self.current_dir]
        self.history_index = 0
        self.show_hidden = any(path.name.startswith('.') for path in request.selected_paths)
        self.view_mode = "grid"
        self.entries: list[Path] = []
        self.children_by_path: dict[Path, Gtk.FlowBoxChild] = {}
        self.location_buttons: list[Gtk.Button] = []
        self.choice_widgets: dict[str, Gtk.Widget] = {}
        self._init_file_management()
        self._init_folder_locations()
        self._init_creative()
        self.media_details = MediaDetailsService()
        self.connect('unrealize', lambda *_: self.media_details.close())
        self.active_processes: set[Gio.Subprocess] = set()
        self.context_popover: Gtk.Popover | None = None
        self.context_submenus: list[Gtk.Popover] = []
        self.qa_submenu_button: Gtk.MenuButton | None = None
        self.volume_monitor = Gio.VolumeMonitor.get()
        self._init_search()

        self.set_default_size(1200, 800)
        if not request.explorer:
            width, height = 1750, 1200
            monitors = self.get_display().get_monitors()
            if monitors.get_n_items():
                bounds = monitors.get_item(0).get_geometry()
                width = min(width, max(820, int(bounds.width * .9)))
                height = min(height, max(560, int(bounds.height * .9)))
            self.set_default_size(width, height)
        self.set_size_request(820, 560)
        self.add_css_class("picker-root")
        if not request.explorer:
            self.add_css_class('file-chooser')
        self._install_theme()
        self._build_header()
        self._build_content()
        self.quicklook = QuickLook(self)
        self.preview_overlay.add_overlay(self.quicklook)
        self.preview_overlay.set_measure_overlay(self.quicklook, False)
        self.preview_overlay.set_clip_overlay(self.quicklook, True)
        mount_handlers = [self.volume_monitor.connect(signal, lambda *_args: self._refresh_sidebar())
                          for signal in ('mount-added', 'mount-removed')]
        self.connect('unrealize', lambda *_: [self.volume_monitor.disconnect(handler)
                                            for handler in mount_handlers])
        self._install_shortcuts()
        self.connect('close-request', self._on_close_requested)
        if self.file_preferences['view_mode'] == self.view_mode:
            self._load()
        else:
            self._set_view(self.file_preferences['view_mode'], persist=False)
        self.tabs.initialize()
        self.folder_watch = FolderWatch(self)
        if request.explorer and request.selected_paths:
            from .reveal import reveal_initial_selection
            reveal_initial_selection(self)
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
        colors = prepare_colors(load_colors())
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
        header.add_css_class('compact-header')
        self.help_button = Gtk.Button.new_from_icon_name('help-browser-symbolic')
        self.help_button.set_valign(Gtk.Align.CENTER)
        self.help_button.add_css_class('header-utility')
        self.help_button.update_property([Gtk.AccessibleProperty.LABEL], ['Help'])
        self.help_button.set_tooltip_text('Help · Features and shortcuts (F1)')
        self.help_button.connect('clicked', lambda *_: show_help(self))
        self._build_transfer_button()
        header.set_show_title_buttons(False)
        self.set_titlebar(header)

    def _build_content(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.preview_overlay = Gtk.Overlay()
        self.preview_overlay.set_child(root)
        self.set_child(self.preview_overlay)

        body = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        body.add_css_class('sidebar-split')
        body.set_wide_handle(False)
        body.set_resize_start_child(False)
        body.set_resize_end_child(True)
        body.set_shrink_start_child(False)
        body.set_shrink_end_child(False)
        self.sidebar_split = body
        self.sidebar_save_timer = 0
        body.set_vexpand(True)
        root.append(body)

        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.sidebar.add_css_class("sidebar")
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_min_content_width(SIDEBAR_MIN_WIDTH)
        sidebar_scroll.set_size_request(SIDEBAR_MIN_WIDTH, -1)
        sidebar_scroll.set_child(self.sidebar)
        self.sidebar_scroll = sidebar_scroll
        body.set_start_child(sidebar_scroll)
        self._build_sidebar()
        self._install_sidebar_context()

        browser = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        browser.set_hexpand(True)
        browser.set_vexpand(True)
        body.set_end_child(browser)
        body.set_position(self.file_preferences['sidebar_width'])
        body.connect('notify::position', self._sidebar_resized)

        self.tabs = BrowserTabs(self)
        browser.append(self.tabs)
        self.update_notice = None
        if self.request.explorer and not self.request.external:
            from .update_ui import UpdateNotice
            self.update_notice = UpdateNotice(self)
            browser.append(self.update_notice)

        self.toolbar = AdaptiveToolbar(compact=True)
        self._build_toolbar()
        self.toolbar.set_valign(Gtk.Align.CENTER)
        self.toolbar.add_action_group('Tools', (self.transfer_button, self.help_button), utility=True)
        self.toolbar.add_action_group('Window', (Gtk.WindowControls(side=Gtk.PackType.END),), utility=True)
        self.get_titlebar().set_title_widget(self.toolbar)
        browser.append(self._build_active_filters())
        browser.append(self._build_search_status())

        self.browser_stack = Gtk.Stack()
        self.browser_stack.set_hhomogeneous(False)
        self.browser_stack.set_vhomogeneous(False)
        self.browser_stack.set_vexpand(True)
        self.browser_stack.set_hexpand(True)
        self.browser_overlay = Gtk.Overlay()
        self.browser_overlay.set_child(self.browser_stack)
        browser.append(self.browser_overlay)

        self.flow = Gtk.FlowBox()
        disable_native_rubberband(self.flow)
        self.flow.set_activate_on_single_click(False)
        self.flow.set_selection_mode(
            Gtk.SelectionMode.MULTIPLE if self.request.multiple else Gtk.SelectionMode.SINGLE
        )
        self.flow.set_row_spacing(12)
        self.flow.set_column_spacing(12)
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_min_children_per_line(1)
        self.flow.set_max_children_per_line(100)
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
        self.list_details = ListDetails(self)
        browser.insert_child_after(self.list_details.widget, self.browser_overlay.get_prev_sibling())
        self.columns = ColumnBrowser(self)
        self.browser_stack.add_named(self.columns, 'columns')
        self.drag_selection = BackgroundSelection(self)
        self.browser_overlay.add_overlay(self.drag_selection)
        self.browser_overlay.set_measure_overlay(self.drag_selection, False)
        self.browser_overlay.set_clip_overlay(self.drag_selection, True)
        self.drag_copy = DragCopy(self)

        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        empty.set_halign(Gtk.Align.CENTER)
        empty.set_valign(Gtk.Align.CENTER)
        empty.append(Gtk.Image.new_from_icon_name("folder-open-symbolic"))
        self.empty_title = label("Nothing here", "empty-title", xalign=0.5)
        empty.append(self.empty_title)
        self.empty_detail = label("Try another folder or search.", "muted", xalign=0.5)
        self.empty_detail.set_wrap(True)
        self.empty_detail.set_max_width_chars(48)
        empty.append(self.empty_detail)
        self.browser_stack.add_named(empty, "empty")

        self.folder_sizes = FolderSizes(self)
        self.view_status = ViewStatus(self)
        browser.append(self.view_status)

        self.metadata = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.metadata.add_css_class("metadata-strip")
        # Preview content must never contribute a new minimum/natural window
        # size. Reserve a fixed height only while a media preview is visible.
        self.metadata_viewport = Gtk.Overlay()
        reserved_strip = Gtk.Box()
        reserved_strip.set_size_request(-1, 113)  # 92 content + padding and border.
        self.metadata_viewport.set_child(reserved_strip)
        self.metadata_viewport.add_overlay(self.metadata)
        self.metadata_viewport.set_measure_overlay(self.metadata, False)
        self.metadata_viewport.set_clip_overlay(self.metadata, True)
        browser.append(self.metadata_viewport)
        self.metadata_viewport.set_visible(False)

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
        button._sidebar_kind = 'location'
        button._sidebar_key = text.casefold()
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(14)
        row.append(icon)
        item_label = label(display_filename(text))
        item_label.set_hexpand(True)
        item_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        item_label.set_max_width_chars(20)
        button.set_tooltip_text(display_filename(text))
        row.append(item_label)
        button.set_child(row)
        button.connect("clicked", callback)
        self.location_buttons.append(button)
        return button

    def _build_sidebar(self) -> None:
        self.sidebar.append(label("PLACES", "sidebar-heading"))
        home = Path.home()
        locations = [
            ("Home", "user-home-symbolic", home),
            ("Downloads", "folder-download-symbolic", home / "Downloads"),
            ("Documents", "folder-documents-symbolic", home / "Documents"),
            ("Music", "folder-music-symbolic", home / "Music"),
            ("Pictures", "folder-pictures-symbolic", home / "Pictures"),
            ("Videos", "folder-videos-symbolic", home / "Videos"),
            ("Projects", "folder-symbolic", home / "Documents/Omarchy"),
            ("Recent", "document-open-recent-symbolic", None),
            ("Trash", "user-trash-symbolic", None),
        ]
        existing_locations = {path for _, _, path in locations if path is not None}
        for name, icon, path in locations:
            if name.casefold() in self.file_preferences['hidden_locations']:
                continue
            if path is not None and not path.exists():
                continue
            if name == "Recent":
                button = self._sidebar_button('Recent Files', icon, lambda _b: self._open_recent())
                button._sidebar_key = 'recent'
            elif name == "Trash":
                button = self._sidebar_button(name, icon, lambda _b: self._open_trash())
            else:
                button = self._sidebar_button(name, icon, lambda _b, p=path: self.navigate(p))
                button._picker_path = path  # type: ignore[attr-defined]
            self.sidebar.append(button)

        extra_bookmarks = [(path, name) for path, name in self._bookmarks() if path not in existing_locations]
        for path, name in extra_bookmarks:
            button = self._sidebar_button(name, 'folder-symbolic', lambda _b, p=path: self.navigate(p))
            button._picker_path = path
            button._sidebar_kind = 'bookmark'
            self.sidebar.append(button)
        self._append_folder_sections()
        # Group from the mount's native URI: GVfs exposes network shares as
        # local paths too, so checking the filesystem path mislabels them.
        network, devices = [], []
        seen: set[str] = set()
        for mount in self.volume_monitor.get_mounts():
            root = mount.get_root().get_path()
            if not root or root in seen:
                continue
            seen.add(root)
            scheme = mount.get_root().get_uri().partition(':')[0].lower()
            target = devices if scheme in {'file', 'mtp', 'gphoto2', 'afc'} else network
            target.append(mount)

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        heading.add_css_class('sidebar-section')
        title = label('NETWORK', 'sidebar-heading')
        title.set_hexpand(True)
        heading.append(title)
        connect = self._sidebar_button('Connect to NAS…', 'list-add-symbolic', self._show_nas_dialog)
        connect.remove_css_class('location-button')
        connect.add_css_class('sidebar-connect')
        connect.set_child(Gtk.Image.new_from_icon_name('list-add-symbolic'))
        connect.update_property([Gtk.AccessibleProperty.LABEL], ['Connect to NAS'])
        connect._sidebar_kind = 'connect'
        heading.append(connect)
        self.sidebar.append(heading)
        self._append_sidebar_mounts(network, 'network-server-symbolic')
        if devices:
            heading = label('DEVICES', 'sidebar-heading')
            heading.add_css_class('sidebar-section')
            self.sidebar.append(heading)
            self._append_sidebar_mounts(devices, 'drive-harddisk-symbolic')

    def _append_sidebar_mounts(self, mounts, icon_name):
        for mount in mounts:
            root = mount.get_root().get_path()
            path = Path(root)
            uri = mount.get_root().get_uri()
            button = self._sidebar_button(
                mount_display_name(mount.get_name(), uri), icon_name,
                lambda _b, uri=uri: self._open_mounted_location(uri)
            )
            button.set_tooltip_text(safe_network_uri(uri) or str(path))
            button._picker_path = path  # type: ignore[attr-defined]
            button._sidebar_kind = 'mount'
            button._sidebar_mount = mount
            row = Gtk.Box()
            row.add_css_class('sidebar-mount-row')
            button.set_hexpand(True)
            row.append(button)
            if mount.can_eject() or mount.can_unmount():
                action = self._sidebar_mount_action(mount)
                name = mount_display_name(mount.get_name(), uri)
                remove = Gtk.Button.new_from_icon_name('media-eject-symbolic')
                remove.add_css_class('sidebar-unmount')
                remove.set_valign(Gtk.Align.CENTER)
                remove.set_tooltip_text(f'{action} {name}')
                remove.update_property([Gtk.AccessibleProperty.LABEL], [f'{action} {name}'])
                remove._sidebar_owner = button
                remove.connect('clicked', lambda _b, m=mount: self._remove_sidebar_mount(m))
                button._unmount_button = remove
                remove.set_sensitive(uri not in getattr(self, 'sidebar_mount_operations', {}))
                row.append(remove)
            self.sidebar.append(row)

    def _open_trash(self) -> None:
        self._open_special('trash')

    def _show_trash(self):
        from .trash_ui import TrashPage
        if not hasattr(self, 'trash_page'):
            self.trash_page = TrashPage(self)
            self.browser_stack.add_named(self.trash_page, 'trash')
        self._cancel_computer_search()
        if self.quicklook.get_visible():
            self.quicklook.close()
        self.drag_selection.cancel()
        self.columns.cancel_pending()
        self._close_context_menu()
        self.entries = []
        self.list_details.reset()
        self.list_details.widget.set_visible(False)
        self._clear_metadata()
        self.browser_stack.set_visible_child_name('trash')
        state = getattr(self, '_trash_restore_state', None)
        self._trash_restore_state = None
        self.trash_page.activate(state)
        self._rebuild_pathbar()
        self._update_nav_state()
        self._update_active_location()
        self._update_accept_state()

    def _refresh_sidebar(self) -> None:
        if not hasattr(self, "sidebar"):
            return
        self._close_context_menu()
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
        self.up_button = self._icon_button("go-up-symbolic", "Up one folder (Alt+Up)", self._go_up)
        self.up_button.update_property([Gtk.AccessibleProperty.LABEL], ['Up one folder'])
        self.toolbar.navigation.append(self.back_button)
        self.toolbar.navigation.append(self.forward_button)
        self.toolbar.navigation.append(self.up_button)

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
        self.path_reveal_tick = 0
        # GtkViewport emits this while allocating. Changing the scroll value
        # there can leave its child positioned at the previous folder's offset.
        self.path_scroll.get_hadjustment().connect('changed', lambda _adjustment: self._reveal_current_breadcrumb())
        self.path_wheel = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.BOTH_AXES)
        self.path_wheel.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.path_wheel.connect('scroll', self._on_path_scroll)
        self.path_scroll.add_controller(self.path_wheel)
        self.path_stack.add_named(self.path_scroll, "crumbs")
        self.path_entry = Gtk.Entry()
        self.path_entry.add_css_class('compact-location')
        self.path_entry.set_width_chars(1)
        self.path_entry.connect("activate", self._on_path_activate)
        self.path_stack.add_named(self.path_entry, "entry")
        self.path_stack.set_visible_child_name("crumbs")
        self.toolbar.navigation.append(self.path_stack)

        location_button = self._icon_button("document-edit-symbolic", "Type a location (Ctrl+L)", self._toggle_path_entry)
        self.toolbar.navigation.append(location_button)

        self.search_button = Gtk.MenuButton(icon_name='system-search-symbolic')
        self.search_button.set_tooltip_text('Search (Ctrl+F)')
        self.search_button.update_property([Gtk.AccessibleProperty.LABEL], ['Search'])
        self.search_popover = Gtk.Popover()
        self.search_popover.add_css_class('compact-popover')
        self.search_button.set_popover(self.search_popover)
        self._build_search_controls()
        self.search_popover.connect('map', lambda *_: self.search.grab_focus())
        filters = self._creative_filter_button()
        self.rating_filter_button = filters

        self.hidden_button = self._icon_button("view-conceal-symbolic", "Show hidden files (Ctrl+H)", self._toggle_hidden)
        self.hidden_button.add_css_class('hidden-toggle')
        self.toolbar.add_action_group('Find and filter', (self.search_button, filters, self.hidden_button))
        sort = self._build_sort_button()
        self.list_button = self._icon_button("view-list-symbolic", "List view", lambda _b: self._set_view("list"))
        self.grid_button = self._icon_button("view-grid-symbolic", "Grid view", lambda _b: self._set_view("grid"))
        self.columns_button = self._icon_button('view-dual-symbolic', 'Column view', lambda _b: self._set_view('columns'))
        self.toolbar.add_action_group('Sort and view', (sort, self.grid_button, self.list_button, self.columns_button))
        self.grid_button.add_css_class('active')
        for row in (self.toolbar.navigation, self.toolbar.actions):
            child = row.get_first_child()
            while child:
                if isinstance(child, (Gtk.Button, Gtk.MenuButton)):
                    child.add_css_class('compact-control')
                child = child.get_next_sibling()

    def _open_search(self):
        self.search_button.popup()
        self.search.grab_focus()
        self.search.select_region(0, -1)

    def _search_activated(self, _entry):
        # Apply immediately if Return beats SearchEntry's debounce timer.
        self._search_changed(self.search)
        self.search_button.popdown()
        if self.special_mode == 'trash':
            self.trash_page.rows.grab_focus()
        else:
            self.flow.child_focus(Gtk.DirectionType.TAB_FORWARD)

    def _build_footer(self) -> None:
        prompt = 'Choose a folder · Files shown for reference' if self.request.directory else self.request.title
        self.chooser_prompt = label(prompt, 'muted')
        self.chooser_prompt.set_ellipsize(Pango.EllipsizeMode.END)
        self.chooser_prompt.set_max_width_chars(60)
        self.chooser_prompt.set_visible(False)
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
        # Honor the caller's selected filter without adding chooser chrome.
        self.filter_combo.set_visible(False)

        if self.request.mode == "save":
            self.filename_entry = Gtk.Entry(placeholder_text="File name")
            self.filename_entry.set_text(self.request.current_name)
            self.filename_entry.set_hexpand(True)
            self.filename_entry.connect("changed", lambda _entry: self._update_accept_state())
            self.filename_entry.connect("activate", lambda _entry: self._accept())
            row.append(self.filename_entry)
        else:
            selection_text = f"Current folder: {display_filename(self.current_dir.name) or '/'}" if self.request.directory else "No file selected"
            self.selection_label = label(selection_text, "muted")
            self.selection_label.set_hexpand(True)
            self.selection_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            self.selection_label.set_max_width_chars(36)
            self.selection_label.set_visible(False)
            row.append(Gtk.Box(hexpand=True))

        cancel = Gtk.Button(label="Cancel")
        cancel.set_valign(Gtk.Align.CENTER)
        cancel.add_css_class('chooser-action')
        cancel.connect("clicked", lambda _button: self._finish(cancelled=True))
        row.append(cancel)
        self.accept_button = Gtk.Button(label=self.request.accept_label)
        self.accept_button.set_valign(Gtk.Align.CENTER)
        self.accept_button.add_css_class('chooser-action')
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

    def _search_changed(self, entry):
        if entry.get_text() != self._last_search:
            self._last_search = entry.get_text()
            self._refresh_files()

    def _on_preview_key(self, _controller, keyval, _keycode, state):
        if keyval == Gdk.KEY_F1 and not self.drag_copy.active and not self.drag_selection.active:
            if self.context_popover:
                self._close_context_menu()
            show_help(self)
            return Gdk.EVENT_STOP
        if self.context_popover:
            return Gdk.EVENT_PROPAGATE
        if self.drag_copy.active:
            if keyval == Gdk.KEY_Escape:
                self.drag_copy.cancel()
            return Gdk.EVENT_STOP
        if not self.quicklook.get_visible() and self.tabs.shortcut(keyval, state):
            return Gdk.EVENT_STOP
        if self.special_mode == 'trash':
            return Gdk.EVENT_PROPAGATE
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
            if keyval in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Left, Gdk.KEY_Right) and not editing \
                    and not isinstance(self.get_focus(), Gtk.Range) and not state & (
                        Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK):
                self.quicklook.step(-1 if keyval in (Gdk.KEY_Up, Gdk.KEY_Left) else 1)
                return Gdk.EVENT_STOP
            # Preview must not accept/delete/rename a file behind the overlay.
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_F2) or \
                    self._remove_shortcut(keyval, state):
                return Gdk.EVENT_STOP
            return Gdk.EVENT_PROPAGATE
        editing = isinstance(self.get_focus(), (Gtk.Editable, Gtk.TextView))
        modifiers = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK)
        if navigate_files(self, keyval, state):
            return Gdk.EVENT_STOP
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
        if keyval == Gdk.KEY_Escape and self.search_popover.get_visible():
            self.search_button.popdown()
            return Gdk.EVENT_STOP
        if keyval == Gdk.KEY_Escape and self.context_popover:
            self._close_context_menu()
            return Gdk.EVENT_STOP
        if self.context_popover:
            return Gdk.EVENT_PROPAGATE
        if not editing and control and not shift and keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            self._undo_file_action()
            return Gdk.EVENT_STOP
        if self.special_mode == 'trash' and not editing:
            if keyval == Gdk.KEY_F5:
                self.trash_page.refresh()
                return Gdk.EVENT_STOP
            if control and keyval in (Gdk.KEY_a, Gdk.KEY_A):
                self.trash_page.rows.select_all()
                return Gdk.EVENT_STOP
            if keyval == Gdk.KEY_Menu or (shift and keyval == Gdk.KEY_F10):
                if button := self._sidebar_target(focus):
                    self._show_sidebar_context_menu(0, 0, button, keyboard=True)
                else:
                    self.trash_page.show_menu(24, 42)
                return Gdk.EVENT_STOP
        if not editing and self.special_mode != 'trash':
            selected = self._selected_paths()
            if keyval == Gdk.KEY_Menu or (shift and keyval == Gdk.KEY_F10):
                button = self._sidebar_target(focus)
                if button:
                    self._show_sidebar_context_menu(0, 0, button, keyboard=True)
                else:
                    self._show_context_menu(24, 24, selected[0] if selected else None, keyboard=True)
                return Gdk.EVENT_STOP
            if self.file_job_active and (keyval == Gdk.KEY_F2 or self._remove_shortcut(keyval, state) or
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
            if self._remove_shortcut(keyval, state) and selected:
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
                self._go_up(None)
                return Gdk.EVENT_STOP
            if alt and keyval == Gdk.KEY_Return:
                self._show_properties(selected or [self.current_dir])
                return Gdk.EVENT_STOP
        if keyval == Gdk.KEY_Escape:
            if self.path_stack.get_visible_child_name() == "entry":
                self._toggle_path_entry(None)
            elif self.search.get_text():
                self.search.set_text("")
            elif self.special_mode == 'trash':
                self.trash_page.rows.unselect_all()
            elif self.request.explorer:
                self.flow.unselect_all()
            else:
                self._finish(cancelled=True)
            return Gdk.EVENT_STOP
        if control and keyval in (Gdk.KEY_l, Gdk.KEY_L):
            self._toggle_path_entry(None)
            return Gdk.EVENT_STOP
        if control and keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self._open_search()
            return Gdk.EVENT_STOP
        if control and keyval in (Gdk.KEY_h, Gdk.KEY_H):
            if self.special_mode != 'trash':
                self._toggle_hidden(None)
            return Gdk.EVENT_STOP
        if alt and keyval == Gdk.KEY_Left:
            self._go_back(None)
            return Gdk.EVENT_STOP
        if alt and keyval == Gdk.KEY_Right:
            self._go_forward(None)
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    @staticmethod
    def _remove_shortcut(keyval, state):
        return keyval == Gdk.KEY_Delete or (
            keyval == Gdk.KEY_BackSpace and bool(state & Gdk.ModifierType.SUPER_MASK))

    def _active_filter(self):
        if self.request.directory:
            return None
        index = self.filter_combo.get_active() - 1
        if 0 <= index < len(self.request.filters):
            return self.request.filters[index]
        return None

    def _sort_entries(self, entries, *, metadata=None):
        prefs = self.file_preferences
        if prefs['sort_key'] in EXTRA_SORTS:
            metadata = {**(metadata or {}), **self.list_details.data}
            if prefs['sort_key'] == 'size':
                for path in entries:
                    if self._entry_is_dir(path):
                        result = self.folder_sizes.result(path)
                        metadata[path] = dict(metadata.get(path, {}), directory=True,
                                              size=result.total if result and result.complete else None)
        elif prefs['sort_key'] in ANNOTATION_COLUMNS:
            metadata = {path: dict(annotation_values(self.ratings.get(path)),
                                   directory=self._entry_is_dir(path)) for path in entries}
        return sort_entries(entries, prefs['sort_key'], prefs['descending'],
                            prefs['folders_first'], metadata=metadata)

    def _directory_entries(self, path):
        entries = list_directory(path, show_hidden=self.show_hidden,
            active_filter=self._active_filter(), query=self.search.get_text(),
            directories_only=self.request.directories_only)
        return self._sort_entries(self._creative_entries(entries))

    def _load(self) -> None:
        if getattr(self, "_restoring_tab", False):
            return
        watcher = getattr(self, 'folder_watch', None)
        if watcher:
            watcher.suspend()
        self._last_search = self.search.get_text()
        self._update_active_filters()
        trash = self.special_mode == 'trash'
        if trash:
            self.active_filters.set_visible(False)
            self.search_scope = 'folder'
        self.sort_button.set_sensitive(True)
        for control in (self.grid_button, self.list_button, self.columns_button):
            control.set_sensitive(True)
        for control in (self.hidden_button, self.rating_filter_button, self.filter_combo):
            control.set_sensitive(not trash)
        self.search_scope_buttons['computer'].set_sensitive(not trash)
        self._update_search_scope()
        if trash:
            self._show_trash()
            if watcher:
                watcher.sync()
            return
        if hasattr(self, 'trash_page'):
            self.trash_page.deactivate()
        query = self.search.get_text() if hasattr(self, "search") else ""
        if self._computer_search_active():
            self._load_computer_search()
            if watcher:
                watcher.sync()
            return
        self._cancel_computer_search()
        if self.special_mode == "recent":
            entries = recent_files()
            if query:
                entries = [item for item in entries if query.casefold() in item.name.casefold()]
            active_filter = self._active_filter() if hasattr(self, "filter_combo") else None
            if active_filter:
                entries = [item for item in entries if active_filter.matches(item)]
            if self.request.directories_only:
                entries = [item for item in entries if item.is_dir()]
            self.entries = entries
        else:
            self.entries = list_directory(
                self.current_dir,
                show_hidden=self.show_hidden,
                active_filter=self._active_filter() if hasattr(self, "filter_combo") else None,
                query=query,
                directories_only=self.request.directories_only,
            )
        self.entries = self._creative_entries(self.entries)
        self.entries = self._sort_entries(self.entries)
        self._rebuild_files()
        self._rebuild_pathbar()
        self._update_nav_state()
        self._update_active_location()

        if watcher:
            watcher.sync()

    def _rebuild_files(self) -> None:
        self.folder_sizes.reset()
        self.view_status.selection = None
        self.list_details.reset()
        self.drag_selection.cancel()
        self._close_context_menu()
        self.empty_title.set_text('Nothing here')
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
            child._picker_is_dir = self._entry_is_dir(path)
            child.set_sensitive(not self.request.directory or child._picker_is_dir)
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
        # Whole-computer results must not launch hundreds of thumbnail decoders.
        if self._computer_search_active():
            poster = Gtk.Image.new_from_gicon(self._search_result_icon(path))
            poster.set_pixel_size(48)
            poster.set_size_request(156, 98)
            thumbnail.set_child(poster)
        else:
            poster = picture_for(path, 156, 98)
            thumbnail.set_child(HoverScrub(path, poster) if path.suffix.casefold() in VIDEO_TYPES else poster)
        badge = self._rating_badge(path)
        badge.set_halign(Gtk.Align.END)
        badge.set_valign(Gtk.Align.START)
        thumbnail.add_overlay(badge)
        thumbnail.set_measure_overlay(badge, False)
        frame.append(thumbnail)
        item.append(frame)
        name = label(display_filename(path.name), "filename", xalign=0.5)
        name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        name.set_width_chars(18)
        name.set_max_width_chars(18)
        item.append(name)
        if self._computer_search_active():
            item.append(self._search_location_label(path))
            item._grid_size_parts = (poster, name, None)
            self.view_status.size_tile(item, self.file_preferences['thumbnail_size'])
            return item
        detail = ""
        try:
            if path.is_dir():
                detail = "…"
            else:
                detail = format_size(path.stat().st_size)
        except OSError:
            detail = file_type(path)
        detail_label = label(detail, "muted", xalign=0.5)
        detail_label.set_ellipsize(Pango.EllipsizeMode.END)
        detail_label.set_max_width_chars(18)
        if self._entry_is_dir(path):
            self.folder_sizes.bind(path, detail_label)
        if isinstance(poster, Thumbnail) and path.suffix.casefold() in IMAGE_TYPES:
            def show_dimensions(pixbuf):
                width, height = (pixbuf.get_option('tEXt::Source' + side) for side in ('Width', 'Height'))
                if width and height:
                    dimensions = f'{width} × {height}'
                    detail_label.set_text(dimensions)
            poster.on_loaded = show_dimensions
        item.append(detail_label)
        item._grid_size_parts = (poster, name, detail_label)
        self.view_status.size_tile(item, self.file_preferences['thumbnail_size'])
        return item

    def _list_item(self, path: Path) -> Gtk.Widget:
        return self.list_details.row(path)

    def _scroll_path_to_current(self, adjustment) -> None:
        adjustment.set_value(max(adjustment.get_lower(), adjustment.get_upper() - adjustment.get_page_size()))

    def _on_path_scroll(self, controller, dx, dy):
        if self.path_reveal_tick:
            self.path_scroll.remove_tick_callback(self.path_reveal_tick)
            self.path_reveal_tick = 0
        return scroll_breadcrumbs(controller, dx, dy, self.path_scroll.get_hadjustment())

    def _reveal_current_breadcrumb(self):
        if self.path_reveal_tick:
            self.path_scroll.remove_tick_callback(self.path_reveal_tick)
        frames = 0

        def reveal(_widget, _clock):
            nonlocal frames
            frames += 1
            # Wait for the new buttons and GTK's focus scrolling to be allocated.
            # Equal-width sibling paths do not emit an adjustment size change.
            if frames < 3:
                return True
            self._scroll_path_to_current(self.path_scroll.get_hadjustment())
            self.path_reveal_tick = 0
            return False

        self.path_reveal_tick = self.path_scroll.add_tick_callback(reveal)

    def _breadcrumb_directory(self):
        # Column selection stays in its parent for drag/file operations, while
        # the path includes the folder whose contents were opened beside it.
        if self.view_mode == 'columns' and self.special_mode is None and not self._computer_search_active():
            active = self.columns.active
            if active in self.columns.columns:
                index = self.columns.columns.index(active) + 1
                selected = active.flow.get_selected_children()
                if index < len(self.columns.columns) and len(selected) == 1:
                    child = self.columns.columns[index]
                    if child.path == selected[0]._picker_path:
                        return child.path
        return self.current_dir

    def _rebuild_pathbar(self) -> None:
        editing_location = (getattr(self, '_refreshing_folder', False) and
                            self.path_stack.get_visible_child_name() == 'entry')
        while child := self.path_box.get_first_child():
            self.path_box.remove(child)
        if self.special_mode in {'recent', 'trash'}:
            button = BreadcrumbButton(self.special_mode.title(), self.colors, first=True, current=True)
            self.path_box.append(button)
            if not editing_location:
                self.path_entry.set_text(self.special_mode + ':///')
            self._reveal_current_breadcrumb()
            return
        path = self._breadcrumb_directory().resolve()
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
        if not editing_location:
            self.path_entry.set_text(str(path))
        self._reveal_current_breadcrumb()

    def _clear_metadata(self) -> None:
        self.media_details.cancel()
        self.metadata_viewport.set_visible(False)
        while child := self.metadata.get_first_child():
            self.metadata.remove(child)

    def _update_metadata(self, path: Path) -> None:
        self._clear_metadata()
        if not self.request.explorer or self.special_mode == 'trash':
            return
        paths = self._selected_paths() or [path]
        # Mixed selections keep their totals in ViewStatus. Preview the first
        # selected media file, with controls scoped to that displayed file.
        path = next((candidate for candidate in paths
                     if candidate.suffix.casefold() in IMAGE_TYPES | RAW_TYPES | VIDEO_TYPES
                     and candidate.is_file()), None)
        if path is None:
            return
        self.metadata_viewport.set_visible(True)
        poster = picture_for(path, 132, 76, crop=True, priority=0)
        self.metadata.append(HoverScrub(path, poster) if path.suffix.casefold() in VIDEO_TYPES else poster)
        primary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, valign=Gtk.Align.CENTER)
        primary.set_size_request(140, -1)
        primary.set_hexpand(True)
        title = label(display_filename(path.name), "metadata-title")
        title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        title.set_max_width_chars(32)
        primary.append(title)
        for detail in (f'{file_type(path)} · {path.parent}',):
            detail_label = label(detail, "muted")
            detail_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            detail_label.set_max_width_chars(36)
            primary.append(detail_label)
        primary.append(self._rating_controls([path]))
        self.metadata.append(primary)
        try:
            stat = path.stat()
            size = "—" if path.is_dir() else format_size(stat.st_size)
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%B %-d, %Y at %-I:%M %p")
        except OSError:
            size, modified = "—", "—"
        facts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5, valign=Gtk.Align.CENTER)
        facts.set_hexpand(True)
        def append_fact(text):
            fact = label(text, 'muted')
            fact.set_ellipsize(Pango.EllipsizeMode.END)
            fact.set_max_width_chars(28)
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
        if hasattr(self, "selection_label") and self.selection_label.get_visible():
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
                self.selection_label.set_text(f"Current folder: {display_filename(self.current_dir.name) or '/'}")
            else:
                self.selection_label.set_text("No file selected")
        self._update_accept_state()

    def _on_child_activated(self, _flow: Gtk.FlowBox, child: Gtk.FlowBoxChild) -> None:
        path = child._picker_path  # type: ignore[attr-defined]
        if path.is_dir():
            if self.view_mode == 'columns' and not self._computer_search_active():
                column = next(c for c in self.columns.columns if c.flow is _flow)
                self.columns.enter_folder(column, path)
            else:
                self.navigate(path)
        elif self.request.directory:
            return
        elif self.request.explorer and path.suffix.casefold() == '.zip':
            self._extract_zip(path)
        else:
            self._accept()

    def _on_context_pressed(self, _gesture: Gtk.GestureClick, _presses: int, x: float, y: float) -> None:
        if self.special_mode == 'trash':
            picked = self.browser_stack.pick(x, y, Gtk.PickFlags.DEFAULT)
            while picked and picked is not self.trash_page and not isinstance(picked, Gtk.FlowBoxChild):
                if isinstance(picked, Gtk.Popover):
                    return
                picked = picked.get_parent()
            if isinstance(picked, Gtk.FlowBoxChild):
                if not picked.is_selected():
                    self.trash_page.rows.unselect_all()
                    self.trash_page.rows.select_child(picked)
            else:
                self.trash_page.rows.unselect_all()
            _gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.trash_page.show_menu(x, y)
            return
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
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_hexpand(True)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(14)
        icon.add_css_class("context-icon")
        row.append(icon)

        copy = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
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
            arrow.set_pixel_size(12)
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
        submenu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        submenu_box.set_margin_top(4)
        submenu_box.set_margin_bottom(4)
        submenu_box.set_margin_start(4)
        submenu_box.set_margin_end(4)
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
        popover = Gtk.Popover(autohide=not keep_open_for_qa, has_arrow=False)
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
        menu.set_margin_top(4)
        menu.set_margin_bottom(4)
        menu.set_margin_start(4)
        menu.set_margin_end(4)
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
        can_create = not self.file_job_active and not self._computer_search_active() and self.special_mode is None and os.access(self.current_dir, os.W_OK)
        new_folder.set_sensitive(can_create)
        new_text.set_sensitive(can_create)
        if path is None:
            menu.append(new_folder)
            menu.append(new_text)
            menu.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        if self.request.explorer:
            if path and path.is_dir():
                menu.append(self._menu_button('Open in New Tab', lambda: self.tabs.new(path),
                                              icon_name='tab-new-symbolic'))
            elif path is None:
                menu.append(self._menu_button('New Tab', lambda: self.tabs.new(), icon_name='tab-new-symbolic'))
        paths = self._selected_paths() if path else []
        if path and path not in paths: paths = [path]
        screenshot_destination = self.current_dir if path is None else path if path.is_dir() else None
        self._append_common_context(menu, paths, background=path is None, qa=keep_open_for_qa,
                                    screenshot_destination=screenshot_destination)

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
        HoverSubmenus(popover)
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
            if popover.get_parent() is self.sidebar_scroll:
                button = getattr(popover, '_sidebar_button', None)
                if button and button.get_root() is self:
                    button.grab_focus()
            elif self.view_mode == 'columns' and self.columns.active:
                self.columns.focus_column(self.columns.active)
            self.context_popover = None
        GLib.idle_add(self._unparent_popover, popover)

    @staticmethod
    def _unparent_popover(popover: Gtk.Popover) -> bool:
        if popover.get_parent() is not None:
            popover.unparent()
        return GLib.SOURCE_REMOVE

    def _show_create_dialog(self, kind: str) -> None:
        if self._computer_search_active():
            return
        if kind == "text":
            try:
                destination = create_untitled_text(self.current_dir)
            except OSError as error:
                self._show_error("Could not create text file", str(error))
                return
            self._record_file_interaction([destination])
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
            self._record_file_interaction([destination])
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
                self._record_file_interaction([output])
                self._load()
                child = self.children_by_path.get(output)
                if child:
                    self.flow.unselect_all()
                    self.flow.select_child(child)
                    child.grab_focus()
                self._show_conversion_notice(output)
                self._play_sound('complete')
            else:
                detail = (stderr or "The converter exited without creating a file.").strip()[-800:]
                self._show_error("Conversion failed", detail)

        process.communicate_utf8_async(None, None, on_finished)

    def _show_conversion_notice(self, output: Path, *, headline='Conversion complete', working=False) -> None:
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
            self.conversion_notice_status = Gtk.Stack()
            self.conversion_notice_status.add_named(icon, 'complete')
            self.conversion_notice_spinner = Gtk.Spinner()
            self.conversion_notice_status.add_named(self.conversion_notice_spinner, 'working')
            row.append(self.conversion_notice_status)
            copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            self.conversion_notice_headline = label('', 'metadata-title')
            copy.append(self.conversion_notice_headline)
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
        self.conversion_notice_status.set_visible_child_name('working' if working else 'complete')
        self.conversion_notice_spinner.set_spinning(working)
        self.conversion_notice_headline.set_text(headline)
        self.conversion_notice_filename.set_text(display_filename(output.name))
        self.conversion_notice.set_reveal_child(True)
        def expire():
            self.conversion_notice_timer = 0
            self.conversion_notice.set_reveal_child(False)
            return False
        if not working:
            self.conversion_notice_timer = GLib.timeout_add_seconds(8, expire)

    def _dismiss_conversion_notice(self) -> None:
        self.conversion_notice_spinner.stop()
        if self.conversion_notice_timer:
            GLib.source_remove(self.conversion_notice_timer)
            self.conversion_notice_timer = 0
        self.conversion_notice.set_reveal_child(False)

    def _notify(self, headline: str, detail: str) -> None:
        notifier = GLib.find_program_in_path("omarchy-notification-send")
        if notifier:
            try:
                Gio.Subprocess.new(
                    [notifier, "--app-name", "Gudfiles", headline, detail],
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

    def _open_mounted_location(self, uri: str, *, new_window=False) -> None:
        # Repair the local bridge off the GTK thread; a GFile path alone does
        # not prove that GVfs has exposed the share to ordinary filesystem APIs.
        token = getattr(self, '_mount_open_generation', 0) + 1
        if not new_window:
            self._mount_open_generation = token
        def complete(path, error):
            if not self.get_visible() or (not new_window and token != self._mount_open_generation):
                return False
            if error:
                self._show_error('Could not open mounted folder', error)
            elif new_window:
                self._open_sidebar_window(path)
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
        if self.special_mode == 'trash':
            return []
        return [child._picker_path for child in self.flow.get_selected_children()]  # type: ignore[attr-defined]

    def _update_accept_state(self) -> None:
        if hasattr(self, 'view_status'):
            self.view_status.update(self._selected_paths())
        if not hasattr(self, "accept_button"):
            return
        if self.special_mode == 'trash':
            self.accept_button.set_sensitive(False)
            return
        if self.request.mode == 'save' and self._computer_search_active():
            self.accept_button.set_label('Open folder')
            self.accept_button.set_sensitive(len(self._selected_paths()) == 1)
            return
        self.accept_button.set_label(self.request.accept_label)
        if self.request.mode == "save":
            enabled = bool(self.filename_entry.get_text().strip())
        elif self.request.directory:
            enabled = not self._computer_search_active() or any(
                path.is_dir() for path in self._selected_paths())
        else:
            enabled = any(path.is_file() for path in self._selected_paths())
        self.accept_button.set_sensitive(enabled)

    def _accept(self) -> None:
        if self.special_mode == 'trash':
            return
        selected = self._selected_paths()
        if self.request.explorer:
            if len(selected) == 1 and selected[0].is_dir():
                self.navigate(selected[0])
                return
            for path in selected:
                if path.is_file():
                    try:
                        Gio.AppInfo.launch_default_for_uri(safe_uri(path), None)
                        self._record_file_interaction([path])
                    except GLib.Error as error:
                        self._show_error(f'Could not open {path.name}', error.message)
            return
        if self.request.mode == "save":
            if self._computer_search_active():
                if len(selected) == 1:
                    target = selected[0]
                    self.navigate(target if target.is_dir() else target.parent)
                return
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
            if self._computer_search_active() and not dirs:
                return
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
        if self.finished:
            return
        if self._guard_transfer_close(lambda: self._finish(cancelled=cancelled, paths=paths)):
            return
        if self.file_job_active:
            self._show_error('File operation in progress', 'Wait for the operation to finish before closing the picker.')
            return
        self.finished = True
        if not cancelled and paths:
            self._record_recent_folders(paths if self.request.directory else [path.parent for path in paths])
        if self.sidebar_save_timer:
            self._save_sidebar_width()
        self.media_details.close()
        self.action_sounds.close()
        self._close_search()
        if self.on_result is not None:
            callback, self.on_result = self.on_result, None
            self.destroy()
            callback(None if cancelled else list(paths or []))
            return
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
        self._record_recent_folders([self.current_dir])
        self.search.set_text("")
        if record:
            self.history = self.history[: self.history_index + 1]
            if not self.history or self.history[-1] != self.current_dir:
                self.history.append(self.current_dir)
                self.history_index = len(self.history) - 1
        self._load()

    def _open_special(self, mode):
        self._mount_open_generation = getattr(self, '_mount_open_generation', 0) + 1
        if self.special_mode != mode:
            location = (mode, self.current_dir)
            self.history = self.history[:self.history_index + 1]
            self.history.append(location)
            self.history_index = len(self.history) - 1
            self._trash_restore_state = {}
        self.special_mode = mode
        self.path_stack.set_visible_child_name('crumbs')
        self.search.set_text('')
        self._load()

    def _open_recent(self) -> None:
        self._open_special('recent')

    def _restore_history_location(self):
        location = self.history[self.history_index]
        if isinstance(location, tuple):
            self.special_mode, self.current_dir = location
        else:
            self.special_mode, self.current_dir = None, location
            self._record_recent_folders([self.current_dir])
        self._trash_restore_state = {}
        self.search.set_text('')
        self._load()

    def _go_back(self, _button) -> None:
        if self.history_index > 0:
            self.history_index -= 1
            self._restore_history_location()

    def _go_forward(self, _button) -> None:
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self._restore_history_location()

    def _go_up(self, _button) -> None:
        path = self._breadcrumb_directory()
        if self.special_mode is None and path != path.parent:
            self.navigate(path.parent)

    def _update_nav_state(self) -> None:
        self.back_button.set_sensitive(self.history_index > 0)
        self.forward_button.set_sensitive(self.history_index < len(self.history) - 1)
        path = self._breadcrumb_directory()
        self.up_button.set_sensitive(self.special_mode is None and path != path.parent)

    def _update_active_location(self) -> None:
        if hasattr(self, "tabs"):
            self.tabs.update()
        matches = []
        for button in self.location_buttons:
            active = getattr(button, "_picker_path", None) == self.current_dir and self.special_mode is None
            if button._sidebar_kind == 'location' and button._sidebar_key in {'recent', 'trash'}:
                active = self.special_mode == button._sidebar_key
            if active:
                matches.append(button)
        # The same folder can appear in Places, Favorites and Recents. Give its
        # stable shortcut precedence, with Recents as a fallback, and highlight
        # exactly one entry rather than suggesting multiple selected folders.
        selected = next((button for button in matches if button._sidebar_kind != 'recent-folder'),
                        matches[0] if matches else None)
        for button in self.location_buttons:
            if button is selected:
                button.add_css_class("active")
            else:
                button.remove_css_class("active")

    def _toggle_hidden(self, _button) -> None:
        self.show_hidden = not self.show_hidden
        self._refresh_files()

    def _set_view(self, mode: str, *, persist=True) -> None:
        if mode not in ('grid', 'list', 'columns'):
            return
        if persist:
            self._set_file_preference('view_mode', mode, reload=False)
        if self.view_mode == mode:
            return
        if self.special_mode == 'trash':
            self.view_mode = mode
            for name, button in (('grid', self.grid_button), ('list', self.list_button), ('columns', self.columns_button)):
                (button.add_css_class if name == mode else button.remove_css_class)('active')
            if hasattr(self, 'trash_page'):
                self.trash_page.set_view(mode)
            self.view_status.update([])
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
            self._refresh_files(selected, rescan=False)
            return
        self.flow.remove_all()
        self.children_by_path = {}
        self.flow.set_homogeneous(False)
        self.flow.set_max_children_per_line(100 if mode == "grid" else 1)
        self.flow.set_row_spacing(12 if mode == "grid" else 2)
        self.flow.set_column_spacing(12 if mode == "grid" else 0)
        if mode == "list":
            self.flow.add_css_class('file-list')
        else:
            self.flow.remove_css_class('file-list')
        self._refresh_files(selected, rescan=False)

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
        self.search_button.popdown()
        if self.path_stack.get_visible_child_name() == "entry":
            self.path_stack.set_visible_child_name("crumbs")
            if self.path_box.buttons:
                self.path_box.buttons[-1].grab_focus()
        else:
            self.path_entry.set_text(self.special_mode + ':///' if self.special_mode else str(self._breadcrumb_directory()))
            self.path_stack.set_visible_child_name("entry")
            self.path_entry.grab_focus()
            self.path_entry.select_region(0, -1)

    def _on_path_activate(self, entry: Gtk.Entry) -> None:
        if entry.get_text().strip() in {'trash:///', 'recent:///'}:
            self._open_special(entry.get_text().strip().split(':')[0])
            self.path_stack.set_visible_child_name('crumbs')
            return
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


def application_id_for(request: PickerRequest) -> str:
    if not request.explorer:
        return "org.omarchy.FilePicker.Picker"
    return "org.omarchy.FilePicker.External" if request.external else "org.omarchy.FilePicker"


class PickerApplication(Gtk.Application):
    def __init__(self, request: PickerRequest, result_path: Path | None):
        super().__init__(application_id=application_id_for(request), flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.request = request
        self.result_path = result_path

    def do_activate(self) -> None:
        window = PickerWindow(self, self.request, self.result_path)
        window.present()


def parse_args(argv: list[str]) -> tuple[PickerRequest, Path | None]:
    parser = argparse.ArgumentParser(description="Gudfiles — visual file manager and file picker",
                                     epilog='Other gudfiles commands: --doctor, --check-updates, --enable-portal, --disable-portal.')
    from . import __version__
    parser.add_argument('--version', action='version', version=f'Gudfiles {__version__}')
    parser.add_argument("--request", type=Path, help="JSON portal request")
    parser.add_argument("--result", type=Path, help="JSON result destination")
    parser.add_argument("--demo", nargs="?", const=str(Path.home() / "Pictures"), help="Open standalone demo")
    parser.add_argument('--desktop', nargs='?', const='',
                        help='Desktop launcher entry; a supplied file or folder opens externally')
    parser.add_argument('--external', action='store_true', help='Open a temporary external browser window')
    parser.add_argument('--select', action='append', type=Path, default=[],
                        help='Reveal and select an item in its parent folder (repeat for siblings)')
    parser.add_argument("--mode", choices=("open", "save", "save_files"), default="open")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--multiple", dest="multiple", action="store_true", default=None,
                           help="Allow multiple selections (default for standalone Open)")
    selection.add_argument("--single", dest="multiple", action="store_false",
                           help="Restrict standalone Open to one selection")
    parser.add_argument("--directory", action="store_true")
    args = parser.parse_args(argv)
    if args.desktop is not None:
        args.demo = args.desktop or str(Path.home() / 'Pictures')
        args.external = args.external or bool(args.desktop)
    if args.request:
        request = PickerRequest.from_dict(json.loads(args.request.read_text(encoding="utf-8")))
    else:
        folder = Path(os.path.abspath(Path(args.demo or Path.cwd()).expanduser()))
        explorer = args.mode == 'open' and not args.directory and args.result is None
        selected = [Path(os.path.abspath(path.expanduser())) for path in args.select] if explorer else []
        if selected:
            folder = selected[0].parent
            if any(path.parent != folder for path in selected):
                parser.error('--select items must share a parent folder')
        elif explorer and args.demo and args.desktop != '' and not folder.is_dir():
            selected = [folder]
        external = explorer and (args.external or bool(selected))
        request = PickerRequest(
            mode=args.mode,
            explorer=explorer,
            external=external,
            selected_paths=selected,
            title="GUDFILES" if explorer else ("Save File" if args.mode == "save" else "Open File"),
            accept_label="Save" if args.mode == "save" else ("Select Folder" if args.directory else "Open"),
            current_folder=folder if folder.is_dir() else folder.parent,
            current_name="untitled.txt" if args.mode == "save" else "",
            multiple=args.mode == "open" and args.multiple is not False,
            directory=args.directory or args.mode == "save_files",
        )
    return request, args.result


def main(argv: list[str] | None = None) -> int:
    request, result_path = parse_args(argv if argv is not None else sys.argv[1:])
    GLib.set_application_name("Gudfiles")
    return PickerApplication(request, result_path).run([])


if __name__ == "__main__":
    raise SystemExit(main())
