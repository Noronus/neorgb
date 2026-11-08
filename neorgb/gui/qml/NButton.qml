import QtQuick
import QtQuick.Controls.Basic
import "."

Button {
    id: b
    property bool primary: false
    property bool danger: false
    implicitHeight: 34
    leftPadding: 14; rightPadding: 14
    contentItem: Text {
        text: b.text; font.pixelSize: 13; font.weight: Font.DemiBold
        color: b.primary ? Theme.bg : (b.danger ? Theme.bad : Theme.text)
        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        opacity: b.enabled ? 1 : 0.4
    }
    background: Rectangle {
        radius: 9
        color: b.primary ? (b.down ? Qt.darker(Theme.accent, 1.2) : Theme.accent)
                         : (b.down ? Theme.line : (b.hovered ? Theme.cardHi : "transparent"))
        border.color: b.primary ? "transparent" : Theme.line
    }
}
