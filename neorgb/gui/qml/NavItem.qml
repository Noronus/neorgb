import QtQuick
import "."

Item {
    id: nav
    property string label
    property string icon
    property bool active: false
    signal clicked()
    width: parent ? parent.width : 200
    height: 44
    Rectangle {
        anchors.fill: parent
        anchors.leftMargin: 10; anchors.rightMargin: 10
        radius: 10
        color: nav.active ? Theme.cardHi : (ma.containsMouse ? Theme.card : "transparent")
        Behavior on color { ColorAnimation { duration: 120 } }
        Rectangle {
            width: 3; height: 18; radius: 2
            anchors.verticalCenter: parent.verticalCenter
            x: 2
            color: Theme.accent
            visible: nav.active
        }
        Image {
            id: ic
            source: nav.icon
            sourceSize: Qt.size(20, 20)
            x: 16; anchors.verticalCenter: parent.verticalCenter
            opacity: nav.active ? 1 : 0.55
        }
        Text {
            text: nav.label
            anchors.left: ic.right; anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            color: nav.active ? Theme.text : Theme.muted
            font.pixelSize: 14
            font.weight: nav.active ? Font.DemiBold : Font.Normal
        }
    }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: nav.clicked() }
}
