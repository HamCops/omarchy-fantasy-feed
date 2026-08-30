pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui

Item {
  id: root

  property var service: null
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  readonly property string scoringMode: service ? service.scoringMode : "ppr"
  readonly property string alertPreset: service ? service.alertPreset : "off"
  readonly property var players: service && Array.isArray(service.favoritePlayerRows)
    ? service.favoritePlayerRows : []

  signal playerActivated(string playerId, string eventToken)

  function signedPoints(value) {
    var number = Number(value)
    if (!isFinite(number)) number = 0
    if (Math.abs(number) < 0.005) number = 0
    var formatted = number.toFixed(2).replace(/\.?0+$/, "")
    return (number > 0 ? "+" : "") + formatted
  }

  function pointsColor(value) {
    var number = Number(value)
    if (!isFinite(number) || Math.abs(number) < 0.005) return Qt.darker(foreground, 1.35)
    return number > 0 ? "#6fcf79" : "#ff6b6b"
  }

  function shortName(value) {
    var words = String(value || "Player").trim().split(/\s+/)
    if (words.length < 2) return words[0].toUpperCase()
    return words[0].charAt(0).toUpperCase() + ". " + words[words.length - 1].toUpperCase()
  }

  onAlertPresetChanged: alertDropdown.value = alertPreset

  visible: players.length > 0
  width: parent ? parent.width : implicitWidth
  height: visible ? Style.space(48) : 0
  implicitHeight: visible ? Style.space(48) : 0

  Column {
    id: railLabel
    anchors.left: parent.left
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(116)
    spacing: Style.space(2)

    Text {
      text: "MY PLAYERS · " + (root.scoringMode === "ppr" ? "PPR" : "STD")
      color: Qt.darker(root.foreground, 1.3)
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }

    Dropdown {
      id: alertDropdown
      width: parent.width
      showLabel: false
      options: [
        {value: "off", label: "ALERTS OFF"},
        {value: "all", label: "★ ALL PLAYS"},
        {value: "touchdowns", label: "★ TD ONLY"},
        {value: "threshold3", label: "★ 3+ PTS"},
        {value: "threshold6", label: "★ 6+ PTS"}
      ]
      value: root.alertPreset
      foreground: root.foreground
      fontFamily: root.fontFamily
      onChanged: function(value) {
        if (root.service) root.service.setAlertPreset(value)
      }
    }
  }

  Flickable {
    anchors.left: railLabel.right
    anchors.leftMargin: Style.space(8)
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    clip: true
    contentWidth: playerChips.implicitWidth
    contentHeight: height
    flickableDirection: Flickable.HorizontalFlick
    boundsBehavior: Flickable.StopAtBounds

    Row {
      id: playerChips
      height: parent.height
      spacing: Style.space(6)

      Repeater {
        model: root.players

        delegate: Rectangle {
          id: playerChip
          required property var modelData
          readonly property var player: modelData
          readonly property real weeklyPoints: Number(player.points
            ? player.points[root.scoringMode] : 0)
          readonly property real latestPoints: Number(player.latestPoints
            ? player.latestPoints[root.scoringMode] : 0)
          readonly property color pulseColor: root.pointsColor(latestPoints)
          width: Style.space(166)
          height: parent.height
          radius: Style.cornerRadius
          color: player.spotlight
            ? Qt.rgba(pulseColor.r, pulseColor.g, pulseColor.b, 0.13)
            : (player.redZone ? Qt.rgba(1, 0.55, 0.2, 0.08) : "transparent")
          border.width: player.spotlight ? 2 : 1
          border.color: player.spotlight
            ? pulseColor
            : (player.redZone ? "#ffb347"
              : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.35))

          onPlayerChanged: {
            if (player && player.spotlight) pulseAnimation.restart()
          }

          SequentialAnimation {
            id: pulseAnimation
            NumberAnimation { target: playerChip; property: "scale"; to: 1.035; duration: 110 }
            NumberAnimation { target: playerChip; property: "scale"; to: 1; duration: 190 }
          }

          HoverHandler { id: chipHover }
          TapHandler {
            onTapped: root.playerActivated(
              String(playerChip.player.playerId || ""),
              String(playerChip.player.latestEventToken || ""))
          }

          ToolTip.visible: chipHover.hovered
          ToolTip.text: String(player.displayName || "Unknown player")
            + (player.redZone ? " · RED ZONE · " + String(player.redZoneDetail || "") : "")
            + "\nClick to jump to the latest play"

          Column {
            anchors.fill: parent
            anchors.margins: Style.space(6)
            spacing: Style.space(2)

            Item {
              width: parent.width
              height: Math.max(playerName.implicitHeight, playerState.implicitHeight)

              Text {
                id: playerName
                anchors.left: parent.left
                anchors.right: playerState.left
                anchors.rightMargin: Style.space(4)
                text: root.shortName(playerChip.player.displayName)
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                elide: Text.ElideRight
              }

              Text {
                id: playerState
                anchors.right: parent.right
                text: playerChip.player.redZone
                  ? "RZ" : (String(playerChip.player.team || "") + " "
                    + String(playerChip.player.position || ""))
                color: playerChip.player.redZone ? "#ffb347" : Color.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
            }

            Text {
              width: parent.width
              text: root.signedPoints(playerChip.weeklyPoints) + " "
                + (root.scoringMode === "ppr" ? "PPR" : "STD")
                + (playerChip.player.latestEvent
                  ? " · " + root.signedPoints(playerChip.latestPoints) : "")
              color: playerChip.player.spotlight
                ? playerChip.pulseColor : root.pointsColor(playerChip.weeklyPoints)
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              font.bold: true
              elide: Text.ElideRight
            }
          }
        }
      }
    }
  }
}
