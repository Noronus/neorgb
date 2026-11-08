pragma Singleton
import QtQuick

QtObject {
    readonly property color bg: "#0c0e13"
    readonly property color panel: "#11141b"
    readonly property color card: "#171b25"
    readonly property color cardHi: "#1f2431"
    readonly property color line: "#262c3a"
    readonly property color text: "#e8ebf2"
    readonly property color muted: "#8b93a7"
    readonly property color faint: "#596176"
    readonly property color accent: "#22d3ee"
    readonly property color accent2: "#a78bfa"
    readonly property color pink: "#f472b6"
    readonly property color good: "#34d399"
    readonly property color warn: "#fbbf24"
    readonly property color bad: "#f87171"
    readonly property int radius: 14
    readonly property int gap: 16

    function tempColor(t, lo, hi) {
        if (t === undefined || t === null) return faint
        var f = Math.max(0, Math.min(1, (t - lo) / (hi - lo)))
        if (f < 0.5) return Qt.rgba(0.13 + f * 1.4, 0.83, 0.93 - f * 1.2, 1)
        return Qt.rgba(0.97, 0.83 - (f - 0.5) * 1.3, 0.33 - (f - 0.5) * 0.4, 1)
    }
    function fmt(v, digits) {
        if (v === undefined || v === null) return "–"
        return Number(v).toFixed(digits === undefined ? 1 : digits)
    }
}
