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
            "-TestOutputs",
            "0|QUEUE_ITEM_COMPLETE",
            "-MaxItems",
            "1",
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
            f"if ($Kind -eq 'selector') {{ '-c'; '{setting}' }}",
            source,
        )
        self.assertIn("Invoke-Codex $prompt 'worker'", source)

    def test_locked_cycle_models_in_dry_run(self):
        cases = [
            ("3fd72941-354b-813e-a9ee-e2e511e7b1e9", "【3-11の後】Codex目視判断の改善ループ", True),
            ("3fd72941354b813ea9eee2e511e7b1e9", "renamed", True),
            ("test-page", "周回3-12 第2周", True),
            ("test-page", "通常の指示", False),
        ]
        for page_id, title, locked in cases:
            with self.subTest(page_id=page_id, title=title):
                log = self.run_queue([{
                    "status": "item", "page_id": page_id,
                    "page_url": "https://example.invalid/test", "title": title,
                    "body": "synthetic fixture", "current_tail10": "", "decision_log": "",
                }])
                expected = "gpt-5.6-sol" if locked else "gpt-6.1-sol"
                self.assertIn(f"item model={expected} arguments=--model {expected}", log)
                if locked:
                    self.assertIn('model_reasoning_effort="medium"', log)
                else:
                    self.assertNotIn('model_reasoning_effort="medium"', log)
                self.assertIn("requested cap of 1 item(s) reached", log)

    def test_audit_selector_excludes_title_and_main_page(self):
        prompt = (ROOT / "scripts" / "audit_select_prompt.md").read_text(encoding="utf-8")
        exclusion = next(line for line in prompt.splitlines() if line.startswith("2. "))
        self.assertIn("周回3-12", exclusion)
        self.assertIn("または page ID", exclusion)
        self.assertIn("3fd72941-354b-813e-a9ee-e2e511e7b1e9", exclusion)
        self.assertIn("絶対に選ばない", exclusion)

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell is required")
    def test_scheduled_scripts_parse_in_windows_powershell(self):
        for name in ("run_queue.ps1", "audit_queue.ps1"):
            with self.subTest(script=name):
                path = str(ROOT / "scripts" / name).replace("'", "''")
                command = (
                    "$t=$null; $e=$null; "
                    f"[System.Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$t,[ref]$e) > $null; "
                    "$e | Out-String | Write-Output; if($e.Count){exit 1}"
                )
                result = subprocess.run(
                    [shutil.which("powershell.exe"), "-NoProfile", "-Command", command],
                    capture_output=True, text=True, errors="replace",
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_current_location_is_fetched_only_for_item(self):
        prompt = SELECTOR_PROMPT.read_text(encoding="utf-8")
        step6 = next(line for line in prompt.splitlines() if line.startswith("6. "))
        self.assertIn("status=`item`", step6)
        self.assertIn("status=`empty`・`error`", step6)
        self.assertIn("現在地をfetchせず", step6)
        self.assertIn("current_tail10・decision_logは空文字", step6)


if __name__ == "__main__":
    unittest.main()
