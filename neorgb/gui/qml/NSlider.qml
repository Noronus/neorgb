import QtQuick
import QtQuick.Controls.Basic
import "."

Slider {
    id: sl
    property color tint: Theme.accent
    property string suffix: ""
    property bool showValue: true
    property int decimals: 0
    implicitHeight: 28
    background: Item {
        x: sl.leftPadding; y: sl.topPadding + sl.availableHeight / 2 - 3
        width: sl.availableWidth - (sl.showValue ? 52 : 0); height: 6
        Rectangle { anchors.fill: parent; radius: 3; color: Theme.line }
        Rectangle { width: sl.visualPosition * parent.width; height: parent.height; radius: 3; color: sl.tint }
    }
    handle: Rectangle {
        x: sl.leftPadding + sl.visualPosition * (sl.availableWidth - (sl.showValue ? 52 : 0)) - width / 2
        y: sl.topPadding + sl.availableHeight / 2 - height / 2
        width: 18; height: 18; radius: 9
        color: sl.pressed ? "#ffffff" : Theme.text
        border.color: sl.tint; border.width: 3
    }
    Text {
        visible: sl.showValue
        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        width: 46; horizontalAlignment: Text.AlignRight
        text: sl.value.toFixed(sl.decimals) + sl.suffix
        color: Theme.text; font.pixelSize: 13
    }
}
