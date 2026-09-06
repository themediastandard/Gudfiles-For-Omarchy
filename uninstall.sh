#!/bin/bash
set -euo pipefail

APP_DIR="$HOME/.local/share/omarchy-file-picker"
BIN_DIR="$HOME/.local/bin"
DATA_DIR="$HOME/.local/share"
CONFIG_DIR="$HOME/.config/xdg-desktop-portal"
SYSTEMD_DIR="$HOME/.config/systemd/user"
PORTAL_CONFIG="$CONFIG_DIR/hyprland-portals.conf"
BACKUP_DIR="$HOME/.config/omarchy/backups/omarchy-file-picker"

systemctl --user disable --now omarchy-file-picker-portal.service >/dev/null 2>&1 || true

rm -f -- "$BIN_DIR/omarchy-file-picker" "$BIN_DIR/omarchy-file-picker-portal" \
  "$DATA_DIR/applications/org.omarchy.FilePicker.desktop" \
  "$DATA_DIR/dbus-1/services/org.freedesktop.impl.portal.desktop.omarchy.FilePicker.service" \
  "$DATA_DIR/xdg-desktop-portal/portals/omarchy-file-picker.portal" \
  "$SYSTEMD_DIR/omarchy-file-picker-portal.service"
rm -rf -- "$APP_DIR"

latest_backup=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'hyprland-portals.conf.*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)
if [[ -n ${latest_backup:-} && -f $latest_backup ]]; then
  cp -- "$latest_backup" "$PORTAL_CONFIG"
elif [[ -f $PORTAL_CONFIG ]] && grep -q 'omarchy-file-picker' "$PORTAL_CONFIG"; then
  rm -f -- "$PORTAL_CONFIG"
fi

systemctl --user daemon-reload
systemctl --user restart xdg-desktop-portal.service
printf 'Removed Omarchy File Picker and restored portal routing.\n'

