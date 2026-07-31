#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons"
SYSTEM_APPS_DIR="/usr/share/applications"
SYSTEM_ICONS_DIR="/usr/share/icons"

mkdir -p "$BIN_DIR" "$APPS_DIR" "$ICONS_DIR"
chmod +x "$REPO_DIR/bin/piswitch"
ln -sfn "$REPO_DIR/bin/piswitch" "$BIN_DIR/piswitch"

cp "$REPO_DIR/assets/piswitch.svg" "$ICONS_DIR/piswitch.svg"

desktop_entry() {  # $1 = Icon= path to embed
  printf '%s\n' \
    '[Desktop Entry]' \
    'Type=Application' \
    'Name=piswitch' \
    'Comment=pi provider and model switcher' \
    "Exec=$BIN_DIR/piswitch" \
    "Icon=$1" \
    'Terminal=false' \
    'Categories=Utility;Development;' \
    'Keywords=pi;model;switch;provider;'
}

desktop_entry "$ICONS_DIR/piswitch.svg" > "$APPS_DIR/piswitch.desktop"
chmod +x "$APPS_DIR/piswitch.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" || true
fi

printf 'installed: %s -> %s\n' "$BIN_DIR/piswitch" "$REPO_DIR/bin/piswitch"

# WSLg's app-list monitor only scans /usr/share/applications,
# /usr/local/share/applications, /var/lib/snapd/desktop/applications and
# /var/lib/flatpak/exports/share/applications. A .desktop under
# ~/.local/share/applications is therefore never exported to the Windows Start
# Menu, so on WSL we install a second, system-wide copy.
# Set PISWITCH_NO_SYSTEM_ENTRY=1 to skip that, and the sudo prompt it needs.
if [ -n "${PISWITCH_NO_SYSTEM_ENTRY:-}" ] || [ ! -d /mnt/wslg ]; then
  exit 0
fi

if [ "$(id -u)" -eq 0 ]; then
  sudo=""
elif command -v sudo >/dev/null 2>&1; then
  sudo="sudo"
else
  printf 'note: WSLg detected but sudo is unavailable, skipping system-wide entry.\n' >&2
  printf '      piswitch will not appear in the Windows Start Menu.\n' >&2
  exit 0
fi

printf 'WSLg detected, installing %s (needs root)\n' "$SYSTEM_APPS_DIR/piswitch.desktop"
if ! $sudo install -Dm644 "$REPO_DIR/assets/piswitch.svg" "$SYSTEM_ICONS_DIR/piswitch.svg"; then
  printf 'note: system-wide install failed, Start Menu entry not created.\n' >&2
  exit 0
fi

# Exec still points at the per-user launcher: piswitch reads ~/.pi, so a shared
# entry would be wrong for any other account on this machine anyway.
desktop_entry "$SYSTEM_ICONS_DIR/piswitch.svg" \
  | $sudo tee "$SYSTEM_APPS_DIR/piswitch.desktop" >/dev/null
$sudo chmod 644 "$SYSTEM_APPS_DIR/piswitch.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
  $sudo update-desktop-database "$SYSTEM_APPS_DIR" || true
fi

printf 'installed: %s\n' "$SYSTEM_APPS_DIR/piswitch.desktop"
