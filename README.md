# Omarchy File Picker

A visual, keyboard-friendly file picker that follows the active Omarchy theme
and serves as an XDG desktop portal backend.

## Features

- Thumbnail-first grid and compact list views
- Image previews and freedesktop video thumbnail cache support
- Pinned folders, recent files, and mounted volumes
- Compact, icon-led right-click menu with grouped media submenus
- Right-click creation of folders and text files
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
