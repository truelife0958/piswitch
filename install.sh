#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons"

mkdir -p "$BIN_DIR" "$APPS_DIR" "$ICONS_DIR"
chmod +x "$REPO_DIR/bin/piswitch"
ln -sfn "$REPO_DIR/bin/piswitch" "$BIN_DIR/piswitch"

cp "$REPO_DIR/assets/piswitch.svg" "$ICONS_DIR/piswitch.svg"

printf '%s\n' \
  '[Desktop Entry]' \
  'Type=Application' \
  'Name=piswitch' \
  'Comment=pi provider and model switcher' \
  "Exec=$BIN_DIR/piswitch" \
  "Icon=$ICONS_DIR/piswitch.svg" \
  'Terminal=false' \
  'Categories=Utility;Development;' \
  'Keywords=pi;model;switch;provider;' > "$APPS_DIR/piswitch.desktop"

chmod +x "$APPS_DIR/piswitch.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" || true
fi

printf 'installed: %s -> %s\n' "$BIN_DIR/piswitch" "$REPO_DIR/bin/piswitch"
