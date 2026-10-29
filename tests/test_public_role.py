"""Guard the concise public application role surface and override plumbing."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PublicRoleTests(unittest.TestCase):
    def test_only_short_public_names(self):
        defaults = (ROOT / "roles/application/defaults/main.yml").read_text()
        for name in ("action", "api_host", "kind", "script", "script_override",
                     "vmid", "settings", "ssh", "cloud_init"):
            self.assertIn("\n" + name + ":", defaults)
        self.assertNotIn("\napplication_", defaults)
        self.assertNotIn("\nctid:", defaults)
        self.assertIn("vmid: null", defaults)
        tasks = (ROOT / "roles/application/tasks/main.yml").read_text()
        self.assertIn("vmid is not none", tasks)
        self.assertIn('_cs_guest_id: "{{ vmid }}"', tasks)
        self.assertNotIn("ctid if kind", tasks)
        self.assertIn('update_scripts_ref: "{{ update_scripts_ref }}"', tasks)

    def test_manual_override_propagates_to_all_existing_guest_paths(self):
        tasks = (ROOT / "roles/application/tasks/main.yml").read_text()
        for binding in (
            'provenance_script_override: "{{ script_override }}"',
            'deploy_script_override: "{{ script_override }}"',
            'hardware_script_override: "{{ script_override }}"',
            'cloud_init_script_override: "{{ script_override }}"',
        ):
            self.assertIn(binding, tasks)
        self.assertIn("action != 'update' or script_override | length == 0", tasks)

    def test_new_install_must_not_use_manual_override_as_proof(self):
        tasks = (ROOT / "roles/deploy/tasks/main.yml").read_text()
        post = tasks.split("- name: Verify exact guest identity after installation", 1)[1]
        self.assertNotIn("script_override:", post)
        self.assertIn("community_scripts_provenance.status == 'verified'", post)

    def test_explicit_lifecycle_separates_creation_hardware_and_updates(self):
        defaults = (ROOT / "roles/application/defaults/main.yml").read_text()
        tasks = (ROOT / "roles/application/tasks/main.yml").read_text()
        self.assertIn("action in ['inspect', 'present', 'reconcile', 'update']", tasks)
        self.assertNotIn("manage_hardware:", defaults)
        self.assertIn("script_vars: {}", defaults)
        self.assertNotIn("installer_env:", defaults)
        creation = tasks.split("- name: Create only if absent", 1)[1].split(
            "- name: Require explicit per-guest hardware settings", 1)[0]
        self.assertIn("when: action == 'present'", creation)
        self.assertNotIn("manage_hardware", creation)
        hardware = tasks.split("- name: Reconcile normalized hardware", 1)[1].split(
            "- name: Manage Cloud-Init", 1)[0]
        self.assertIn("action == 'reconcile'", hardware)
        for variable in ("cores", "memory", "swap", "sockets", "disk_size"):
            self.assertIn("settings." + variable, hardware)
            self.assertNotIn("_cs_effective_settings." + variable, hardware)
        self.assertNotIn("manage_hardware", tasks)

    def test_update_settings_cannot_self_reference(self):
        tasks = (ROOT / "roles/application/tasks/main.yml").read_text()
        for name in ("update_request_id", "update_apply", "update_backup",
                     "update_backup_storage", "update_accept_no_backup"):
            self.assertNotIn(name + ': "{{ ' + name + ' }}"', tasks)


if __name__ == "__main__":
    unittest.main()
