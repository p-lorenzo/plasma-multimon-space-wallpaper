import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

QQC2.ScrollView {
    id: root

    property alias cfg_nasaEndpoint: nasaEndpoint.text
    property alias cfg_nasaApiKey: nasaApiKey.text
    property alias cfg_refreshIntervalHours: refreshHours.value
    property alias cfg_cacheDir: cacheDir.text
    property alias cfg_cropMode: cropMode.currentValue
    property alias cfg_monitorMode: monitorMode.currentValue
    property alias cfg_debugLogging: debugLogging.checked

    ColumnLayout {
        width: root.availableWidth
        spacing: 12

        QQC2.Label {
            text: "NASA endpoint"
        }
        QQC2.TextField {
            id: nasaEndpoint
            Layout.fillWidth: true
            placeholderText: "https://api.nasa.gov/planetary/apod"
        }

        QQC2.Label {
            text: "NASA API key"
        }
        QQC2.TextField {
            id: nasaApiKey
            Layout.fillWidth: true
            placeholderText: "DEMO_KEY"
        }

        QQC2.Label {
            text: "Refresh interval (hours)"
        }
        QQC2.SpinBox {
            id: refreshHours
            from: 1
            to: 168
            editable: true
        }

        QQC2.Label {
            text: "Cache directory (empty = default)"
        }
        QQC2.TextField {
            id: cacheDir
            Layout.fillWidth: true
            placeholderText: "~/.cache/plasma-multimon-space-wallpaper"
        }

        QQC2.Label {
            text: "Crop mode"
        }
        QQC2.ComboBox {
            id: cropMode
            Layout.fillWidth: true
            textRole: "text"
            valueRole: "value"
            model: [
                {"text": "Cover", "value": "cover"},
                {"text": "Contain", "value": "contain"},
                {"text": "Smart center crop", "value": "smart_center"}
            ]
        }

        QQC2.Label {
            text: "Monitor mode"
        }
        QQC2.ComboBox {
            id: monitorMode
            Layout.fillWidth: true
            textRole: "text"
            valueRole: "value"
            model: [
                {"text": "Span across all monitors", "value": "span"},
                {"text": "Per-monitor independent crop (Phase 2)", "value": "per_monitor"}
            ]
        }

        QQC2.CheckBox {
            id: debugLogging
            text: "Enable debug logging"
        }

        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: "Use the wallpaper context menu action 'Refresh now' to trigger an immediate refresh."
            opacity: 0.8
        }
    }
}
