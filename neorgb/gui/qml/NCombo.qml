import QtQuick
import QtQuick.Controls.Basic
import "."

ComboBox {
    id: cb
    implicitHeight: 34
    implicitWidth: 200
    font.pixelSize: 13
    contentItem: Text {
        leftPadding: 12; rightPadding: 28
        text: cb.displayText; color: Theme.text; font: cb.font
        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    indicator: Canvas {
        x: cb.width - width - 12; y: cb.height / 2 - height / 2
        width: 10; height: 6
        onPaint: { var c = getContext("2d"); c.reset(); c.strokeStyle = "#8b93a7"; c.lineWidth = 1.6
            c.beginPath(); c.moveTo(1, 1); c.lineTo(5, 5); c.lineTo(9, 1); c.stroke() }
    }
    background: Rectangle { radius: 9; color: cb.hovered ? Theme.cardHi : Theme.panel; border.color: cb.activeFocus ? Theme.accent : Theme.line }
    delegate: ItemDelegate {
        width: cb.width
        highlighted: cb.highlightedIndex === index
        contentItem: Text {
            text: cb.textRole ? (Array.isArray(cb.model) ? modelData[cb.textRole] : model[cb.textRole]) : modelData
            color: Theme.text; font: cb.font; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle { color: highlighted ? Theme.cardHi : Theme.card }
    }
    popup: Popup {
        y: cb.height + 4; width: cb.width
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 360)
        padding: 4
        contentItem: ListView { clip: true; implicitHeight: contentHeight; model: cb.popup.visible ? cb.delegateModel : null; currentIndex: cb.highlightedIndex }
        background: Rectangle { radius: 10; color: Theme.card; border.color: Theme.line }
    }
}
