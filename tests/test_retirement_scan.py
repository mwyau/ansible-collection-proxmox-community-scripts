"""Verify retired stubs are reported separately from active scripts."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

scanner_file = Path(__file__).resolve().parents[1] / "scripts" / "scan_community_scripts.py"
spec = importlib.util.spec_from_file_location("scanner_retired", scanner_file)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class RetiredScanTests(unittest.TestCase):
    def test_retired_stub_reported_separately(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "ct").mkdir()
            (root / "vm").mkdir()
            for name in ("booklore", "litellm", "minio", "musicseerr"):
                (root / "ct" / (name + ".sh")).write_text(
                    'msg_error "This script is no longer available."\nexit 1\n')
            rows = scanner.scan(root, "lxc")
            excluded = [x for x in rows if x["retirement"]]
            active = [x for x in rows if not x["retirement"]]
            self.assertEqual(len(excluded), 4)
            self.assertEqual(active, [])
            self.assertIn("Retired scripts excluded: **4**",
                          scanner.markdown(active, "scripts", "core", excluded))


if __name__ == "__main__":
    unittest.main()
