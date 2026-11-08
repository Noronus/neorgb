import QtQuick
import "."

Rectangle {
    id: s
    property string label
    property string value: "–"
    property string unit: ""
    property string sub: ""
    property color tint: Theme.accent
    property real fill: -1          // 0..1 shows a bar
    color: Theme.card
    radius: Theme.radius
    border.color: Theme.line
    implicitHeight: 124
    Column {
        x: 18; y: 16
        width: s.width - 36
        spacing: 6
        Row {
            spacing: 8
            Rectangle { width: 8; height: 8; radius: 4; color: s.tint; anchors.verticalCenter: parent.verticalCenter }
            Text { text: s.label; color: Theme.muted; font.pixelSize: 12 }
        }
        Row {
            spacing: 4
            Text { text: s.value; color: Theme.text; font.pixelSize: 30; font.weight: Font.DemiBold }
            Text { text: s.unit; color: Theme.muted; font.pixelSize: 15; anchors.baseline: parent.children[0].baseline }
        }
        Item {
            width: parent.width; height: 6
            visible: s.fill >= 0
            Rectangle { anchors.fill: parent; radius: 3; color: Theme.line }
            Rectangle {
                width: parent.width * Math.max(0, Math.min(1, s.fill)); height: parent.height; radius: 3
                color: s.tint
                Behavior on width { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
            }
        }
        Text { text: s.sub; color: Theme.faint; font.pixelSize: 11; visible: text.length > 0 }
    }
}
