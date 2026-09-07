# Omarchy File Picker

## Purpose

Provide a fast, visual, theme-aware Open/Save dialog for Omarchy and expose it
as the desktop's XDG FileChooser portal backend.

## Current state

- Native GTK 4 picker with grid and list layouts.
- Image and cached video thumbnails, selection metadata, search, file filters,
  multi-select, folder selection, Open, Save, and SaveFiles modes.
- Compact context actions create folders and text files; cascading media menus
  expose resize presets and format conversions without replacing originals.
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
- Breadcrumbs scroll within a bounded toolbar viewport; long metadata, type,
  sidebar and selection labels ellipsize instead of growing the window.
- In-window Quick Look expands from the selected tile on Space and contracts
  on Space/Escape. Includes images, bounded read-only text, first-page PDFs,
  adjacent-file browsing, reduced motion and optional GStreamer media playback.
- NAS dialog uses flat theme-colored controls, automatically searches Avahi/
  GVfs network advertisements, and offers explicit SMB share browsing, Refresh,
  saved/mounted locations, inline errors and cancellable mounting.

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
- `omarchy_file_picker/network.py` / `network_ui.py` — bounded service discovery
  and explicit server/share browsing in the NAS dialog.
- `data/` — user-local portal, D-Bus, desktop, and systemd templates.
- `install.sh` / `uninstall.sh` — reversible user installation.

## Development

```bash
python -m unittest discover -v
PYTHONPATH=. python tests/ui_file_management.py
PYTHONPATH=. python tests/ui_quicklook.py
PYTHONPATH=. python tests/ui_nas.py
PYTHONPATH=. python tests/ui_layout.py
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
- Media actions use the ImageMagick and FFmpeg packages already shipped in the
  current Omarchy environment; NAS access uses GVfs SMB/NFS support.
- Portal routing changes are user-local and backed up before replacement.
- The stock GTK portal remains the fallback for all non-FileChooser interfaces.
- Context popovers are parented to the stable browser stack, not replaceable
  file tiles. Entry dialogs release focus/hide before deferred destruction to
  avoid queued Wayland input-method events reaching destroyed widgets.
- Content must not increase the top-level minimum size during navigation.
  Keep path ancestors in a horizontal scroller (current folder auto-revealed),
  preserve the full typed path, and use tooltips for truncated labels. The layout
  regression exercises deep paths, long names/types and user-selected sizes.
- UI smoke tests require a desktop session and temporarily use the clipboard;
  file actions run only against a disposable fixture with isolated preferences.
- For unobstructed NAS visual QA, set `NAS_QA_SCREENSHOT=/tmp/nas-qa.png` when
  running `tests/ui_nas.py`; it snapshots the native dialog via GTK's renderer,
  excluding other desktop windows and authentication overlays.

## Known risks and next actions

- Apps that bypass XDG portals keep their toolkit-native chooser.
- A NAS must be reachable and provide valid credentials for a live mount test;
  live passive discovery is verified, while authenticated share browsing and
  mounting require a user-selected server/login and remain unverified here.
- This machine lacks `gst-plugins-good` and `gst-libav`; playback currently
  shows a codec explanation. Installing them requires administrator approval.
- Sandboxed-app and native-app Open/Save flows must both be smoke-tested after
  each portal protocol change.
