import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

Flickable {
    id: page
    property var win
    readonly property var st: win.st
    contentHeight: col.implicitHeight + 56
    clip: true
    ScrollBar.vertical: ScrollBar {}

    function pump() { var f = st.fans || []; for (var i = 0; i < f.length; i++) if (f[i].pump) return win.live(f[i].id); return null }

    ColumnLayout {
        id: col
        x: 28; y: 28
        width: page.width - 56
        spacing: Theme.gap

        Column {
            Text { text: "Übersicht"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
            Text { text: (st.devices || []).length + " Geräte · " + (st.fans || []).length + " Lüfter/Pumpen · " + (st.zones || []).length + " Lichtzonen"; color: Theme.muted; font.pixelSize: 13 }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: page.width > 1100 ? 4 : 2
            columnSpacing: Theme.gap; rowSpacing: Theme.gap
            Stat { Layout.fillWidth: true; label: "Wasser"; value: Theme.fmt(win.sensor("liquid")); unit: "°C"
                tint: Theme.accent; fill: (win.sensor("liquid") - 20) / 30; sub: "AIO-Kühlmittel" }
            Stat { Layout.fillWidth: true; label: "CPU"; value: Theme.fmt(win.sensor("cpu")); unit: "°C"
                tint: Theme.accent2; fill: (win.sensor("cpu") - 25) / 70; sub: "Tctl" }
            Stat { Layout.fillWidth: true; label: "GPU"; value: Theme.fmt(win.sensor("gpu")); unit: "°C"
                tint: Theme.pink; fill: (win.sensor("gpu") - 25) / 85; sub: "Hotspot" }
            Stat { Layout.fillWidth: true; label: "Pumpe"; value: page.pump() && page.pump().rpm != null ? page.pump().rpm : "–"; unit: "rpm"
                tint: Theme.good; fill: page.pump() && page.pump().duty != null ? page.pump().duty / 100 : -1
                sub: page.pump() && page.pump().duty != null ? Math.round(page.pump().duty) + " % Leistung" : "" }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gap
            Card {
                Layout.fillWidth: true
                Layout.preferredWidth: 3
                Layout.alignment: Qt.AlignTop
                title: "Temperaturen"; subtitle: "letzte 10 Minuten"
                header: [
                    Row { spacing: 14
                        Repeater { model: [["Wasser", Theme.accent], ["CPU", Theme.accent2], ["GPU", Theme.pink]]
                            Row { spacing: 6
                                Rectangle { width: 10; height: 3; radius: 2; color: modelData[1]; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: modelData[0]; color: Theme.muted; font.pixelSize: 12 } } } }
                ]
                Sparkline {
                    width: parent.width; height: 210
                    series: [
                        { data: (backend.history || {}).liquid || [], color: "#22d3ee" },
                        { data: (backend.history || {}).cpu || [], color: "#a78bfa" },
                        { data: (backend.history || {}).gpu || [], color: "#f472b6" }
                    ]
                }
            }
            Card {
                Layout.fillWidth: true
                Layout.preferredWidth: 2
                Layout.alignment: Qt.AlignTop
                title: "Lüfter & Pumpe"
                Column {
                    width: parent.width; spacing: 14
                    Repeater {
                        model: st.fans || []
                        Column {
                            id: fr
                            property var lv: win.live(modelData.id)
                            width: parent.width; spacing: 6
                            Row {
                                width: parent.width
                                Text { text: modelData.cfg.label || modelData.name; color: Theme.text; font.pixelSize: 13; width: parent.width - 140 }
                                Text { text: fr.lv.rpm + " rpm"; color: Theme.muted; font.pixelSize: 13; width: 80; horizontalAlignment: Text.AlignRight }
                                Text { text: fr.lv.duty == null ? "–" : Math.round(fr.lv.duty) + " %"; color: Theme.text; font.pixelSize: 13; font.weight: Font.DemiBold; width: 60; horizontalAlignment: Text.AlignRight }
                            }
                            Item { width: parent.width; height: 6
                                Rectangle { anchors.fill: parent; radius: 3; color: Theme.line }
                                Rectangle { height: 6; radius: 3; width: parent.width * (fr.lv.duty || 0) / 100
                                    color: fr.lv.failsafe ? Theme.bad : (modelData.pump ? Theme.good : Theme.accent)
                                    Behavior on width { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } } }
                            }
                        }
                    }
                    Text { visible: !(st.fans || []).length; text: "Keine Lüftersteuerung gefunden"; color: Theme.muted; font.pixelSize: 13 }
                }
            }
        }

        Card {
            Layout.fillWidth: true
            title: "Beleuchtung"
            subtitle: {
                var g = ((st.config || {}).lighting || {}).global || {}
                var e = (st.effects || {})[g.effect]
                return "Aktueller Effekt: " + (e ? e.name : (g.effect || "–"))
            }
            header: [ NButton { text: "Bearbeiten"; onClicked: win.page = 2 } ]
            Column {
                width: parent.width; spacing: 14
                Row {
                    width: parent.width; spacing: 14
                    Text { text: "Helligkeit"; color: Theme.muted; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter; width: 80 }
                    NSlider {
                        width: Math.min(420, parent.width - 100); from: 0; to: 100; suffix: " %"
                        value: ((st.config || {}).lighting || {}).brightness || 0
                        onMoved: backend.call("set_brightness", { value: value })
                    }
                }
                Flow {
                    width: parent.width; spacing: 18
                    Repeater {
                        model: st.zones || []
                        Column {
                            spacing: 6
                            width: modelData.kind === "ring" ? 120 : 260
                            Text { text: modelData.name; color: Theme.muted; font.pixelSize: 12 }
                            LedPreview { width: parent.width; hex: win.frame[modelData.id] || ""; kind: modelData.kind; segments: modelData.segments; leds: modelData.leds }
                        }
                    }
                }
            }
        }
    }
}
