"""Manual provenance override never masks conflicting positive evidence."""
import unittest
from plugins.module_utils.provenance import provenance, apply_script_override
from plugins.module_utils.deployment import validate_spec
from plugins.module_utils.core import ProxmoxError


class ManualOverrideTests(unittest.TestCase):
    def test_unknown_lxc_can_be_explicitly_attributed(self):
        original = provenance({"tags": "community-script"}, "lxc", expected_script="adguard")
        self.assertEqual(original["status"], "unknown")
        adopted = apply_script_override(original, "adguard", "adguard")
        self.assertEqual(adopted["status"], "overridden")
        self.assertEqual(adopted["script"], "adguard")
        self.assertEqual(adopted["override"]["source"], "operator")
        self.assertEqual(adopted["evidence"], [])

    def test_conflicting_evidence_cannot_be_overridden(self):
        conflicting = provenance(
            {"description": "https://community-scripts.org/scripts/other"}, "lxc",
            expected_script="adguard")
        self.assertEqual(conflicting["status"], "conflicting")
        with self.assertRaisesRegex(ValueError, "conflicting"):
            apply_script_override(conflicting, "adguard", "adguard")

    def test_verified_identity_cannot_be_replaced(self):
        verified = provenance({"description": "https://community-scripts.org/scripts/adguard"}, "lxc")
        self.assertEqual(apply_script_override(verified, "adguard")["status"], "verified")
        with self.assertRaisesRegex(ValueError, "verified"):
            apply_script_override(verified, "vaultwarden")

    def test_override_must_match_expected_and_safe_slug(self):
        assessment = provenance({}, "vm", expected_script="haos-vm")
        with self.assertRaisesRegex(ValueError, "match"):
            apply_script_override(assessment, "other", "haos-vm")
        with self.assertRaisesRegex(ValueError, "valid"):
            apply_script_override(assessment, "../haos-vm", "haos-vm")
        self.assertIs(apply_script_override(assessment, ""), assessment)

    def test_existing_guest_does_not_require_revision_pins(self):
        validate_spec("lxc", "adguard", 120, "", "", {}, require_pins=False)
        with self.assertRaisesRegex(ProxmoxError, "immutable"):
            validate_spec("lxc", "adguard", 120, "", "", {}, require_pins=True)

    def test_vm_kind_cannot_be_changed_by_script_override(self):
        assessment = provenance({}, "vm", expected_script="haos-vm")
        self.assertEqual(apply_script_override(assessment, "haos-vm")["status"], "overridden")
        with self.assertRaises(ValueError):
            provenance({}, "not-a-kind")


if __name__ == "__main__":
    unittest.main()
