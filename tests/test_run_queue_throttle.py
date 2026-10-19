import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_queue.ps1"
SELECTOR_PROMPT = ROOT / "scripts" / "queue_select_prompt.md"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(POWERSHELL, "PowerShell is required")
class RunQueueThrottleTests(unittest.TestCase):
    NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        for name in ("share", "drive", "logs", "scripts"):
            (self.base / name).mkdir()
        (self.base / "drive" / "CONTEXT.md").write_text("context", encoding="utf-8")
        (self.base / "drive" / "PROGRESS.md").write_text("progress", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    @property
    def empty_file(self):
        return self.base / "logs" / "queue_empty_at.txt"

    @property
    def wake_file(self):
        return self.base / "scripts" / "WAKE_RUN_QUEUE"

    def set_previous_empty(self, when):
        self.empty_file.write_text(when.isoformat(), encoding="utf-8")

    def run_queue(self, selections):
        encoded = [json.dumps(item, ensure_ascii=False) for item in selections]
        command = [
            POWERSHELL,
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-DryRun",
            "-TestHarnessRoot",
            str(self.base),
            "-TestNow",
            self.NOW.isoformat(),
        ]
        for selection in encoded:
            command.extend(["-TestSelections", selection])
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        logs = sorted((self.base / "logs").glob("queue_*.log"))
        self.assertTrue(logs)
        return logs[-1].read_text(encoding="utf-8-sig")

    def test_non_empty_or_initial_previous_outcome_invokes_selector(self):
        log = self.run_queue([{"status": "empty"}])
        self.assertIn("queue empty: done", log)

    def test_recent_empty_without_trigger_skips_and_logs(self):
        previous = self.NOW - timedelta(minutes=30)
        self.set_previous_empty(previous)
        log = self.run_queue([])
        self.assertIn("skip: queue was empty at", log)
        self.assertEqual(self.empty_file.read_text(encoding="utf-8").strip(), previous.isoformat())

    def test_new_instruction_invokes_selector(self):
        previous = self.NOW - timedelta(minutes=30)
        self.set_previous_empty(previous)
        instruction = self.base / "share" / "指示_new.md"
        instruction.write_text("new", encoding="utf-8")
        newer = self.NOW - timedelta(minutes=1)
        os.utime(instruction, (newer.timestamp(), newer.timestamp()))
        log = self.run_queue([{"status": "empty"}])
        self.assertIn("queue empty: done", log)
        self.assertNotIn("skip: queue was empty", log)

    def test_wake_invokes_selector_then_is_emptied_but_kept(self):
        previous = self.NOW - timedelta(minutes=30)
        self.set_previous_empty(previous)
        self.wake_file.write_text("wake", encoding="utf-8")
        log = self.run_queue([{"status": "empty"}])
        self.assertIn("queue empty: done", log)
        self.assertTrue(self.wake_file.exists())
        self.assertEqual(self.wake_file.read_text(encoding="utf-8").strip(), "")

    def test_three_hours_elapsed_invokes_selector(self):
        self.set_previous_empty(self.NOW - timedelta(hours=3))
        log = self.run_queue([{"status": "empty"}])
        self.assertIn("queue empty: done", log)
        self.assertNotIn("skip: queue was empty", log)

    def test_empty_writes_timestamp_and_other_outcome_clears_it(self):
        self.run_queue([{"status": "empty"}])
        self.assertEqual(
            datetime.fromisoformat(self.empty_file.read_text(encoding="utf-8").strip()),
            self.NOW,
        )

        instruction = self.base / "share" / "指示_after_empty.md"
        instruction.write_text("new", encoding="utf-8")
        newer = self.NOW + timedelta(minutes=1)
        os.utime(instruction, (newer.timestamp(), newer.timestamp()))
        log = self.run_queue([{"status": "error", "error": "test failure"}])
        self.assertIn("selector status/error: error test failure", log)
        self.assertEqual(self.empty_file.read_text(encoding="utf-8").strip(), "")

    def test_low_reasoning_is_added_only_for_selector(self):
        source = SCRIPT.read_text(encoding="utf-8")
        setting = 'model_reasoning_effort="low"'
        self.assertEqual(source.count(setting), 1)
        self.assertIn(
            "if ($Kind -eq 'selector') { $arguments += @('-c', "
            f"'{setting}') }}",
            source,
        )
        self.assertIn("Invoke-Codex $prompt 'worker'", source)

    def test_current_location_is_fetched_only_for_item(self):
        prompt = SELECTOR_PROMPT.read_text(encoding="utf-8")
        step6 = next(line for line in prompt.splitlines() if line.startswith("6. "))
        self.assertIn("status=`item`", step6)
        self.assertIn("status=`empty`・`error`", step6)
        self.assertIn("現在地をfetchせず", step6)
        self.assertIn("current_tail10・decision_logは空文字", step6)


if __name__ == "__main__":
    unittest.main()
