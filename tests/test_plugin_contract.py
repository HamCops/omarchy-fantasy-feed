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
        self.assertEqual({"service", "bar-widget"}, set(manifest["kinds"]))
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
            "events",
            "latestEvent",
            "loading",
            "stale",
            "lastError",
            "lastUpdated",
            "nextPollSeconds",
            "demoMode",
        ):
            self.assertRegex(self.source, rf"property [^\n]*\b{property_name}\b")
        self.assertIn('target: "tdh.fantasy-feed"', self.source)
        for method_name in ("status", "refresh", "demo", "live"):
            self.assertIn(f"function {method_name}(): string", self.source)
        self.assertIn("readonly property int livePollSeconds: 30", self.source)
        self.assertIn("readonly property int scheduledPollSeconds: 60", self.source)
        self.assertIn("readonly property int idlePollSeconds: 300", self.source)

    def test_refresh_failure_marks_retained_snapshot_stale(self):
        self.assertIn("_refreshFailed = true", self.source)
        self.assertIn(
            "readonly property bool stale: _refreshFailed ||", self.source
        )
        self.assertIn("_refreshFailed = false", self.source)


if __name__ == "__main__":
    unittest.main()
