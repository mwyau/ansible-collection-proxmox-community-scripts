import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "module_utils"))
from catalog import parse_directory, catalog_diff


class TestCatalog(unittest.TestCase):
    def test_dynamic_listing(self):
        entries = [
            {"name": "adguard.sh", "path": "ct/adguard.sh", "type": "file", "sha": "a" * 40},
            {"name": "new-app.sh", "path": "ct/new-app.sh", "type": "file", "sha": "b" * 40},
            {"name": "README.md", "path": "ct/README.md", "type": "file", "sha": "c" * 40},
            {"name": "wrong.sh", "path": "vm/wrong.sh", "type": "file", "sha": "d" * 40},
        ]
        found = parse_directory(entries, "lxc", "main")
        self.assertEqual(sorted(found), ["adguard", "new-app"])
        self.assertEqual(catalog_diff(found, {"adguard": "f" * 40, "gone": "x"}), {
            "added": ["new-app"], "removed": ["gone"], "updated": ["adguard"]
        })

    def test_reject_unsafe_ref(self):
        with self.assertRaises(ValueError):
            parse_directory([], "vm", "../secret")


if __name__ == "__main__":
    unittest.main()
