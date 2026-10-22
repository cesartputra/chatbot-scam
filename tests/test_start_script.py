"""Exercise the launcher without installing packages or starting a server."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StartScriptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="iasc-start-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shutil.copyfile(ROOT / "start.sh", self.root / "start.sh")
        shutil.copyfile(ROOT / "requirements.txt", self.root / "requirements.txt")
        self.log = self.root / "calls.jsonl"
        self.marker = self.root / ".venv/.requirements-installed"
        stub = self.root / ".venv/bin/python"
        stub.parent.mkdir(parents=True)
        stub.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "with open(os.environ['START_TEST_CALLS'], 'a') as output:\n"
            "    output.write(json.dumps({'args': sys.argv[1:], 'index': os.getenv('PIP_INDEX_URL')}) + '\\n')\n"
            "if sys.argv[1:3] == ['-m', 'pip']:\n"
            "    sys.exit(int(os.environ.get('START_TEST_INSTALL_EXIT', '0')))\n"
        )
        stub.chmod(0o700)

    def run_launcher(self, **settings):
        env = {**os.environ, "START_TEST_CALLS": str(self.log)}
        for key in ("PIP_INDEX_URL", "PORT", "START_TEST_INSTALL_EXIT"):
            env.pop(key, None)
        env.update(settings)
        return subprocess.run(["bash", "start.sh"], cwd=self.root, env=env, capture_output=True, text=True, timeout=10)

    def calls(self):
        return [record["args"] for record in self.records()]

    def records(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_success_records_requirements_and_next_launch_skips_installation(self):
        self.assertEqual(self.run_launcher().returncode, 0)
        self.assertEqual(self.marker.read_bytes(), (self.root / "requirements.txt").read_bytes())
        installed = self.calls()[0]
        self.assertEqual(installed[:3], ["-m", "pip", "install"])
        for option, value in (("--timeout", "60"), ("--retries", "5")):
            self.assertEqual(installed[installed.index(option) + 1], value)
        self.assertNotIn("--no-cache-dir", installed)
        self.assertEqual(self.run_launcher().returncode, 0)
        calls = self.calls()
        self.assertEqual(sum(call[:2] == ["-m", "pip"] for call in calls), 1)
        self.assertEqual(sum(call[:2] == ["-m", "uvicorn"] for call in calls), 2)

    def test_failed_install_never_marks_or_starts_server_and_can_be_retried(self):
        failed = self.run_launcher(START_TEST_INSTALL_EXIT="7")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("gagal", failed.stderr.lower())
        self.assertFalse(self.marker.exists())
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.calls()[0][:2], ["-m", "pip"])
        self.assertEqual(self.run_launcher().returncode, 0)
        self.assertTrue(self.marker.exists())
        self.assertEqual(sum(call[:2] == ["-m", "pip"] for call in self.calls()), 2)
        self.assertEqual(sum(call[:2] == ["-m", "uvicorn"] for call in self.calls()), 1)

    def test_changed_requirements_reinstall_with_custom_index_and_port_inherited(self):
        settings = {"PIP_INDEX_URL": "https://packages.example.test/simple", "PORT": "8799"}
        self.assertEqual(self.run_launcher(**settings).returncode, 0)
        installed, launched = self.calls()
        self.assertEqual(installed[:3], ["-m", "pip", "install"])
        self.assertEqual(self.records()[0]["index"], settings["PIP_INDEX_URL"])
        self.assertEqual(launched[launched.index("--port") + 1], "8799")
        requirements = self.root / "requirements.txt"
        requirements.write_text(requirements.read_text() + "\n# Changed requirement fingerprint\n")
        self.assertEqual(self.run_launcher(**settings).returncode, 0)
        self.assertEqual(self.marker.read_bytes(), requirements.read_bytes())
        self.assertEqual(sum(call[:2] == ["-m", "pip"] for call in self.calls()), 2)
        self.assertTrue(all(record["index"] == settings["PIP_INDEX_URL"] for record in self.records()))


if __name__ == "__main__":
    unittest.main()
