#!/usr/bin/env bash
# Puts `bag-catalog` on PATH and adds it to the desktop app launcher. Re-run after moving the repo.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin="$HOME/.local/bin"
apps="$HOME/.local/share/applications"
icons="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$bin" "$apps" "$icons"
ln -sfn "$here/bin/bag-catalog" "$bin/bag-catalog"
ln -sfn "$here/src/bag_catalog/resources/icon.svg" "$icons/bag-catalog.svg"  # linked, so logo changes show up
touch "$HOME/.local/share/icons/hicolor"  # tells the desktop to look at its icons again
sed "s|@EXEC@|$here/bin/bag-catalog|" "$here/share/bag-catalog.desktop.in" > "$apps/bag-catalog.desktop"
update-desktop-database -q "$apps" 2>/dev/null || true
echo "Installed $bin/bag-catalog and $apps/bag-catalog.desktop"
