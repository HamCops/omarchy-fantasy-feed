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
  readonly property var players: service && Array.isArray(service.favoritePlayerRows)
    ? service.favoritePlayerRows : []
  readonly property bool matchup: service ? service.hasMatchup === true : false
  readonly property var totals: service && service.matchupTotals
    ? service.matchupTotals : ({me: 0, opp: 0})
  readonly property color opponentColor: "#ff6b6b"
  readonly property color mineColor: "#6fcf79"

  function points(value) {
    return service ? service.pointsIn(value) : 0
  }

  function opponentLabel() {
    var league = service ? service.league : null
    return league && league.opponent ? String(league.opponent.abbrev || "OPP") : "OPP"
  }

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
      text: root.matchup ? "MATCHUP" : "MY PLAYERS"
      color: Qt.darker(root.foreground, 1.3)
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }

    Text {
      visible: root.matchup
      text: "ME " + Number(root.totals.me).toFixed(1) + " · " + root.opponentLabel()
        + " " + Number(root.totals.opp).toFixed(1)
      color: Number(root.totals.me) >= Number(root.totals.opp) ? root.mineColor : root.opponentColor
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
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
          readonly property bool opponent: String(player.side || "") === "opp"
          readonly property real weeklyPoints: root.points(player.points)
          readonly property real latestPoints: root.points(player.latestPoints)
          // An opponent's gain is your loss: their positive plays pulse red.
          readonly property color pulseColor: opponent
            ? root.pointsColor(-latestPoints) : root.pointsColor(latestPoints)
          width: Style.space(166)
          height: parent.height
          radius: Style.cornerRadius
          color: player.spotlight
            ? Qt.rgba(pulseColor.r, pulseColor.g, pulseColor.b, 0.13)
            : (player.redZone ? Qt.rgba(1, 0.55, 0.2, 0.08)
              : (opponent ? Qt.rgba(root.opponentColor.r, root.opponentColor.g, root.opponentColor.b, 0.05)
                : "transparent"))
          border.width: player.spotlight ? 2 : 1
          border.color: player.spotlight
            ? pulseColor
            : (player.redZone ? "#ffb347"
              : (opponent
                ? Qt.rgba(root.opponentColor.r, root.opponentColor.g, root.opponentColor.b, 0.45)
                : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.35)))

          onPlayerChanged: {
            if (player && player.spotlight) pulseAnimation.restart()
          }

          SequentialAnimation {
            id: pulseAnimation
            NumberAnimation { target: playerChip; property: "scale"; to: 1.035; duration: 110 }
            NumberAnimation { target: playerChip; property: "scale"; to: 1; duration: 190 }
          }

          TapHandler {
            onTapped: root.playerActivated(
              String(playerChip.player.playerId || ""),
              String(playerChip.player.latestEventToken || ""))
          }

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
                  ? "RZ" : ((playerChip.opponent ? "⚔ " : "")
                    + String(playerChip.player.team || "") + " "
                    + String(playerChip.player.slot || playerChip.player.position || ""))
                color: playerChip.player.redZone ? "#ffb347"
                  : (playerChip.opponent ? root.opponentColor : Color.accent)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
            }

            // Weekly points and last delta on the left, ESPN's projection
            // for the week on the right.
            Item {
              width: parent.width
              height: Math.max(chipPoints.implicitHeight, chipProjection.implicitHeight)

              Text {
                id: chipPoints
                anchors.left: parent.left
                anchors.right: chipProjection.left
                anchors.rightMargin: Style.space(4)
                text: root.signedPoints(playerChip.weeklyPoints)
                  + (playerChip.player.latestEvent
                    ? " · " + root.signedPoints(playerChip.latestPoints) : "")
                color: playerChip.player.spotlight
                  ? playerChip.pulseColor
                  : (playerChip.opponent
                    ? root.pointsColor(-playerChip.weeklyPoints)
                    : root.pointsColor(playerChip.weeklyPoints))
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                font.bold: true
                elide: Text.ElideRight
              }

              Text {
                id: chipProjection
                anchors.right: parent.right
                anchors.baseline: chipPoints.baseline
                visible: playerChip.player.projected !== null && playerChip.player.projected !== undefined
                width: visible ? implicitWidth : 0
                text: "P " + Number(playerChip.player.projected || 0).toFixed(1)
                color: Qt.darker(root.foreground, 1.5)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }
          }
        }
      }
    }
  }
}
