"""Exercise safe no-op, conflicts, pinned refs and common Core mappings."""
import unittest

from plugins.module_utils.core import ProxmoxError
from plugins.module_utils.deployment import (
    create_environment, deployment_decision, validate_spec
)

SCRIPT_SHA = "a" * 40
CORE_SHA = "b" * 40


class DeploymentTests(unittest.TestCase):
    def test_omitted_settings_never_override_script_defaults(self):
        for kind in ("lxc", "vm"):
            with self.subTest(kind=kind):
                env = create_environment(kind, 120, SCRIPT_SHA, CORE_SHA, {})
                for mapped in ("var_hostname", "VM_HOSTNAME", "var_ram",
                               "VM_RAM", "var_disk", "VM_DISK_SIZE"):
                    self.assertNotIn(mapped, env)

    def test_lxc_overrides(self):
        settings = {
            "cores": 2, "memory": 2048, "disk_size": 8,
            "hostname": "adguard", "bridge": "vmbr1", "vlan_id": 12,
            "os": "debian", "os_version": 13,
            "ipv4": "dhcp", "ipv6_method": "auto", "unprivileged": False,
        }
        fields = validate_spec("lxc", "adguard", 120, SCRIPT_SHA, CORE_SHA, settings)
        env = create_environment("lxc", 120, SCRIPT_SHA, CORE_SHA, settings, fields)
        self.assertEqual(env["var_ctid"], "120")
        self.assertEqual(env["mode"], "generated")
        self.assertEqual(env["var_cpu"], "2")
        self.assertEqual(env["var_ram"], "2048")
        self.assertEqual(env["var_disk"], "8")
        self.assertEqual(env["var_vlan"], "12")
        self.assertEqual(env["var_unprivileged"], "1")
        self.assertIn(SCRIPT_SHA, env["COMMUNITY_SCRIPTS_URL"])
        self.assertIn(CORE_SHA, env["COMMUNITY_SCRIPTS_CORE_URL"])

    def test_vm_overrides(self):
        settings = {
            "cores": 4, "memory": 8192, "disk_size": 32, "hostname": "homeassistant",
            "datastore_id": "local-lvm", "bridge": "vmbr0", "started": False,
        }
        validate_spec("vm", "haos-vm", 121, SCRIPT_SHA, CORE_SHA, settings)
        env = create_environment("vm", 121, SCRIPT_SHA, CORE_SHA, settings)
        self.assertEqual(env["VM_VMID"], "121")
        self.assertEqual(env["VM_UNATTENDED"], "1")
        self.assertEqual(env["VM_DISK_SIZE"], "32G")
        self.assertEqual(env["VM_START"], "no")

    def test_bounded_application_specific_variables(self):
        from plugins.module_utils.deployment import validate_script_vars
        env = create_environment("lxc", 120, SCRIPT_SHA, CORE_SHA,
                                 {"cores": 2}, script_vars={"var_custom_option": "yes"})
        self.assertEqual(env["var_custom_option"], "yes")
        for unsafe in ("var_ctid", "VM_VMID", "var_unattended", "COMMUNITY_SCRIPTS_URL"):
            with self.assertRaises(ProxmoxError):
                validate_script_vars("lxc", {unsafe: "malicious"}, {})
        with self.assertRaises(ProxmoxError):
            validate_script_vars("lxc", {"var_cpu": "10"}, {"var_cpu": "2"})
        with self.assertRaises(ProxmoxError):
            validate_script_vars("vm", {"VM_CUSTOM": "x" * 32769}, {})
        with self.assertRaises(ProxmoxError):
            validate_script_vars("lxc", {"var_custom": "a" + chr(10) + "b"}, {})

    def test_extended_core_network_dns_and_lxc_features(self):
        settings = {
            "mac_address": "02:12:34:56:78:9a", "mtu": 1500,
            "dns": "1.1.1.1", "searchdomain": "lab.example",
            "timezone": "America/New_York",
            "nesting": 1, "protection": False, "sdn_vnet": "vnet1",
        }
        validate_spec("lxc", "adguard", 120, SCRIPT_SHA, CORE_SHA, settings)
        env = create_environment("lxc", 120, SCRIPT_SHA, CORE_SHA, settings)
        self.assertEqual(env["var_mac"], "02:12:34:56:78:9a")
        self.assertEqual(env["var_ns"], "1.1.1.1")
        self.assertEqual(env["var_nesting"], "1")
        with self.assertRaises(ProxmoxError):
            validate_spec("lxc", "adguard", 120, SCRIPT_SHA, CORE_SHA,
                          {"mac_address": "not-mac"})
        with self.assertRaises(ProxmoxError):
            validate_spec("lxc", "adguard", 120, SCRIPT_SHA, CORE_SHA,
                          {"nesting": "suspicious"})

    def test_core_boolean_and_vm_value_encodings(self):
        lxc = {"tun": True, "fuse": False, "protection": True,
               "nesting": 1, "keyctl": 0, "disk_size": 12}
        validate_spec("lxc", "adguard", 120, SCRIPT_SHA, CORE_SHA, lxc)
        env = create_environment("lxc", 120, SCRIPT_SHA, CORE_SHA, lxc)
        self.assertEqual(env["var_tun"], "yes")
        self.assertEqual(env["var_fuse"], "no")
        self.assertEqual(env["var_protection"], "yes")
        self.assertEqual(env["var_nesting"], "1")
        self.assertEqual(env["var_disk"], "12")

        vm = {"cores": 4, "memory": 2048, "disk_size": 30,
              "cpu_type": "host", "disk_cache": "writethrough",
              "machine": "q35", "datastore_id": "local-lvm", "bridge": "vmbr0"}
        validate_spec("vm", "ubuntu-vm", 121, SCRIPT_SHA, CORE_SHA, vm)
        env = create_environment("vm", 121, SCRIPT_SHA, CORE_SHA, vm)
        self.assertEqual(env["VM_CPU"], "host")
        self.assertEqual(env["VM_DISK_CACHE"], "cache=writethrough,")
        self.assertEqual(env["VM_MACHINE"], "q35")
        self.assertEqual(env["VM_STORAGE"], "local-lvm")
        self.assertEqual(env["VM_DISK_SIZE"], "30G")

    def test_unsupported_core_fields_are_not_silently_ignored(self):
        for kind, unsupported in (
            ("lxc", {"disk": 10}), ("vm", {"disk": 10}),
            ("lxc", {"ssh_public_key": "ssh-ed25519 x"}),
            ("lxc", {"ipv6_static": "2001:db8::1/64"}),
            ("vm", {"cpu_type": "EPYC"}),
            ("vm", {"disk_cache": "writeback"}),
            ("vm", {"machine": "surprise"}),
            ("lxc", {"vlan_id": 4095}),
            ("lxc", {"ipv6_method": "static"}),
        ):
            with self.subTest(kind=kind, values=unsupported):
                with self.assertRaises(ProxmoxError):
                    validate_spec(kind, "example", 120, SCRIPT_SHA, CORE_SHA, unsupported)

    def test_reject_bad_ids_refs_and_unsupported_fields(self):
        for bad in (None, 99, True, 1_000_000_000):
            with self.assertRaises(ProxmoxError):
                validate_spec("lxc", "adguard", bad, SCRIPT_SHA, CORE_SHA, {})
        with self.assertRaisesRegex(ProxmoxError, "immutable"):
            validate_spec("lxc", "adguard", 120, "main", CORE_SHA, {})
        with self.assertRaisesRegex(ProxmoxError, "Unsupported"):
            validate_spec("vm", "haos-vm", 120, SCRIPT_SHA, CORE_SHA, {"var_ctid": 123})
        with self.assertRaises(ProxmoxError):
            validate_spec("lxc", "adguard", 120, SCRIPT_SHA, CORE_SHA, {"hostname": "x\nBAD"})

    def test_any_app_specific_environment_variable_is_allowed_safely(self):
        env = create_environment(
            "vm", 121, SCRIPT_SHA, CORE_SHA, {"cores": 2},
            script_vars={"VM_ISO_STORAGE": "local", "APP_LICENSE_KEY": "vault-supplied"})
        self.assertEqual(env["VM_ISO_STORAGE"], "local")
        self.assertEqual(env["APP_LICENSE_KEY"], "vault-supplied")
        lxc = create_environment("lxc", 120, SCRIPT_SHA, CORE_SHA, {},
                                 script_vars={"CUSTOM_APP_MODE": "testing"})
        self.assertEqual(lxc["CUSTOM_APP_MODE"], "testing")
        from plugins.module_utils.deployment import validate_script_vars
        for protected in ("PATH", "HOME", "BASH_ENV", "SHELLOPTS", "IFS",
                          "LD_PRELOAD", "GIT_CONFIG_COUNT", "VM_VMID",
                          "VM_UNATTENDED", "PHS_SILENT", "MODE", "mode",
                          "COMMUNITY_SCRIPTS_ROOT", "var_ctid", "var_disk",
                          "VM_RAM", "var_ssh", "CLOUDINIT_USER"):
            with self.subTest(name=protected):
                with self.assertRaises(ProxmoxError):
                    validate_script_vars("lxc", {protected: "bad"}, {})
        for bad in ("APP-VAR", "BAD VAR", "1BAD", "X" * 129):
            with self.assertRaises(ProxmoxError):
                validate_script_vars("lxc", {bad: "value"}, {})

    def test_lxc_additional_shared_core_settings(self):
        settings = {"gpu": True, "mknod": 1, "mount_fs": "nfs,fuse",
                    "apt_cacher": True, "apt_cacher_ip": "192.168.1.42",
                    "inherit_host_ca": False, "timezone": "America/New_York"}
        validate_spec("lxc", "adguard", 120, SCRIPT_SHA, CORE_SHA, settings)
        env = create_environment("lxc", 120, SCRIPT_SHA, CORE_SHA, settings)
        self.assertEqual(env["var_gpu"], "yes")
        self.assertEqual(env["var_mknod"], "1")
        self.assertEqual(env["var_mount_fs"], "nfs,fuse")
        self.assertEqual(env["var_apt_cacher"], "yes")
        self.assertEqual(env["var_inherit_host_ca"], "no")
        vm_env = create_environment("vm", 121, SCRIPT_SHA, CORE_SHA,
                                     {"timezone": "America/New_York"})
        self.assertEqual(vm_env["VM_TIMEZONE"], "America/New_York")

    def test_absent_is_proposed_change(self):
        p = deployment_decision([], 120, "lxc", "adguard")
        self.assertTrue(p["needs_create"])
        self.assertTrue(p["changed"])

    def test_verified_present_is_idempotent(self):
        inventory = [{"vmid": 120, "type": "lxc", "node": "pve1"}]
        config = {"description": "https://community-scripts.org/scripts/adguard"}
        p = deployment_decision(inventory, 120, "lxc", "adguard", config)
        self.assertFalse(p["needs_create"])
        self.assertFalse(p["changed"])

    def test_collision_and_unknown_identity_fail_closed(self):
        guests = [{"vmid": 120, "type": "qemu", "node": "pve1"}]
        with self.assertRaisesRegex(ProxmoxError, "collision"):
            deployment_decision(guests, 120, "lxc", "adguard", {})
        guests[0]["type"] = "lxc"
        with self.assertRaisesRegex(ProxmoxError, "matching"):
            deployment_decision(guests, 120, "lxc", "adguard", {})
        with self.assertRaisesRegex(ProxmoxError, "matching"):
            deployment_decision(
                guests, 120, "lxc", "adguard",
                {"description": "https://community-scripts.org/scripts/other"})
        with self.assertRaises(ProxmoxError):
            deployment_decision(guests * 2, 120, "lxc", "adguard", {})


if __name__ == "__main__":
    unittest.main()
