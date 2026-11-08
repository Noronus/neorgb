import QtQuick
import "."

Rectangle {
    id: card
    property string title: ""
    property string subtitle: ""
    property int pad: 18
    default property alias content: body.data
    property alias header: headerRow.data
    color: Theme.card
    radius: Theme.radius
    border.color: Theme.line
    border.width: 1
    implicitHeight: body.childrenRect.height + body.y + pad

    Item {
        id: head
        x: card.pad; y: card.pad
        width: card.width - card.pad * 2
        height: card.title.length ? 26 : 0
        visible: card.title.length > 0
        Column {
            anchors.verticalCenter: parent.verticalCenter
            Text { text: card.title; color: Theme.text; font.pixelSize: 15; font.weight: Font.DemiBold }
            Text { text: card.subtitle; color: Theme.muted; font.pixelSize: 12; visible: text.length > 0 }
        }
        Row { id: headerRow; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 8 }
    }
    Item {
        id: body
        x: card.pad
        y: card.title.length ? head.y + head.height + (card.subtitle.length ? 22 : 12) : card.pad
        width: card.width - card.pad * 2
        height: childrenRect.height
    }
}
