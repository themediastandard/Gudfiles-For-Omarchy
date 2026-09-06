#!/bin/bash
set -euo pipefail

SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
APP_DIR="$HOME/.local/share/omarchy-file-picker"
BIN_DIR="$HOME/.local/bin"
DATA_DIR="$HOME/.local/share"
CONFIG_DIR="$HOME/.config/xdg-desktop-portal"
SYSTEMD_DIR="$HOME/.config/systemd/user"
PORTAL_CONFIG="$CONFIG_DIR/hyprland-portals.conf"
BACKUP_DIR="$HOME/.config/omarchy/backups/omarchy-file-picker"
STAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$APP_DIR" "$BIN_DIR" "$DATA_DIR/applications" \
  "$DATA_DIR/dbus-1/services" "$DATA_DIR/xdg-desktop-portal/portals" \
  "$CONFIG_DIR" "$SYSTEMD_DIR" "$BACKUP_DIR"

if [[ -f $PORTAL_CONFIG ]] && ! cmp -s "$PORTAL_CONFIG" "$SOURCE_DIR/data/hyprland-portals.conf"; then
  cp -- "$PORTAL_CONFIG" "$BACKUP_DIR/hyprland-portals.conf.$STAMP"
fi

mkdir -p "$APP_DIR/omarchy_file_picker"
cp -R -- "$SOURCE_DIR/omarchy_file_picker/." "$APP_DIR/omarchy_file_picker/"

sed "s|@APP_DIR@|$APP_DIR|g" "$SOURCE_DIR/bin/omarchy-file-picker" > "$BIN_DIR/omarchy-file-picker"
sed "s|@APP_DIR@|$APP_DIR|g" "$SOURCE_DIR/bin/omarchy-file-picker-portal" > "$BIN_DIR/omarchy-file-picker-portal"
chmod 755 "$BIN_DIR/omarchy-file-picker" "$BIN_DIR/omarchy-file-picker-portal"

install -m 644 "$SOURCE_DIR/data/org.omarchy.FilePicker.desktop" "$DATA_DIR/applications/org.omarchy.FilePicker.desktop"
install -m 644 "$SOURCE_DIR/data/omarchy-file-picker.portal" "$DATA_DIR/xdg-desktop-portal/portals/omarchy-file-picker.portal"
install -m 644 "$SOURCE_DIR/data/hyprland-portals.conf" "$PORTAL_CONFIG"
sed "s|@BIN_DIR@|$BIN_DIR|g" "$SOURCE_DIR/data/org.freedesktop.impl.portal.desktop.omarchy.FilePicker.service" \
  > "$DATA_DIR/dbus-1/services/org.freedesktop.impl.portal.desktop.omarchy.FilePicker.service"
sed "s|@BIN_DIR@|$BIN_DIR|g" "$SOURCE_DIR/data/omarchy-file-picker-portal.service" \
  > "$SYSTEMD_DIR/omarchy-file-picker-portal.service"

update-desktop-database "$DATA_DIR/applications" >/dev/null 2>&1 || true
systemctl --user daemon-reload
systemctl --user restart omarchy-file-picker-portal.service
systemctl --user restart xdg-desktop-portal.service

printf 'Installed Omarchy File Picker.\n'
printf 'Portal config backup directory: %s\n' "$BACKUP_DIR"
