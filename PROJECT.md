# Omarchy File Picker

## Purpose

Provide a fast, visual, theme-aware Open/Save dialog for Omarchy and expose it
as the desktop's XDG FileChooser portal backend.

## Current state

- Native GTK 4 picker with grid and list layouts.
- Standalone browsing runs in explorer mode: footer hidden, normal default-app
  file opening without quitting, and Escape clears selection. The preview strip
  remains. Portal requests, CLI `--result`, folder picking and Save modes retain
  picker footer controls and result semantics.
- List view uses compact 32-pixel rows with no inter-row gap; grid spacing is
  unchanged. Native range and individual selection remain supported.
- Standalone Open defaults to multi-selection with native Shift-click ranges,
  Ctrl-click toggles and Ctrl+A. `--single` opts out; portal caller constraints
  and single-destination Save behavior remain authoritative.
- Blank-background drags select intersecting files in grid/list views with a
  theme-colored rectangle, Shift-add, Ctrl-toggle, edge scrolling and Escape
  restoration. File-origin click gestures remain native GTK.
- Image and cached video thumbnails, selection metadata, search, file filters,
  multi-select, folder selection, Open, Save, and SaveFiles modes.
- Compact context actions create folders and text files; cascading media menus
  expose resize presets and format conversions without replacing originals.
- Conversion completion uses one dismissible in-window notification, expiring
  after eight seconds, without a modal dialog or duplicate system notification.
- New Text File creates and selects an empty `untitled.txt` immediately, with
  numbered collision-safe names and no naming dialog. Rename remains available.
- Context-menu surfaces use scoped GTK CSS, compact flat rows, and inward
  submenu placement near the chooser's right edge.
- File and background menus include rename, clipboard file operations,
  confirmed trash/permanent deletion, properties, bookmarks, view and sort.
  NAS connection is sidebar-only. Rename and paste never overwrite collisions.
- SMB/NFS NAS connection dialog backed by Gio/GVfs with native credential
  prompts; mounted shares are refreshed into the Devices sidebar.
- Reads the active Omarchy `colors.toml` on every launch.
- User-local portal installation with GTK retained as the fallback backend.
- Sidebar uses the same application background, not a contrasting white panel.
- Native draggable sidebar divider with a 160-pixel minimum, scrollable places,
  and debounced width persistence without reloading files or clearing selection.
- Mouse context menus preserve browser-relative pointer coordinates. Only
  keyboard-opened menus use the selected row/tile's center as their anchor.
- Breadcrumbs scroll within a bounded toolbar viewport; long metadata, type,
  sidebar and selection labels ellipsize instead of growing the window.
- In-window Quick Look expands from the selected tile on Space and contracts
  on Space/Escape. Includes images, bounded read-only text, first-page PDFs,
  adjacent-file browsing, reduced motion and optional GStreamer media playback.
- Installed GStreamer good/bad/ugly/libav codecs; generated H.264/AAC, HEVC/AAC,
  ProRes/PCM, VP9/Opus and AV1/AAC clips verify decoding, play, pause, seek,
  resume and stop on preview close. Actual user media and audible output remain
  separate manual checks.
- Selection previews occupy a reserved 113-pixel strip. Neither the strip's
  content nor the Quick Look overlay participates in window size requests;
  long titles and metadata ellipsize with full values available in tooltips.
- NAS dialog uses flat theme-colored controls, automatically searches Avahi/
  GVfs network advertisements, and offers explicit SMB share browsing, Refresh,
  saved/mounted locations, inline errors and cancellable mounting.
- Mounted-device clicks and successful NAS connections verify the local path
  on a worker thread, recover a missing GVfs FUSE bridge when available, and
  report unavailable folders. Credential prompts belong to the NAS dialog.

## Architecture

- `omarchy_file_picker/picker.py` — native chooser UI and result protocol.
- `omarchy_file_picker/portal.py` — XDG FileChooser D-Bus backend.
- `omarchy_file_picker/model.py` — request parsing, filters, filesystem helpers.
- `omarchy_file_picker/actions.py` — validated media commands, output naming,
  and NAS address normalization.
- `omarchy_file_picker/file_actions.py` — filesystem operations and sorting.
- `omarchy_file_picker/file_management.py` — file dialogs, clipboard, shared
  GTK bookmarks and persisted display preferences.
- `omarchy_file_picker/theme.py` — active Omarchy palette to GTK CSS.
- `omarchy_file_picker/quicklook.py` — frame-clock animation and preview loading.
- `omarchy_file_picker/drag_selection.py` — background selection and edge scrolling.
- `omarchy_file_picker/network.py` / `network_ui.py` — bounded service discovery
  and explicit server/share browsing in the NAS dialog.
- `data/` — user-local portal, D-Bus, desktop, and systemd templates.
- `install.sh` / `uninstall.sh` — reversible user installation.

## Development

```bash
python -m unittest discover -v
PYTHONPATH=. python tests/ui_file_management.py
PYTHONPATH=. python tests/ui_quicklook.py
PYTHONPATH=. python tests/ui_video_playback.py
PYTHONPATH=. python tests/ui_preview_geometry.py
PYTHONPATH=. python tests/ui_nas.py
PYTHONPATH=. python tests/ui_layout.py
PYTHONPATH=. python tests/ui_selection.py
PYTHONPATH=. python tests/ui_sidebar_menu.py
PYTHONPATH=. python tests/ui_explorer.py
PYTHONPATH=. python tests/ui_drag_selection.py
PYTHONPATH=. python tests/ui_conversion_notice.py
PYTHONPATH=. python tests/ui_mounts.py
./bin/omarchy-file-picker --demo ~/Pictures
./install.sh
```

After installation, portal routing is verified with:

```bash
systemctl --user status omarchy-file-picker-portal.service
gdbus introspect --session \
  --dest org.freedesktop.impl.portal.desktop.omarchy.FilePicker \
  --object-path /org/freedesktop/portal/desktop
```

## Decisions and constraints

- No files under `/usr/share/omarchy` are modified.
- The implementation depends only on Omarchy's existing GTK 4/PyGObject stack.
- PDF preview uses optional Poppler GI/Cairo. Media playback needs GStreamer
  codecs; missing dependencies produce an inline explanation. Discovery uses
  the existing Avahi tools/GVfs and never brute-force scans a network.
- The picker defaults to app-local `GSK_RENDERER=gl` before GTK initialization,
  respecting explicit overrides. Vulkan video QA produced an allocation warning
  and GTK rendering crash; all five codec fixtures pass with OpenGL. No global
  graphics configuration is changed. Codec packages require separate privileged
  installation and are not installed by `install.sh`.
- Media actions use the ImageMagick and FFmpeg packages already shipped in the
  current Omarchy environment; NAS access uses GVfs SMB/NFS support.
- Portal routing changes are user-local and backed up before replacement.
- The stock GTK portal remains the fallback for all non-FileChooser interfaces.
- Context popovers are parented to the stable browser stack, not replaceable
  file tiles. Entry dialogs release focus/hide before deferred destruction to
  avoid queued Wayland input-method events reaching destroyed widgets.
- Sidebar/menu QA uses isolated preferences and native Paned positions, verifies
  restored width, and checks pointer/keyboard anchors against real GTK bounds.
  Present test windows before destroying them; an unshown second window triggered
  a GTK destruction crash on this desktop. No desktop rules are changed by QA.
- Content must not increase the top-level minimum size during navigation.
  Keep path ancestors in a horizontal scroller (current folder auto-revealed),
  preserve the full typed path, and use tooltips for truncated labels. The layout
  regression exercises deep paths, long names/types and user-selected sizes.
- Preview geometry tests verify both minimum and natural size requests, native
  window size/position, and browser height during selection and Space preview
  open/close with portrait, landscape, square images and long-name text. They
  float/resize only their disposable test window, without editing desktop rules.
- UI smoke tests require a desktop session and temporarily use the clipboard;
  file actions run only against a disposable fixture with isolated preferences.
- Selection smoke tests exercise GTK's native range/toggle action signals in
  both views, not injected mouse events; reuse native FlowBox pointer handling.
- Background-drag tests invoke the gesture handlers against actual GTK bounds
  and hit testing, including scrolling and cancellation; no physical pointer
  injection. Overlays are excluded from size requests. Conversion-notice QA
  performs a real ImageMagick conversion against a disposable image fixture.
- A GVfs mount and `GFile.get_path()` can exist without a running FUSE bridge.
  Verify local directory accessibility before navigation; never treat a path
  string as proof of a working mount. Start only the existing user bridge, not
  a new server connection, when recovering this condition.
- `PICKER_QA_LIVE_MOUNT=1 PYTHONPATH=. python tests/ui_mounts.py` additionally
  exercises an already-mounted NAS sidebar button, subfolder activation and
  Back read-only. It does not request credentials or mount a new share.
- For unobstructed NAS visual QA, set `NAS_QA_SCREENSHOT=/tmp/nas-qa.png` when
  running `tests/ui_nas.py`; it snapshots the native dialog via GTK's renderer,
  excluding other desktop windows and authentication overlays.

## Known risks and next actions

- Apps that bypass XDG portals keep their toolkit-native chooser.
- A NAS must be reachable and provide valid credentials for a live mount test;
  live passive discovery is verified, while authenticated share browsing and
  mounting require a user-selected server/login and remain unverified here.
  Browsing an existing authenticated mount and entering a subfolder are verified.
- Sandboxed-app and native-app Open/Save flows must both be smoke-tested after
  each portal protocol change.
