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
- SMB/NFS NAS connection dialog backed by Gio/GVfs with native credential
  prompts; mounted shares are refreshed into the Devices sidebar.
- Reads the active Omarchy `colors.toml` on every launch.
- User-local portal installation with GTK retained as the fallback backend.

## Architecture

- `omarchy_file_picker/picker.py` — native chooser UI and result protocol.
- `omarchy_file_picker/portal.py` — XDG FileChooser D-Bus backend.
- `omarchy_file_picker/model.py` — request parsing, filters, filesystem helpers.
- `omarchy_file_picker/actions.py` — validated media commands, output naming,
  and NAS address normalization.
- `omarchy_file_picker/theme.py` — active Omarchy palette to GTK CSS.
- `data/` — user-local portal, D-Bus, desktop, and systemd templates.
- `install.sh` / `uninstall.sh` — reversible user installation.

## Development

```bash
python -m unittest discover -v
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
- Media actions use the ImageMagick and FFmpeg packages already shipped in the
  current Omarchy environment; NAS access uses GVfs SMB/NFS support.
- Portal routing changes are user-local and backed up before replacement.
- The stock GTK portal remains the fallback for all non-FileChooser interfaces.

## Known risks and next actions

- Apps that bypass XDG portals keep their toolkit-native chooser.
- A NAS must be reachable and provide valid credentials for a live mount test;
  URI validation and the mount request path are covered locally.
- Sandboxed-app and native-app Open/Save flows must both be smoke-tested after
  each portal protocol change.
