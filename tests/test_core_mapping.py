"""Guard the shared Core contract and per-VM resource override evidence."""
import tempfile
import unittest
from pathlib import Path

from scripts.verify_core_mapping import check_core
from plugins.module_utils.deployment import LXC_FIELDS, VM_FIELDS
from plugins.module_utils.vm_contract import vm_script_evidence


class CoreMappingTests(unittest.TestCase):
    def test_core_contract_fails_closed_on_removed_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for part in ("ui", "pve", "vm"):
                (root / part).mkdir()
            keys = sorted(set(LXC_FIELDS.values()) | {"var_ssh", "var_ssh_authorized_key"})
            (root / "ui/defaults.func").write_text("\n".join(keys))
            (root / "pve/vm-core.func").write_text(
                "vm_apply_env_overrides() {\n"
                + "\n".join(sorted(set(VM_FIELDS.values())))
                + "\n}\nvm_start_script() {\n"
                + "VM_UNATTENDED\nvm_apply_env_overrides\nVM_CLOUD_INIT\n}\n")
            (root / "vm/cloud-init.func").write_text(
                "\n".join(("CLOUDINIT_USER", "CLOUDINIT_NETWORK_MODE",
                           "CLOUDINIT_IP", "CLOUDINIT_GW", "CLOUDINIT_DNS",
                           "CLOUDINIT_SSH_KEYS")))
            first = check_core(root)
            self.assertTrue(first["ok"], first["missing"])
            (root / "pve/vm-core.func").write_text(
                (root / "pve/vm-core.func").read_text().replace("VM_RAM", "LEGACY_RAM"))
            second = check_core(root)
            self.assertFalse(second["ok"])
            self.assertIn("vm:VM_RAM", second["missing"])

    def test_vm_shared_core_entrypoint_and_field_evidence(self):
        source = """
            source <(curl https://example/pve/vm-core.func)
            default_settings() { CORE_COUNT=2; RAM_SIZE=4096; }
            vm_start_script "Use defaults"
            qm create "$VMID" -cores "$CORE_COUNT" -memory "$RAM_SIZE"
            vm_start_vm "$APP"
        """
        evidence = vm_script_evidence(source)
        self.assertTrue(evidence["uses_shared_unattended"])
        self.assertTrue(evidence["field_references"]["cores"])
        self.assertTrue(evidence["field_references"]["memory"])
        self.assertTrue(evidence["field_references"]["start"])
        self.assertFalse(evidence["field_references"]["disk_size"])
        self.assertIn("disk_size", evidence["unverified_fields"])

        appliance = vm_script_evidence("qm create 120 -memory 4096")
        self.assertFalse(appliance["uses_shared_unattended"])
        self.assertEqual(appliance["validation"], "static_source_evidence_only")


if __name__ == "__main__":
    unittest.main()
