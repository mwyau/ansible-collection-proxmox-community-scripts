"""Positive and negative retirement tests; no upstream script is executed."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "module_utils"))
from retirement import retired_info
from catalog import exclude_retired


class RetirementTests(unittest.TestCase):
    def test_actual_removal_notice_patterns(self):
        for name in ("BookLore", "LiteLLM", "MinIO"):
            source = ('APP="' + name + '"\n'
                      'msg_error "This script is no longer available in community-scripts."\n'
                      'exit 1\n')
            info = retired_info(source, "lxc")
            self.assertEqual(info["status"], "retired")
            self.assertEqual(info["reason"], "removed")

    def test_rename_successor(self):
        source = ('msg_error "This script is no longer available."\n'
                  'msg_warn "MusicSeerr has been renamed to DroppedNeedle."\n'
                  "exit 1\n")
        self.assertEqual(retired_info(source, "lxc")["successor"], "droppedneedle")

    def test_normal_installer_is_not_retired_even_with_guard(self):
        source = ('msg_error "This script is no longer available."\n'
                  "exit 1\nstart\nbuild_container\n")
        self.assertIsNone(retired_info(source, "lxc"))
        self.assertIsNone(retired_info("APP=Foo\nexit 1\n", "lxc"))

    def test_known_retirement_cache_avoids_bulk_fetch(self):
        scripts = {
            "lxc/booklore": {"slug": "booklore", "kind": "lxc"},
            "lxc/adguard": {"slug": "adguard", "kind": "lxc"},
        }
        present, excluded = exclude_retired(scripts)
        self.assertEqual(list(present), ["lxc/adguard"])
        self.assertIn("lxc/booklore", excluded)
        self.assertEqual(excluded["lxc/booklore"]["reason"], "removed")
        self.assertEqual(present["lxc/adguard"]["retirement_check"], "catalog_cache")

    def test_selected_script_source_can_confirm_revival(self):
        scripts = {"lxc/booklore": {"slug": "booklore", "kind": "lxc"}}
        present, excluded = exclude_retired(scripts, source_lookup=lambda _: "start\nbuild_container\n")
        self.assertIn("lxc/booklore", present)
        self.assertFalse(excluded)
        present, excluded = exclude_retired(scripts, source_lookup=lambda _: (
            'msg_error "This script is no longer available."\nexit 1\n'))
        self.assertFalse(present)
        self.assertIn("lxc/booklore", excluded)


if __name__ == "__main__":
    unittest.main()
