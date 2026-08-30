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
  readonly property string scoringMode: service ? service.scoringMode : "ppr"
  property string positionFilter: "ALL"
  property bool followNewest: true
  property int unseenArrivals: 0
  property string _lastTopToken: ""
  property real _heldContentY: 0
  property real _lastFeedContentHeight: 0
  readonly property string playerSearch: leaderboardSearch.text.trim().toLowerCase()

  readonly property color foreground: Color.foreground
  readonly property color background: Color.background
  readonly property color positivePoints: "#6fcf79"
  readonly property color negativePoints: "#ff6b6b"
  readonly property string fontFamily: Style.font.family

  readonly property var displayedEvents: {
    var source = service
      ? (activeTab === "favorites" ? service.visibleFavoriteEvents : service.visibleEvents)
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
      if (positionFilter !== "ALL" && String(row.position || "") !== positionFilter)
        continue
      if (playerSearch !== "") {
        var searchable = (String(row.displayName || "") + " "
          + String(row.team || "") + " " + String(row.position || "")).toLowerCase()
        if (searchable.indexOf(playerSearch) === -1) continue
      }
      var gameIds = row.gameIds && row.gameIds.length !== undefined ? row.gameIds : []
      var belongsToSelectedGame = !service || service.games.length === 0 || gameIds.length === 0
      for (var gameIndex = 0; gameIndex < gameIds.length; gameIndex++) {
        if (service.gameEnabled(gameIds[gameIndex])) {
          belongsToSelectedGame = true
          break
        }
      }
      if (belongsToSelectedGame) filtered.push(row)
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
        if (payload && (payload.playerId || payload.eventToken)) {
          var playerId = String(payload.playerId || "")
          var eventToken = String(payload.eventToken || "")
          Qt.callLater(function() { root.jumpToFavoritePlay(playerId, eventToken) })
        }
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

  function eventToken(event) {
    return service ? service.eventToken(event) : ""
  }

  function followLiveTape() {
    followNewest = true
    unseenArrivals = 0
    Qt.callLater(function() {
      if (feedList.count > 0) feedList.positionViewAtBeginning()
    })
  }

  function jumpToFavoritePlay(playerId, preferredToken) {
    activeTab = "favorites"
    Qt.callLater(function() {
      var target = -1
      for (var index = 0; index < root.displayedEvents.length; index++) {
        var event = root.displayedEvents[index]
        if (preferredToken && root.eventToken(event) === preferredToken) {
          target = index
          break
        }
        var participants = event && event.participants
          && event.participants.length !== undefined ? event.participants : []
        for (var participantIndex = 0; participantIndex < participants.length; participantIndex++) {
          if (String(participants[participantIndex].playerId || "") === String(playerId || "")) {
            target = index
            break
          }
        }
        if (target !== -1) break
      }
      if (target === -1) return
      root.followNewest = target === 0
      root.unseenArrivals = 0
      feedList.positionViewAtIndex(target, ListView.Center)
    })
  }

  function resetTapeTracking() {
    followNewest = true
    unseenArrivals = 0
    _lastTopToken = displayedEvents.length > 0 ? eventToken(displayedEvents[0]) : ""
    Qt.callLater(function() {
      if (feedList.count > 0) feedList.positionViewAtBeginning()
    })
  }

  function handleDisplayedEventsChange() {
    var topToken = displayedEvents.length > 0 ? eventToken(displayedEvents[0]) : ""
    if (_lastTopToken === "") {
      _lastTopToken = topToken
      return
    }
    if (topToken === "" || topToken === _lastTopToken) return
    var isPresentedArrival = service
      && topToken === String(service.lastPresentedToken || "")
    if (isPresentedArrival) {
      if (followNewest)
        Qt.callLater(function() { feedList.positionViewAtBeginning() })
      else
        unseenArrivals += 1
    }
    _lastTopToken = topToken
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

  function scoringLabel() {
    return scoringMode === "ppr" ? "PPR" : "STD"
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

  function htmlEscape(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;")
  }

  function regexEscape(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  }

  function playerNameMatch(playText, displayName) {
    var words = String(displayName || "").trim().split(/\s+/)
    if (words.length === 0 || words[0] === "") return null
    var exact = new RegExp("\\b" + regexEscape(words.join(" ")).replace(/ /g, "\\s+") + "\\b", "i")
    var exactMatch = exact.exec(playText)
    if (exactMatch) return exactMatch
    while (words.length > 2 && /^(Jr\.?|Sr\.?|II|III|IV)$/i.test(words[words.length - 1])) words.pop()
    if (words.length < 2) return null
    return new RegExp("\\b" + regexEscape(words[0].charAt(0)) + "\\.?\\s*"
      + regexEscape(words[words.length - 1]) + "\\b", "i").exec(playText)
  }

  function annotatedPlay(event) {
    var raw = String(event && event.rawText ? event.rawText : "Play text unavailable")
    var participants = event && event.participants && event.participants.length !== undefined
      ? event.participants : []
    var annotations = []
    for (var index = 0; index < participants.length; index++) {
      var participant = participants[index]
      var match = playerNameMatch(raw, participant ? participant.displayName : "")
      if (!match) continue
      var points = participant && participant.points ? participant.points[scoringMode] : 0
      annotations.push({start: match.index, end: match.index + match[0].length, points: points})
    }
    annotations.sort(function(left, right) { return left.start - right.start })
    var result = ""
    var cursor = 0
    for (var annotationIndex = 0; annotationIndex < annotations.length; annotationIndex++) {
      var annotation = annotations[annotationIndex]
      if (annotation.start < cursor) continue
      result += htmlEscape(raw.slice(cursor, annotation.end))
      result += " <b><font color=\"" + htmlEscape(String(pointsColor(annotation.points))) + "\">("
        + htmlEscape(signedPoints(annotation.points)) + ")</font></b>"
      cursor = annotation.end
    }
    return result + htmlEscape(raw.slice(cursor))
  }

  function stateLabel() {
    if (!service) return "OFFLINE"
    if (service.stale) return "STALE"
    if (service.demoMode) return "DEMO"
    if (service.simulatorMode) return "SIM"
    var state = service.snapshot ? String(service.snapshot.sourceState || "") : ""
    return state ? state.toUpperCase() : "CONNECTING"
  }

  function weekLabel() {
    if (!service || !service.week) return "CURRENT NFL WEEK"
    var label = String(service.week.label || ("Week " + service.week.number))
    return label + " · " + String(service.week.season || "")
  }

  function isFavorite(playerId) {
    return service ? service.isFavorite(playerId) : false
  }

  function toggleFavorite(player) {
    if (service) service.toggleFavorite(player)
  }

  onScoringModeChanged: scoringDropdown.value = scoringMode
  onDisplayedEventsChanged: handleDisplayedEventsChange()
  onActiveTabChanged: resetTapeTracking()

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
          if (root.service) root.service.toggleScoringMode()
          event.accepted = true
        } else if (event.key === Qt.Key_Slash && root.activeTab === "leaders") {
          leaderboardSearch.forceActiveFocus(); event.accepted = true
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
                text: "🏈  Fantasy Feed"
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
              text: root.weekLabel() + (root.service && root.service.pendingEventCount > 0
                ? " · " + root.service.pendingEventCount + " INCOMING" : "")
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

            Dropdown {
              id: scoringDropdown
              width: Style.space(86)
              showLabel: false
              options: [
                {value: "ppr", label: "PPR"},
                {value: "standard", label: "STD"}
              ]
              value: root.scoringMode
              foreground: root.foreground
              fontFamily: root.fontFamily
              onChanged: function(value) {
                if (root.service) root.service.setScoringMode(value)
              }
            }

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

        GameSelector {
          service: root.service
          foreground: root.foreground
          fontFamily: root.fontFamily
        }


        FavoritePulseRail {
          service: root.service
          foreground: root.foreground
          fontFamily: root.fontFamily
          onPlayerActivated: function(playerId, eventToken) {
            root.jumpToFavoritePlay(playerId, eventToken)
          }
        }

        Row {
          visible: root.activeTab === "leaders"
          width: parent.width
          spacing: Style.space(6)

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

          TextField {
            id: leaderboardSearch
            width: Style.space(210)
            placeholderText: "Search player or team…  /"
            foreground: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            verticalPadding: Style.space(4)

            Keys.onPressed: function(event) {
              if (event.key === Qt.Key_Escape && text !== "") {
                clear()
                event.accepted = true
              }
            }
          }

          Button {
            visible: root.playerSearch !== ""
            text: "×"
            tooltipText: "Clear player search"
            foreground: root.foreground
            fontFamily: root.fontFamily
            fontSize: Style.font.bodySmall
            bordered: true
            onClicked: leaderboardSearch.clear()
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
              : (root.service && root.service.games.length > 0
                  && root.service.enabledGameCount === 0
                ? "No games selected. Click one or more matchups above to add them back."
                : "No fantasy-relevant plays yet.")
            color: Qt.darker(root.foreground, 1.35)
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.WordWrap
          }

          ListView {
            id: feedList
            anchors.fill: parent
            visible: root.activeTab !== "leaders" && root.displayedEvents.length > 0
            spacing: Style.space(4)
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.displayedEvents
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            onMovementEnded: {
              root.followNewest = atYBeginning
              if (root.followNewest) root.unseenArrivals = 0
              root._heldContentY = contentY
              root._lastFeedContentHeight = contentHeight
            }
            onContentHeightChanged: {
              var increase = contentHeight - root._lastFeedContentHeight
              if (!root.followNewest && root._lastFeedContentHeight > 0 && increase > 0) {
                contentY = root._heldContentY + increase
                root._heldContentY = contentY
              }
              root._lastFeedContentHeight = contentHeight
            }

            delegate: Rectangle {
              id: eventCard
              required property var modelData
              readonly property var eventData: modelData
              readonly property bool favoriteSpotlight: root.service
                ? root.service.isSpotlightEvent(eventData) : false
              width: ListView.view.width
              height: eventColumn.implicitHeight + Style.space(12)
              color: favoriteSpotlight
                ? Qt.rgba(root.positivePoints.r, root.positivePoints.g, root.positivePoints.b, 0.08)
                : "transparent"
              border.width: favoriteSpotlight ? 2 : 1
              border.color: favoriteSpotlight
                ? root.positivePoints
                : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.35)

              Column {
                id: eventColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Style.space(6)
                spacing: Style.space(3)

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
                    text: (eventCard.favoriteSpotlight ? "★ " : "")
                      + String(eventCard.eventData.lifecycle || "current").toUpperCase()
                    color: eventCard.eventData.lifecycle === "voided" ? root.negativePoints : Qt.darker(root.foreground, 1.35)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                  }
                }

                Text {
                  width: parent.width
                  text: root.annotatedPlay(eventCard.eventData)
                  textFormat: Text.StyledText
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

              }
            }
          }

          Button {
            anchors.top: parent.top
            anchors.right: parent.right
            anchors.margins: Style.space(8)
            z: 3
            visible: root.activeTab !== "leaders"
              && !root.followNewest && root.unseenArrivals > 0
            text: String(root.unseenArrivals) + " NEW ↑"
            tooltipText: "Return to the live edge"
            foreground: root.positivePoints
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            bordered: true
            onClicked: root.followLiveTape()
          }

          Text {
            anchors.centerIn: parent
            visible: root.activeTab === "leaders" && root.sortedLeaders.length === 0
            text: root.playerSearch !== ""
              ? "No players match ‘" + leaderboardSearch.text.trim() + "’."
              : "No weekly player totals are available yet."
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
                text: root.signedPoints(leaderRow.selectedPoints) + " " + root.scoringLabel()
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
          text: "Click games to filter · / search players · 1 feed · 2 leaderboard · 3 favorites · p scoring · r refresh · Esc close"
          color: Qt.darker(root.foreground, 1.55)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
  }
}
