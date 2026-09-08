import QtQuick
import qs.Commons
import qs.Ui

// The bar is deliberately terse. The singleton service owns all state and
// polling; this per-monitor widget only chooses one useful line to render and
// hosts the monitor-local panel.
BarWidget {
  id: root
  moduleName: "io.github.studioxvii.fantasy-feed"

  readonly property var feedService: bar && bar.shell
    ? bar.shell.serviceFor("io.github.studioxvii.fantasy-feed")
    : null
  readonly property var latestEvent: feedService ? feedService.latestVisibleEvent : null
  readonly property bool feedLoading: feedService ? feedService.loading === true : false
  readonly property bool feedStale: feedService ? feedService.stale === true : false

  function statusLabel() {
    if (!feedService) return "UNAVAILABLE"
    if (feedLoading && !feedService.snapshot) return "LOADING"
    if (feedStale) return "STALE"
    if (feedService.demoMode) return "DEMO"
    var state = feedService.snapshot ? String(feedService.snapshot.sourceState || "") : ""
    if (state === "live") return "LIVE"
    if (state === "scheduled") return "SCHEDULED"
    if (state === "final") return "FINAL"
    return state ? state.toUpperCase() : "CONNECTING"
  }

  function barLabel() {
    var label = statusLabel()
    if (feedService && feedService.favoriteSpotlightActive)
      label += " · ★ " + feedService.favoriteBarLabel()
    else if (feedService && feedService.hasMatchup)
      label += " · " + feedService.matchupBarLabel()
    else if (feedService && feedService.favoriteCount > 0)
      label += " · ★" + feedService.favoriteCount
    return label
  }

  function tooltip() {
    var status = feedService && feedService.favoriteSpotlightActive
      ? "Favorite-player play"
      : (feedStale ? "Stale fantasy feed" : (feedLoading ? "Refreshing fantasy feed" : "Fantasy feed"))
    if (feedService && feedService.hasMatchup && feedService.league) {
      var league = feedService.league
      status += "\n" + String(league.name || "") + " · week " + String(league.week || "")
        + " · " + String(league.me ? league.me.name : "me") + " vs "
        + String(league.opponent ? league.opponent.name : "?")
      if (feedService.liveMatchupFresh && feedService.liveMatchup) {
        var live = feedService.liveMatchup
        status += "\nESPN: " + Number(live.me.points).toFixed(1) + " – "
          + Number(live.opponent.points).toFixed(1)
          + " · projected " + Number(live.me.projected).toFixed(1) + " – "
          + Number(live.opponent.projected).toFixed(1)
        if (live.winProbability !== null && live.winProbability !== undefined)
          status += " · win " + Math.round(Number(live.winProbability) * 100) + "%"
      }
    }
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
      var glyph = root.feedLoading ? "󰦖" : "🏈"
      if (root.vertical) return glyph
      return glyph + "  " + root.barLabel()
    }
    fontSize: Style.font.body
    active: root.feedStale || (root.feedService && root.feedService.favoriteSpotlightActive)
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
