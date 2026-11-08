import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

ApplicationWindow {
    id: win
    width: 1280; height: 820
    minimumWidth: 980; minimumHeight: 640
    visible: true
    title: "NeoRGB"
    color: Theme.bg
    property int page: 0
    // per-key store: each part only notifies when it really changed
    readonly property var st: backend.store
    readonly property var frame: backend.frame || ({})
    onPageChanged: backend.setPreview(page === 0 || page === 2 || page === 3)
    Component.onCompleted: backend.setPreview(true)

    function live(id) { return (st.fan_live || {})[id] || ({}) }
    function sensor(id) {
        var l = st.sensors || []
        for (var i = 0; i < l.length; i++) if (l[i].id === id) return l[i].value
        return null
    }
    function sensorLabel(id) {
        var l = st.sensors || []
        for (var i = 0; i < l.length; i++) if (l[i].id === id) return l[i].label
        return id
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ------------------------------------------------------- sidebar
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 220
            color: Theme.panel
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
            Column {
                anchors.fill: parent
                anchors.topMargin: 22
                spacing: 4
                Row {
                    x: 22; spacing: 12; height: 52
                    Image { source: "../icons/neorgb.svg"; sourceSize: Qt.size(34, 34); anchors.verticalCenter: parent.verticalCenter }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        Text { text: "NeoRGB"; color: Theme.text; font.pixelSize: 19; font.weight: Font.Bold }
                        Text { text: backend.connected ? "verbunden" : "Dienst aus"; color: backend.connected ? Theme.good : Theme.bad; font.pixelSize: 11 }
                    }
                }
                Item { width: 1; height: 14 }
                NavItem { label: "Übersicht"; icon: "../icons/overview.svg"; active: win.page === 0; onClicked: win.page = 0 }
                NavItem { label: "Kühlung"; icon: "../icons/fan.svg"; active: win.page === 1; onClicked: win.page = 1 }
                NavItem { label: "Beleuchtung"; icon: "../icons/light.svg"; active: win.page === 2; onClicked: win.page = 2 }
                NavItem { label: "Geräte"; icon: "../icons/devices.svg"; active: win.page === 3; onClicked: win.page = 3 }
                NavItem { label: "Einstellungen"; icon: "../icons/settings.svg"; active: win.page === 4; onClicked: win.page = 4 }
            }
            // mini status at the bottom
            Column {
                anchors.bottom: parent.bottom; anchors.bottomMargin: 18
                x: 22; spacing: 8
                width: parent.width - 44
                Repeater {
                    model: [["liquid", "Wasser"], ["cpu", "CPU"], ["gpu", "GPU"]]
                    Row {
                        width: parent.width
                        Text { text: modelData[1]; color: Theme.muted; font.pixelSize: 12; width: parent.width - 60 }
                        Text { text: Theme.fmt(win.sensor(modelData[0])) + " °C"; width: 60; horizontalAlignment: Text.AlignRight
                            color: Theme.tempColor(win.sensor(modelData[0]), modelData[0] === "liquid" ? 25 : 35, modelData[0] === "liquid" ? 45 : 90)
                            font.pixelSize: 12; font.weight: Font.DemiBold }
                    }
                }
            }
        }

        // --------------------------------------------------------- pages
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            StackLayout {
                anchors.fill: parent
                currentIndex: win.page
                OverviewPage { win: win }
                CoolingPage { win: win }
                LightingPage { win: win }
                DevicesPage { win: win }
                SettingsPage { win: win }
            }

            // daemon offline banner
            Rectangle {
                visible: !backend.connected
                anchors.fill: parent
                color: Qt.rgba(0.05, 0.06, 0.08, 0.92)
                Column {
                    anchors.centerIn: parent
                    spacing: 14
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "Der NeoRGB-Dienst läuft nicht"; color: Theme.text; font.pixelSize: 22; font.weight: Font.DemiBold }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "Ohne ihn steuert die AIO wieder ihre gespeicherte Hardware-Kurve."; color: Theme.muted; font.pixelSize: 14 }
                    NButton { anchors.horizontalCenter: parent.horizontalCenter; text: "Dienst starten"; primary: true; onClicked: backend.startDaemon() }
                }
            }

            // toast
            Rectangle {
                id: toast
                property string msg: ""
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom; anchors.bottomMargin: 24
                width: tt.implicitWidth + 32; height: 40; radius: 20
                color: Theme.cardHi; border.color: Theme.bad
                opacity: msg.length ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 200 } }
                Text { id: tt; anchors.centerIn: parent; text: toast.msg; color: Theme.text; font.pixelSize: 13 }
                Timer { id: toastTimer; interval: 4000; onTriggered: toast.msg = "" }
                Connections { target: backend; function onToast(m) { toast.msg = m; toastTimer.restart() } }
            }
        }
    }
}
