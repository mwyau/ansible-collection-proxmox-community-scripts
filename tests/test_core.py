"""Deterministic safety and reconciliation tests (no live Proxmox)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "module_utils"))

from core import ProxmoxError, locate_resource, resource_path, detect_script, verify_identity, plan_changes, disk_size_gib, ProxmoxAPI, pending_status


class TestResource(unittest.TestCase):
    def setUp(self):
        self.lxc = {"vmid": 120, "node": "pve1", "type": "lxc"}
        self.config = {
            "cores": 2, "memory": 2048, "swap": 512,
            "tags": "community-script;adblock", "rootfs": "local-zfs:subvol-120-disk-0,size=8G",
            "hostname": "dns"
        }

    def test_find_existing_and_type(self):
        self.assertEqual(locate_resource([self.lxc], 120, "lxc")["node"], "pve1")
        self.assertEqual(resource_path(self.lxc), "/nodes/pve1/lxc/120")
        with self.assertRaises(ProxmoxError):
            locate_resource([self.lxc], 120, "vm")
        with self.assertRaises(ProxmoxError):
            locate_resource([self.lxc], 121)

    def test_idempotence(self):
        plan = plan_changes(self.config, "lxc", {"cores": 2, "memory": "2048"}, {"key": "rootfs", "size_gb": 8})
        self.assertFalse(plan["changed"])

    def test_changes_and_growth(self):
        plan = plan_changes(self.config, "lxc", {"cores": 4, "memory": 4096}, {"key": "rootfs", "size_gb": 16})
        self.assertTrue(plan["changed"])
        self.assertEqual(plan["settings"], {"cores": 4, "memory": 4096})
        self.assertEqual(plan["resize"]["size_gb"], 16)
        self.assertEqual(self.config["cores"], 2)

    def test_shrink_forbidden(self):
        with self.assertRaisesRegex(ProxmoxError, "shrink"):
            plan_changes(self.config, "lxc", disk={"key": "rootfs", "size_gb": 4})
        with self.assertRaises(ProxmoxError):
            plan_changes(self.config, "lxc", disk={"key": "scsi0", "size_gb": 16})

    def test_unknown_field_forbidden(self):
        with self.assertRaises(ProxmoxError):
            plan_changes(self.config, "lxc", {"unprivileged": 0})
        with self.assertRaises(ProxmoxError):
            plan_changes(self.config, "lxc", {"net0": "name=eth0,bridge=vmbr1"})

    def test_additive_tags(self):
        plan = plan_changes(self.config, "lxc", {"tags": "ansible_managed;adblock"})
        self.assertEqual(plan["settings"]["tags"], "adblock;ansible_managed;community-script")
        self.assertFalse(plan_changes(self.config, "lxc", {"tags": "adblock"})["changed"])

    def test_vm_disk_and_memory(self):
        config = {"cores": 4, "memory": 8192, "scsi0": "local-lvm:vm-121-disk-0,size=32G"}
        plan = plan_changes(config, "qemu", {"memory": 16384}, {"key": "scsi0", "size_gb": 64})
        self.assertTrue(plan["changed"])
        self.assertEqual(plan["resize"]["key"], "scsi0")
        self.assertEqual(disk_size_gib("local-lvm:vm-121-disk-0,size=32768M"), 32)

    def test_identity_strict(self):
        self.assertIsNone(detect_script(self.config, "lxc"))
        with self.assertRaisesRegex(ProxmoxError, "unverified"):
            verify_identity(self.config, "lxc", "adguard")
        self.assertIsNone(verify_identity(self.config, "lxc", "adguard", adopt=True))
        vm = {"tags": "community-script;app-deployer;haos", "description": "community-scripts.org/scripts/haos"}
        self.assertEqual(verify_identity(vm, "qemu", "haos"), "haos")
        with self.assertRaisesRegex(ProxmoxError, "conflicts"):
            verify_identity(vm, "qemu", "debian", adopt=True)

    def test_pending_config_does_not_imply_live_cpu_change(self):
        pending = pending_status([
            {"key": "cores", "value": "2", "pending": "4"},
            {"key": "memory", "value": "4096", "pending": "8192"},
            {"key": "name", "value": "test"}
        ], {"cores": 4, "memory": 8192})
        self.assertTrue(pending["restart_required_for_requested_settings"])
        self.assertEqual(pending["pending"]["cores"]["current"], "2")
        self.assertEqual(pending["pending_desired"]["memory"]["pending"], "8192")

    def test_pending_cpu_memory_are_planned_as_noop(self):
        from core import effective_desired_config
        current = {"cores": 2, "memory": 4096}
        desired = {"cores": 4, "memory": 8192}
        pending = pending_status([
            {"key": "cores", "value": 2, "pending": 4},
            {"key": "memory", "value": 4096, "pending": 8192},
        ], desired)
        simulated = effective_desired_config(current, pending, desired)
        self.assertFalse(plan_changes(simulated, "qemu", desired)["changed"])
        self.assertTrue(pending["restart_required_for_requested_settings"])
        self.assertEqual(current["cores"], 2)
        self.assertTrue(plan_changes(current, "qemu", desired)["changed"])

    def test_disk_media_guard(self):
        from core import validate_disk_for_resize
        with self.assertRaises(ProxmoxError):
            validate_disk_for_resize("local:cloudinit,media=cdrom,size=4M", "qemu", "ide2")
        with self.assertRaises(ProxmoxError):
            validate_disk_for_resize("/dev/disk/by-id/nvme-id,size=32G", "qemu", "scsi0")

    def test_bad_api_hosts(self):
        for host in ("http://pve:8006", "https://user:pass@pve:8006", "https://pve/foo"):
            with self.assertRaises(ProxmoxError):
                ProxmoxAPI(host, "user@pve!token", "secret")


if __name__ == "__main__":
    unittest.main()
