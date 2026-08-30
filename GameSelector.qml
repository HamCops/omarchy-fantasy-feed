pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui

Item {
  id: root

  property var service: null
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family

  readonly property var games: service && Array.isArray(service.games) ? service.games : []
  readonly property bool allSelected: games.length > 0
    && service && service.enabledGameCount === games.length

  function gameLabel(game) {
    var away = String(game && game.away ? game.away : "AWAY")
    var home = String(game && game.home ? game.home : "HOME")
    var hasScores = game && game.awayScore !== undefined && game.homeScore !== undefined
    var matchup = hasScores
      ? away + " " + String(game.awayScore) + " @ " + home + " " + String(game.homeScore)
      : away + " @ " + home
    var status = gameStatusLabel(game)
    return status ? matchup + " · " + status : matchup
  }

  function gameStatusLabel(game) {
    var state = String(game && game.state ? game.state : "").toLowerCase()
    var period = Number(game && game.period)
    var clock = String(game && game.clock ? game.clock : "")
    if (state === "live" && period > 0 && clock)
      return "Q" + period + " " + clock
    var detail = String(game && game.detail ? game.detail : "")
    if (detail) return detail.toUpperCase() === "FINAL" ? "FINAL" : detail
    if (state === "final") return "FINAL"
    return ""
  }

  function gameTooltip(game) {
    var enabled = service && service.gameEnabled(game.id)
    var detail = String(game && game.detail ? game.detail : "")
    var action = enabled ? "Hide this game" : "Show this game"
    return detail ? action + " · " + detail : action
  }

  visible: games.length > 0
  width: parent ? parent.width : implicitWidth
  height: visible ? gameChips.implicitHeight : 0
  implicitHeight: visible ? gameChips.implicitHeight : 0

  Flickable {
    anchors.fill: parent
    clip: true
    contentWidth: gameChips.implicitWidth
    contentHeight: height
    flickableDirection: Flickable.HorizontalFlick
    boundsBehavior: Flickable.StopAtBounds

    Row {
      id: gameChips
      spacing: Style.space(6)

      Button {
        text: "ALL"
        tooltipText: root.allSelected ? "Hide every game" : "Show every game"
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.caption
        bordered: true
        selected: root.allSelected
        onClicked: {
          if (!root.service) return
          if (root.allSelected) root.service.hideAllGames()
          else root.service.showAllGames()
        }
      }

      Repeater {
        model: root.games

        delegate: Button {
          required property var modelData
          readonly property bool gameSelected: root.service
            ? root.service.gameEnabled(modelData.id) : false

          text: root.gameLabel(modelData)
          tooltipText: root.gameTooltip(modelData)
          foreground: gameSelected ? root.foreground : Qt.darker(root.foreground, 1.65)
          fontFamily: root.fontFamily
          fontSize: Style.font.caption
          bordered: true
          selected: gameSelected
          onClicked: if (root.service) root.service.toggleGame(modelData.id)
        }
      }
    }
  }
}
