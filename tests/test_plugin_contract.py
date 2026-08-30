from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PluginManifestTests(unittest.TestCase):
    def test_manifest_declares_existing_service_and_widget_entry_points(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(1, manifest["schemaVersion"])
        self.assertEqual("tdh.fantasy-feed", manifest["id"])
        self.assertEqual({"service", "bar-widget", "panel"}, set(manifest["kinds"]))
        self.assertTrue(manifest["keepLoaded"])
        self.assertFalse(manifest["barWidget"]["allowMultiple"])
        for entry_point in manifest["entryPoints"].values():
            self.assertTrue((ROOT / entry_point).is_file())


class ServiceBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "Service.qml").read_text(encoding="utf-8")

    def test_service_owns_exactly_one_process_and_uses_argv(self):
        self.assertEqual(1, len(re.findall(r"(?m)^  Process \{", self.source)))
        self.assertIn('return ["python3", script, "--once"]', self.source)
        self.assertNotIn("execDetached", self.source)
        self.assertNotRegex(self.source, r'\["(?:ba)?sh",\s*"-[cl]"')

    def test_service_waits_for_injected_manifest(self):
        self.assertIn("onManifestChanged: initializeFromManifest()", self.source)
        self.assertNotIn("Component.onCompleted: refresh", self.source)

    def test_service_exposes_polling_and_ipc_contract(self):
        for property_name in (
            "snapshot",
            "games",
            "events",
            "visibleEvents",
            "latestVisibleEvent",
            "latestEvent",
            "loading",
            "stale",
            "lastError",
            "lastUpdated",
            "nextPollSeconds",
            "nextPollReason",
            "demoMode",
        ):
            self.assertRegex(self.source, rf"property [^\n]*\b{property_name}\b")
        self.assertIn('target: "tdh.fantasy-feed"', self.source)
        for method_name in ("status", "refresh", "demo", "live"):
            self.assertIn(f"function {method_name}(): string", self.source)
        self.assertIn("readonly property int livePollSeconds: 15", self.source)
        self.assertIn("readonly property int scheduledPollSeconds: 60", self.source)
        self.assertIn("readonly property int kickoffPollSeconds: 30", self.source)
        self.assertIn("readonly property int nearKickoffPollSeconds: 120", self.source)
        self.assertIn("readonly property int distantKickoffPollSeconds: 900", self.source)
        self.assertIn("readonly property var failureBackoffSchedule: [60, 120, 300, 900]", self.source)
        self.assertNotIn("idlePollSeconds", self.source)

    def test_service_uses_game_aware_deadlines_and_failure_backoff(self):
        for method_name in (
            "gameState",
            "secondsUntilDailyCheck",
            "failureDecision",
            "pollDecisionFor",
        ):
            self.assertIn(f"function {method_name}(", self.source)
        for reason in (
            "live game",
            "kickoff within 10 minutes",
            "kickoff within 1 hour",
            "scheduled game more than 1 hour away",
            "all games final; daily 06:00 check",
        ):
            self.assertIn(reason, self.source)
        self.assertIn("_consecutiveFailures += 1", self.source)
        self.assertIn("_consecutiveFailures = 0", self.source)

    def test_service_owns_shared_multi_game_selection(self):
        self.assertIn("property var hiddenGameIds", self.source)
        self.assertIn("readonly property int enabledGameCount", self.source)
        self.assertIn("readonly property var visibleFavoriteEvents", self.source)
        for method_name in ("gameEnabled", "toggleGame", "showAllGames", "hideAllGames"):
            self.assertIn(f"function {method_name}(", self.source)

    def test_refresh_failure_marks_retained_snapshot_stale(self):
        self.assertIn("_refreshFailed = true", self.source)
        self.assertIn(
            "readonly property bool stale: _refreshFailed ||", self.source
        )
        self.assertIn("_refreshFailed = false", self.source)

    def test_service_persists_favorites_without_an_extra_process(self):
        self.assertIn("FileView {", self.source)
        self.assertIn("atomicWrites: true", self.source)
        self.assertIn("fantasy-feed.json", self.source)
        self.assertIn('Quickshell.env("XDG_CONFIG_HOME")', self.source)
        self.assertIn("function toggleFavorite(player)", self.source)
        self.assertIn("readonly property var favoriteEvents", self.source)


class FeedUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bar = (ROOT / "BarWidget.qml").read_text(encoding="utf-8")
        cls.panel = (ROOT / "FeedPanel.qml").read_text(encoding="utf-8")
        cls.standalone = (ROOT / "Standalone.qml").read_text(encoding="utf-8")
        cls.game_selector = (ROOT / "GameSelector.qml").read_text(encoding="utf-8")

    def test_bar_forwards_the_complete_popout_shape(self):
        self.assertIn('source: Qt.resolvedUrl("FeedPanel.qml")', self.bar)
        self.assertRegex(self.bar, r"readonly property bool opened\b")
        self.assertRegex(self.bar, r"readonly property bool popoutSwitchClosing\b")
        for method_name in ("open", "close", "toggle", "closeForPopoutSwitch"):
            self.assertRegex(self.bar, rf"function {method_name}\(\)")

    def test_bar_uses_only_the_shared_service_and_adapts_to_orientation(self):
        self.assertIn('bar.shell.serviceFor("tdh.fantasy-feed")', self.bar)
        self.assertNotIn("firstPartyServiceFor", self.bar)
        self.assertIn("if (root.vertical) return glyph", self.bar)
        self.assertIn("function barLabel()", self.bar)
        self.assertIn('label += " · ★" + feedService.favoriteCount', self.bar)
        self.assertIn("buttonCode === Qt.MiddleButton", self.bar)
        self.assertIn("root.feedService.refresh()", self.bar)
        self.assertNotRegex(self.bar, r"(?m)^\s*(Process|Timer)\s*\{")

    def test_all_surfaces_use_football_branding(self):
        for source in (self.bar, self.panel, self.standalone):
            self.assertIn("🏈", source)
            self.assertNotIn("󰇎", source)

    def test_panel_is_a_presentation_only_keyboard_panel(self):
        self.assertRegex(self.panel, r"(?m)^Panel \{")
        self.assertIn("manageIpc: false", self.panel)
        self.assertIn("KeyboardPanel {", self.panel)
        self.assertIn("PanelKeyCatcher {", self.panel)
        self.assertIn("ListView {", self.panel)
        self.assertIn('bar.shell.serviceFor("tdh.fantasy-feed")', self.panel)
        self.assertNotRegex(self.panel, r"(?m)^\s*(Process|Timer)\s*\{")
        self.assertNotIn("Quickshell.Io", self.panel)

    def test_panel_renders_the_normalized_scoring_contract(self):
        for field in (
            "away",
            "home",
            "quarter",
            "clock",
            "rawText",
            "lifecycle",
            "participants",
            "stats",
            "points.ppr",
            "points.standard",
        ):
            self.assertIn(field, self.panel)
        self.assertIn("serviceEvents.length - 1", self.panel)
        self.assertNotIn("boxscore", self.panel.lower())
        self.assertNotIn("drives", self.panel.lower())
        self.assertIn("stats.length === undefined", self.panel)
        self.assertNotIn("FANTASY IMPACT · POINTS FROM THIS PLAY", self.panel)
        self.assertIn("eventCard.fantasyEvent.participants.length !== undefined", self.panel)
        self.assertNotIn("Array.isArray(eventCard.fantasyEvent.participants)", self.panel)

    def test_game_selector_is_shared_clickable_and_presentation_only(self):
        self.assertIn("GameSelector {", self.panel)
        self.assertIn("GameSelector {", self.standalone)
        self.assertIn("service.toggleGame(modelData.id)", self.game_selector)
        self.assertIn("service.hideAllGames()", self.game_selector)
        self.assertIn("service.showAllGames()", self.game_selector)
        self.assertNotRegex(self.game_selector, r"(?m)^\s*(Process|Timer)\s*\{")

    def test_panel_exposes_required_states_controls_and_keys(self):
        for text in (
            "Feed service unavailable",
            "Loading NFL plays",
            "Could not load the feed",
            "No fantasy plays yet",
            "STALE",
            "DEMO",
            "LIVE",
            'text === "r"',
            'text === "d"',
            "onTabRequested",
            "onCloseRequested",
            "onMoveRequested",
            "Open standalone window",
            "root.popOut()",
        ):
            self.assertIn(text, self.panel)

    def test_compact_participant_rows_have_concrete_responsive_heights(self):
        self.assertRegex(
            self.panel,
            r"(?s)id: participantRow.*?height: Math\.max\(participantSummary\.implicitHeight, pointLine\.implicitHeight\).*?id: participantSummary.*?wrapMode: Text\.WordWrap",
        )

    def test_feed_cards_are_dense_without_truncating_play_context(self):
        for source in (self.panel, self.standalone):
            self.assertIn("height: eventColumn.implicitHeight + Style.space(12)", source)
            self.assertIn("anchors.margins: Style.space(6)", source)
            self.assertIn("spacing: Style.space(3)", source)
            self.assertNotIn("FANTASY IMPACT · POINTS FROM THIS PLAY", source)
        self.assertNotIn("maximumLineCount: 3", self.panel)
        self.assertIn('+ " · " + root.statLabels(participantRow.participant.stats)', self.panel)
        self.assertIn('+ " · " + root.statLabels(participantRow.participant.stats)', self.standalone)

    def test_points_use_positive_negative_and_neutral_colors(self):
        self.assertIn('readonly property color positivePoints: "#6fcf79"', self.panel)
        self.assertIn('readonly property color negativePoints: "#ff6b6b"', self.panel)
        self.assertIn("function pointsColor(value)", self.panel)
        self.assertIn("color: root.pointsColor(participantRow.points.ppr)", self.panel)
        self.assertIn("color: root.pointsColor(participantRow.points.standard)", self.panel)

    def test_panel_exposes_automatic_refresh_countdown(self):
        self.assertIn("function autoRefreshLabel()", self.panel)
        self.assertIn("function countdownLabel(seconds)", self.panel)
        self.assertIn("function countdownLabel(seconds)", self.standalone)
        self.assertIn("AUTO REFRESH", self.panel)

    def test_standalone_window_has_feed_leaderboard_and_favorites(self):
        self.assertIn("FloatingWindow {", self.standalone)
        self.assertIn('title: "Fantasy Feed"', self.standalone)
        self.assertIn('property string scoringMode: "ppr"', self.standalone)
        self.assertIn('["ALL", "QB", "RB", "WR", "TE"]', self.standalone)
        self.assertIn("service.visibleFavoriteEvents", self.standalone)
        self.assertNotIn("FANTASY IMPACT · POINTS FROM THIS PLAY", self.standalone)
        self.assertNotIn("Array.isArray(eventCard.eventData.participants)", self.standalone)
        self.assertIn("service.toggleFavorite(player)", self.standalone)
        self.assertIn('placeholderText: "Search player or team…  /"', self.standalone)
        self.assertIn("searchable.indexOf(playerSearch)", self.standalone)
        self.assertIn("Qt.Key_Slash", self.standalone)
        self.assertIn('return scoringMode === "ppr" ? "PPR" : "STD"', self.standalone)
        self.assertIn('root.signedPoints(leaderRow.selectedPoints) + " " + root.scoringLabel()', self.standalone)
        self.assertIn("stats.length === undefined", self.standalone)
        self.assertNotRegex(self.standalone, r"(?m)^\s*(Process|Timer)\s*\{")


if __name__ == "__main__":
    unittest.main()
