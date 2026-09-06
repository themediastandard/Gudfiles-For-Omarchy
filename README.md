# Omarchy File Picker

A visual, keyboard-friendly file picker that follows the active Omarchy theme
and serves as an XDG desktop portal backend.

## Features

- Thumbnail-first grid and compact list views
- Image previews and freedesktop video thumbnail cache support
- Pinned folders, recent files, and mounted volumes
- Compact, icon-led right-click menu with grouped media submenus
- Right-click creation of folders and text files
- Background right-click works in blank areas and empty folders
- Rename, Cut/Copy/Paste, Copy Location, Properties, and confirmed Trash/Delete
- GTK-shared bookmarks, hidden files, configurable list details, and sorting
- Non-destructive image resizing: Small (1080 px), Medium (2160 px), Large (3160 px)
- Image conversion to JPEG, PNG, WebP, and AVIF
- Video conversion to MP4, WebM, MOV, and GIF
- SMB and NFS NAS mounting with native credential prompts
- Search, breadcrumb navigation, typed paths, and history
- Open, multi-open, select-folder, Save, and SaveFiles flows
- Portal file filters and caller-supplied choices
- `Ctrl+F`, `Ctrl+L`, `Ctrl+H`, `Alt+Left`, `Alt+Right`, and `Escape`
- Automatic colors from the active Omarchy theme

All media operations create a new, uniquely named file beside the original.
Image work uses ImageMagick; video work uses FFmpeg. NAS connections use the
installed GVfs SMB/NFS backends and appear in the Devices section after mount.
NAS connection is sidebar-only, not a context-menu action.

Rename and paste refuse filename collisions instead of overwriting existing
files. Trash and permanent deletion both require confirmation. Clipboard file
operations support local file URIs, including mounted shares exposed as paths.
Display preferences persist in `~/.config/omarchy-file-picker/preferences.json`;
bookmarks use the shared GTK `~/.config/gtk-3.0/bookmarks` file.

Keyboard actions include `F2` Rename, `Delete` Trash, `Shift+Delete` permanent
delete, `Ctrl+X/C/V` Cut/Copy/Paste, `Ctrl+Shift+C` Copy Location,
`Ctrl+Shift+N` New Folder, `F5` Refresh, `Alt+Enter` Properties, and
`Shift+F10` context menu. `Ctrl+A` selects all when the caller permits multiple
files. Text-entry editing retains its normal clipboard shortcuts.

See [stock-picker-comparison.md](stock-picker-comparison.md) for the stock GTK
action comparison and intentional differences.

## Try it

```bash
./bin/omarchy-file-picker --demo ~/Pictures
```

## Install

```bash
./install.sh
```

This installs entirely in `~/.local` and `~/.config`. It backs up an existing
Hyprland portal routing file, makes this picker the FileChooser backend, leaves
the GTK portal as fallback, and restarts the affected user services.

Revert with:

```bash
./uninstall.sh
```
