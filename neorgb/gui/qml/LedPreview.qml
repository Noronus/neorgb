import QtQuick
import "."

// Draws the live colours of one zone: fans/pumps as rings, strips as a bar.
Canvas {
    id: cv
    property string hex: ""
    property string kind: "linear"
    property var segments: []
    property int leds: 0
    implicitHeight: kind === "ring" ? 64 : 22
    onHexChanged: requestPaint()
    onWidthChanged: requestPaint()
    renderStrategy: Canvas.Cooperative
    function col(i) {
        var o = i * 6
        if (o + 6 > hex.length) return "rgb(20,24,32)"
        var r = parseInt(hex.substr(o, 2), 16), g = parseInt(hex.substr(o + 2, 2), 16), b = parseInt(hex.substr(o + 4, 2), 16)
        // lift very dark LEDs a bit so "off" still shows the shape
        return "rgb(" + Math.max(r, 22) + "," + Math.max(g, 26) + "," + Math.max(b, 34) + ")"
    }
    onPaint: {
        var c = getContext("2d"); c.reset()
        var n = leds, segs = (segments && segments.length) ? segments : [n]
        if (!n) return
        if (kind === "ring") {
            var size = height - 6, gap = 10, idx = 0
            var count = Math.min(segs.length, Math.floor((width + gap) / (size + gap)))
            for (var s = 0; s < segs.length; s++) {
                if (s >= count) { idx += segs[s]; continue }
                var cx = 3 + s * (size + gap) + size / 2, cy = height / 2, r = size / 2 - 5
                c.strokeStyle = "#1f2431"; c.lineWidth = 6; c.beginPath(); c.arc(cx, cy, r, 0, Math.PI * 2); c.stroke()
                for (var i = 0; i < segs[s]; i++) {
                    var a = -Math.PI / 2 + i / segs[s] * Math.PI * 2
                    var col_ = col(idx + i)
                    c.fillStyle = col_; c.shadowColor = col_; c.shadowBlur = 8
                    c.beginPath(); c.arc(cx + Math.cos(a) * r, cy + Math.sin(a) * r, segs[s] > 20 ? 3 : 4.2, 0, Math.PI * 2); c.fill()
                }
                c.shadowBlur = 0
                idx += segs[s]
            }
        } else {
            var w = width / n
            for (var j = 0; j < n; j++) {
                var cc = col(j)
                c.fillStyle = cc; c.shadowColor = cc; c.shadowBlur = 6
                var bw = Math.max(1, w - (w > 4 ? 2 : 0))
                c.beginPath()
                if (c.roundedRect) c.roundedRect(j * w, 4, bw, height - 8, 2, 2); else c.rect(j * w, 4, bw, height - 8)
                c.fill()
            }
        }
    }
}
