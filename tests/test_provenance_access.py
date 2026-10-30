import unittest
from plugins.module_utils.provenance import provenance
from plugins.module_utils.deployment import guest_access_environment
from plugins.module_utils.core import ProxmoxError, verify_identity

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPUFcMCRObddaMmvUDio11yge6gRGXNv3uqMq7ve0x3 test@host"


class ProvenanceTests(unittest.TestCase):
    def test_lxc_generated_update_script(self):
        entrypoint = ('#!/bin/bash\nexport SCRIPT_SLUG="vaultwarden"\n'
                      'export UPDATE_SCRIPT_NAME="debian"\n')
        result = provenance({"tags": "community-script;password"}, "lxc", entrypoint,
                            "vaultwarden")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["script"], "vaultwarden")
        self.assertEqual(result["context"][0]["slug"], "debian")
        self.assertEqual(verify_identity({}, "lxc", "vaultwarden", update_entrypoint=entrypoint),
                         "vaultwarden")

    def test_legacy_lxc_url(self):
        result = provenance({}, "lxc",
                            'bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/adguard.sh)"')
        self.assertEqual(result["script"], "adguard")

    def test_vm_description_and_conflicts(self):
        self.assertEqual(provenance({
            "description": "<a href='https://community-scripts.org/scripts/haos-vm'>VM</a>",
            "tags": "community-script;network;app-deployer",
        }, "vm", expected_script="haos-vm")["status"], "verified")
        hinted = provenance({"tags": "community-script;app-deployer;network"}, "vm")
        self.assertEqual(hinted["status"], "unknown")
        self.assertEqual(hinted["context"][0]["source"], "vm_app_deployer_tag_hint")
        self.assertEqual(provenance({
            "description": "https://community-scripts.org/scripts/haos-vm",
        }, "vm", expected_script="debian")["status"], "conflicting")
        self.assertEqual(provenance({"description": "https://community-scripts.org/scripts/foo"},
                                    "lxc", 'export SCRIPT_SLUG="bar"')["status"], "conflicting")

    def test_access_lxc_defaults_and_key(self):
        self.assertEqual(guest_access_environment("lxc")["environment"], {})
        result = guest_access_environment("lxc", {"enabled": True, "public_keys": [KEY]})
        self.assertEqual(result["environment"]["var_ssh"], "yes")
        self.assertEqual(result["environment"]["var_ssh_authorized_key"], KEY)
        result = guest_access_environment("lxc", {"enabled": False})
        self.assertEqual(result["environment"]["var_ssh"], "no")
        with self.assertRaises(ProxmoxError):
            guest_access_environment("lxc", {"enabled": False, "public_keys": [KEY]})
        with self.assertRaises(ProxmoxError):
            guest_access_environment("lxc", cloud_init={"enabled": True})

    def test_vm_omitted_cloud_init_preserves_image_required_default(self):
        self.assertEqual(guest_access_environment("vm")["environment"], {})
        with self.assertRaises(ProxmoxError):
            guest_access_environment("vm", {"enabled": False})
        with self.assertRaises(ProxmoxError):
            guest_access_environment("vm", {"enabled": True}, {"enabled": True})

    def test_legacy_staging_remains_read_only(self):
        from plugins.module_utils.deployment import deployment_decision
        inventory = [{"vmid": 120, "type": "lxc", "node": "pve1"}]
        state = deployment_decision(inventory, 120, "lxc", "vaultwarden", {},
                                    allow_unknown_existing=True)
        self.assertFalse(state["needs_create"])
        self.assertTrue(state["identity_requires_host_check"])
        self.assertFalse(state["changed"])
        with self.assertRaises(ProxmoxError):
            deployment_decision(inventory, 120, "lxc", "vaultwarden", {})

    def test_vm_cloud_init_keys_and_network(self):
        result = guest_access_environment(
            "vm", {"enabled": True, "public_keys": [KEY]},
            {"enabled": True, "user": "ubuntu", "network_mode": "static",
             "ip": "10.5.0.4/24", "gateway": "10.5.0.1", "dns": ["1.1.1.1"]},
            301, "/var/lib/ansible-community-scripts/keys")
        env = result["environment"]
        self.assertEqual(env["VM_CLOUD_INIT"], "yes")
        self.assertEqual(env["CLOUDINIT_USER"], "ubuntu")
        self.assertEqual(env["CLOUDINIT_IP"], "10.5.0.4/24")
        self.assertEqual(env["CLOUDINIT_SSH_KEYS"],
                         "/var/lib/ansible-community-scripts/keys/vm-301.pub")
        self.assertEqual(result["public_keys"], [KEY])
        with self.assertRaises(ProxmoxError):
            guest_access_environment("vm", {"enabled": True, "public_keys": [KEY]})
        with self.assertRaises(ProxmoxError):
            guest_access_environment("vm", cloud_init={"enabled": True, "network_mode": "static"})
        with self.assertRaises(ProxmoxError):
            guest_access_environment("vm", cloud_init={"enabled": True, "user": "invalid username"})


if __name__ == "__main__":
    unittest.main()
