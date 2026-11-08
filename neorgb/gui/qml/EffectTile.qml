import QtQuick
import "."

Rectangle {
    id: tile
    property string effectId
    property string label
    property bool selected: false
    signal clicked()
    width: 132; height: 86
    radius: 12
    color: selected ? Theme.cardHi : Theme.panel
    border.color: selected ? Theme.accent : (ma.containsMouse ? Theme.faint : Theme.line)
    border.width: selected ? 2 : 1
    Rectangle {
        id: sw
        x: 10; y: 10; width: parent.width - 20; height: 38; radius: 8
        clip: true
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: tile.stops[0] }
            GradientStop { position: 0.5; color: tile.stops[1] }
            GradientStop { position: 1.0; color: tile.stops[2] }
        }
        opacity: tile.effectId === "off" ? 0.25 : 1
        SequentialAnimation on opacity {
            running: tile.effectId === "breathing"; loops: Animation.Infinite
            NumberAnimation { from: 1; to: 0.25; duration: 1400; easing.type: Easing.InOutSine }
            NumberAnimation { from: 0.25; to: 1; duration: 1400; easing.type: Easing.InOutSine }
        }
    }
    property var stops: ({
        "static": ["#22d3ee", "#22d3ee", "#22d3ee"],
        "breathing": ["#a78bfa", "#a78bfa", "#a78bfa"],
        "spectrum": ["#ff2d55", "#34d399", "#3b82f6"],
        "rainbow": ["#ff2d55", "#ffd60a", "#22d3ee"],
        "gradient": ["#22d3ee", "#a78bfa", "#f472b6"],
        "spin": ["#0c0e13", "#22d3ee", "#0c0e13"],
        "comet": ["#0c0e13", "#1e3a8a", "#f472b6"],
        "twinkle": ["#111827", "#fde68a", "#111827"],
        "temperature": ["#3b82f6", "#fbbf24", "#ef4444"],
        "off": ["#000000", "#000000", "#000000"]
    })[effectId] || ["#444", "#666", "#888"]
    Text { x: 12; anchors.bottom: parent.bottom; anchors.bottomMargin: 10; width: tile.width - 20; elide: Text.ElideRight; text: tile.label; color: tile.selected ? Theme.text : Theme.muted; font.pixelSize: 13 }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: tile.clicked() }
}
