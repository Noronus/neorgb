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
    WheelScroll { flick: page }
    ScrollBar.vertical: ScrollBar {}

    readonly property var hwNames: ({
        "auto": qsTr("Wie der globale Effekt"), "rainbow_wave": qsTr("Regenbogen-Welle"), "rainbow": qsTr("Regenbogen"),
        "color_shift": qsTr("Farbwechsel"), "color_pulse": qsTr("Pulsieren"), "color_wave": qsTr("Farbwelle"), "static": qsTr("Statisch"),
        "visor": "Visor", "marquee": qsTr("Lauflicht"), "blink": qsTr("Blinken"), "sequential": qsTr("Nacheinander"), "off": qsTr("Aus")
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
    property string addingHost: ""
    function addWled() {
        var h = wHost.text.trim()
        if (!h) return
        addingHost = h.replace(/^https?:\/\//, "").replace(/\/.*$/, "")
        backend.call("add_wled", { host: h, name: wName.text.trim() })
    }
    // the new device shows up in the list: empty the form
    Connections { target: page.st; function onDevicesChanged() {
        var d = page.st.devices || []
        for (var i = 0; i < d.length; i++) if (d[i].kind === "wled" && d[i].host === page.addingHost) { wHost.text = ""; wName.text = ""; page.addingHost = "" }
    } }
    function zoneFor(key, ch) { var z = st.zones || []; for (var i = 0; i < z.length; i++) if (z[i].id === key + "/ch" + ch) return z[i]; return null }

    ColumnLayout {
        id: col
        x: 28; y: 28
        width: page.width - 56
        spacing: Theme.gap

        Column {
            Text { text: qsTr("Geräte"); color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
            Text { text: qsTr("Lighting Nodes erkennen nicht, was angeschlossen ist. Trag hier pro Kanal ein, was in welcher Reihenfolge dranhängt.")
                color: Theme.muted; font.pixelSize: 13; wrapMode: Text.WordWrap; width: col.width }
        }

        Card {
            Layout.fillWidth: true
            title: qsTr("WLED-Gerät hinzufügen")
            subtitle: qsTr("IP-Adresse oder Hostname des WLED-Controllers. NeoRGB schickt ihm die Effekte per DDP.")
            Row {
                spacing: 10
                TextField {
                    id: wHost
                    width: 240; height: 34
                    placeholderText: qsTr("z. B. 10.0.5.120"); placeholderTextColor: Theme.faint
                    color: Theme.text; font.pixelSize: 13
                    background: Rectangle { radius: 9; color: Theme.panel; border.color: wHost.activeFocus ? Theme.accent : Theme.line }
                    onAccepted: page.addWled()
                }
                TextField {
                    id: wName
                    width: 200; height: 34
                    placeholderText: qsTr("Name (optional)"); placeholderTextColor: Theme.faint
                    color: Theme.text; font.pixelSize: 13
                    background: Rectangle { radius: 9; color: Theme.panel; border.color: wName.activeFocus ? Theme.accent : Theme.line }
                    onAccepted: page.addWled()
                }
                NButton { text: qsTr("Hinzufügen"); primary: true; enabled: wHost.text.trim().length > 0; onClicked: page.addWled() }
            }
        }

        Repeater {
            model: st.devices || []
            Card {
                id: dc
                property var dev: modelData
                property bool off: dev.status === "disabled"
                Layout.fillWidth: true
                opacity: off ? 0.6 : 1
                title: qsTr(dev.name)
                subtitle: off ? qsTr("Ausgeschlossen: NeoRGB fasst dieses Gerät nicht an")
                              : [dev.firmware ? qsTr("Firmware %1").arg(dev.firmware) : "", dev.path || "",
                                 (dev.status !== "ok" && dev.kind !== "hwmon_fans" && dev.kind !== "amdgpu_fan") ? qsTr(dev.status) + (dev.error ? ": " + qsTr(dev.error) : "") : ""]
                                .filter(function (x) { return x.length > 0 }).join(" · ")
                header: [
                    NButton { visible: dc.dev.key !== "openrgb"; text: dc.off ? qsTr("Wieder einbinden") : qsTr("Ausschließen"); primary: dc.off; danger: !dc.off
                        onClicked: backend.call("set_device", { key: dc.dev.key, disabled: !dc.off, name: dc.dev.name, kind: dc.dev.kind }) },
                    Rectangle { width: 10; height: 10; radius: 5; anchors.verticalCenter: parent.verticalCenter
                        color: dc.off ? Theme.faint : (dc.dev.status === "ok" ? Theme.good : (dc.dev.status === "starting" ? Theme.warn : Theme.bad)) }
                ]

                Column {
                    width: parent.width; spacing: 14
                    Text { visible: dc.off; width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 13
                        text: dc.dev.kind === "commander_core"
                              ? qsTr("Lüfter und Pumpe regelt dann die AIO selbst nach ihrer gespeicherten Kurve. Die Einstellung bleibt auch nach Neustarts.")
                              : qsTr("Das Gerät behält sein eigenes Licht. Die Einstellung bleibt auch nach Neustarts.") }
                    Loader {
                        visible: !dc.off; active: !dc.off
                        width: parent.width
                        property var dev: dc.dev
                        sourceComponent: dc.dev.kind === "lighting_node" ? lnC : (dc.dev.kind === "commander_core" ? ccC : (dc.dev.kind === "wled" ? wledC : ((dc.dev.kind === "hwmon_fans" || dc.dev.kind === "amdgpu_fan") ? fanC : otherC)))
                    }
                    Column {
                        visible: !dc.off && (dc.dev.fans || []).length > 0
                        width: parent.width; spacing: 4
                        NSwitch { text: qsTr("Lüfter von NeoRGB steuern"); checked: page.devCfg(dc.dev.key).fan_control !== false
                            onToggled: backend.call("set_device", { key: dc.dev.key, fan_control: checked, restart: false }) }
                        Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.faint; font.pixelSize: 12
                            text: dc.dev.kind === "commander_core"
                                  ? qsTr("Aus: Die AIO fährt ihre gespeicherte Kurve. Drehzahlen bleiben unter „Kühlung“ sichtbar.")
                                  : dc.dev.kind === "amdgpu_fan" ? qsTr("Aus: Die Grafikkarte regelt selbst. Drehzahlen bleiben unter „Kühlung“ sichtbar.")
                                  : qsTr("Aus: Das BIOS regelt selbst. Drehzahlen bleiben unter „Kühlung“ sichtbar.") }
                    }
                    RowLayout {
                        visible: !dc.off && (dc.dev.zones || []).length > 0
                        width: Math.min(parent.width, 720); spacing: 24
                        Text { text: qsTr("Mindesthelligkeit"); color: Theme.muted; font.pixelSize: 13 }
                        NSlider { Layout.fillWidth: true; from: 0; to: 100; suffix: " %"; value: page.devCfg(dc.dev.key).min_brightness || 0
                            onPressedChanged: if (!pressed) backend.call("set_device", { key: dc.dev.key, min_brightness: Math.round(value), restart: false }) }
                    }
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
                            Text { text: qsTr("Kanal %1").arg(chBox.ch + 1); color: Theme.text; font.pixelSize: 14; font.weight: Font.DemiBold }
                            Text { text: chBox.total + " LEDs"; color: chBox.total > 204 ? Theme.bad : Theme.accent; font.pixelSize: 13 }
                            Item { Layout.fillWidth: true }
                            NButton { text: chBox.testing ? qsTr("Zählen beenden") : qsTr("LEDs zählen"); primary: !chBox.its.length && !chBox.testing
                                onClicked: backend.call("led_test", { key: dev.key, ch: chBox.ch, block: chBox.testPreset.leds, on: !chBox.testing }) }
                            NButton { text: qsTr("Aufblinken"); enabled: page.zoneFor(dev.key, chBox.ch) !== null
                                onClicked: backend.call("identify", { zone: dev.key + "/ch" + chBox.ch }) }
                            NButton { text: qsTr("Leeren"); danger: true; enabled: chBox.its.length > 0; onClicked: page.saveItems(dev.key, chBox.ch, []) }
                        }
                        Rectangle {
                            visible: chBox.testing
                            width: parent.width; height: tcol.implicitHeight + 24
                            radius: 10; color: Theme.card; border.color: Theme.accent
                            Column {
                                id: tcol
                                x: 12; y: 12; width: parent.width - 24; spacing: 10
                                Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 13
                                    text: qsTr("Jedes Teil an diesem Kanal leuchtet jetzt in einer eigenen Farbe (je %1 LEDs, Typ oben im Auswahlfeld). Schau ins Gehäuse und zähle die Farben in dieser Reihenfolge:").arg(dev.test ? dev.test.block : 10) }
                                Row {
                                    spacing: 10
                                    Repeater {
                                        model: [["#ff0000", qsTr("Rot")], ["#00ff00", qsTr("Grün")], ["#003cff", qsTr("Blau")], ["#ffc800", qsTr("Gelb")], ["#dc00ff", qsTr("Lila")], ["#00e6e6", qsTr("Türkis")], ["#ffffff", qsTr("Weiß")], ["#ff5000", qsTr("Orange")]]
                                        Column {
                                            spacing: 4
                                            Rectangle { width: 46; height: 14; radius: 7; color: modelData[0]; anchors.horizontalCenter: parent.horizontalCenter }
                                            Text { text: (index + 1) + ". " + modelData[1]; color: Theme.muted; font.pixelSize: 11; anchors.horizontalCenter: parent.horizontalCenter }
                                        }
                                    }
                                }
                                Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.faint; font.pixelSize: 12
                                    text: qsTr("Was dunkel bleibt oder seine alten Farben behält, hängt nicht an diesem Kanal. Ist eine Farbe nur halb zu sehen, oben einen anderen Typ wählen und neu zählen.") }
                                Row {
                                    spacing: 6
                                    Text { text: qsTr("Ich sehe:"); color: Theme.text; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
                                    Repeater {
                                        model: 8
                                        NButton { text: (index + 1) === 1 ? qsTr("1 Farbe") : (index + 1) + ""; onClicked: {
                                            var a = []; for (var i = 0; i <= index; i++) a.push({ name: chBox.testPreset.name, leds: chBox.testPreset.leds, kind: chBox.testPreset.kind })
                                            page.saveItems(dev.key, chBox.ch, a) } }
                                    }
                                    NButton { text: qsTr("nichts"); danger: true; onClicked: backend.call("led_test", { key: dev.key, ch: chBox.ch, on: false }) }
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
                                    Text { id: lab; x: 12; anchors.verticalCenter: parent.verticalCenter; text: (index + 1) + ". " + qsTr(modelData.name); color: Theme.text; font.pixelSize: 12 }
                                    Text { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; text: "×"; color: Theme.muted; font.pixelSize: 16
                                        MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor
                                            onClicked: { var a = chBox.its.slice(); a.splice(index, 1); page.saveItems(dev.key, chBox.ch, a) } } }
                                }
                            }
                            Text { visible: !chBox.its.length; text: qsTr("Nichts eingetragen: der Hub behält sein eigenes Licht"); color: Theme.faint; font.pixelSize: 12; height: 30; verticalAlignment: Text.AlignVCenter }
                        }
                        Row {
                            spacing: 8
                            NCombo { id: pre; width: 340; model: page.presets.map(function (p) { return { name: qsTr(p.name) } }).concat([{ name: qsTr("Eigene Anzahl…") }]); textRole: "name" }
                            SpinBox {
                                id: cnt
                                visible: pre.currentIndex === page.presets.length
                                from: 1; to: 204; value: 10; editable: true
                                height: 34
                                palette.text: Theme.text; palette.base: Theme.panel; palette.button: Theme.card; palette.buttonText: Theme.text
                            }
                            NButton { text: qsTr("Hinzufügen"); primary: true; onClicked: {
                                var p = pre.currentIndex < page.presets.length ? page.presets[pre.currentIndex] : { name: cnt.value + " LEDs", leds: cnt.value, kind: "linear" }
                                var a = chBox.its.slice(); a.push({ name: p.name, leds: p.leds, kind: p.kind }); page.saveItems(dev.key, chBox.ch, a) } }
                        }
                    }
                }
            }
            Row {
                spacing: 12
                Text { text: qsTr("Wenn NeoRGB nicht läuft:"); color: Theme.muted; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
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
            Text { text: qsTr("Die angeschlossenen Lüfter und die Pumpe meldet der Commander CORE selbst."); color: Theme.muted; font.pixelSize: 13 }
            Repeater {
                model: dev.detected || []
                Row {
                    spacing: 12
                    property var names: [qsTr("Pumpe"), qsTr("Lüfter %1").arg(1), qsTr("Lüfter %1").arg(2), qsTr("Lüfter %1").arg(3), qsTr("Lüfter %1").arg(4), qsTr("Lüfter %1").arg(5), qsTr("Lüfter %1").arg(6)]
                    property var over: (page.devCfg(dev.key).ports || {})[String(index)]
                    Text { text: names[index]; color: Theme.text; font.pixelSize: 13; width: 90; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: modelData ? qsTr("%1 LEDs erkannt").arg(modelData) : qsTr("nichts erkannt"); color: modelData ? Theme.muted : Theme.faint; font.pixelSize: 13; width: 160; anchors.verticalCenter: parent.verticalCenter }
                    NCombo {
                        width: 220
                        visible: index > 0
                        property var opts: [-1, 0, 4, 8, 10, 12, 16, 34]
                        model: opts.map(function (n) { return { name: n < 0 ? qsTr("automatisch") : (n === 0 ? qsTr("aus") : n + " LEDs") } }); textRole: "name"
                        currentIndex: parent.over === undefined || parent.over === null ? 0 : opts.indexOf(parent.over)
                        onActivated: function (i) { var p = {}; p[String(index)] = opts[i] < 0 ? null : opts[i]; backend.call("set_device", { key: dev.key, ports: p }) }
                    }
                }
            }
        }
    }

    // ------------------------------------------------- mainboard / GPU fans
    Component {
        id: fanC
        Column {
            spacing: 8
            Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 13
                text: qsTr("%1 Lüfter · eingestellt wird unter „Kühlung“.").arg((dev.fans || []).length) + " " + (dev.kind === "hwmon_fans"
                      ? qsTr("Anschlüsse erscheinen, sobald dort einmal ein Lüfter gedreht hat. Stoppt NeoRGB, regelt wieder das BIOS.")
                      : qsTr("Die Kurve läuft in der Grafikkarte selbst, gegen die Hotspot-Temperatur.")) }
            Text { visible: !!dev.error; width: parent.width; wrapMode: Text.WordWrap; color: Theme.warn; font.pixelSize: 13; text: qsTr(dev.error || "") }
            Row {
                visible: !!dev.fix_cmd
                spacing: 10
                Rectangle {
                    width: cmdText.implicitWidth + 24; height: 34; radius: 8
                    color: Theme.panel; border.color: Theme.line
                    TextEdit { id: cmdText; anchors.centerIn: parent; text: dev.fix_cmd || ""; readOnly: true; selectByMouse: true
                        color: Theme.text; selectionColor: Theme.accent; font.family: "monospace"; font.pixelSize: 13 }
                }
                NButton { text: qsTr("Kopieren"); onClicked: backend.copyText(dev.fix_cmd) }
            }
        }
    }

    // ---------------------------------------------------------------- WLED
    Component {
        id: wledC
        Column {
            spacing: 10
            Text { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 13
                color: dev.status === "ok" ? Theme.muted : Theme.bad
                text: dev.status === "ok"
                      ? qsTr("WLED über das Netzwerk · %1 LEDs. Läuft NeoRGB nicht, zeigt WLED nach ein paar Sekunden wieder seinen eigenen Effekt.").arg(dev.leds)
                      : qsTr("Nicht erreichbar, NeoRGB versucht es alle 10 s erneut.") + (dev.error ? " (" + qsTr(dev.error) + ")" : "") }
            Row {
                spacing: 10
                TextField {
                    id: wRename
                    width: 220; height: 34
                    text: dev.name; color: Theme.text; font.pixelSize: 13
                    background: Rectangle { radius: 9; color: Theme.panel; border.color: wRename.activeFocus ? Theme.accent : Theme.line }
                    onEditingFinished: if (text.trim() !== dev.name) backend.call("rename_wled", { key: dev.key, name: text.trim() })
                }
                NButton { text: qsTr("WLED-Oberfläche öffnen"); onClicked: Qt.openUrlExternally(dev.path) }
                NButton { text: qsTr("Entfernen"); danger: true; onClicked: backend.call("remove_wled", { key: dev.key }) }
            }
        }
    }

    Component {
        id: otherC
        Column {
            spacing: 10
            Text { text: qsTr("Über OpenRGB angebunden · %1").arg(dev.path || ""); color: Theme.muted; font.pixelSize: 13; width: parent.width; elide: Text.ElideRight }
            Repeater {
                model: dev.orgb_zones || []
                Row {
                    spacing: 12
                    Text { text: qsTr(modelData.name); color: Theme.text; font.pixelSize: 13; width: 220; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight }
                    Text { text: modelData.count + " LEDs"; color: modelData.count ? Theme.muted : Theme.faint; font.pixelSize: 13; width: 80; anchors.verticalCenter: parent.verticalCenter }
                    SpinBox {
                        id: zs
                        visible: modelData.max > modelData.min
                        from: modelData.min; to: Math.min(modelData.max, 300); value: modelData.count; editable: true
                        height: 34
                        palette.text: Theme.text; palette.base: Theme.panel; palette.button: Theme.card; palette.buttonText: Theme.text
                    }
                    NButton { visible: modelData.max > modelData.min; text: qsTr("Übernehmen"); enabled: zs.value !== modelData.count
                        onClicked: backend.call("set_orgb_zone", { key: dev.key, zone: modelData.index, size: zs.value }) }
                    Text { visible: modelData.max > modelData.min && modelData.count === 0; text: qsTr("ARGB-Anschluss: Anzahl der LEDs eintragen"); color: Theme.faint; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                }
            }
        }
    }
}
