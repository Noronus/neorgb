import QtQuick
import QtQuick.Controls.Basic
import "."

Switch {
    id: sw
    implicitHeight: 28
    indicator: Rectangle {
        x: sw.leftPadding; y: parent.height / 2 - height / 2
        width: 40; height: 22; radius: 11
        color: sw.checked ? Theme.accent : Theme.line
        Behavior on color { ColorAnimation { duration: 120 } }
        Rectangle {
            x: sw.checked ? parent.width - width - 3 : 3
            y: 3; width: 16; height: 16; radius: 8
            color: sw.checked ? Theme.bg : Theme.muted
            Behavior on x { NumberAnimation { duration: 120 } }
        }
    }
    contentItem: Text {
        leftPadding: sw.indicator.width + 10
        text: sw.text; color: Theme.text; font.pixelSize: 13
        verticalAlignment: Text.AlignVCenter
    }
}
