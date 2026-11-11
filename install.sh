#!/bin/sh
# Installs NeoRGB for the current user from this checkout (no root needed).
# The devices are reachable through the uaccess udev tags OpenRGB ships.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
UNIT="$HOME/.config/systemd/user"
mkdir -p "$BIN" "$APPS" "$ICONS" "$UNIT"

wrap() {  # name module
    cat > "$BIN/$1" <<EOS
#!/bin/sh
export PYTHONPATH="$SRC\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m $2 "\$@"
EOS
    chmod +x "$BIN/$1"
}
wrap neorgbd neorgb.daemon
wrap neorgbctl neorgb.cli
wrap neorgb neorgb.gui.app

cp "$SRC/neorgb/gui/icons/neorgb.svg" "$ICONS/neorgb.svg"
sed "s|@BIN@|$BIN|g" "$SRC/packaging/neorgb.desktop" > "$APPS/neorgb.desktop"
sed "s|@BIN@|$BIN|g" "$SRC/packaging/neorgbd.service" > "$UNIT/neorgbd.service"
systemctl --user daemon-reload

if [ ! -e /usr/lib/udev/rules.d/60-openrgb.rules ] && [ ! -e /etc/udev/rules.d/60-openrgb.rules ]; then
    echo "Hinweis: keine OpenRGB-udev-Regeln gefunden. Ohne sie fehlt der Zugriff auf /dev/hidraw*."
    echo "         openrgb --print-udev-rules | sudo tee /etc/udev/rules.d/60-openrgb.rules"
fi
if ! getent group neorgb >/dev/null; then
    echo "Hinweis: Für Mainboard- und GPU-Lüfter einmalig (root):"
    echo "         sudo groupadd -r neorgb && sudo usermod -aG neorgb \$USER"
    echo "         sudo install -Dm644 $SRC/packaging/60-neorgb.rules /etc/udev/rules.d/60-neorgb.rules"
    echo "         sudo install -Dm644 $SRC/packaging/neorgb-modules.conf /etc/modules-load.d/neorgb.conf"
    echo "         danach neu starten"
fi
echo "Installiert. Autostart + sofort starten:  systemctl --user enable --now neorgbd"
