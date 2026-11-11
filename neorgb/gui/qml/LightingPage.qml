import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

Flickable {
    id: page
    property var win
    readonly property var st: win.st
    readonly property var lighting: (st.config || {}).lighting || ({})
    property string target: ""          // "" = global, otherwise a zone id
    contentHeight: col.implicitHeight + 56
    clip: true
    WheelScroll { flick: page }
    ScrollBar.vertical: ScrollBar {}

    function zoneById(id) { var z = st.zones || []; for (var i = 0; i < z.length; i++) if (z[i].id === id) return z[i]; return null }
    readonly property var tzone: target ? zoneById(target) : null
    readonly property bool own: tzone !== null && tzone.cfg && tzone.cfg.follow === false
    readonly property var spec: own && tzone.cfg.spec ? tzone.cfg.spec : (lighting.global || ({}))
    readonly property var effects: st.effects || ({})
    readonly property var params: (effects[spec.effect] || { params: [] }).params
    readonly property bool editable: target === "" || own

    function sameSpec(a, b) {
        var ka = Object.keys(a).filter(function (k) { return k !== "by_effect" }).sort()
        var kb = Object.keys(b).filter(function (k) { return k !== "by_effect" }).sort()
        if (ka.join() !== kb.join()) return false
        for (var i = 0; i < ka.length; i++) if (JSON.stringify(a[ka[i]]) !== JSON.stringify(b[ka[i]])) return false
        return true
    }
    function has(p) { return params.indexOf(p) >= 0 }
    function apply(patch) {
        if (target === "") backend.call("set_global", { spec: patch })
        else backend.call("set_zone", { zone: target, follow: false, spec: patch })
    }
    readonly property var saved: ((lighting.saved || {})[target || "global"]) || []
    function colorsWanted() { return has("colors1") ? 1 : (has("colors2") ? 2 : (has("colors") ? 6 : 0)) }

    ColorPicker {
        id: picker
        property int idx: 0
        property string field: "colors"
        parent: Overlay.overlay
        x: (parent.width - width) / 2; y: (parent.height - height) / 2
        onPicked: function (c) {
            var hex = c.toString()
            if (field === "background") { page.apply({ background: hex }); return }
            var cs = (page.spec.colors || []).slice()
            cs[idx] = hex
            page.apply({ colors: cs })
        }
    }

    ColumnLayout {
        id: col
        x: 28; y: 28
        width: page.width - 56
        spacing: Theme.gap

        RowLayout {
            Layout.fillWidth: true
            Column {
                Layout.fillWidth: true
                Text { text: qsTr("Beleuchtung"); color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
                Text { text: qsTr("Ein Effekt für alles oder eigene Effekte pro Zone."); color: Theme.muted; font.pixelSize: 13 }
            }
            Text { text: qsTr("Gesamthelligkeit"); color: Theme.muted; font.pixelSize: 13 }
            NSlider { Layout.preferredWidth: 260; from: 0; to: 100; suffix: " %"; value: page.lighting.brightness || 0
                onMoved: backend.call("set_brightness", { value: value }) }
        }

        // ----------------------------------------------------------- profiles
        Card {
            Layout.fillWidth: true
            title: qsTr("Profile")
            subtitle: qsTr("Ein Profil speichert die Effekte aller Zonen auf einmal")
            Column {
                width: parent.width
                spacing: 8
                Flow {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: page.lighting.profiles || []
                        Chip { text: qsTr(modelData.name); selected: st.active_profile === modelData.name
                            onClicked: backend.call("load_profile", { index: index })
                            onRightClicked: backend.call("delete_profile", { index: index }) }
                    }
                    TextField {
                        id: profName
                        width: 180; height: 30
                        placeholderText: qsTr("Name")
                        color: Theme.text; placeholderTextColor: Theme.faint; font.pixelSize: 13
                        background: Rectangle { radius: 15; color: Theme.panel; border.color: profName.activeFocus ? Theme.accent : Theme.line }
                        leftPadding: 12
                        onAccepted: profBtn.clicked()
                    }
                    NButton { id: profBtn; text: qsTr("Alles speichern"); height: 30
                        onClicked: { backend.call("save_profile", { name: profName.text }); profName.text = "" } }
                }
                Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.faint; font.pixelSize: 11
                    text: (page.lighting.profiles || []).length ? qsTr("Klick lädt das Profil. Rechtsklick löscht. Gleicher Name überschreibt.")
                                                                : qsTr("Noch keine Profile. Speichert den globalen Effekt und alle Zonen mit eigenem Effekt.") }
            }
        }

        // ----------------------------------------------------------- targets
        Card {
            Layout.fillWidth: true
            title: qsTr("Zonen")
            subtitle: qsTr("Klick auf eine Zone, um ihr einen eigenen Effekt zu geben")
            Column {
                width: parent.width
                spacing: 12
                Chip { text: qsTr("Alle (globaler Effekt)"); selected: page.target === ""; onClicked: page.target = "" }
                Flow {
                    width: parent.width; spacing: 12
                    Repeater {
                        model: st.zones || []
                        Rectangle {
                            property bool sel: page.target === modelData.id
                            width: modelData.kind === "ring" ? 150 : 300
                            height: 100 + (modelData.kind === "ring" ? 0 : -30)
                            radius: 12
                            color: sel ? Theme.cardHi : Theme.panel
                            border.color: sel ? Theme.accent : Theme.line
                            border.width: sel ? 2 : 1
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: page.target = modelData.id }
                            Column {
                                x: 12; y: 10; width: parent.width - 24; spacing: 6
                                Row {
                                    width: parent.width
                                    Text { text: qsTr(modelData.name); color: Theme.text; font.pixelSize: 13; width: parent.width - 50; elide: Text.ElideRight }
                                    Text { text: modelData.cfg.follow === false ? qsTr("eigen") : ""; color: Theme.accent2; font.pixelSize: 11; width: 50; horizontalAlignment: Text.AlignRight }
                                }
                                LedPreview { width: parent.width; hex: win.frame[modelData.id] || ""; kind: modelData.kind; segments: modelData.segments; leds: modelData.leds }
                            }
                        }
                    }
                }
                Text { visible: !(st.zones || []).length; color: Theme.muted; font.pixelSize: 13
                    text: qsTr("Noch keine Lichtzonen. Unter „Geräte“ eintragen, was an den Lighting Nodes hängt.") }
            }
        }

        // ------------------------------------------- zone switch + saved effects
        Card {
            Layout.fillWidth: true
            title: page.tzone ? qsTr(page.tzone.name) : qsTr("Globaler Effekt")
            subtitle: page.tzone ? qsTr("%1 LEDs").arg(page.tzone.leds) : qsTr("Gilt für alle Zonen ohne eigenen Effekt")
            header: [ NButton { visible: page.tzone !== null; text: qsTr("Aufblinken lassen"); onClicked: backend.call("identify", { zone: page.target }) } ]
            Column {
                width: parent.width
                spacing: 8
                NSwitch {
                    visible: page.tzone !== null
                    text: qsTr("Eigener Effekt für diese Zone")
                    checked: page.own
                    onToggled: backend.call("set_zone", { zone: page.target, follow: !checked })
                }
                Item { visible: page.tzone !== null; width: 1; height: 6 }
                SectionLabel { text: qsTr("Gespeicherte Effekte") }
                Flow {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: page.saved
                        Chip { text: qsTr(modelData.name); tint: Theme.accent2
                            selected: page.editable && page.sameSpec(modelData.spec, page.spec)
                            onClicked: backend.call("load_effect", { target: page.target, index: index })
                            onRightClicked: backend.call("delete_effect", { target: page.target, index: index }) }
                    }
                    TextField {
                        id: saveName
                        width: 180; height: 30
                        placeholderText: qsTr("Name")
                        color: Theme.text; placeholderTextColor: Theme.faint; font.pixelSize: 13
                        background: Rectangle { radius: 15; color: Theme.panel; border.color: saveName.activeFocus ? Theme.accent : Theme.line }
                        leftPadding: 12
                        onAccepted: saveBtn.clicked()
                    }
                    NButton { id: saveBtn; text: qsTr("Aktuellen speichern"); height: 30
                        onClicked: { backend.call("save_effect", { target: page.target, name: saveName.text }); saveName.text = "" } }
                }
                Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.faint; font.pixelSize: 11
                    text: !page.saved.length ? qsTr("Noch nichts gespeichert. Ohne Namen wird der Effektname verwendet.")
                        : page.target === "" ? qsTr("Klick lädt den Effekt. Rechtsklick löscht. Gleicher Name überschreibt.")
                        : qsTr("Klick lädt den Effekt (die Zone bekommt dann ihren eigenen Effekt). Rechtsklick löscht. Gleicher Name überschreibt.") }
            }
        }

        // ------------------------------------------------------------ effects
        Card {
            Layout.fillWidth: true
            opacity: page.editable ? 1 : 0.45
            enabled: page.editable
            title: page.target === "" ? qsTr("Effekt für alle Zonen") : qsTr("Effekt für %1").arg(page.tzone ? qsTr(page.tzone.name) : "")
            subtitle: page.editable ? "" : qsTr("Diese Zone folgt dem globalen Effekt")
            Column {
                width: parent.width
                spacing: 18
                Flow {
                    width: parent.width; spacing: 10
                    Repeater {
                        model: st.effect_order || Object.keys(page.effects)
                        EffectTile { effectId: modelData; label: qsTr(page.effects[modelData].name); selected: page.spec.effect === modelData
                            onClicked: page.apply({ effect: modelData }) }
                    }
                }

                // colours
                Column {
                    visible: page.colorsWanted() > 0
                    spacing: 8
                    SectionLabel { text: page.has("colors2") ? (page.spec.effect === "temperature" ? qsTr("Farben: kalt · heiß") : qsTr("Farben: Vordergrund · Hintergrund")) : qsTr("Farben") }
                    Row {
                        spacing: 10
                        Repeater {
                            model: Math.min(page.colorsWanted(), Math.max(page.has("colors") ? 1 : page.colorsWanted(), (page.spec.colors || []).length))
                            Rectangle {
                                width: 40; height: 40; radius: 20
                                color: (page.spec.colors || [])[index] || "#000000"
                                border.color: Theme.line; border.width: 2
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                                    onClicked: function (m) {
                                        if (m.button === Qt.RightButton && page.has("colors") && (page.spec.colors || []).length > 1) {
                                            var cs = page.spec.colors.slice(); cs.splice(index, 1); page.apply({ colors: cs }); return
                                        }
                                        picker.idx = index; picker.field = "colors"; picker.openWith(parent.color)
                                    } }
                            }
                        }
                        Rectangle {
                            visible: page.has("colors") && (page.spec.colors || []).length < 6
                            width: 40; height: 40; radius: 20; color: "transparent"; border.color: Theme.faint; border.width: 2
                            Text { anchors.centerIn: parent; text: "+"; color: Theme.muted; font.pixelSize: 20 }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: { var cs = (page.spec.colors || []).slice(); cs.push("#ffffff"); page.apply({ colors: cs }); picker.idx = cs.length - 1; picker.field = "colors"; picker.openWith("#ffffff") } }
                        }
                        Text { visible: page.has("colors"); text: qsTr("Rechtsklick entfernt"); color: Theme.faint; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
                    }
                }

                GridLayout {
                    width: Math.min(parent.width, 720)
                    columns: 2; columnSpacing: 24; rowSpacing: 10
                    Text { visible: page.has("screen_area"); text: qsTr("Bildbereich"); color: Theme.muted; font.pixelSize: 13 }
                    Row { visible: page.has("screen_area"); spacing: 8
                        Chip { text: qsTr("Rand rundum"); selected: (page.spec.screen_area || "edges") === "edges"; onClicked: page.apply({ screen_area: "edges" }) }
                        Chip { text: qsTr("Ganzes Bild"); selected: page.spec.screen_area === "full"; onClicked: page.apply({ screen_area: "full" }) } }
                    Text { visible: page.has("saturation"); text: qsTr("Farbverstärkung"); color: Theme.muted; font.pixelSize: 13 }
                    NSlider { visible: page.has("saturation"); Layout.fillWidth: true; from: 0; to: 100; suffix: " %"; value: page.spec.saturation === undefined ? 40 : page.spec.saturation
                        onPressedChanged: if (!pressed) page.apply({ saturation: Math.round(value) }) }
                    Text { visible: page.has("screen_area"); Layout.columnSpan: 2; Layout.fillWidth: true; wrapMode: Text.WordWrap; font.pixelSize: 12
                        readonly property var sc: st.screen || ({})
                        color: sc.error ? Theme.warn : Theme.faint
                        text: sc.error ? qsTr("Bildschirmaufnahme: %1").arg(qsTr(sc.error))
                            : (sc.live ? qsTr("Bildschirm wird aufgenommen.") : qsTr("Beim ersten Mal fragt KDE, welcher Bildschirm geteilt werden soll. Danach läuft es ohne Nachfrage.")) }
                    Text { visible: page.has("speed"); text: page.has("screen_area") ? qsTr("Reaktion") : qsTr("Geschwindigkeit"); color: Theme.muted; font.pixelSize: 13 }
                    NSlider { visible: page.has("speed"); Layout.fillWidth: true; from: 0; to: 100; value: page.spec.speed === undefined ? 50 : page.spec.speed
                        onPressedChanged: if (!pressed) page.apply({ speed: Math.round(value) }) }
                    Text { visible: page.has("scale"); text: qsTr("Wiederholungen"); color: Theme.muted; font.pixelSize: 13 }
                    NSlider { visible: page.has("scale"); Layout.fillWidth: true; from: 0.25; to: 4; stepSize: 0.25; decimals: 2; suffix: "×"; value: page.spec.scale || 1
                        onPressedChanged: if (!pressed) page.apply({ scale: value }) }
                    Text { visible: page.has("tail"); text: qsTr("Schweif"); color: Theme.muted; font.pixelSize: 13 }
                    NSlider { visible: page.has("tail"); Layout.fillWidth: true; from: 1; to: 20; stepSize: 1; suffix: " LEDs"; value: page.spec.tail || 3
                        onPressedChanged: if (!pressed) page.apply({ tail: value }) }
                    Text { visible: page.has("density"); text: qsTr("Dichte"); color: Theme.muted; font.pixelSize: 13 }
                    NSlider { visible: page.has("density"); Layout.fillWidth: true; from: 1; to: 100; suffix: " %"; value: page.spec.density || 30
                        onPressedChanged: if (!pressed) page.apply({ density: Math.round(value) }) }
                    Text { visible: page.has("background"); text: qsTr("Hintergrund"); color: Theme.muted; font.pixelSize: 13 }
                    Rectangle { visible: page.has("background"); width: 32; height: 32; radius: 16; color: page.spec.background || "#000000"; border.color: Theme.line; border.width: 2
                        MouseArea { anchors.fill: parent; onClicked: { picker.field = "background"; picker.openWith(parent.color) } } }
                    Text { visible: page.has("sensor"); text: qsTr("Sensor"); color: Theme.muted; font.pixelSize: 13 }
                    NCombo { visible: page.has("sensor"); Layout.preferredWidth: 260
                        model: (st.sensors || []).map(function (s) { return { name: qsTr(s.label) } }); textRole: "name"
                        currentIndex: (st.sensors || []).map(function (s) { return s.id }).indexOf(page.spec.sensor || "cpu")
                        onActivated: function (i) { page.apply({ sensor: st.sensors[i].id }) } }
                    Text { visible: page.has("temp_low"); text: qsTr("Kalt bis"); color: Theme.muted; font.pixelSize: 13 }
                    NSlider { visible: page.has("temp_low"); Layout.fillWidth: true; from: 15; to: 80; suffix: " °C"; value: page.spec.temp_low || 30
                        onPressedChanged: if (!pressed) page.apply({ temp_low: Math.round(value) }) }
                    Text { visible: page.has("temp_high"); text: qsTr("Heiß ab"); color: Theme.muted; font.pixelSize: 13 }
                    NSlider { visible: page.has("temp_high"); Layout.fillWidth: true; from: 25; to: 100; suffix: " °C"; value: page.spec.temp_high || 80
                        onPressedChanged: if (!pressed) page.apply({ temp_high: Math.round(value) }) }
                    Text { visible: page.has("reverse"); text: qsTr("Richtung umkehren"); color: Theme.muted; font.pixelSize: 13 }
                    NSwitch { visible: page.has("reverse"); checked: !!page.spec.reverse; onToggled: page.apply({ reverse: checked }) }
                    Text { text: qsTr("Helligkeit dieses Effekts"); color: Theme.muted; font.pixelSize: 13; visible: page.spec.effect !== "off" }
                    NSlider { visible: page.spec.effect !== "off"; Layout.fillWidth: true; from: 0; to: 100; suffix: " %"; value: page.spec.brightness === undefined ? 100 : page.spec.brightness
                        onPressedChanged: if (!pressed) page.apply({ brightness: Math.round(value) }) }
                    Text { text: qsTr("Mindesthelligkeit"); color: Theme.muted; font.pixelSize: 13; visible: page.spec.effect !== "off" }
                    NSlider { visible: page.spec.effect !== "off"; Layout.fillWidth: true; from: 0; to: 100; suffix: " %"; value: page.spec.min_brightness || 0
                        onPressedChanged: if (!pressed) page.apply({ min_brightness: Math.round(value) }) }
                }
            }
        }
    }
}
