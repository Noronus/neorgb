import QtQuick
import "."

Item {
    id: ed
    property var points: []          // [[temp, duty], ...]
    property real tMin: 20
    property real tMax: 60
    property var temp: null          // current sensor temperature
    property var duty: null          // current duty of the selected channel
    property color tint: Theme.accent
    property bool editable: true
    property int maxPoints: 10
    property real minDuty: 0
    signal edited(var points)

    property var pts: []
    property int drag: -1
    property int hover: -1
    readonly property int padL: 40
    readonly property int padB: 26
    readonly property real plotW: width - padL - 12
    readonly property real plotH: height - padB - 10

    function copyIn() { if (drag < 0) { pts = (points || []).map(function (p) { return [Number(p[0]), Number(p[1])] }); cv.requestPaint() } }
    onPointsChanged: copyIn()
    onTempChanged: cv.requestPaint()
    onDutyChanged: cv.requestPaint()
    onTMinChanged: cv.requestPaint()
    onTMaxChanged: cv.requestPaint()
    Component.onCompleted: copyIn()

    function px(t) { return padL + (t - tMin) / (tMax - tMin) * plotW }
    function py(d) { return 10 + plotH - d / 100 * plotH }
    function tOf(x) { return tMin + (x - padL) / plotW * (tMax - tMin) }
    function dOf(y) { return (10 + plotH - y) / plotH * 100 }
    function nearest(x, y) {
        var best = -1, bd = 14 * 14
        for (var i = 0; i < pts.length; i++) {
            var dx = px(pts[i][0]) - x, dy = py(pts[i][1]) - y
            if (dx * dx + dy * dy < bd) { bd = dx * dx + dy * dy; best = i }
        }
        return best
    }
    function interp(t) {
        if (!pts.length) return 0
        var s = pts.slice().sort(function (a, b) { return a[0] - b[0] })
        if (t <= s[0][0]) return s[0][1]
        if (t >= s[s.length - 1][0]) return s[s.length - 1][1]
        for (var i = 0; i < s.length - 1; i++)
            if (t >= s[i][0] && t <= s[i + 1][0])
                return s[i][1] + (s[i + 1][1] - s[i][1]) * (t - s[i][0]) / Math.max(0.001, s[i + 1][0] - s[i][0])
        return 0
    }

    Canvas {
        id: cv
        anchors.fill: parent
        onPaint: {
            var c = getContext("2d"); c.reset()
            c.font = "11px sans-serif"
            // grid
            c.strokeStyle = "#232937"; c.lineWidth = 1; c.fillStyle = "#596176"
            for (var d = 0; d <= 100; d += 20) {
                c.beginPath(); c.moveTo(padL, py(d)); c.lineTo(padL + plotW, py(d)); c.stroke()
                c.fillText(d + "%", 4, py(d) + 4)
            }
            var step = (tMax - tMin) > 50 ? 10 : 5
            for (var t = Math.ceil(tMin / step) * step; t <= tMax; t += step) {
                c.beginPath(); c.moveTo(px(t), 10); c.lineTo(px(t), 10 + plotH); c.stroke()
                c.fillText(t + "°", px(t) - 8, height - 8)
            }
            if (minDuty > 0) {
                c.fillStyle = "rgba(248,113,113,0.07)"
                c.fillRect(padL, py(minDuty), plotW, plotH + 10 - py(minDuty))
            }
            if (pts.length < 1) return
            var s = pts.slice().sort(function (a, b) { return a[0] - b[0] })
            // area
            var grad = c.createLinearGradient(0, 10, 0, 10 + plotH)
            grad.addColorStop(0, Qt.rgba(ed.tint.r, ed.tint.g, ed.tint.b, 0.35))
            grad.addColorStop(1, Qt.rgba(ed.tint.r, ed.tint.g, ed.tint.b, 0.02))
            c.fillStyle = grad
            c.beginPath(); c.moveTo(padL, py(0)); c.lineTo(padL, py(s[0][1]))
            for (var i = 0; i < s.length; i++) c.lineTo(px(s[i][0]), py(s[i][1]))
            c.lineTo(padL + plotW, py(s[s.length - 1][1])); c.lineTo(padL + plotW, py(0)); c.closePath(); c.fill()
            // line
            c.strokeStyle = ed.tint; c.lineWidth = 2.5; c.lineJoin = "round"
            c.beginPath(); c.moveTo(padL, py(s[0][1]))
            for (i = 0; i < s.length; i++) c.lineTo(px(s[i][0]), py(s[i][1]))
            c.lineTo(padL + plotW, py(s[s.length - 1][1])); c.stroke()
            // current temperature
            if (ed.temp !== null && ed.temp !== undefined) {
                var tx = px(Math.max(tMin, Math.min(tMax, ed.temp)))
                c.strokeStyle = "rgba(251,191,36,0.8)"; c.lineWidth = 1.5; c.setLineDash([4, 4])
                c.beginPath(); c.moveTo(tx, 10); c.lineTo(tx, 10 + plotH); c.stroke(); c.setLineDash([])
                var dd = (ed.duty !== null && ed.duty !== undefined) ? ed.duty : interp(ed.temp)
                c.fillStyle = "#fbbf24"; c.beginPath(); c.arc(tx, py(dd), 5, 0, Math.PI * 2); c.fill()
                c.fillText(Number(ed.temp).toFixed(1) + "°C · " + Math.round(dd) + "%", Math.min(tx + 8, width - 110), 22)
            }
            // points
            for (i = 0; i < pts.length; i++) {
                var hot = (i === drag || i === hover)
                c.fillStyle = hot ? "#ffffff" : "#0c0e13"; c.strokeStyle = ed.tint; c.lineWidth = 2.5
                c.beginPath(); c.arc(px(pts[i][0]), py(pts[i][1]), hot ? 7 : 5.5, 0, Math.PI * 2); c.fill(); c.stroke()
            }
            if (drag >= 0 || hover >= 0) {
                var p = pts[drag >= 0 ? drag : hover]
                var label = Number(p[0]).toFixed(0) + "°C → " + Math.round(p[1]) + "%"
                var lx = Math.min(px(p[0]) + 10, width - 90), ly = Math.max(py(p[1]) - 12, 20)
                c.fillStyle = "rgba(23,27,37,0.95)"; c.fillRect(lx - 4, ly - 13, 88, 18)
                c.fillStyle = "#e8ebf2"; c.fillText(label, lx, ly)
            }
        }
    }
    MouseArea {
        anchors.fill: parent
        enabled: ed.editable
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: ed.drag >= 0 ? Qt.ClosedHandCursor : (ed.hover >= 0 ? Qt.OpenHandCursor : Qt.CrossCursor)
        onPressed: function (m) {
            var i = ed.nearest(m.x, m.y)
            if (m.button === Qt.RightButton) {
                if (i >= 0 && ed.pts.length > 2) { ed.pts.splice(i, 1); ed.hover = -1; cv.requestPaint(); ed.edited(ed.pts) }
                return
            }
            ed.drag = i
        }
        onPositionChanged: function (m) {
            if (ed.drag < 0) { var h = ed.nearest(m.x, m.y); if (h !== ed.hover) { ed.hover = h; cv.requestPaint() } return }
            var t = Math.round(Math.max(ed.tMin, Math.min(ed.tMax, ed.tOf(m.x))))
            var d = Math.round(Math.max(ed.minDuty, Math.min(100, ed.dOf(m.y))))
            ed.pts[ed.drag] = [t, d]
            cv.requestPaint()
        }
        onReleased: { if (ed.drag >= 0) { ed.drag = -1; ed.edited(ed.pts) } }
        onDoubleClicked: function (m) {
            if (ed.nearest(m.x, m.y) >= 0 || ed.pts.length >= ed.maxPoints) return
            var t = Math.round(ed.tOf(m.x)), d = Math.round(Math.max(ed.minDuty, Math.min(100, ed.dOf(m.y))))
            ed.pts.push([t, d]); cv.requestPaint(); ed.edited(ed.pts)
        }
        onExited: { ed.hover = -1; cv.requestPaint() }
    }
}
