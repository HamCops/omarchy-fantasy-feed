import QtQuick
import qs.Commons
import qs.Ui

// The bar is deliberately terse. The singleton service owns all state and
// polling; this per-monitor widget only chooses one useful line to render and
// hosts the monitor-local panel.
BarWidget {
  id: root
  moduleName: "tdh.fantasy-feed"

  readonly property var feedService: bar && bar.shell
    ? bar.shell.serviceFor("tdh.fantasy-feed")
    : null
  readonly property var latestEvent: feedService ? feedService.latestEvent : null
  readonly property bool feedLoading: feedService ? feedService.loading === true : false
  readonly property bool feedStale: feedService ? feedService.stale === true : false

  function signedPoints(value) {
    var number = Number(value)
    if (!isFinite(number)) number = 0
    if (Math.abs(number) < 0.005) number = 0
    var formatted = number.toFixed(2).replace(/\.?0+$/, "")
    return (number > 0 ? "+" : "") + formatted
  }

  function shortPlayerName(value) {
    var parts = String(value || "PLAYER").trim().split(/\s+/)
    return parts[parts.length - 1].toUpperCase()
  }

  function latestLabel() {
    if (!latestEvent) {
      if (feedLoading) return "LOADING"
      return feedService ? "NO PLAYS" : "UNAVAILABLE"
    }
    if (latestEvent.lifecycle === "voided")
      return String(latestEvent.away || "NFL") + "@" + String(latestEvent.home || "") + " · VOID"

    var participants = Array.isArray(latestEvent.participants) ? latestEvent.participants : []
    if (participants.length === 0) return String(latestEvent.kind || "PLAY").replace(/_/g, " ").toUpperCase()

    // ESPN pass plays list the receiver after the passer; using the final
    // participant makes the at-a-glance label match the player who completed
    // the play while still doing the right thing for single-player rushes.
    var participant = participants[participants.length - 1]
    var points = participant && participant.points ? participant.points : ({})
    return shortPlayerName(participant ? participant.displayName : "")
      + " · " + signedPoints(points.ppr) + " PPR / "
      + signedPoints(points.standard) + " STD"
  }

  function tooltip() {
    var status = feedStale ? "Stale fantasy feed" : (feedLoading ? "Refreshing fantasy feed" : "Fantasy feed")
    var play = latestEvent ? String(latestEvent.rawText || "") : ""
    var message = status + "\nLeft click: open feed · Middle click: refresh"
    return play ? message + "\n" + play : message
  }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  // Shape contract used by shell.summon/hide/toggle and the bar's one-popout
  // coordinator. The bar widget is the mounted identity, so it forwards the
  // nested panel's complete lifecycle.
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item
    ? panelLoader.item.popoutSwitchClosing === true
    : false

  function open() {
    if (panelLoader.item) panelLoader.item.open()
  }

  function close() {
    if (panelLoader.item) panelLoader.item.close()
  }

  function toggle() {
    if (panelLoader.item) panelLoader.item.toggle()
  }

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("FeedPanel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: {
      var glyph = root.feedLoading ? "󰦖" : "󰇎"
      if (root.vertical) return glyph
      var prefix = root.feedStale ? "STALE · " : ""
      return glyph + "  " + prefix + root.latestLabel()
    }
    fontSize: Style.font.body
    active: root.feedStale
    dimmed: !root.feedService || (!root.latestEvent && !root.feedLoading)
    tooltipText: root.tooltip()

    onPressed: function(buttonCode) {
      if (buttonCode === Qt.MiddleButton) {
        if (root.feedService) root.feedService.refresh()
      } else if (buttonCode === Qt.LeftButton) {
        root.toggle()
      }
    }
  }
}
