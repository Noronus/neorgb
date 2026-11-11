import QtQuick

// Qt's own wheel scrolling in a Flickable moves only a few pixels per notch.
// This scrolls a fixed, comfortable step per notch and follows touchpads 1:1.
WheelHandler {
    required property Flickable flick
    property real step: 120          // pixels per wheel notch
    target: null
    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
    onWheel: function (ev) {
        var dy = ev.pixelDelta.y !== 0 ? ev.pixelDelta.y : ev.angleDelta.y / 120 * step
        var maxY = Math.max(0, flick.contentHeight - flick.height)
        flick.cancelFlick()
        flick.contentY = Math.max(0, Math.min(maxY, flick.contentY - dy))
        ev.accepted = true
    }
}
