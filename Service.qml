import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: root

  // Both properties are injected by omarchy-shell after this object is made.
  property var manifest: null
  property var shell: null

  property var snapshot: null
  readonly property var games: snapshot && Array.isArray(snapshot.games) ? snapshot.games : []
  readonly property var events: snapshot && Array.isArray(snapshot.events) ? snapshot.events : []
  readonly property var latestEvent: events.length > 0 ? events[events.length - 1] : null
  readonly property var leaderboard: snapshot && Array.isArray(snapshot.leaderboard) ? snapshot.leaderboard : []
  readonly property var week: snapshot && snapshot.week ? snapshot.week : null
  property var hiddenGameIds: []
  readonly property int enabledGameCount: {
    var count = 0
    var hidden = hiddenGameIds
    for (var index = 0; index < games.length; index++) {
      if (hidden.indexOf(String(games[index].id || "")) === -1) count += 1
    }
    return count
  }
  readonly property var visibleEvents: {
    var filtered = []
    var hidden = hiddenGameIds
    for (var index = 0; index < events.length; index++) {
      var event = events[index]
      if (hidden.indexOf(String(event.gameId || "")) === -1) filtered.push(event)
    }
    return filtered
  }
  readonly property var latestVisibleEvent: visibleEvents.length > 0
    ? visibleEvents[visibleEvents.length - 1] : null
  property var favorites: []
  readonly property int favoriteCount: favorites.length
  readonly property var favoriteEvents: {
    var filtered = []
    var sourceEvents = events
    for (var eventIndex = 0; eventIndex < sourceEvents.length; eventIndex++) {
      var event = sourceEvents[eventIndex]
      var participants = event && event.participants
        && event.participants.length !== undefined ? event.participants : []
      for (var participantIndex = 0; participantIndex < participants.length; participantIndex++) {
        if (isFavorite(participants[participantIndex].playerId)) {
          filtered.push(event)
          break
        }
      }
    }
    return filtered
  }
  readonly property var visibleFavoriteEvents: {
    var filtered = []
    var hidden = hiddenGameIds
    for (var index = 0; index < favoriteEvents.length; index++) {
      var event = favoriteEvents[index]
      if (hidden.indexOf(String(event.gameId || "")) === -1) filtered.push(event)
    }
    return filtered
  }
  property bool loading: false
  property bool _refreshFailed: false
  readonly property bool stale: _refreshFailed || (snapshot ? snapshot.stale === true : false)
  property string lastError: ""
  property string lastUpdated: ""
  property int nextPollSeconds: 0
  property string nextPollReason: ""
  property bool demoMode: false

  property string _sourceDir: ""
  property string _stdout: ""
  property string _stderr: ""
  property bool _runDemoMode: false
  property bool _timedOut: false
  property bool _refreshAfterExit: false
  property bool _favoritesLoaded: false
  property int _consecutiveFailures: 0

  readonly property string configHome: String(Quickshell.env("XDG_CONFIG_HOME") || "").startsWith("/")
    ? Quickshell.env("XDG_CONFIG_HOME") : Quickshell.env("HOME") + "/.config"
  readonly property string favoritesPath: configHome + "/omarchy/fantasy-feed.json"

  readonly property int livePollSeconds: 15
  readonly property int scheduledPollSeconds: 60
  readonly property int kickoffPollSeconds: 30
  readonly property int nearKickoffPollSeconds: 120
  readonly property int distantKickoffPollSeconds: 900
  readonly property var failureBackoffSchedule: [60, 120, 300, 900]
  readonly property int dailyCheckHour: 6
  readonly property int watchdogMilliseconds: 18000

  function compactError(value) {
    var text = String(value || "").replace(/\s+/g, " ").trim()
    return text.length > 240 ? text.substring(0, 237) + "…" : text
  }

  function sourceDirectory() {
    if (!manifest || manifest.__sourceDir === undefined || manifest.__sourceDir === null)
      return ""
    return String(manifest.__sourceDir).replace(/\/+$/, "")
  }

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value)
  }

  function isObjectArray(value) {
    if (!Array.isArray(value)) return false
    for (var index = 0; index < value.length; index++) {
      if (!isObject(value[index])) return false
    }
    return true
  }

  function validateSnapshot(value) {
    if (!isObject(value) || value.schemaVersion !== 1) return false
    if (typeof value.observedAt !== "string" || value.observedAt === "") return false
    if (typeof value.sourceState !== "string") return false
    if (["live", "scheduled", "final", "idle", "offline", "malformed"].indexOf(value.sourceState) === -1)
      return false
    if (typeof value.stale !== "boolean") return false
    return isObjectArray(value.games)
      && isObjectArray(value.events)
      && (!value.leaderboard || isObjectArray(value.leaderboard))
      && isObjectArray(value.skipped)
      && isObjectArray(value.errors)
  }

  function snapshotError(value) {
    if (!value || !Array.isArray(value.errors) || value.errors.length === 0) return ""
    var error = value.errors[0]
    if (!isObject(error)) return ""
    return compactError(error.message || error.code || "")
  }

  function isFavorite(playerId) {
    var id = String(playerId || "")
    if (id === "") return false
    for (var index = 0; index < favorites.length; index++) {
      if (String(favorites[index].playerId || "") === id) return true
    }
    return false
  }

  function gameEnabled(gameId) {
    var id = String(gameId || "")
    return id !== "" && hiddenGameIds.indexOf(id) === -1
  }

  function toggleGame(gameId) {
    var id = String(gameId || "")
    if (id === "") return false
    var next = hiddenGameIds.slice()
    var index = next.indexOf(id)
    if (index === -1) next.push(id)
    else next.splice(index, 1)
    hiddenGameIds = next
    return index !== -1
  }

  function showAllGames() {
    hiddenGameIds = []
  }

  function hideAllGames() {
    var hidden = []
    for (var index = 0; index < games.length; index++) {
      var id = String(games[index].id || "")
      if (id !== "" && hidden.indexOf(id) === -1) hidden.push(id)
    }
    hiddenGameIds = hidden
  }

  function toggleFavorite(player) {
    if (!player || typeof player !== "object") return false
    var playerId = String(player.playerId || "")
    if (playerId === "") return false
    var next = []
    var removed = false
    for (var index = 0; index < favorites.length; index++) {
      if (String(favorites[index].playerId || "") === playerId) removed = true
      else next.push(favorites[index])
    }
    if (!removed) {
      next.push({
        playerId: playerId,
        displayName: String(player.displayName || "Unknown player"),
        team: String(player.team || ""),
        position: String(player.position || "")
      })
    }
    next.sort(function(left, right) {
      return String(left.displayName).localeCompare(String(right.displayName))
    })
    favorites = next
    if (_favoritesLoaded) favoritesSaveTimer.restart()
    return !removed
  }

  function loadFavorites(raw) {
    if (_favoritesLoaded) return
    var loaded = []
    try {
      var parsed = raw ? JSON.parse(String(raw)) : null
      var values = parsed && parsed.version === 1 && Array.isArray(parsed.favorites)
        ? parsed.favorites : []
      var seen = ({})
      for (var index = 0; index < values.length; index++) {
        var item = values[index]
        if (!item || typeof item !== "object") continue
        var playerId = String(item.playerId || "")
        if (playerId === "" || seen[playerId]) continue
        seen[playerId] = true
        loaded.push({
          playerId: playerId,
          displayName: String(item.displayName || "Unknown player"),
          team: String(item.team || ""),
          position: String(item.position || "")
        })
      }
    } catch (error) {
      console.warn("fantasy-feed: favorites parse failed:", error)
    }
    favorites = loaded
    _favoritesLoaded = true
  }

  function saveFavorites() {
    favoritesFile.setText(JSON.stringify({version: 1, favorites: favorites}, null, 2) + "\n")
  }

  function gameState(game) {
    return String(game && (game.state || game.status) ? (game.state || game.status) : "")
      .toLowerCase()
  }

  function secondsUntilDailyCheck(nowMilliseconds) {
    var now = new Date(nowMilliseconds)
    var next = new Date(
      now.getFullYear(), now.getMonth(), now.getDate(), dailyCheckHour, 0, 0, 0)
    if (next.getTime() <= now.getTime()) next.setDate(next.getDate() + 1)
    return Math.max(60, Math.ceil((next.getTime() - now.getTime()) / 1000))
  }

  function failureDecision() {
    var index = Math.max(0,
      Math.min(_consecutiveFailures - 1, failureBackoffSchedule.length - 1))
    return {
      seconds: failureBackoffSchedule[index],
      reason: "retry backoff " + (index + 1) + "/" + failureBackoffSchedule.length
    }
  }

  function pollDecisionFor(value, failed, nowMilliseconds) {
    if (failed) return failureDecision()

    var now = Number(nowMilliseconds)
    if (!isFinite(now) || now <= 0) now = Date.now()
    var gameValues = value && Array.isArray(value.games) ? value.games : []
    var hasLiveGame = false
    var scheduledWithoutTime = false
    var earliestStart = Number.POSITIVE_INFINITY

    for (var index = 0; index < gameValues.length; index++) {
      var game = gameValues[index]
      var state = gameState(game)
      if (state === "live") {
        hasLiveGame = true
        continue
      }
      if (state !== "scheduled") continue
      var start = Date.parse(String(game.startTime || ""))
      if (isFinite(start)) earliestStart = Math.min(earliestStart, start)
      else scheduledWithoutTime = true
    }

    if (hasLiveGame)
      return {seconds: livePollSeconds, reason: "live game"}

    if (isFinite(earliestStart)) {
      var untilKickoff = Math.max(0, Math.ceil((earliestStart - now) / 1000))
      if (untilKickoff <= 10 * 60)
        return {seconds: kickoffPollSeconds, reason: "kickoff within 10 minutes"}
      if (untilKickoff <= 60 * 60)
        return {seconds: nearKickoffPollSeconds, reason: "kickoff within 1 hour"}
      return {
        seconds: distantKickoffPollSeconds,
        reason: "scheduled game more than 1 hour away"
      }
    }

    var sourceState = value ? String(value.sourceState || "") : ""
    if (scheduledWithoutTime || sourceState === "scheduled")
      return {seconds: scheduledPollSeconds, reason: "scheduled game time unavailable"}
    if (sourceState === "live")
      return {seconds: livePollSeconds, reason: "live source fallback"}

    return {
      seconds: secondsUntilDailyCheck(now),
      reason: "all games final; daily 06:00 check"
    }
  }

  function schedulePoll(seconds, reason) {
    pollTimer.stop()
    countdownTimer.stop()
    nextPollSeconds = Math.max(1, Number(seconds) || scheduledPollSeconds)
    nextPollReason = String(reason || "scheduled refresh")
    pollTimer.interval = nextPollSeconds * 1000
    pollTimer.start()
    countdownTimer.start()
  }

  function finishFailure(message) {
    loading = false
    _refreshFailed = true
    _consecutiveFailures += 1
    lastError = compactError(message) || "Fantasy feed refresh failed"
    var decision = pollDecisionFor(snapshot, true)
    schedulePoll(decision.seconds, decision.reason)
  }

  function applyOutput(exitCode, output, errorOutput) {
    if (exitCode !== 0 && exitCode !== 10) {
      finishFailure(errorOutput || ("Fantasy feed helper exited " + exitCode))
      return
    }

    var value = null
    try {
      value = JSON.parse(String(output || ""))
    } catch (error) {
      finishFailure("Fantasy feed returned invalid JSON")
      return
    }
    if (!validateSnapshot(value)) {
      finishFailure("Fantasy feed returned an unsupported snapshot")
      return
    }

    snapshot = value
    loading = false
    lastUpdated = value.observedAt
    if (exitCode === 10) {
      _refreshFailed = true
      _consecutiveFailures += 1
      lastError = snapshotError(value) || "Live data unavailable; showing cached feed"
    } else {
      _refreshFailed = false
      _consecutiveFailures = 0
      lastError = ""
    }
    var decision = pollDecisionFor(value, exitCode === 10)
    schedulePoll(decision.seconds, decision.reason)
  }

  function helperCommand() {
    var script = _sourceDir + "/scripts/feed.py"
    if (_runDemoMode)
      return ["python3", script, "--fixture", _sourceDir + "/fixtures/replays/demo.json"]
    return ["python3", script, "--once"]
  }

  function refresh() {
    if (_sourceDir === "") return "not ready"
    if (feedProcess.running) return "already refreshing"

    pollTimer.stop()
    countdownTimer.stop()
    nextPollSeconds = 0
    nextPollReason = ""
    _stdout = ""
    _stderr = ""
    _timedOut = false
    _runDemoMode = demoMode
    loading = true
    feedProcess.command = helperCommand()
    feedProcess.running = true
    watchdog.start()
    return _runDemoMode ? "refreshing demo feed" : "refreshing live feed"
  }

  function selectMode(useDemo) {
    demoMode = useDemo
    if (feedProcess.running) {
      _refreshAfterExit = true
      return useDemo ? "demo mode queued" : "live mode queued"
    }
    return refresh()
  }

  function initializeFromManifest() {
    var directory = sourceDirectory()
    if (directory === "" || directory === _sourceDir) return
    _sourceDir = directory
    Qt.callLater(function() { root.refresh() })
  }

  onManifestChanged: initializeFromManifest()

  Timer {
    id: pollTimer
    repeat: false
    onTriggered: root.refresh()
  }

  Timer {
    id: countdownTimer
    interval: 1000
    repeat: true
    onTriggered: {
      if (root.nextPollSeconds > 0) root.nextPollSeconds -= 1
      if (root.nextPollSeconds <= 0) stop()
    }
  }

  Timer {
    id: watchdog
    interval: root.watchdogMilliseconds
    repeat: false
    onTriggered: {
      if (!feedProcess.running) return
      root._timedOut = true
      feedProcess.running = false
      root.finishFailure("Fantasy feed refresh timed out")
    }
  }

  Timer {
    id: favoritesSaveTimer
    interval: 200
    repeat: false
    onTriggered: root.saveFavorites()
  }

  FileView {
    id: favoritesFile
    path: root.favoritesPath
    watchChanges: false
    atomicWrites: true
    printErrors: false
    onLoaded: root.loadFavorites(text())
    onLoadFailed: root.loadFavorites("")
  }

  Process {
    id: feedProcess
    running: false
    command: []
    stdout: StdioCollector {
      id: feedStdout
      waitForEnd: true
      onStreamFinished: root._stdout = text
    }
    stderr: StdioCollector {
      id: feedStderr
      waitForEnd: true
      onStreamFinished: root._stderr = text
    }
    onExited: function(exitCode) {
      watchdog.stop()

      if (root._timedOut) {
        root._timedOut = false
      } else if (root._runDemoMode !== root.demoMode) {
        root.loading = false
      } else {
        var output = String(feedStdout.text || root._stdout || "")
        var errorOutput = String(feedStderr.text || root._stderr || "")
        root.applyOutput(exitCode, output, errorOutput)
      }

      if (root._refreshAfterExit || root._runDemoMode !== root.demoMode) {
        root._refreshAfterExit = false
        Qt.callLater(function() { root.refresh() })
      }
    }
  }

  Component.onDestruction: {
    pollTimer.stop()
    countdownTimer.stop()
    watchdog.stop()
    favoritesSaveTimer.stop()
    if (feedProcess.running) feedProcess.running = false
  }

  IpcHandler {
    target: "tdh.fantasy-feed"

    function status(): string {
      return JSON.stringify({
        mode: root.demoMode ? "demo" : "live",
        loading: root.loading,
        stale: root.stale,
        sourceState: root.snapshot ? root.snapshot.sourceState : "unavailable",
        eventCount: root.events.length,
        visibleEventCount: root.visibleEvents.length,
        gameCount: root.games.length,
        enabledGameCount: root.enabledGameCount,
        leaderboardCount: root.leaderboard.length,
        favoriteCount: root.favoriteCount,
        lastUpdated: root.lastUpdated,
        lastError: root.lastError,
        nextPollSeconds: root.nextPollSeconds,
        nextPollReason: root.nextPollReason,
        consecutiveFailures: root._consecutiveFailures
      })
    }

    function refresh(): string {
      return root.refresh()
    }

    function demo(): string {
      return root.selectMode(true)
    }

    function live(): string {
      return root.selectMode(false)
    }
  }
}
