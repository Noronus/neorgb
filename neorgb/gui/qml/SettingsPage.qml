import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

Flickable {
    id: page
    property var win
    readonly property var st: win.st
    readonly property var orgb: ((st.config || {}).openrgb) || ({})
    contentHeight: col.implicitHeight + 56
    clip: true

    ColumnLayout {
        id: col
        x: 28; y: 28
        width: Math.min(page.width - 56, 860)
        spacing: Theme.gap

        Text { text: "Einstellungen"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }

        Card {
            Layout.fillWidth: true
            title: "Andere RGB-Geräte über OpenRGB"
            subtitle: "Mainboard (Aura), RAM, Tastatur und Maus laufen über einen OpenRGB-Server. Die Corsair-Hubs bleiben bei NeoRGB."
            Column {
                width: parent.width; spacing: 10
                NSwitch { text: "OpenRGB-Geräte einbinden"; checked: !!page.orgb.enabled; onToggled: backend.call("set_openrgb", { enabled: checked }) }
                NSwitch { text: "OpenRGB-Server selbst starten (ohne Corsair-Hubs)"; checked: page.orgb.spawn !== false; onToggled: backend.call("set_openrgb", { spawn: checked }) }
                Text { text: "Änderungen hier greifen nach einem Neustart des Dienstes."; color: Theme.faint; font.pixelSize: 12 }
            }
        }

        Card {
            Layout.fillWidth: true
            title: "Beleuchtung"
            GridLayout {
                width: parent.width; columns: 2; columnSpacing: 24
                Text { text: "Bilder pro Sekunde"; color: Theme.muted; font.pixelSize: 13; Layout.fillWidth: true }
                NSlider { Layout.preferredWidth: 300; from: 10; to: 60; stepSize: 5; value: ((st.config || {}).lighting || {}).fps || 30
                    onPressedChanged: if (!pressed) backend.call("set_lighting", { fps: value }) }
            }
        }

        Card {
            Layout.fillWidth: true
            title: "Dienst"
            subtitle: "neorgbd läuft im Hintergrund und regelt auch ohne dieses Fenster."
            Column {
                width: parent.width; spacing: 8
                Text { text: "Läuft seit " + Math.round((st.uptime || 0) / 60) + " min"; color: Theme.muted; font.pixelSize: 13 }
                Text { text: "Autostart: systemctl --user enable --now neorgbd"; color: Theme.text; font.family: "monospace"; font.pixelSize: 13 }
                Text { text: "Konfiguration: ~/.config/neorgb/config.json"; color: Theme.text; font.family: "monospace"; font.pixelSize: 13 }
            }
        }

        Card {
            Layout.fillWidth: true
            title: "Über"
            Text { text: "NeoRGB 0.1 · GPL-3.0-or-later · Protokolle nach liquidctl, OpenLinkHub und OpenRGB"; color: Theme.muted; font.pixelSize: 13 }
        }
    }
}
