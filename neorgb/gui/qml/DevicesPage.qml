import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

Flickable {
    id: page
    property var win
    readonly property var st: win.st
    readonly property var presets: st.presets || []
    contentHeight: col.implicitHeight + 56
    clip: true
    ScrollBar.vertical: ScrollBar {}

    readonly property var hwNames: ({
        "auto": "Wie der globale Effekt", "rainbow_wave": "Regenbogen-Welle", "rainbow": "Regenbogen",
        "color_shift": "Farbwechsel", "color_pulse": "Pulsieren", "color_wave": "Farbwelle", "static": "Statisch",
        "visor": "Visor", "marquee": "Lauflicht", "blink": "Blinken", "sequential": "Nacheinander", "off": "Aus"
    })
    function devCfg(key) { return (((st.config || {}).devices || {})[key]) || ({}) }
    function chanCfg(key, ch) { return (devCfg(key).channels || {})[String(ch)] || ({}) }
    function items(key, ch) {
        var c = chanCfg(key, ch)
        if (c.items) return c.items
        return (c.segments || []).map(function (n) { return { name: n + " LEDs", leds: n, kind: c.kind || "linear" } })
    }
    function saveItems(key, ch, its, name) {
        var ring = its.length > 0 && its.every(function (i) { return i.kind === "ring" })
        var c = { items: its, segments: its.map(function (i) { return i.leds }), kind: ring ? "ring" : "linear",
                  name: name !== undefined ? name : (chanCfg(key, ch).name || "") }
        var chans = {}; chans[String(ch)] = c
        backend.call("set_device", { key: key, channels: chans })
    }
    function zoneFor(key, ch) { var z = st.zones || []; for (var i = 0; i < z.length; i++) if (z[i].id === key + "/ch" + ch) return z[i]; return null }

    ColumnLayout {
        id: col
        x: 28; y: 28
        width: page.width - 56
        spacing: Theme.gap

        Column {
            Text { text: "Geräte"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
            Text { text: "Lighting Nodes erkennen nicht, was angeschlossen ist. Trag hier pro Kanal ein, was in welcher Reihenfolge dranhängt."
                color: Theme.muted; font.pixelSize: 13; wrapMode: Text.WordWrap; width: col.width }
        }

        Repeater {
            model: st.devices || []
            Card {
                id: dc
                property var dev: modelData
                Layout.fillWidth: true
                title: dev.name
                subtitle: "Firmware " + (dev.firmware || "?") + " · " + (dev.path || "") + (dev.status !== "ok" ? " · " + dev.status + (dev.error ? ": " + dev.error : "") : "")
                header: [ Rectangle { width: 10; height: 10; radius: 5; color: dc.dev.status === "ok" ? Theme.good : (dc.dev.status === "starting" ? Theme.warn : Theme.bad) } ]

                Loader {
                    width: parent.width
                    property var dev: dc.dev
                    sourceComponent: dc.dev.kind === "lighting_node" ? lnC : (dc.dev.kind === "commander_core" ? ccC : otherC)
                }
            }
        }
    }

    // ------------------------------------------------------ Lighting Node
    Component {
        id: lnC
        Column {
            spacing: 16
            Repeater {
                model: dev.channels || 0
                Rectangle {
                    id: chBox
                    property int ch: index
                    property var its: page.items(dev.key, ch)
                    property bool testing: !!dev.test && dev.test.ch === ch
                    property var testPreset: pre.currentIndex < page.presets.length ? page.presets[pre.currentIndex] : { name: cnt.value + " LEDs", leds: cnt.value, kind: "linear" }
                    property int total: its.reduce(function (a, b) { return a + b.leds }, 0)
                    width: parent.width
                    height: chCol.implicitHeight + 28
                    radius: 12; color: Theme.panel; border.color: Theme.line
                    Column {
                        id: chCol
                        x: 14; y: 14; width: parent.width - 28; spacing: 10
                        RowLayout {
                            width: parent.width
                            Text { text: "Kanal " + (chBox.ch + 1); color: Theme.text; font.pixelSize: 14; font.weight: Font.DemiBold }
                            Text { text: chBox.total + " LEDs"; color: chBox.total > 204 ? Theme.bad : Theme.accent; font.pixelSize: 13 }
                            Item { Layout.fillWidth: true }
                            NButton { text: chBox.testing ? "Zählen beenden" : "LEDs zählen"; primary: !chBox.its.length && !chBox.testing
                                onClicked: backend.call("led_test", { key: dev.key, ch: chBox.ch, block: chBox.testPreset.leds, on: !chBox.testing }) }
                            NButton { text: "Aufblinken"; enabled: page.zoneFor(dev.key, chBox.ch) !== null
                                onClicked: backend.call("identify", { zone: dev.key + "/ch" + chBox.ch }) }
                            NButton { text: "Leeren"; danger: true; enabled: chBox.its.length > 0; onClicked: page.saveItems(dev.key, chBox.ch, []) }
                        }
                        Rectangle {
                            visible: chBox.testing
                            width: parent.width; height: tcol.implicitHeight + 24
                            radius: 10; color: Theme.card; border.color: Theme.accent
                            Column {
                                id: tcol
                                x: 12; y: 12; width: parent.width - 24; spacing: 10
                                Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 13
                                    text: "Jedes Teil an diesem Kanal leuchtet jetzt in einer eigenen Farbe (je " + (dev.test ? dev.test.block : 10) + " LEDs, Typ oben im Auswahlfeld). Schau ins Gehäuse und zähle die Farben in dieser Reihenfolge:" }
                                Row {
                                    spacing: 10
                                    Repeater {
                                        model: [["#ff0000", "Rot"], ["#00ff00", "Grün"], ["#003cff", "Blau"], ["#ffc800", "Gelb"], ["#dc00ff", "Lila"], ["#00e6e6", "Türkis"], ["#ffffff", "Weiß"], ["#ff5000", "Orange"]]
                                        Column {
                                            spacing: 4
                                            Rectangle { width: 46; height: 14; radius: 7; color: modelData[0]; anchors.horizontalCenter: parent.horizontalCenter }
                                            Text { text: (index + 1) + ". " + modelData[1]; color: Theme.muted; font.pixelSize: 11; anchors.horizontalCenter: parent.horizontalCenter }
                                        }
                                    }
                                }
                                Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.faint; font.pixelSize: 12
                                    text: "Was dunkel bleibt oder seine alten Farben behält, hängt nicht an diesem Kanal. Ist eine Farbe nur halb zu sehen, oben einen anderen Typ wählen und neu zählen." }
                                Row {
                                    spacing: 6
                                    Text { text: "Ich sehe:"; color: Theme.text; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
                                    Repeater {
                                        model: 8
                                        NButton { text: (index + 1) === 1 ? "1 Farbe" : (index + 1) + ""; onClicked: {
                                            var a = []; for (var i = 0; i <= index; i++) a.push({ name: chBox.testPreset.name, leds: chBox.testPreset.leds, kind: chBox.testPreset.kind })
                                            page.saveItems(dev.key, chBox.ch, a) } }
                                    }
                                    NButton { text: "nichts"; danger: true; onClicked: backend.call("led_test", { key: dev.key, ch: chBox.ch, on: false }) }
                                }
                            }
                        }
                        LedPreview {
                            width: parent.width
                            visible: page.zoneFor(dev.key, chBox.ch) !== null && !chBox.testing
                            property var zn: page.zoneFor(dev.key, chBox.ch)
                            hex: zn ? (win.frame[zn.id] || "") : ""
                            kind: zn ? zn.kind : "linear"; segments: zn ? zn.segments : []; leds: zn ? zn.leds : 0
                        }
                        Flow {
                            width: parent.width; spacing: 8
                            Repeater {
                                model: chBox.its
                                Rectangle {
                                    height: 30; radius: 15; width: lab.implicitWidth + 44
                                    color: Theme.card; border.color: Theme.line
                                    Text { id: lab; x: 12; anchors.verticalCenter: parent.verticalCenter; text: (index + 1) + ". " + modelData.name; color: Theme.text; font.pixelSize: 12 }
                                    Text { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; text: "×"; color: Theme.muted; font.pixelSize: 16
                                        MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor
                                            onClicked: { var a = chBox.its.slice(); a.splice(index, 1); page.saveItems(dev.key, chBox.ch, a) } } }
                                }
                            }
                            Text { visible: !chBox.its.length; text: "Nichts eingetragen: der Hub behält sein eigenes Licht"; color: Theme.faint; font.pixelSize: 12; height: 30; verticalAlignment: Text.AlignVCenter }
                        }
                        Row {
                            spacing: 8
                            NCombo { id: pre; width: 340; model: page.presets.concat([{ name: "Eigene Anzahl…", leds: 0, kind: "linear" }]); textRole: "name" }
                            SpinBox {
                                id: cnt
                                visible: pre.currentIndex === page.presets.length
                                from: 1; to: 204; value: 10; editable: true
                                height: 34
                                palette.text: Theme.text; palette.base: Theme.panel; palette.button: Theme.card; palette.buttonText: Theme.text
                            }
                            NButton { text: "Hinzufügen"; primary: true; onClicked: {
                                var p = pre.currentIndex < page.presets.length ? page.presets[pre.currentIndex] : { name: cnt.value + " LEDs", leds: cnt.value, kind: "linear" }
                                var a = chBox.its.slice(); a.push({ name: p.name, leds: p.leds, kind: p.kind }); page.saveItems(dev.key, chBox.ch, a) } }
                        }
                    }
                }
            }
            Row {
                spacing: 12
                Text { text: "Wenn NeoRGB nicht läuft:"; color: Theme.muted; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
                NCombo {
                    width: 260
                    property var keys: st.hw_effects || []
                    model: keys.map(function (k) { return { name: page.hwNames[k] || k } }); textRole: "name"
                    currentIndex: keys.indexOf(page.devCfg(dev.key).hw_effect || "auto")
                    onActivated: function (i) { backend.call("set_device", { key: dev.key, hw_effect: keys[i], restart: false }) }
                }
            }
        }
    }

    // ------------------------------------------------------ Commander CORE
    Component {
        id: ccC
        Column {
            spacing: 10
            Text { text: "Die angeschlossenen Lüfter und die Pumpe meldet der Commander CORE selbst."; color: Theme.muted; font.pixelSize: 13 }
            Repeater {
                model: dev.detected || []
                Row {
                    spacing: 12
                    property var names: ["Pumpe", "Lüfter 1", "Lüfter 2", "Lüfter 3", "Lüfter 4", "Lüfter 5", "Lüfter 6"]
                    property var over: (page.devCfg(dev.key).ports || {})[String(index)]
                    Text { text: names[index]; color: Theme.text; font.pixelSize: 13; width: 90; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: modelData ? modelData + " LEDs erkannt" : "nichts erkannt"; color: modelData ? Theme.muted : Theme.faint; font.pixelSize: 13; width: 160; anchors.verticalCenter: parent.verticalCenter }
                    NCombo {
                        width: 220
                        visible: index > 0
                        property var opts: [-1, 0, 4, 8, 10, 12, 16, 34]
                        model: opts.map(function (n) { return { name: n < 0 ? "automatisch" : (n === 0 ? "aus" : n + " LEDs") } }); textRole: "name"
                        currentIndex: parent.over === undefined || parent.over === null ? 0 : opts.indexOf(parent.over)
                        onActivated: function (i) { var p = {}; p[String(index)] = opts[i] < 0 ? null : opts[i]; backend.call("set_device", { key: dev.key, ports: p }) }
                    }
                }
            }
        }
    }

    Component {
        id: otherC
        Column {
            spacing: 10
            Text { text: "Über OpenRGB angebunden · " + (dev.path || ""); color: Theme.muted; font.pixelSize: 13; width: parent.width; elide: Text.ElideRight }
            Repeater {
                model: dev.orgb_zones || []
                Row {
                    spacing: 12
                    Text { text: modelData.name; color: Theme.text; font.pixelSize: 13; width: 220; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight }
                    Text { text: modelData.count + " LEDs"; color: modelData.count ? Theme.muted : Theme.faint; font.pixelSize: 13; width: 80; anchors.verticalCenter: parent.verticalCenter }
                    SpinBox {
                        id: zs
                        visible: modelData.max > modelData.min
                        from: modelData.min; to: Math.min(modelData.max, 300); value: modelData.count; editable: true
                        height: 34
                        palette.text: Theme.text; palette.base: Theme.panel; palette.button: Theme.card; palette.buttonText: Theme.text
                    }
                    NButton { visible: modelData.max > modelData.min; text: "Übernehmen"; enabled: zs.value !== modelData.count
                        onClicked: backend.call("set_orgb_zone", { key: dev.key, zone: modelData.index, size: zs.value }) }
                    Text { visible: modelData.max > modelData.min && modelData.count === 0; text: "ARGB-Anschluss: Anzahl der LEDs eintragen"; color: Theme.faint; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                }
            }
        }
    }
}
