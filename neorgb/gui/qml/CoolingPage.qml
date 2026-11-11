import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

Flickable {
    id: page
    property var win
    readonly property var st: win.st
    readonly property var cooling: (st.config || {}).cooling || ({})
    readonly property var curves: cooling.curves || ({})
    property string selFan: ""
    property string selCurve: "balanced"
    contentHeight: col.implicitHeight + 56
    clip: true
    WheelScroll { flick: page }
    ScrollBar.vertical: ScrollBar {}

    function fanById(id) { var f = st.fans || []; for (var i = 0; i < f.length; i++) if (f[i].id === id) return f[i]; return null }
    function curveIds() { return Object.keys(curves) }
    function curveName(id) { return curves[id] ? curves[id].name : id }
    // The GPU runs its curve itself and only knows its own temperature.
    function gpuCurve(id) { var s = curves[id] ? curves[id].sensor || "" : ""; return s === "gpu" || s.indexOf("hwmon:amdgpu") === 0 }
    function fanCurveIds(fan) {
        if (fan.source !== "gpu") return curveIds()
        var ids = curveIds().filter(gpuCurve)
        if (fan.cfg.curve && curves[fan.cfg.curve] && ids.indexOf(fan.cfg.curve) < 0) ids.push(fan.cfg.curve)
        return ids
    }
    function defaultCurve(fan) {
        var c = fan.cfg.curve
        if (fan.source === "gpu") { if (c && gpuCurve(c)) return c; var g = curveIds().filter(gpuCurve); return g.length ? g[0] : "gpu" }
        return c || (fan.pump ? "pump_balanced" : "balanced")
    }
    function sensorRange(sid) { return sid === "liquid" ? [20, 55] : [20, 100] }
    readonly property var curCurve: curves[selCurve] || ({ points: [], sensor: "liquid", name: "" })
    readonly property var range: sensorRange(curCurve.sensor)
    readonly property var selectedFan: fanById(selFan)

    Component.onCompleted: pickDefault()
    Connections { target: page.st; function onFansChanged() { if (!page.selFan) page.pickDefault() } }
    function pickDefault() {
        var f = st.fans || []
        if (f.length) { selFan = f[f.length > 1 ? 1 : 0].id; if (selectedFan && selectedFan.cfg.curve) selCurve = selectedFan.cfg.curve }
    }
    function newCurveId() { var i = 1; while (curves["custom" + i]) i++; return "custom" + i }
    function saveCurve(patch) {
        var c = JSON.parse(JSON.stringify(curCurve))
        for (var k in patch) c[k] = patch[k]
        backend.call("set_curve", { id: selCurve, curve: c })
    }

    ColumnLayout {
        id: col
        x: 28; y: 28
        width: page.width - 56
        spacing: Theme.gap

        Column {
            Text { text: "Kühlung"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
            Text { text: "Lüfter, Pumpe, Mainboard- und GPU-Lüfter folgen einer Kurve, laufen fest oder bleiben bei BIOS/GPU. Ziehe Punkte, Doppelklick fügt hinzu, Rechtsklick entfernt."; color: Theme.muted; font.pixelSize: 13; wrapMode: Text.WordWrap; width: col.width }
        }

        // ---------------------------------------------------- channel cards
        Flow {
            Layout.fillWidth: true
            spacing: Theme.gap
            Repeater {
                model: st.fans || []
                Rectangle {
                    id: fc
                    property var lv: win.live(modelData.id)
                    property bool sel: page.selFan === modelData.id
                    width: Math.max(220, (col.width - Theme.gap * 3) / 4)
                    height: Math.max(168, cardCol.implicitHeight + 28)
                    radius: Theme.radius
                    color: sel ? Theme.cardHi : Theme.card
                    border.color: sel ? (modelData.pump ? Theme.good : Theme.accent) : Theme.line
                    border.width: sel ? 2 : 1
                    MouseArea { anchors.fill: parent; onClicked: { page.selFan = modelData.id; if (modelData.cfg.mode === "curve") page.selCurve = modelData.cfg.curve } }
                    Column {
                        id: cardCol
                        x: 16; y: 14; width: parent.width - 32; spacing: 8
                        Row {
                            width: parent.width
                            Text { text: modelData.cfg.label || modelData.name; color: Theme.text; font.pixelSize: 15; font.weight: Font.DemiBold; width: parent.width - fsb.width; elide: Text.ElideRight }
                            Text { id: fsb; text: fc.lv.failsafe ? "FAILSAFE" + (fc.lv.why ? ": " + fc.lv.why : "") : ""
                                color: Theme.bad; font.pixelSize: 11; font.weight: Font.Bold; width: Math.min(implicitWidth, parent.width * 0.7)
                                elide: Text.ElideRight; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter }
                        }
                        Row {
                            spacing: 6
                            Text { text: fc.lv.rpm === undefined ? "–" : fc.lv.rpm; color: Theme.text; font.pixelSize: 26; font.weight: Font.DemiBold }
                            Text { text: "rpm"; color: Theme.muted; font.pixelSize: 13; anchors.baseline: parent.children[0].baseline }
                            Item { width: 10; height: 1 }
                            Text { text: fc.lv.duty == null ? "" : Math.round(fc.lv.duty) + " %"; color: modelData.pump ? Theme.good : Theme.accent; font.pixelSize: 15; font.weight: Font.DemiBold; anchors.baseline: parent.children[0].baseline }
                        }
                        Text { visible: modelData.managed === false; width: parent.width; wrapMode: Text.WordWrap
                            text: "Regelt sich selbst (Lüftersteuerung für dieses Gerät aus, siehe Geräte)"; color: Theme.faint; font.pixelSize: 12 }
                        Text { visible: modelData.writable === false && modelData.managed !== false; width: parent.width; wrapMode: Text.WordWrap
                            text: modelData.hint || "Nur Anzeige: keine Schreibrechte (siehe Geräte)"; color: Theme.faint; font.pixelSize: 12 }
                        Row {
                            spacing: 6
                            visible: modelData.writable !== false && modelData.managed !== false
                            Chip { visible: !!modelData.hw_name; text: modelData.hw_name || ""; selected: modelData.cfg.mode === "hardware"; height: 26
                                onClicked: backend.call("set_fan", { fan: modelData.id, mode: "hardware" }) }
                            Chip { text: "Kurve"; selected: modelData.cfg.mode === "curve"; height: 26
                                onClicked: { backend.call("set_fan", { fan: modelData.id, mode: "curve", curve: page.defaultCurve(modelData) }); page.selFan = modelData.id } }
                            Chip { text: "Fest"; selected: modelData.cfg.mode === "fixed"; height: 26
                                onClicked: { backend.call("set_fan", { fan: modelData.id, mode: "fixed", fixed: Math.round(fc.lv.duty || 50) }); page.selFan = modelData.id } }
                        }
                        Text { visible: !!modelData.mode_note && modelData.writable !== false && modelData.managed !== false; width: parent.width; wrapMode: Text.WordWrap
                            text: modelData.mode_note || ""; color: Theme.warn; font.pixelSize: 11 }
                        Loader {
                            width: parent.width
                            visible: modelData.writable !== false && modelData.managed !== false
                            sourceComponent: modelData.cfg.mode === "hardware" ? hwC : (modelData.cfg.mode === "fixed" ? fixedC : curveC)
                            property var fan: modelData
                        }
                    }
                }
            }
            Component {
                id: hwC
                Text { text: fan.source === "gpu" ? "Die Grafikkarte regelt selbst" : "Das Mainboard regelt nach BIOS-Einstellung"
                    color: Theme.muted; font.pixelSize: 12; wrapMode: Text.WordWrap; height: 34; verticalAlignment: Text.AlignVCenter }
            }
            Component {
                id: fixedC
                NSlider {
                    from: fan.pump ? 50 : 0; to: 100; suffix: " %"; tint: fan.pump ? Theme.good : Theme.accent
                    value: fan.cfg.fixed || 50
                    onPressedChanged: if (!pressed) backend.call("set_fan", { fan: fan.id, fixed: Math.round(value) })
                }
            }
            Component {
                id: curveC
                NCombo {
                    property var ids: page.fanCurveIds(fan)
                    model: ids.map(function (k) { return { id: k, name: page.curveName(k) } })
                    textRole: "name"
                    currentIndex: ids.indexOf(fan.cfg.curve)
                    onActivated: function (i) { var id = ids[i]; backend.call("set_fan", { fan: fan.id, mode: "curve", curve: id }); page.selCurve = id; page.selFan = fan.id }
                }
            }
        }

        // -------------------------------------------------------- curve editor
        Card {
            Layout.fillWidth: true
            title: "Kurve: " + (page.curCurve.name || page.selCurve)
            subtitle: {
                var users = (st.fans || []).filter(function (f) { return f.cfg.mode === "curve" && f.cfg.curve === page.selCurve }).map(function (f) { return f.cfg.label || f.name })
                return users.length ? "verwendet von " + users.join(", ") : "von keinem Kanal verwendet"
            }
            header: [
                NButton { text: "Neue Kurve"; onClicked: {
                    var id = page.newCurveId()
                    backend.call("set_curve", { id: id, curve: { name: "Eigene " + id.substring(6), sensor: page.curCurve.sensor || "liquid", average: 0, points: page.curCurve.points } })
                    page.selCurve = id } },
                NButton { text: "Löschen"; danger: true; enabled: page.curveIds().length > 1; onClicked: backend.call("delete_curve", { id: page.selCurve }) }
            ]
            Column {
                width: parent.width
                spacing: 14
                Flow {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: page.curveIds()
                        Chip { text: page.curveName(modelData); selected: page.selCurve === modelData; onClicked: page.selCurve = modelData }
                    }
                }
                RowLayout {
                    width: parent.width
                    spacing: 20
                    Column {
                        spacing: 6
                        SectionLabel { text: "Sensor" }
                        NCombo {
                            width: 230
                            model: (st.sensors || []).map(function (s) { return { id: s.id, name: s.label + (s.value !== null ? "  (" + Theme.fmt(s.value) + " °C)" : "") } })
                            textRole: "name"
                            currentIndex: (st.sensors || []).map(function (s) { return s.id }).indexOf(page.curCurve.sensor)
                            onActivated: function (i) { page.saveCurve({ sensor: st.sensors[i].id }) }
                        }
                    }
                    Column {
                        spacing: 6
                        SectionLabel { text: "Glätten" }
                        NCombo {
                            width: 150
                            model: [{ v: 0, name: "aus" }, { v: 4, name: "4 Sekunden" }, { v: 8, name: "8 Sekunden" }, { v: 15, name: "15 Sekunden" }, { v: 30, name: "30 Sekunden" }]
                            textRole: "name"
                            currentIndex: [0, 4, 8, 15, 30].indexOf(Number(page.curCurve.average || 0))
                            onActivated: function (i) { page.saveCurve({ average: [0, 4, 8, 15, 30][i] }) }
                        }
                    }
                    Column {
                        spacing: 6
                        SectionLabel { text: "Name" }
                        TextField {
                            id: nameField
                            width: 200; height: 34
                            text: page.curCurve.name || ""
                            color: Theme.text; font.pixelSize: 13
                            background: Rectangle { radius: 9; color: Theme.panel; border.color: nameField.activeFocus ? Theme.accent : Theme.line }
                            onEditingFinished: if (text !== page.curCurve.name) page.saveCurve({ name: text })
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Column {
                        spacing: 4
                        SectionLabel { text: "Aktuell" }
                        Text {
                            property var t: win.sensor(page.curCurve.sensor)
                            text: (t === null ? "–" : Theme.fmt(t) + " °C") + "  ·  " + win.sensorLabel(page.curCurve.sensor)
                            color: Theme.warn; font.pixelSize: 15; font.weight: Font.DemiBold
                        }
                    }
                }
                CurveEditor {
                    width: parent.width; height: 320
                    points: page.curCurve.points
                    tMin: page.range[0]; tMax: page.range[1]
                    temp: win.sensor(page.curCurve.sensor)
                    duty: page.selectedFan && page.selectedFan.cfg.mode === "curve" && page.selectedFan.cfg.curve === page.selCurve ? win.live(page.selectedFan.id).duty : null
                    tint: page.selCurve.indexOf("pump") === 0 ? Theme.good : Theme.accent
                    minDuty: page.selCurve.indexOf("pump") === 0 ? 50 : 0
                    onEdited: function (p) { page.saveCurve({ points: p }) }
                }
            }
        }

        // ---------------------------------------------------------- advanced
        Card {
            Layout.fillWidth: true
            title: "Verhalten"
            subtitle: "Gilt für alle Kurven"
            GridLayout {
                width: parent.width
                columns: 2; columnSpacing: 24; rowSpacing: 12
                Text { text: "Hysterese (erst bei so viel Grad weniger langsamer werden)"; color: Theme.muted; font.pixelSize: 13; Layout.fillWidth: true }
                NSlider { Layout.preferredWidth: 300; from: 0; to: 5; stepSize: 0.5; decimals: 1; suffix: " °C"; value: (page.cooling.settings || {}).hysteresis || 0
                    onPressedChanged: if (!pressed) backend.call("set_cooling", { hysteresis: value }) }
                Text { text: "Hochregeln höchstens (pro Sekunde)"; color: Theme.muted; font.pixelSize: 13 }
                NSlider { Layout.preferredWidth: 300; from: 1; to: 30; stepSize: 1; suffix: " %"; value: (page.cooling.settings || {}).ramp_up || 8
                    onPressedChanged: if (!pressed) backend.call("set_cooling", { ramp_up: value }) }
                Text { text: "Runterregeln höchstens (pro Sekunde)"; color: Theme.muted; font.pixelSize: 13 }
                NSlider { Layout.preferredWidth: 300; from: 0.5; to: 20; stepSize: 0.5; decimals: 1; suffix: " %"; value: (page.cooling.settings || {}).ramp_down || 3
                    onPressedChanged: if (!pressed) backend.call("set_cooling", { ramp_down: value }) }
                Column {
                    Layout.fillWidth: true; spacing: 2
                    Text { text: "Leistung, wenn der Sensor einer Kurve ausfällt"; color: Theme.muted; font.pixelSize: 13 }
                    Text { text: "Gilt nur für Kanäle, deren eigener Sensor fehlt. Die Pumpe läuft nie unter 50 %. Ab 50 °C Wasser gehen immer alle auf 100 %."
                        color: Theme.faint; font.pixelSize: 12; wrapMode: Text.WordWrap; width: parent.width }
                }
                NSlider { Layout.preferredWidth: 300; from: 30; to: 100; stepSize: 5; suffix: " %"
                    value: (page.cooling.settings || {}).failsafe_duty !== undefined ? page.cooling.settings.failsafe_duty : 100
                    onPressedChanged: if (!pressed) backend.call("set_cooling", { failsafe_duty: value }) }
                Text { text: "Sensor gilt als ausgefallen nach"; color: Theme.muted; font.pixelSize: 13 }
                NSlider { Layout.preferredWidth: 300; from: 3; to: 60; stepSize: 1; suffix: " s"
                    value: (page.cooling.settings || {}).sensor_timeout || 6
                    onPressedChanged: if (!pressed) backend.call("set_cooling", { sensor_timeout: value }) }
                Column {
                    Layout.fillWidth: true; spacing: 2
                    Text { text: "Kurven in der AIO speichern"; color: Theme.text; font.pixelSize: 13 }
                    Text { text: "Läuft NeoRGB nicht (Boot, Absturz), regelt die AIO selbst nach Wassertemperatur. Kurven mit anderem Sensor werden dort durch „Ausgewogen“ ersetzt."
                        color: Theme.faint; font.pixelSize: 12; wrapMode: Text.WordWrap; width: parent.width }
                }
                NSwitch { checked: page.cooling.hw_fallback !== false; onToggled: backend.call("set_cooling", { hw_fallback: checked }) }
            }
        }
    }
}
