"""The AI agent can read every part of the station: each tool runs and the snapshot covers all."""
import json
import logging
import unittest

import app.main  # noqa: F401  (installs the log buffer like the running station)
from app.services import agent_service as a


class AgentToolsTests(unittest.TestCase):
    def test_every_declared_tool_exists_and_the_read_tools_run(self):
        names = {d["name"] for d in a.DECLARATIONS}
        self.assertEqual(names, set(a.TOOLS))
        self.assertEqual(set(a.TOOL_LABELS), set(a.TOOLS))
        for name in ("get_full_snapshot", "get_stage_calibration", "get_stage_errors", "get_scan_progress",
                     "get_camera", "get_motion", "get_access", "get_recent_events", "get_settings"):
            with self.subTest(tool=name):
                out = a.run_tool(name, {})
                self.assertNotIn("error", out if isinstance(out, dict) else {}, out)
                json.dumps(out, ensure_ascii=False, default=str)

    def test_snapshot_covers_the_whole_station_compactly(self):
        snap = a.get_full_snapshot()
        for part in ("station", "scan", "motion", "camera", "access", "stage_calibration", "stage_errors",
                     "statistics", "hardware", "settings", "recent_warnings"):
            self.assertIn(part, snap)
            self.assertFalse(isinstance(snap[part], dict) and "error" in snap[part], (part, snap[part]))
        self.assertLess(len(json.dumps(snap, ensure_ascii=False, default=str)), 40000)  # fits a model turn

    def test_settings_are_explained_and_cover_every_setting(self):
        from app.routers.system import get_settings as raw_settings

        explained = a.get_settings()
        covered = {k for group in explained.values() for k in group}
        hidden = {"cors_origins", "host", "port", "model_search_dirs"}
        self.assertEqual(covered, set(raw_settings()) - hidden)
        self.assertIn("meaning", explained["สเตจ XY"]["stage_approach_mm"])
        self.assertNotIn("อื่นๆ", explained, "a new setting needs a line in SETTINGS_GLOSSARY")
        self.assertNotIn("operator_passcode", json.dumps(explained))

    def test_recent_events_see_station_logs(self):
        logging.getLogger("app.services.test_probe").warning("probe warning for the agent")
        events = a.get_recent_events("WARNING", 50)["events"]
        self.assertTrue(any("probe warning" in e["message"] for e in events))


if __name__ == "__main__":
    unittest.main()
