import QtQuick
import "."

// series: [{data: [[ts, v], ...], color: "#..", label: ".."}]
Canvas {
    id: cv
    property var series: []
    property real span: 600
    onSeriesChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    Connections { target: backend; function onLanguageChanged() { cv.requestPaint() } }
    onPaint: {
        var c = getContext("2d"); c.reset()
        var lo = 1e9, hi = -1e9, now = Date.now() / 1000
        for (var s = 0; s < series.length; s++) {
            var d = series[s].data || []
            for (var i = 0; i < d.length; i++) { lo = Math.min(lo, d[i][1]); hi = Math.max(hi, d[i][1]) }
        }
        if (hi < lo) return
        lo = Math.floor(lo / 5) * 5 - 2; hi = Math.ceil(hi / 5) * 5 + 2
        var padL = 34, padB = 18, w = width - padL - 6, h = height - padB - 6
        c.font = "11px sans-serif"; c.fillStyle = "#596176"; c.strokeStyle = "#262c3a"; c.lineWidth = 1
        var step = (hi - lo) > 40 ? 20 : ((hi - lo) > 20 ? 10 : 5)
        for (var g = Math.ceil(lo / step) * step; g <= hi; g += step) {
            var gy = 6 + h - (g - lo) / (hi - lo) * h
            c.beginPath(); c.moveTo(padL, gy); c.lineTo(padL + w, gy); c.stroke()
            c.fillText(g + "°", 4, gy + 4)
        }
        c.fillText("-" + Math.round(span / 60) + " min", padL, height - 3)
        var nowTxt = qsTr("jetzt")
        c.fillText(nowTxt, padL + w - c.measureText(nowTxt).width, height - 3)
        for (s = 0; s < series.length; s++) {
            d = series[s].data || []
            if (d.length < 2) continue
            c.strokeStyle = series[s].color; c.lineWidth = 2; c.lineJoin = "round"
            c.beginPath()
            for (i = 0; i < d.length; i++) {
                var x = padL + w - (now - d[i][0]) / span * w
                var y = 6 + h - (d[i][1] - lo) / (hi - lo) * h
                if (i === 0) c.moveTo(x, y); else c.lineTo(x, y)
            }
            c.stroke()
        }
    }
}
