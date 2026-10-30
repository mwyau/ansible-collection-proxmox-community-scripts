"""Versioned shared Ansible/Terraform input contract.

The JSON is normative; these tests guard the actual Ansible engine adapter.
"""
import json
import unittest
from pathlib import Path

from plugins.module_utils.deployment import (
    LXC_FIELDS, VM_FIELDS, create_environment, validate_spec,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "contracts/guest.v1.json").read_text())
SHA = "a" * 40

class SharedContractTests(unittest.TestCase):
    def test_version_and_all_48_environment_bindings(self):
        self.assertEqual(CONTRACT["schema_version"], 1)
        self.assertEqual(CONTRACT["lxc_fields"], LXC_FIELDS)
        self.assertEqual(CONTRACT["vm_fields"], VM_FIELDS)
        self.assertEqual(len(LXC_FIELDS), 34)
        self.assertEqual(len(VM_FIELDS), 14)

    def test_shared_normalization_goldens(self):
        for case in CONTRACT["encoding_cases"]:
            with self.subTest(kind=case["kind"]):
                kind, settings = case["kind"], case["settings"]
                validate_spec(kind, "adguard" if kind == "lxc" else "ubuntu-vm",
                              120, SHA, SHA, settings)
                env = create_environment(kind, 120, SHA, SHA, settings)
                for name, expected in case["expected_env"].items():
                    self.assertEqual(env[name], expected, (kind, name))
                self.assertEqual(
                    set(env).intersection(set(LXC_FIELDS.values()) |
                                          set(VM_FIELDS.values())),
                    set(case["expected_env"]),
                )

    def test_bpg_style_facade_and_shared_contract(self):
        defaults = (ROOT / "roles/application/defaults/main.yml").read_text()
        keys = {line.split(":", 1)[0] for line in defaults.splitlines() if line and not line.startswith((" ", "#", "-")) and ":" in line}
        self.assertTrue(set(CONTRACT["common_inputs"]).issubset(keys))
        self.assertEqual(CONTRACT["identity"]["lxc"]["required"], "vm_id")
        self.assertEqual(CONTRACT["identity"]["vm"]["required"], "vm_id")
        role = (ROOT / "roles/application/tasks/main.yml").read_text()
        self.assertIn('_cs_guest_id: "{{ vm_id }}"', role)
        self.assertIn("vm_id is not none", role)
        self.assertIn('update_scripts_ref: "{{ update_scripts_ref }}"', role)

if __name__ == "__main__":
    unittest.main()
