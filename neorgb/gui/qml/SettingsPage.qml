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
    WheelScroll { flick: page }

    ColumnLayout {
        id: col
        x: 28; y: 28
        width: Math.min(page.width - 56, 860)
        spacing: Theme.gap

        Text { text: qsTr("Einstellungen"); color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }

        Card {
            Layout.fillWidth: true
            title: qsTr("Sprache")
            Row {
                spacing: 8
                Chip { text: "Deutsch"; selected: backend.language === "de"; onClicked: backend.setLanguage("de") }
                Chip { text: "English"; selected: backend.language === "en"; onClicked: backend.setLanguage("en") }
            }
        }

        Card {
            Layout.fillWidth: true
            title: qsTr("Andere RGB-Geräte über OpenRGB")
            subtitle: qsTr("Mainboard (Aura), RAM, Tastatur und Maus laufen über einen OpenRGB-Server. Die Corsair-Hubs bleiben bei NeoRGB.")
            Column {
                width: parent.width; spacing: 10
                NSwitch { text: qsTr("OpenRGB-Geräte einbinden"); checked: !!page.orgb.enabled; onToggled: backend.call("set_openrgb", { enabled: checked }) }
                NSwitch { text: qsTr("OpenRGB-Server selbst starten (ohne Corsair-Hubs)"); checked: page.orgb.spawn !== false; onToggled: backend.call("set_openrgb", { spawn: checked }) }
                Text { text: qsTr("Änderungen hier greifen nach einem Neustart des Dienstes."); color: Theme.faint; font.pixelSize: 12 }
            }
        }

        Card {
            Layout.fillWidth: true
            title: qsTr("Beleuchtung")
            GridLayout {
                width: parent.width; columns: 2; columnSpacing: 24
                Text { text: qsTr("Bilder pro Sekunde"); color: Theme.muted; font.pixelSize: 13; Layout.fillWidth: true }
                NSlider { Layout.preferredWidth: 300; from: 10; to: 60; stepSize: 5; value: ((st.config || {}).lighting || {}).fps || 30
                    onPressedChanged: if (!pressed) backend.call("set_lighting", { fps: value }) }
            }
        }

        Card {
            Layout.fillWidth: true
            title: qsTr("Dienst")
            subtitle: qsTr("neorgbd läuft im Hintergrund und regelt auch ohne dieses Fenster.")
            Column {
                width: parent.width; spacing: 8
                Text { text: qsTr("Läuft seit %1 min").arg(Math.round((st.uptime || 0) / 60)); color: Theme.muted; font.pixelSize: 13 }
                Row {
                    spacing: 10
                    NButton { text: qsTr("Dienst neu starten"); onClicked: backend.restartDaemon() }
                    NButton { text: qsTr("Ausschalten bis zum Neustart"); danger: true; onClicked: backend.stopDaemon() }
                }
                Text { text: qsTr("Neu starten lädt auch den OpenRGB-Server neu. Ausgeschaltet regelt die AIO nach ihrer gespeicherten Kurve, bis zum nächsten Login.")
                    color: Theme.faint; font.pixelSize: 12; width: parent.width; wrapMode: Text.WordWrap }
                Text { text: qsTr("Autostart: systemctl --user enable --now neorgbd"); color: Theme.text; font.family: "monospace"; font.pixelSize: 13 }
                Text { text: qsTr("Konfiguration: ~/.config/neorgb/config.json"); color: Theme.text; font.family: "monospace"; font.pixelSize: 13 }
            }
        }

        Card {
            Layout.fillWidth: true
            title: qsTr("Über")
            Text { text: qsTr("NeoRGB %1 · GPL-3.0-or-later · Protokolle nach liquidctl, OpenLinkHub und OpenRGB").arg(backend.version); color: Theme.muted; font.pixelSize: 13 }
        }
    }
}
