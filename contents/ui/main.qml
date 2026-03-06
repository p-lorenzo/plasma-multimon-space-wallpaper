import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.plasma.core as PlasmaCore

WallpaperItem {
    id: wallpaper

    property string cacheDir: wallpaper.configuration.cacheDir || ""
    property string nasaEndpoint: wallpaper.configuration.nasaEndpoint || "https://api.nasa.gov/planetary/apod"
    property string nasaApiKey: wallpaper.configuration.nasaApiKey || "DEMO_KEY"
    property string cropMode: wallpaper.configuration.cropMode || "cover"
    property string monitorMode: wallpaper.configuration.monitorMode || "span"
    property int refreshIntervalHours: Math.max(1, wallpaper.configuration.refreshIntervalHours || 6)
    property bool debugLogging: wallpaper.configuration.debugLogging || false
    property string lastImagePath: ""

    function helperScriptPath() {
        return Qt.resolvedUrl("../../scripts/multimon_wallpaper.py").toString().replace("file://", "")
    }

    function refreshNow() {
        const args = [
            helperScriptPath(),
            "refresh",
            "--nasa-endpoint", nasaEndpoint,
            "--api-key", nasaApiKey,
            "--crop-mode", cropMode,
            "--monitor-mode", monitorMode,
            "--cache-dir", cacheDir,
            "--screen-x", Math.round(wallpaper.screenGeometry.x),
            "--screen-y", Math.round(wallpaper.screenGeometry.y),
            "--screen-width", Math.round(wallpaper.screenGeometry.width),
            "--screen-height", Math.round(wallpaper.screenGeometry.height)
        ]
        if (debugLogging) {
            args.push("--debug")
        }

        executable.exec("python3 " + args.map(a => "'" + String(a).replace(/'/g, "'\\''") + "'").join(" "))
    }

    Component.onCompleted: refreshNow()

    Timer {
        id: refreshTimer
        interval: wallpaper.refreshIntervalHours * 3600 * 1000
        repeat: true
        running: true
        onTriggered: wallpaper.refreshNow()
    }

    Plasma5Support.DataSource {
        id: executable
        engine: "executable"
        connectedSources: []

        function exec(cmd) {
            connectSource(cmd)
        }

        onNewData: function(sourceName, data) {
            const exitCode = data["exit code"]
            if (exitCode !== 0) {
                console.warn("multimon-space-wallpaper refresh failed", sourceName, data.stderr)
            }

            if (data.stdout && data.stdout.trim().length > 0) {
                wallpaper.lastImagePath = data.stdout.trim()
            }

            disconnectSource(sourceName)
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "black"
    }

    Image {
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        cache: false
        source: wallpaper.lastImagePath.length > 0 ? "file://" + wallpaper.lastImagePath + "?t=" + Date.now() : ""
    }

    contextualActions: [
        PlasmaCore.Action {
            text: "Refresh now"
            icon.name: "view-refresh"
            onTriggered: wallpaper.refreshNow()
        }
    ]
}
