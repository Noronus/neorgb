import QtQuick
import QtQuick.Controls.Basic
import "."

Popup {
    id: pop
    property color current: "#ffffff"
    property real hue: 0
    property real sat: 1
    property real val: 1
    signal picked(color c)
    width: 300; height: 330
    padding: 14
    modal: false
    focus: true
    background: Rectangle { radius: 14; color: Theme.card; border.color: Theme.line }

    function openWith(c) {
        current = c
        hue = c.hsvHue < 0 ? 0 : c.hsvHue; sat = c.hsvSaturation; val = c.hsvValue
        hex.text = c.toString().substring(1)
        open()
    }
    function emitColor() {
        current = Qt.hsva(hue, sat, val, 1)
        hex.text = current.toString().substring(1)
        picked(current)
    }

    Column {
        spacing: 12
        Row {
            spacing: 12
            Item {
                id: sv
                width: 230; height: 180
                Rectangle { anchors.fill: parent; radius: 8; color: Qt.hsva(pop.hue, 1, 1, 1) }
                Rectangle { anchors.fill: parent; radius: 8
                    gradient: Gradient { orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: "#ffffffff" } GradientStop { position: 1; color: "#00ffffff" } } }
                Rectangle { anchors.fill: parent; radius: 8
                    gradient: Gradient { GradientStop { position: 0; color: "#00000000" } GradientStop { position: 1; color: "#ff000000" } } }
                Rectangle { x: pop.sat * sv.width - 8; y: (1 - pop.val) * sv.height - 8; width: 16; height: 16; radius: 8
                    color: "transparent"; border.color: "white"; border.width: 2 }
                MouseArea { anchors.fill: parent
                    function set(m) { pop.sat = Math.max(0, Math.min(1, m.x / sv.width)); pop.val = Math.max(0, Math.min(1, 1 - m.y / sv.height)); pop.emitColor() }
                    onPressed: function (m) { set(m) } onPositionChanged: function (m) { set(m) } }
            }
            Item {
                id: hb
                width: 26; height: 180
                Rectangle { anchors.fill: parent; radius: 8
                    gradient: Gradient {
                        GradientStop { position: 0.00; color: "#ff0000" } GradientStop { position: 0.17; color: "#ffff00" }
                        GradientStop { position: 0.33; color: "#00ff00" } GradientStop { position: 0.50; color: "#00ffff" }
                        GradientStop { position: 0.67; color: "#0000ff" } GradientStop { position: 0.83; color: "#ff00ff" }
                        GradientStop { position: 1.00; color: "#ff0000" } } }
                Rectangle { y: pop.hue * hb.height - 3; x: -2; width: hb.width + 4; height: 6; radius: 3; color: "transparent"; border.color: "white"; border.width: 2 }
                MouseArea { anchors.fill: parent
                    function set(m) { pop.hue = Math.max(0, Math.min(0.999, m.y / hb.height)); pop.emitColor() }
                    onPressed: function (m) { set(m) } onPositionChanged: function (m) { set(m) } }
            }
        }
        Row {
            spacing: 6
            Repeater {
                model: ["#ffffff", "#ff2d55", "#ff8a00", "#ffd60a", "#34d399", "#22d3ee", "#3b82f6", "#a78bfa", "#f472b6"]
                Rectangle { width: 26; height: 26; radius: 13; color: modelData; border.color: Theme.line
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: { var c = Qt.color(modelData); pop.hue = c.hsvHue < 0 ? 0 : c.hsvHue; pop.sat = c.hsvSaturation; pop.val = c.hsvValue; pop.emitColor() } } }
            }
        }
        Row {
            spacing: 8
            Rectangle { width: 34; height: 34; radius: 8; color: pop.current; border.color: Theme.line }
            Text { text: "#"; color: Theme.muted; font.pixelSize: 15; anchors.verticalCenter: parent.verticalCenter }
            TextField {
                id: hex
                width: 110; height: 34
                color: Theme.text; font.pixelSize: 14; font.family: "monospace"
                maximumLength: 6
                validator: RegularExpressionValidator { regularExpression: /[0-9a-fA-F]{0,6}/ }
                background: Rectangle { radius: 8; color: Theme.panel; border.color: hex.activeFocus ? Theme.accent : Theme.line }
                onEditingFinished: if (text.length === 6) { var c = Qt.color("#" + text); pop.hue = c.hsvHue < 0 ? 0 : c.hsvHue; pop.sat = c.hsvSaturation; pop.val = c.hsvValue; pop.emitColor() }
            }
            NButton { text: "Fertig"; primary: true; onClicked: pop.close() }
        }
    }
}
