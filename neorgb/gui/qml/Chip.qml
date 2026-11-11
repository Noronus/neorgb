import QtQuick
import "."

Rectangle {
    id: c
    property string text
    property bool selected: false
    property color tint: Theme.accent
    signal clicked()
    signal doubleClicked()
    signal rightClicked()
    height: 30
    width: t.implicitWidth + 26
    radius: 15
    color: selected ? Qt.rgba(tint.r, tint.g, tint.b, 0.16) : (ma.containsMouse ? Theme.cardHi : "transparent")
    border.color: selected ? tint : Theme.line
    Text { id: t; anchors.centerIn: parent; text: c.text; color: c.selected ? Theme.text : Theme.muted; font.pixelSize: 13 }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function (m) { if (m.button === Qt.RightButton) c.rightClicked(); else c.clicked() }
        onDoubleClicked: function (m) { if (m.button === Qt.LeftButton) c.doubleClicked() } }
}
