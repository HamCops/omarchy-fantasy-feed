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
  readonly property var snapshotEvents: snapshot && Array.isArray(snapshot.events) ? snapshot.events : []
  property var presentedEvents: []
  readonly property var events: presentedEvents
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
  property string scoringMode: "ppr"
  property string alertPreset: "off"
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
  property string providerBaseUrl: ""
  readonly property bool simulatorMode: providerBaseUrl !== ""

  property string _sourceDir: ""
  property string _stdout: ""
  property string _stderr: ""
  property bool _runDemoMode: false
  property string _runProviderBaseUrl: ""
  property bool _resetSimulatorCache: false
  property bool _runResetSimulatorCache: false
  property bool _timedOut: false
  property bool _refreshAfterExit: false
  property bool _favoritesLoaded: false
  property int _consecutiveFailures: 0
  property string _presentationContext: ""
  property var _arrivalQueue: []
  readonly property int pendingEventCount: _arrivalQueue.length
  property string lastPresentedToken: ""
  property int presentationSequence: 0
  property string favoriteSpotlightToken: ""
  property bool favoriteSpotlightActive: false
  property var favoriteSpotlightEvent: null
  readonly property var favoritePlayerRows: buildFavoritePlayerRows()
  readonly property int favoriteRedZoneGameCount: {
    var count = 0
    for (var index = 0; index < games.length; index++) {
      if (gameHasFavoriteRedZone(games[index])) count += 1
    }
    return count
  }

  readonly property string configHome: String(Quickshell.env("XDG_CONFIG_HOME") || "").startsWith("/")
    ? Quickshell.env("XDG_CONFIG_HOME") : Quickshell.env("HOME") + "/.config"
  readonly property string favoritesPath: configHome + "/omarchy/fantasy-feed.json"
  readonly property string cacheHome: String(Quickshell.env("XDG_CACHE_HOME") || "").startsWith("/")
    ? Quickshell.env("XDG_CACHE_HOME") : Quickshell.env("HOME") + "/.cache"
  readonly property string simulatorCachePath: cacheHome
    + "/fantasy-feed/simulator-snapshot.json"
  readonly property string simulatorBaseUrl: "http://127.0.0.1:8765"

  readonly property int livePollSeconds: 15
  readonly property int simulatorPollSeconds: 1
  readonly property int scheduledPollSeconds: 60
  readonly property int kickoffPollSeconds: 30
  readonly property int nearKickoffPollSeconds: 120
  readonly property int distantKickoffPollSeconds: 900
  readonly property var failureBackoffSchedule: [60, 120, 300, 900]
  readonly property int dailyCheckHour: 6
  readonly property int watchdogMilliseconds: 18000
  readonly property int arrivalIntervalMilliseconds: 600
  readonly property int arrivalCatchupMilliseconds: 300
  readonly property int arrivalUrgentMilliseconds: 160
  readonly property int favoriteHoldMilliseconds: 2600

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

  function isFavoriteTeam(team) {
    var abbreviation = String(team || "")
    if (abbreviation === "") return false
    for (var index = 0; index < favorites.length; index++) {
      if (String(favorites[index].team || "") === abbreviation) return true
    }
    return false
  }

  function gameHasFavoriteRedZone(game) {
    if (!game || game.isRedZone !== true || gameState(game) !== "live") return false
    return isFavoriteTeam(game.possession)
  }

  function favoriteRedZoneNames(game) {
    if (!gameHasFavoriteRedZone(game)) return ""
    var team = String(game.possession || "")
    var names = []
    for (var index = 0; index < favorites.length; index++) {
      var favorite = favorites[index]
      if (String(favorite.team || "") !== team) continue
      names.push(String(favorite.displayName || "Unknown player"))
    }
    return names.join(", ")
  }

  function eventParticipant(event, playerId) {
    var participants = event && event.participants
      && event.participants.length !== undefined ? event.participants : []
    for (var index = 0; index < participants.length; index++) {
      if (String(participants[index].playerId || "") === String(playerId || ""))
        return participants[index]
    }
    return null
  }

  function buildFavoritePlayerRows() {
    var rows = []
    for (var favoriteIndex = 0; favoriteIndex < favorites.length; favoriteIndex++) {
      var favorite = favorites[favoriteIndex]
      var playerId = String(favorite.playerId || "")
      var leader = null
      for (var leaderIndex = 0; leaderIndex < leaderboard.length; leaderIndex++) {
        if (String(leaderboard[leaderIndex].playerId || "") === playerId) {
          leader = leaderboard[leaderIndex]
          break
        }
      }

      var latestEvent = null
      var latestParticipant = null
      for (var eventIndex = events.length - 1; eventIndex >= 0; eventIndex--) {
        latestParticipant = eventParticipant(events[eventIndex], playerId)
        if (!latestParticipant) continue
        latestEvent = events[eventIndex]
        break
      }

      var team = String(leader && leader.team ? leader.team : favorite.team || "")
      var gameIds = leader && leader.gameIds && leader.gameIds.length !== undefined
        ? leader.gameIds : []
      var redZoneGame = null
      for (var gameIndex = 0; gameIndex < games.length; gameIndex++) {
        var game = games[gameIndex]
        if (!gameHasFavoriteRedZone(game) || String(game.possession || "") !== team) continue
        if (gameIds.length > 0 && gameIds.indexOf(String(game.id || "")) === -1) continue
        redZoneGame = game
        break
      }

      rows.push({
        playerId: playerId,
        displayName: String(leader && leader.displayName
          ? leader.displayName : favorite.displayName || "Unknown player"),
        team: team,
        position: String(leader && leader.position ? leader.position : favorite.position || ""),
        points: leader && leader.points ? leader.points : ({ppr: 0, standard: 0}),
        stats: leader && leader.stats ? leader.stats : [],
        gameIds: gameIds,
        latestEvent: latestEvent,
        latestEventToken: latestEvent ? eventToken(latestEvent) : "",
        latestPoints: latestParticipant && latestParticipant.points
          ? latestParticipant.points : ({ppr: 0, standard: 0}),
        spotlight: favoriteSpotlightActive && favoriteSpotlightEvent
          ? eventParticipant(favoriteSpotlightEvent, playerId) !== null : false,
        redZone: redZoneGame !== null,
        redZoneGameId: redZoneGame ? String(redZoneGame.id || "") : "",
        redZoneDetail: redZoneGame ? String(redZoneGame.downDistance || "") : ""
      })
    }
    return rows
  }

  function normalizedScoringMode(value) {
    return String(value || "") === "standard" ? "standard" : "ppr"
  }

  function setScoringMode(value) {
    var next = normalizedScoringMode(value)
    if (scoringMode === next) return next
    scoringMode = next
    if (_favoritesLoaded) favoritesSaveTimer.restart()
    return next
  }

  function toggleScoringMode() {
    return setScoringMode(scoringMode === "ppr" ? "standard" : "ppr")
  }

  function validAlertPreset(value) {
    return ["off", "all", "touchdowns", "threshold3", "threshold6"]
      .indexOf(String(value || "")) !== -1
  }

  function setAlertPreset(value) {
    var next = validAlertPreset(value) ? String(value) : "off"
    if (alertPreset === next) return next
    alertPreset = next
    if (_favoritesLoaded) favoritesSaveTimer.restart()
    return next
  }

  function alertThreshold() {
    if (alertPreset === "threshold3") return 3
    if (alertPreset === "threshold6") return 6
    return 0
  }

  function signedPoints(value) {
    var number = Number(value)
    if (!isFinite(number)) number = 0
    if (Math.abs(number) < 0.005) number = 0
    var formatted = number.toFixed(2).replace(/\.?0+$/, "")
    return (number > 0 ? "+" : "") + formatted
  }

  function shortPlayerName(value) {
    var words = String(value || "Player").trim().split(/\s+/)
    return words.length > 0 ? words[words.length - 1].toUpperCase() : "PLAYER"
  }

  function favoriteParticipants(event) {
    var matches = []
    var participants = event && event.participants
      && event.participants.length !== undefined ? event.participants : []
    for (var index = 0; index < participants.length; index++) {
      if (isFavorite(participants[index].playerId)) matches.push(participants[index])
    }
    return matches
  }

  function favoriteBarLabel() {
    var matches = favoriteParticipants(favoriteSpotlightEvent)
    if (matches.length === 0) return "PLAY"
    var participant = matches[0]
    var points = participant.points ? participant.points[scoringMode] : 0
    var label = shortPlayerName(participant.displayName) + " " + signedPoints(points)
    return matches.length > 1 ? label + " +" + (matches.length - 1) : label
  }

  function eventIsTouchdown(event) {
    if (String(event && event.kind ? event.kind : "").toLowerCase().indexOf("touchdown") !== -1)
      return true
    var participants = event && event.participants
      && event.participants.length !== undefined ? event.participants : []
    for (var participantIndex = 0; participantIndex < participants.length; participantIndex++) {
      var stats = participants[participantIndex] && participants[participantIndex].stats
        && participants[participantIndex].stats.length !== undefined
        ? participants[participantIndex].stats : []
      for (var statIndex = 0; statIndex < stats.length; statIndex++) {
        if (String(stats[statIndex].key || "").toLowerCase().indexOf("touchdown") !== -1)
          return true
      }
    }
    return false
  }

  function shouldNotifyFavoriteEvent(event) {
    if (alertPreset === "off" || !gameEnabled(event ? event.gameId : "")) return false
    var matches = favoriteParticipants(event)
    if (matches.length === 0) return false
    if (alertPreset === "all") return true
    if (alertPreset === "touchdowns") return eventIsTouchdown(event)
    var threshold = alertThreshold()
    for (var index = 0; index < matches.length; index++) {
      var points = matches[index].points ? Number(matches[index].points[scoringMode]) : 0
      if (isFinite(points) && points >= threshold) return true
    }
    return false
  }

  function sendFavoriteNotification(event) {
    if (!shouldNotifyFavoriteEvent(event)) return
    var matches = favoriteParticipants(event)
    var labels = []
    for (var index = 0; index < matches.length && index < 2; index++) {
      var participant = matches[index]
      var points = participant.points ? participant.points[scoringMode] : 0
      labels.push(shortPlayerName(participant.displayName) + " " + signedPoints(points))
    }
    if (matches.length > 2) labels.push("+" + (matches.length - 2) + " more")
    var headline = "★ " + labels.join(" · ") + " "
      + (scoringMode === "ppr" ? "PPR" : "STD")
    var payload = JSON.stringify({
      tab: "favorites",
      playerId: String(matches[0].playerId || ""),
      eventToken: eventToken(event)
    })
    Quickshell.execDetached([
      "omarchy-notification-send",
      "--app-name", "Fantasy Feed",
      "-g", "🏈",
      "-u", "low",
      "-t", "6500",
      headline,
      String(event.rawText || "Favorite-player fantasy play"),
      "--exec", "omarchy-shell", "shell", "summon", "tdh.fantasy-feed", payload
    ])
  }

  function eventToken(event) {
    if (!event || typeof event !== "object") return ""
    var identity = String(event.eventId || (String(event.provider || "") + ":"
      + String(event.gameId || "") + ":" + String(event.playId || "")))
    var revision = String(event.revision || event.sourceRevision || "")
    return identity && revision ? identity + "|" + revision : ""
  }

  function eventIdentity(event) {
    if (!event || typeof event !== "object") return ""
    return String(event.eventId || (String(event.provider || "") + ":"
      + String(event.gameId || "") + ":" + String(event.playId || "")))
  }

  function eventHasFavorite(event) {
    var participants = event && event.participants
      && event.participants.length !== undefined ? event.participants : []
    for (var index = 0; index < participants.length; index++) {
      if (isFavorite(participants[index].playerId)) return true
    }
    return false
  }

  function isSpotlightEvent(event) {
    return favoriteSpotlightActive && eventToken(event) === favoriteSpotlightToken
  }

  function dataModeName() {
    if (demoMode) return "demo"
    if (simulatorMode) return "simulator"
    return "live"
  }

  function presentationContextFor(value) {
    var valueWeek = value && value.week ? value.week : null
    return dataModeName() + ":" + String(valueWeek ? valueWeek.season : "")
      + ":" + String(valueWeek ? valueWeek.seasonType : "")
      + ":" + String(valueWeek ? valueWeek.number : "")
  }

  function eventOrder(left, right) {
    var wallclockOrder = String(left && left.wallclock ? left.wallclock : "")
      .localeCompare(String(right && right.wallclock ? right.wallclock : ""))
    if (wallclockOrder !== 0) return wallclockOrder
    var gameOrder = String(left && left.gameId ? left.gameId : "")
      .localeCompare(String(right && right.gameId ? right.gameId : ""))
    if (gameOrder !== 0) return gameOrder
    var sequenceOrder = Number(left && left.sequence) - Number(right && right.sequence)
    if (isFinite(sequenceOrder) && sequenceOrder !== 0) return sequenceOrder
    return eventIdentity(left).localeCompare(eventIdentity(right))
  }

  function resetPresentation(nextEvents, context) {
    arrivalTimer.stop()
    spotlightTimer.stop()
    _arrivalQueue = []
    _presentationContext = context
    presentedEvents = nextEvents.slice()
    lastPresentedToken = presentedEvents.length > 0
      ? eventToken(presentedEvents[presentedEvents.length - 1]) : ""
    favoriteSpotlightToken = ""
    favoriteSpotlightActive = false
    favoriteSpotlightEvent = null
  }

  function stagePresentation(value) {
    var nextEvents = value && Array.isArray(value.events) ? value.events : []
    var context = presentationContextFor(value)
    if (_presentationContext === "" || _presentationContext !== context) {
      resetPresentation(nextEvents, context)
      return
    }

    var known = ({})
    for (var presentedIndex = 0; presentedIndex < presentedEvents.length; presentedIndex++) {
      var presentedToken = eventToken(presentedEvents[presentedIndex])
      if (presentedToken) known["$" + presentedToken] = true
    }
    for (var queuedIndex = 0; queuedIndex < _arrivalQueue.length; queuedIndex++) {
      var queuedToken = eventToken(_arrivalQueue[queuedIndex])
      if (queuedToken) known["$" + queuedToken] = true
    }

    var queue = _arrivalQueue.slice()
    for (var eventIndex = 0; eventIndex < nextEvents.length; eventIndex++) {
      var event = nextEvents[eventIndex]
      var token = eventToken(event)
      if (!token || known["$" + token]) continue
      var identity = eventIdentity(event)
      var replacedQueuedRevision = false
      for (var queueIndex = 0; queueIndex < queue.length; queueIndex++) {
        if (eventIdentity(queue[queueIndex]) !== identity) continue
        queue[queueIndex] = event
        replacedQueuedRevision = true
        break
      }
      if (!replacedQueuedRevision) queue.push(event)
      known["$" + token] = true
    }
    _arrivalQueue = queue
    if (_arrivalQueue.length > 0 && !arrivalTimer.running) {
      arrivalTimer.interval = Math.min(250, arrivalIntervalMilliseconds)
      arrivalTimer.start()
    }
  }

  function arrivalDelay() {
    if (_arrivalQueue.length > 24) return arrivalUrgentMilliseconds
    if (_arrivalQueue.length > 10) return arrivalCatchupMilliseconds
    return arrivalIntervalMilliseconds
  }

  function revealNextEvent() {
    if (_arrivalQueue.length === 0) return
    var queue = _arrivalQueue.slice()
    var event = queue.shift()
    _arrivalQueue = queue

    var identity = eventIdentity(event)
    var nextPresented = []
    for (var index = 0; index < presentedEvents.length; index++) {
      if (eventIdentity(presentedEvents[index]) !== identity)
        nextPresented.push(presentedEvents[index])
    }
    nextPresented.push(event)
    nextPresented.sort(eventOrder)
    if (nextPresented.length > 200)
      nextPresented = nextPresented.slice(nextPresented.length - 200)
    presentedEvents = nextPresented
    lastPresentedToken = eventToken(event)
    presentationSequence += 1

    var favoriteArrival = eventHasFavorite(event)
    if (favoriteArrival) {
      favoriteSpotlightToken = lastPresentedToken
      favoriteSpotlightActive = true
      favoriteSpotlightEvent = event
      spotlightTimer.restart()
      sendFavoriteNotification(event)
    }
    if (_arrivalQueue.length > 0) {
      arrivalTimer.interval = favoriteArrival
        ? favoriteHoldMilliseconds : arrivalDelay()
      arrivalTimer.start()
    }
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

  function showGame(gameId) {
    var id = String(gameId || "")
    var index = hiddenGameIds.indexOf(id)
    if (id === "" || index === -1) return false
    var next = hiddenGameIds.slice()
    next.splice(index, 1)
    hiddenGameIds = next
    return true
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
      var settings = parsed && parsed.version === 1 && isObject(parsed.settings)
        ? parsed.settings : ({})
      scoringMode = normalizedScoringMode(settings.scoringMode)
      alertPreset = validAlertPreset(settings.alertPreset)
        ? String(settings.alertPreset) : "off"
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
    favoritesFile.setText(JSON.stringify({
      version: 1,
      favorites: favorites,
      settings: {scoringMode: scoringMode, alertPreset: alertPreset}
    }, null, 2) + "\n")
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
    if (simulatorMode)
      return {seconds: simulatorPollSeconds, reason: "ten-game simulator load"}

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

    stagePresentation(value)
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
    if (_runProviderBaseUrl !== "") {
      var command = [
        "python3", script, "--once",
        "--cache", simulatorCachePath,
        "--provider-base-url", _runProviderBaseUrl
      ]
      if (_runResetSimulatorCache) command.push("--reset-cache")
      return command
    }
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
    _runProviderBaseUrl = providerBaseUrl
    _runResetSimulatorCache = _resetSimulatorCache
    _resetSimulatorCache = false
    loading = true
    feedProcess.command = helperCommand()
    feedProcess.running = true
    watchdog.start()
    if (_runDemoMode) return "refreshing demo feed"
    return _runProviderBaseUrl !== ""
      ? "refreshing simulator feed" : "refreshing live feed"
  }

  function selectMode(useDemo) {
    demoMode = useDemo
    providerBaseUrl = ""
    if (feedProcess.running) {
      _refreshAfterExit = true
      return useDemo ? "demo mode queued" : "live mode queued"
    }
    return refresh()
  }

  function selectSimulator() {
    demoMode = false
    providerBaseUrl = simulatorBaseUrl
    _resetSimulatorCache = true
    if (feedProcess.running) {
      _refreshAfterExit = true
      return "simulator mode queued"
    }
    return refresh()
  }

  function modeChangedDuringRun() {
    return _runDemoMode !== demoMode || _runProviderBaseUrl !== providerBaseUrl
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
    id: arrivalTimer
    repeat: false
    onTriggered: root.revealNextEvent()
  }

  Timer {
    id: spotlightTimer
    interval: root.favoriteHoldMilliseconds
    repeat: false
    onTriggered: root.favoriteSpotlightActive = false
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
      } else if (root.modeChangedDuringRun()) {
        root.loading = false
      } else {
        var output = String(feedStdout.text || root._stdout || "")
        var errorOutput = String(feedStderr.text || root._stderr || "")
        root.applyOutput(exitCode, output, errorOutput)
      }

      if (root._refreshAfterExit || root.modeChangedDuringRun()) {
        root._refreshAfterExit = false
        Qt.callLater(function() { root.refresh() })
      }
    }
  }

  Component.onDestruction: {
    pollTimer.stop()
    arrivalTimer.stop()
    spotlightTimer.stop()
    countdownTimer.stop()
    watchdog.stop()
    favoritesSaveTimer.stop()
    if (feedProcess.running) feedProcess.running = false
  }

  IpcHandler {
    target: "tdh.fantasy-feed"

    function status(): string {
      return JSON.stringify({
        mode: root.demoMode ? "demo" : (root.simulatorMode ? "simulator" : "live"),
        loading: root.loading,
        stale: root.stale,
        sourceState: root.snapshot ? root.snapshot.sourceState : "unavailable",
        eventCount: root.events.length,
        providerEventCount: root.snapshotEvents.length,
        pendingEventCount: root.pendingEventCount,
        visibleEventCount: root.visibleEvents.length,
        gameCount: root.games.length,
        enabledGameCount: root.enabledGameCount,
        leaderboardCount: root.leaderboard.length,
        favoriteCount: root.favoriteCount,
        favoriteSpotlightActive: root.favoriteSpotlightActive,
        favoriteRedZoneGameCount: root.favoriteRedZoneGameCount,
        scoringMode: root.scoringMode,
        alertPreset: root.alertPreset,
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

    function simulate(): string {
      return root.selectSimulator()
    }
  }
}
