pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui

// Per-monitor presentation for the singleton fantasy-feed service. This file
// intentionally contains no Process, Timer, network, cache, or parser logic.
Panel {
  id: root
  moduleName: "tdh.fantasy-feed"
  ipcTarget: "tdh.fantasy-feed"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root
  readonly property var feedService: bar && bar.shell
    ? bar.shell.serviceFor("tdh.fantasy-feed")
    : null

  readonly property var serviceEvents: feedService && Array.isArray(feedService.visibleEvents)
    ? feedService.visibleEvents
    : []
  readonly property var newestEvents: {
    var reversed = []
    for (var index = serviceEvents.length - 1; index >= 0; index--)
      reversed.push(serviceEvents[index])
    return reversed
  }
  readonly property bool hasSnapshot: feedService && feedService.snapshot !== null
  readonly property bool hasEvents: newestEvents.length > 0
  readonly property color contentForeground: bar ? bar.foreground : Color.foreground
  readonly property color contentUrgent: bar ? bar.urgent : Color.urgent
  readonly property color positivePoints: "#6fcf79"
  readonly property color negativePoints: "#ff6b6b"
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family

  // Selection belongs to this panel instance, so opening the same feed on a
  // second monitor never moves the first monitor's cursor.
  property int selectedIndex: 0
  property bool cursorActive: true
  property string scoringMode: "ppr"

  function open() {
    root.controller.show()
    Qt.callLater(function() {
      if (root.opened) root.setCenterHoverRevealSuppressed(true)
    })
  }

  function close() {
    root.setCenterHoverRevealSuppressed(false)
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.open()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function setCenterHoverRevealSuppressed(value) {
    if (root.bar && "centerHoverRevealSuppressed" in root.bar)
      root.bar.centerHoverRevealSuppressed = value
  }

  function clampSelection() {
    if (newestEvents.length === 0) {
      selectedIndex = 0
      return
    }
    selectedIndex = Math.max(0, Math.min(selectedIndex, newestEvents.length - 1))
  }

  function moveSelection(delta) {
    if (newestEvents.length === 0) return
    cursorActive = true
    selectedIndex = Math.max(0, Math.min(selectedIndex + delta, newestEvents.length - 1))
  }

  function refreshFeed() {
    if (feedService) feedService.refresh()
  }

  function toggleMode() {
    if (!feedService) return
    if (feedService.demoMode) feedService.selectMode(false)
    else feedService.selectMode(true)
  }

  function popOut() {
    var hostShell = bar && bar.shell ? bar.shell : null
    root.close()
    if (hostShell && typeof hostShell.summon === "function")
      hostShell.summon("tdh.fantasy-feed", JSON.stringify({tab: "feed"}))
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
    if (!isFinite(number) || Math.abs(number) < 0.005) return Qt.darker(contentForeground, 1.35)
    return number > 0 ? positivePoints : negativePoints
  }

  function scoringLabel() {
    return scoringMode === "ppr" ? "PPR" : "STD"
  }

  function autoRefreshLabel() {
    if (!feedService) return "AUTO REFRESH OFFLINE"
    if (feedService.loading) return "AUTO REFRESHING"
    if (feedService.nextPollSeconds > 0)
      return "AUTO REFRESH " + countdownLabel(feedService.nextPollSeconds)
    return "AUTO REFRESH ON"
  }

  function countdownLabel(seconds) {
    var remaining = Math.max(0, Number(seconds) || 0)
    if (remaining < 90) return Math.ceil(remaining) + "s"
    if (remaining < 3600) return Math.ceil(remaining / 60) + "m"
    var hours = Math.floor(remaining / 3600)
    var minutes = Math.ceil((remaining - hours * 3600) / 60)
    if (minutes >= 60) {
      hours += 1
      minutes = 0
    }
    return hours + "h" + (minutes > 0 ? " " + minutes + "m" : "")
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

  function matchup(event) {
    return String(event && event.away ? event.away : "NFL")
      + " @ " + String(event && event.home ? event.home : "")
  }

  function gameTime(event) {
    var quarter = Number(event && event.quarter)
    var quarterLabel = quarter > 0 ? "Q" + quarter : "GAME"
    var clock = event ? String(event.clock || "") : ""
    return quarterLabel + (clock ? "  " + clock : "")
  }

  function lifecycle(event) {
    var value = event ? String(event.lifecycle || "current") : "current"
    return value.toUpperCase()
  }

  function stateLabel() {
    if (!feedService) return "OFFLINE"
    if (feedService.stale) return "STALE"
    if (feedService.demoMode) return "DEMO"
    var source = feedService.snapshot ? String(feedService.snapshot.sourceState || "") : ""
    if (source === "live") return "LIVE"
    if (source === "scheduled") return "SCHEDULED"
    if (source === "final") return "FINAL"
    return source ? source.toUpperCase() : "CONNECTING"
  }

  function updateLabel() {
    if (!feedService) return "Service unavailable"
    if (feedService.loading) return "Refreshing…"
    if (feedService.lastUpdated) {
      var compact = String(feedService.lastUpdated).replace("T", " ").replace("Z", " UTC")
      return newestEvents.length + (newestEvents.length === 1 ? " play · " : " plays · ") + compact
    }
    return newestEvents.length + (newestEvents.length === 1 ? " play" : " plays")
  }

  function emptyTitle() {
    if (!feedService) return "Feed service unavailable"
    if (feedService.loading && !hasSnapshot) return "Loading NFL plays"
    if (feedService.lastError && !hasSnapshot) return "Could not load the feed"
    if (feedService.games.length > 0 && feedService.enabledGameCount === 0)
      return "No games selected"
    return "No fantasy plays yet"
  }

  function emptyDetail() {
    if (!feedService) return "The shared Fantasy Feed service is not running."
    if (feedService.loading && !hasSnapshot) return "Fetching the latest games and fantasy-relevant plays."
    if (feedService.lastError && !hasSnapshot) return String(feedService.lastError)
    if (feedService.games.length > 0 && feedService.enabledGameCount === 0)
      return "Click one or more matchups above to add them back to the feed."
    if (feedService.demoMode) return "Replay mode is ready, but this fixture has no visible events."
    return "Keep this panel open or switch to Demo for a deterministic sample."
  }

  onNewestEventsChanged: clampSelection()
  onOpenedChanged: {
    if (opened) {
      selectedIndex = 0
      cursorActive = true
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(560))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(640))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: scoringDropdown.popupOpen
      onMoveRequested: function(dx, dy) {
        if (dy !== 0) root.moveSelection(dy)
      }
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        if (text === "r" || text === "R") root.refreshFeed()
        else if (text === "d" || text === "D") root.toggleMode()
        else if (text === "o" || text === "O") root.popOut()
        else if (text === "p" || text === "P")
          root.scoringMode = root.scoringMode === "ppr" ? "standard" : "ppr"
      }

      Column {
        id: panelColumn
        width: parent.width
        spacing: Style.space(10)

        Item {
          width: parent.width
          implicitHeight: Math.max(headerGlyph.implicitHeight, headerText.implicitHeight)
          height: implicitHeight

          Text {
            id: headerGlyph
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: root.feedService && root.feedService.loading ? "󰦖" : "🏈"
            color: root.feedService && root.feedService.stale ? root.contentUrgent : root.contentForeground
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.display
          }

          Column {
            id: headerText
            anchors.left: headerGlyph.right
            anchors.leftMargin: Style.space(12)
            anchors.right: headerActions.left
            anchors.rightMargin: Style.space(12)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Row {
              spacing: Style.space(8)

              Text {
                text: "Fantasy Feed"
                color: root.contentForeground
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.title
                font.bold: true
              }

              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.stateLabel()
                color: root.feedService && root.feedService.stale
                  ? root.contentUrgent
                  : Color.accent
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
            }

            Text {
              width: parent.width
              text: root.updateLabel()
              color: Qt.darker(root.contentForeground, 1.4)
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
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
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              onChanged: function(value) { root.scoringMode = value }
            }

            Button {
              text: "↗"
              tooltipText: "Open standalone window (o)"
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              fontSize: Style.font.body
              bordered: true
              onClicked: root.popOut()
            }

            Button {
              iconText: "󰑐"
              tooltipText: "Refresh (r)"
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              horizontalPadding: Style.spacing.controlPaddingX
              verticalPadding: Style.spacing.controlPaddingY
              iconSpinning: root.feedService && root.feedService.loading
              onClicked: root.refreshFeed()
            }

            Button {
              text: root.feedService && root.feedService.demoMode ? "LIVE" : "DEMO"
              tooltipText: root.feedService && root.feedService.demoMode
                ? "Switch to live data (d)"
                : "Run deterministic demo (d)"
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              fontSize: Style.font.caption
              bordered: true
              onClicked: root.toggleMode()
            }
          }
        }

        Text {
          visible: root.feedService && root.feedService.lastError !== ""
          width: parent.width
          text: root.feedService ? root.feedService.lastError : ""
          color: root.contentUrgent
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          maximumLineCount: 2
          elide: Text.ElideRight
        }

        GameSelector {
          service: root.feedService
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
        }

        PanelSeparator {
          foreground: root.contentForeground
        }

        Item {
          visible: !root.hasEvents
          width: parent.width
          implicitHeight: emptyColumn.implicitHeight + Style.space(30)
          height: implicitHeight

          Column {
            id: emptyColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(6)

            Text {
              anchors.horizontalCenter: parent.horizontalCenter
              text: root.feedService && root.feedService.loading ? "󰦖" : "🏈"
              color: root.contentForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.displayLarge

              RotationAnimator on rotation {
                running: root.feedService && root.feedService.loading
                from: 0
                to: 360
                duration: 900
                loops: Animation.Infinite
              }
            }

            Text {
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
              text: root.emptyTitle()
              color: root.contentForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.subtitle
              font.bold: true
            }

            Text {
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
              text: root.emptyDetail()
              color: Qt.darker(root.contentForeground, 1.4)
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
            }
          }
        }

        ListView {
          id: eventList
          visible: root.hasEvents
          width: parent.width
          height: visible ? Math.min(contentHeight, Style.space(470)) : 0
          spacing: Style.space(4)
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          interactive: contentHeight > height

          ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

          model: root.newestEvents
          currentIndex: root.selectedIndex
          onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)

          delegate: CursorSurface {
            id: eventCard
            required property var modelData
            required property int index
            readonly property var fantasyEvent: modelData

            width: ListView.view.width
            height: eventColumn.implicitHeight + Style.space(12)
            foreground: root.contentForeground
            accent: Color.accent
            bordered: true
            hasCursor: root.cursorActive && root.selectedIndex === index

            HoverHandler {
              onHoveredChanged: {
                if (!hovered) return
                root.cursorActive = true
                root.selectedIndex = eventCard.index
              }
            }

            Column {
              id: eventColumn
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.top: parent.top
              anchors.margins: Style.space(6)
              spacing: Style.space(3)

              Item {
                width: parent.width
                implicitHeight: Math.max(gameLabel.implicitHeight, lifecycleLabel.implicitHeight)
                height: implicitHeight

                Text {
                  id: gameLabel
                  anchors.left: parent.left
                  anchors.right: lifecycleLabel.left
                  anchors.rightMargin: Style.space(8)
                  text: root.matchup(eventCard.fantasyEvent) + " · " + root.gameTime(eventCard.fantasyEvent)
                  color: Qt.darker(root.contentForeground, 1.35)
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                  elide: Text.ElideRight
                }

                Text {
                  id: lifecycleLabel
                  anchors.right: parent.right
                  text: root.lifecycle(eventCard.fantasyEvent)
                  color: eventCard.fantasyEvent.lifecycle === "voided"
                    ? root.contentUrgent
                    : (eventCard.fantasyEvent.lifecycle === "corrected" ? Color.accent : Qt.darker(root.contentForeground, 1.35))
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }
              }

              Text {
                width: parent.width
                text: root.annotatedPlay(eventCard.fantasyEvent)
                textFormat: Text.StyledText
                color: root.contentForeground
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.bodySmall
                wrapMode: Text.WordWrap
              }

              Text {
                visible: eventCard.fantasyEvent.lifecycle === "voided"
                width: parent.width
                text: "NO FANTASY POINTS · PREVIOUS RESULT REMOVED"
                color: root.contentUrgent
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }

            }
          }
        }

        Text {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          text: root.autoRefreshLabel() + " · p PPR/STD · o pop out · j/k select · r refresh · d demo/live · Esc close"
          color: Qt.darker(root.contentForeground, 1.55)
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
  }
}
