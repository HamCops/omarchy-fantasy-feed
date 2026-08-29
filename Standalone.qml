pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import Quickshell
import qs.Commons
import qs.Ui

Item {
  id: root

  property var shell: null
  property var service: null
  property bool closingFromHost: false
  property string activeTab: "feed"
  property string scoringMode: "ppr"
  property string positionFilter: "ALL"

  readonly property color foreground: Color.foreground
  readonly property color background: Color.background
  readonly property color positivePoints: "#6fcf79"
  readonly property color negativePoints: "#ff6b6b"
  readonly property string fontFamily: Style.font.family

  readonly property var displayedEvents: {
    var source = service
      ? (activeTab === "favorites" ? service.favoriteEvents : service.events)
      : []
    var reversed = []
    for (var index = source.length - 1; index >= 0; index--) reversed.push(source[index])
    return reversed
  }

  readonly property var sortedLeaders: {
    var source = service && Array.isArray(service.leaderboard) ? service.leaderboard : []
    var filtered = []
    for (var index = 0; index < source.length; index++) {
      var row = source[index]
      if (positionFilter === "ALL" || String(row.position || "") === positionFilter)
        filtered.push(row)
    }
    var mode = scoringMode
    filtered.sort(function(left, right) {
      var leftPoints = Number(left && left.points ? left.points[mode] : 0)
      var rightPoints = Number(right && right.points ? right.points[mode] : 0)
      if (rightPoints !== leftPoints) return rightPoints - leftPoints
      return String(left.displayName || "").localeCompare(String(right.displayName || ""))
    })
    return filtered
  }

  function open(payloadJson) {
    closingFromHost = false
    if (payloadJson) {
      try {
        var payload = JSON.parse(String(payloadJson))
        if (payload && ["feed", "leaders", "favorites"].indexOf(payload.tab) !== -1)
          activeTab = payload.tab
      } catch (error) { /* ignore malformed optional payload */ }
    }
    window.visible = true
    Qt.callLater(function() { focusScope.forceActiveFocus() })
  }

  function close() {
    closingFromHost = true
    window.visible = false
    closingFromHost = false
  }

  function requestClose() {
    if (shell && typeof shell.hide === "function") shell.hide("tdh.fantasy-feed")
    else window.visible = false
  }

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
    return number > 0 ? positivePoints : negativePoints
  }

  function statLabels(stats) {
    if (!stats || stats.length === undefined || stats.length === 0) return "NO STAT DELTA"
    var labels = []
    for (var index = 0; index < stats.length; index++) {
      var label = stats[index] ? String(stats[index].label || "") : ""
      if (label) labels.push(label)
    }
    return labels.length > 0 ? labels.join(" · ") : "NO STAT DELTA"
  }

  function stateLabel() {
    if (!service) return "OFFLINE"
    if (service.stale) return "STALE"
    if (service.demoMode) return "DEMO"
    var state = service.snapshot ? String(service.snapshot.sourceState || "") : ""
    return state ? state.toUpperCase() : "CONNECTING"
  }

  function weekLabel() {
    if (!service || !service.week) return "CURRENT NFL WEEK"
    var label = String(service.week.label || ("Week " + service.week.number))
    return label + " · " + String(service.week.season || "")
  }

  function autoRefreshLabel() {
    if (!service) return "AUTO REFRESH OFFLINE"
    if (service.loading) return "AUTO REFRESHING"
    if (service.nextPollSeconds > 0) return "AUTO REFRESH " + service.nextPollSeconds + "s"
    return "AUTO REFRESH ON"
  }

  function isFavorite(playerId) {
    return service ? service.isFavorite(playerId) : false
  }

  function toggleFavorite(player) {
    if (service) service.toggleFavorite(player)
  }

  FloatingWindow {
    id: window
    title: "Fantasy Feed"
    color: root.background
    implicitWidth: 860
    implicitHeight: 720
    minimumSize: Qt.size(680, 520)

    onVisibleChanged: {
      if (!visible && !root.closingFromHost && root.shell && typeof root.shell.hide === "function")
        root.shell.hide("tdh.fantasy-feed")
    }

    FocusScope {
      id: focusScope
      anchors.fill: parent
      focus: true

      Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Escape) {
          root.requestClose(); event.accepted = true
        } else if (event.key === Qt.Key_1) {
          root.activeTab = "feed"; event.accepted = true
        } else if (event.key === Qt.Key_2) {
          root.activeTab = "leaders"; event.accepted = true
        } else if (event.key === Qt.Key_3) {
          root.activeTab = "favorites"; event.accepted = true
        } else if (event.key === Qt.Key_P) {
          root.scoringMode = root.scoringMode === "ppr" ? "standard" : "ppr"
          event.accepted = true
        } else if (event.key === Qt.Key_R && root.service) {
          root.service.refresh(); event.accepted = true
        }
      }

      Column {
        anchors.fill: parent
        anchors.margins: Style.space(18)
        spacing: Style.space(10)

        Item {
          width: parent.width
          height: Math.max(titleColumn.implicitHeight, headerActions.implicitHeight)

          Column {
            id: titleColumn
            anchors.left: parent.left
            anchors.right: headerActions.left
            anchors.rightMargin: Style.space(12)
            spacing: Style.space(2)

            Row {
              spacing: Style.space(8)
              Text {
                text: "󰇎  Fantasy Feed"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
              }
              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.stateLabel()
                color: root.service && root.service.stale ? root.negativePoints : Color.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
            }

            Text {
              text: root.weekLabel() + " · " + root.autoRefreshLabel()
              color: Qt.darker(root.foreground, 1.4)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          Row {
            id: headerActions
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(6)

            Button {
              iconText: "󰑐"
              tooltipText: "Refresh now (r); automatic refresh stays enabled"
              foreground: root.foreground
              fontFamily: root.fontFamily
              iconSpinning: root.service && root.service.loading
              onClicked: if (root.service) root.service.refresh()
            }
            Button {
              text: root.service && root.service.demoMode ? "LIVE" : "DEMO"
              tooltipText: "Toggle deterministic replay/live data"
              foreground: root.foreground
              fontFamily: root.fontFamily
              fontSize: Style.font.caption
              bordered: true
              onClicked: if (root.service) root.service.selectMode(!root.service.demoMode)
            }
          }
        }

        Row {
          spacing: Style.space(6)
          Repeater {
            model: [
              {key: "feed", label: "FEED"},
              {key: "leaders", label: "LEADERBOARD"},
              {key: "favorites", label: "★ FAVORITES"}
            ]
            delegate: Button {
              required property var modelData
              text: modelData.label
              foreground: root.foreground
              fontFamily: root.fontFamily
              fontSize: Style.font.caption
              bordered: true
              active: root.activeTab === modelData.key
              onClicked: root.activeTab = modelData.key
            }
          }
        }

        Row {
          visible: root.activeTab === "leaders"
          width: parent.width
          spacing: Style.space(6)

          Button {
            text: root.scoringMode === "ppr" ? "PPR ▼" : "STANDARD ▼"
            tooltipText: "Sort by " + (root.scoringMode === "ppr" ? "standard" : "PPR") + " points (p)"
            foreground: root.foreground
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            bordered: true
            onClicked: root.scoringMode = root.scoringMode === "ppr" ? "standard" : "ppr"
          }

          Repeater {
            model: ["ALL", "QB", "RB", "WR", "TE"]
            delegate: Button {
              required property string modelData
              text: modelData
              foreground: root.foreground
              fontFamily: root.fontFamily
              fontSize: Style.font.caption
              bordered: true
              active: root.positionFilter === modelData
              onClicked: root.positionFilter = modelData
            }
          }
        }

        PanelSeparator { foreground: root.foreground }

        Item {
          width: parent.width
          height: parent.height - y - footer.implicitHeight - Style.space(8)

          Text {
            anchors.centerIn: parent
            visible: root.activeTab !== "leaders" && root.displayedEvents.length === 0
            width: parent.width - Style.space(40)
            horizontalAlignment: Text.AlignHCenter
            text: root.activeTab === "favorites"
              ? (root.service && root.service.favoriteCount > 0
                ? "No plays for your favorite players yet."
                : "Favorite a player from the leaderboard to build a custom feed.")
              : "No fantasy-relevant plays yet."
            color: Qt.darker(root.foreground, 1.35)
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.WordWrap
          }

          ListView {
            id: feedList
            anchors.fill: parent
            visible: root.activeTab !== "leaders" && root.displayedEvents.length > 0
            spacing: Style.space(8)
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.displayedEvents
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
              id: eventCard
              required property var modelData
              readonly property var eventData: modelData
              width: ListView.view.width
              height: eventColumn.implicitHeight + Style.space(18)
              color: "transparent"
              border.width: 1
              border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.35)

              Column {
                id: eventColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Style.space(9)
                spacing: Style.space(5)

                Item {
                  width: parent.width
                  height: Math.max(gameText.implicitHeight, lifecycleText.implicitHeight)
                  Text {
                    id: gameText
                    anchors.left: parent.left
                    text: String(eventCard.eventData.away || "NFL") + " @ "
                      + String(eventCard.eventData.home || "") + " · Q"
                      + String(eventCard.eventData.quarter || "-") + "  "
                      + String(eventCard.eventData.clock || "")
                    color: Qt.darker(root.foreground, 1.35)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                  }
                  Text {
                    id: lifecycleText
                    anchors.right: parent.right
                    text: String(eventCard.eventData.lifecycle || "current").toUpperCase()
                    color: eventCard.eventData.lifecycle === "voided" ? root.negativePoints : Qt.darker(root.foreground, 1.35)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                  }
                }

                Text {
                  width: parent.width
                  text: String(eventCard.eventData.rawText || "Play text unavailable")
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  wrapMode: Text.WordWrap
                }

                Text {
                  visible: eventCard.eventData.lifecycle === "voided"
                  text: "NO FANTASY POINTS · PREVIOUS RESULT REMOVED"
                  color: root.negativePoints
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }

                Repeater {
                  model: Array.isArray(eventCard.eventData.participants) ? eventCard.eventData.participants : []
                  delegate: Item {
                    id: participantRow
                    required property var modelData
                    readonly property var participant: modelData
                    readonly property var participantPoints: participant && participant.points ? participant.points : ({})
                    width: parent.width
                    height: Math.max(participantText.implicitHeight, participantActions.implicitHeight)

                    Column {
                      id: participantText
                      anchors.left: parent.left
                      anchors.right: participantActions.left
                      anchors.rightMargin: Style.space(8)
                      spacing: Style.space(1)
                      Text {
                        width: parent.width
                        text: String(participantRow.participant.displayName || "Unknown player").toUpperCase()
                          + (participantRow.participant.team ? " · " + participantRow.participant.team : "")
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.bodySmall
                        font.bold: true
                        elide: Text.ElideRight
                      }
                      Text {
                        width: parent.width
                        text: root.statLabels(participantRow.participant.stats)
                        color: Qt.darker(root.foreground, 1.35)
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        elide: Text.ElideRight
                      }
                    }

                    Row {
                      id: participantActions
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      spacing: Style.space(7)
                      Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "PPR " + root.signedPoints(participantRow.participantPoints.ppr)
                        color: root.pointsColor(participantRow.participantPoints.ppr)
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.bodySmall
                        font.bold: true
                      }
                      Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "STD " + root.signedPoints(participantRow.participantPoints.standard)
                        color: root.pointsColor(participantRow.participantPoints.standard)
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.bodySmall
                        font.bold: true
                      }
                      Button {
                        text: root.isFavorite(participantRow.participant.playerId) ? "★" : "☆"
                        tooltipText: root.isFavorite(participantRow.participant.playerId)
                          ? "Remove favorite" : "Favorite player"
                        foreground: root.isFavorite(participantRow.participant.playerId) ? root.positivePoints : root.foreground
                        fontFamily: root.fontFamily
                        fontSize: Style.font.bodySmall
                        onClicked: root.toggleFavorite(participantRow.participant)
                      }
                    }
                  }
                }
              }
            }
          }

          Text {
            anchors.centerIn: parent
            visible: root.activeTab === "leaders" && root.sortedLeaders.length === 0
            text: "No weekly player totals are available yet."
            color: Qt.darker(root.foreground, 1.35)
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          ListView {
            id: leaderboardList
            anchors.fill: parent
            visible: root.activeTab === "leaders" && root.sortedLeaders.length > 0
            spacing: Style.space(4)
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.sortedLeaders
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
              id: leaderRow
              required property var modelData
              required property int index
              readonly property var player: modelData
              readonly property real selectedPoints: Number(player.points ? player.points[root.scoringMode] : 0)
              width: ListView.view.width
              height: Style.space(48)
              color: index % 2 === 0
                ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.045)
                : "transparent"

              Text {
                anchors.left: parent.left
                anchors.leftMargin: Style.space(10)
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(36)
                text: String(index + 1).padStart(2, "0")
                color: Qt.darker(root.foreground, 1.45)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
              Text {
                anchors.left: parent.left
                anchors.leftMargin: Style.space(48)
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(48)
                text: String(leaderRow.player.position || "")
                color: Color.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                font.bold: true
              }
              Column {
                anchors.left: parent.left
                anchors.leftMargin: Style.space(100)
                anchors.right: pointsText.left
                anchors.rightMargin: Style.space(12)
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(1)
                Text {
                  width: parent.width
                  text: String(leaderRow.player.displayName || "Unknown player").toUpperCase()
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  font.bold: true
                  elide: Text.ElideRight
                }
                Text {
                  width: parent.width
                  text: String(leaderRow.player.team || "") + " · " + root.statLabels(leaderRow.player.stats)
                  color: Qt.darker(root.foreground, 1.35)
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                }
              }
              Text {
                id: pointsText
                anchors.right: favoriteButton.left
                anchors.rightMargin: Style.space(10)
                anchors.verticalCenter: parent.verticalCenter
                text: root.signedPoints(leaderRow.selectedPoints) + " " + root.scoringMode.toUpperCase()
                color: root.pointsColor(leaderRow.selectedPoints)
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
              }
              Button {
                id: favoriteButton
                anchors.right: parent.right
                anchors.rightMargin: Style.space(8)
                anchors.verticalCenter: parent.verticalCenter
                text: root.isFavorite(leaderRow.player.playerId) ? "★" : "☆"
                tooltipText: root.isFavorite(leaderRow.player.playerId) ? "Remove favorite" : "Favorite player"
                foreground: root.isFavorite(leaderRow.player.playerId) ? root.positivePoints : root.foreground
                fontFamily: root.fontFamily
                fontSize: Style.font.bodySmall
                onClicked: root.toggleFavorite(leaderRow.player)
              }
            }
          }
        }

        Text {
          id: footer
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          text: "1 feed · 2 leaderboard · 3 favorites · p PPR/standard · r refresh now · Esc close"
          color: Qt.darker(root.foreground, 1.55)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
  }
}
