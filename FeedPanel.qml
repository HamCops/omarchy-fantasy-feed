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

  readonly property var serviceEvents: feedService && Array.isArray(feedService.events)
    ? feedService.events
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

  function autoRefreshLabel() {
    if (!feedService) return "AUTO REFRESH OFFLINE"
    if (feedService.loading) return "AUTO REFRESHING"
    if (feedService.nextPollSeconds > 0) return "AUTO REFRESH " + feedService.nextPollSeconds + "s"
    return "AUTO REFRESH ON"
  }

  function statLabels(stats) {
    if (!stats || stats.length === undefined || stats.length === 0) return "NO STAT DELTA"
    var labels = []
    for (var index = 0; index < stats.length; index++) {
      var label = stats[index] ? String(stats[index].label || "") : ""
      if (label !== "") labels.push(label)
    }
    return labels.length > 0 ? labels.join(" · ") : "NO STAT DELTA"
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
    return "No fantasy plays yet"
  }

  function emptyDetail() {
    if (!feedService) return "The shared Fantasy Feed service is not running."
    if (feedService.loading && !hasSnapshot) return "Fetching the latest games and fantasy-relevant plays."
    if (feedService.lastError && !hasSnapshot) return String(feedService.lastError)
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
      onMoveRequested: function(dx, dy) {
        if (dy !== 0) root.moveSelection(dy)
      }
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        if (text === "r" || text === "R") root.refreshFeed()
        else if (text === "d" || text === "D") root.toggleMode()
        else if (text === "o" || text === "O") root.popOut()
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
            text: root.feedService && root.feedService.loading ? "󰦖" : "󰇎"
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
              text: root.feedService && root.feedService.loading ? "󰦖" : "󰇎"
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
          spacing: Style.space(8)
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
            height: eventColumn.implicitHeight + Style.space(18)
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
              anchors.margins: Style.space(9)
              spacing: Style.space(5)

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
                text: String(eventCard.fantasyEvent.rawText || "Play text unavailable")
                color: root.contentForeground
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.bodySmall
                wrapMode: Text.WordWrap
                maximumLineCount: 3
                elide: Text.ElideRight
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

              Repeater {
                model: Array.isArray(eventCard.fantasyEvent.participants)
                  ? eventCard.fantasyEvent.participants
                  : []

                delegate: Column {
                  id: participantRow
                  required property var modelData
                  readonly property var participant: modelData
                  readonly property var points: participant && participant.points ? participant.points : ({})

                  width: parent.width
                  height: implicitHeight
                  spacing: Style.space(2)

                  Item {
                    width: parent.width
                    implicitHeight: Math.max(playerName.implicitHeight, pointLine.implicitHeight)
                    height: implicitHeight

                    Text {
                      id: playerName
                      anchors.left: parent.left
                      anchors.right: pointLine.left
                      anchors.rightMargin: Style.space(8)
                      text: String(participantRow.participant.displayName || "Unknown player").toUpperCase()
                        + (participantRow.participant.team ? " · " + String(participantRow.participant.team) : "")
                      color: root.contentForeground
                      font.family: root.contentFontFamily
                      font.pixelSize: Style.font.bodySmall
                      font.bold: true
                      elide: Text.ElideRight
                    }

                    Row {
                      id: pointLine
                      anchors.right: parent.right
                      spacing: Style.space(4)

                      Text {
                        text: "PPR"
                        color: Qt.darker(root.contentForeground, 1.35)
                        font.family: root.contentFontFamily
                        font.pixelSize: Style.font.bodySmall
                      }

                      Text {
                        text: root.signedPoints(participantRow.points.ppr)
                        color: root.pointsColor(participantRow.points.ppr)
                        font.family: root.contentFontFamily
                        font.pixelSize: Style.font.bodySmall
                        font.bold: true
                      }

                      Text {
                        text: "· STD"
                        color: Qt.darker(root.contentForeground, 1.35)
                        font.family: root.contentFontFamily
                        font.pixelSize: Style.font.bodySmall
                      }

                      Text {
                        text: root.signedPoints(participantRow.points.standard)
                        color: root.pointsColor(participantRow.points.standard)
                        font.family: root.contentFontFamily
                        font.pixelSize: Style.font.bodySmall
                        font.bold: true
                      }
                    }
                  }

                  Text {
                    width: parent.width
                    text: root.statLabels(participantRow.participant.stats)
                    color: Qt.darker(root.contentForeground, 1.35)
                    font.family: root.contentFontFamily
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }
                }
              }
            }
          }
        }

        Text {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          text: root.autoRefreshLabel() + " · o pop out · j/k select · r refresh · d demo/live · Esc close"
          color: Qt.darker(root.contentForeground, 1.55)
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
  }
}
