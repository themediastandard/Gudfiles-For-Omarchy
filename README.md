# Omarchy File Picker

A visual, keyboard-friendly file picker that follows the active Omarchy theme
and serves as an XDG desktop portal backend.

## Features

- Thumbnail-first grid and compact list views
- Dense list rows with no gaps between files
- Image previews and freedesktop video thumbnail cache support
- Pinned folders, recent files, and mounted volumes
- Compact, icon-led right-click menu with grouped media submenus
- Right-click creation of folders and text files
- New Text File immediately creates `untitled.txt`, then `untitled (1).txt`, etc.,
  without a naming prompt; use Rename or F2 whenever you want to name it
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
- Cohesive sidebar, browser, previews and dialogs using the same Omarchy palette
- Space-bar Quick Look: animated expansion from the selected file and return
- Image, UTF-8 text and first-page PDF previews; arrow keys browse adjacent files
- NAS dialog automatically discovers advertised SMB/NFS servers and GVfs
  network locations; select an SMB server to browse its shares, then Connect

All media operations create a new, uniquely named file beside the original.
Image work uses ImageMagick; video work uses FFmpeg. NAS connections use the
installed GVfs SMB/NFS backends and appear in the Devices section after mount.
NAS connection is sidebar-only, not a context-menu action.

Press `Space` on a selected file to preview it, and `Space` again or `Escape`
to close. The preview restores file focus and respects GTK's reduced-motion
setting. Images are scaled to fit without cropping, text is read-only and
limited to 128 KB, and PDFs show their first page with the total page count.
Video/audio playback uses GTK/GStreamer and needs the appropriate codecs
(`gst-plugins-good` and `gst-libav` on Arch). Missing codecs show an explanation
instead of opening another app. These optional system packages are not installed
by `install.sh`.

Network search starts every time Connect to NAS opens; Refresh scans again.
Discovery uses Avahi DNS-SD and GVfs, plus mounted shares and GTK-saved network
bookmarks. It does not port-scan the subnet or connect to servers automatically.
Selecting a server explicitly browses shares and may prompt for credentials;
selecting a share fills the address for Connect. Non-advertising servers may
still require a typed address. No passwords are saved by the picker.
Mounted shares need GVfs's local filesystem bridge. The picker checks it when
opening a mounted device and starts the installed bridge if missing, without
reconnecting or changing NAS credentials. Unavailable folders show an error.

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

Standalone Open enables multi-selection by default: click replaces the selection,
Shift-click selects a continuous range in display order, and Ctrl-click adds or
removes individual files. Both grid and list views support these gestures. Use
`--single` for a single-selection standalone picker. Portal dialogs honor the
calling application's single/multiple setting; Save stays a single destination.

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
