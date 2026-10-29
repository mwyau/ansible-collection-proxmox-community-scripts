"""Run the one-shot wrapper with fake pct and a harmless fixture, never real PVE."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

WRAPPER = Path(__file__).resolve().parents[1] / "roles" / "update" / "files" / "update_once.sh"


class UpdateOnceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.state = self.root / "state"
        self.state.mkdir()
        self.updater = self.root / "updater.sh"
        self.updater.write_text("#!/usr/bin/env bash\nprintf 'update\\n' >> \"$TEST_UPDATE_COUNTER\"\n")
        self.counter = self.root / "counter"
        pct = self.bin / "pct"
        pct.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"$1\" == status ]]; then echo 'status: running'; exit 0; fi\n"
            "if [[ \"$1\" == exec ]]; then echo 'export SCRIPT_SLUG=\"adguard\"'; exit 0; fi\n"
            "exit 8\n"
        )
        pct.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        TEST_UPDATE_COUNTER=str(self.counter))

    def tearDown(self):
        self.temp.cleanup()

    def run_wrapper(self, slug="adguard", request="release-2026-10"):
        return subprocess.run(
            ["bash", str(WRAPPER), "120", slug, request,
             str(self.updater), str(self.state)],
            env=self.env, text=True, capture_output=True, timeout=10,
        )

    def test_once_and_second_run_noop(self):
        one = self.run_wrapper()
        self.assertEqual(one.returncode, 0, one.stderr)
        self.assertIn("APPLIED", one.stdout)
        two = self.run_wrapper()
        self.assertEqual(two.returncode, 0, two.stderr)
        self.assertIn("ALREADY_APPLIED", two.stdout)
        self.assertEqual(self.counter.read_text(), "update\n")
        self.assertTrue((self.state / "release-2026-10.complete").exists())

    def test_identity_mismatch_never_updates(self):
        result = self.run_wrapper(slug="different")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.counter.exists())

    def test_invalid_request_never_updates(self):
        result = self.run_wrapper(request="../escape")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.counter.exists())


if __name__ == "__main__":
    unittest.main()
