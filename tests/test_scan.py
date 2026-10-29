"""Static scanner unit tests with synthetic script and shared Core fixtures."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "scripts" / "scan_community_scripts.py"
spec = importlib.util.spec_from_file_location("scanner", path)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for folder in ("ct", "vm", "install", "core/core", "core/pve"):
            (self.root / folder).mkdir(parents=True)
        (self.root / "core/core/core.func").write_text(
            "is_unattended() { return 0; }\n")
        (self.root / "core/pve/vm-core.func").write_text(
            "vm_apply_env_overrides() { :; }\n"
            "vm_start_script() { : \"VM_UNATTENDED\"; }\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_shared_lxc_no_local_prompt(self):
        (self.root / "ct/ubuntu.sh").write_text(
            "source \"core/build.func\"\nvar_cpu=2\nstart\nbuild_container\n")
        (self.root / "install/ubuntu-install.sh").write_text("echo installed\n")
        row = scanner.scan(self.root, "lxc", "ubuntu", self.root / "core")[0]
        self.assertEqual(row["assessment"], "shared_engine_no_app_prompts_detected")
        self.assertTrue(row["shared_engine_unattended_contract"])
        self.assertIn("var_cpu", row["variables"])
        self.assertFalse(row["flags"])
        self.assertTrue(row["install_payload"]["syntax_ok"])

    def test_lxc_os_menu_and_payload_prompt(self):
        (self.root / "ct/adguard.sh").write_text(
            "source \"core/build.func\"\n"
            "var_os=$(msg_menu 'Choose OS' 'debian' 'Debian')\n"
            "start\nbuild_container\n")
        (self.root / "install/adguard-install.sh").write_text(
            "prompt_confirm 'Proceed?' 'y'\n")
        row = scanner.scan(self.root, "lxc", "adguard", self.root / "core")[0]
        self.assertEqual(row["assessment"], "shared_engine_install_input_review")
        self.assertIn("set_var_os_for_os_menu", row["flags"])
        self.assertEqual(len(row["prompt_sites"]), 2)

    def test_update_menu_is_not_install_prompt(self):
        (self.root / "ct/vaultwarden.sh").write_text(
            "source \"core/build.func\"\n"
            "update_deb_based() {\n msg_menu \"Update options\" \"1\" \"Update\"\n}\n"
            "start\nbuild_container\n")
        (self.root / "install/vaultwarden-install.sh").write_text("echo ready\n")
        row = scanner.scan(self.root, "lxc", "vaultwarden", self.root / "core")[0]
        self.assertEqual(row["assessment"], "shared_engine_update_prompts_only")
        self.assertEqual(row["prompt_phase_counts"], {"update": 1})

    def test_vm_inherits_unattended(self):
        (self.root / "vm/ubuntu-vm.sh").write_text(
            "source \"pve/vm-core.func\"\n"
            "default_settings() { true; }\nvm_start_script 'Use defaults'\n")
        row = scanner.scan(self.root, "vm", "ubuntu-vm", self.root / "core")[0]
        self.assertTrue(row["shared_engine_unattended_contract"])
        self.assertEqual(row["assessment"], "shared_engine_no_app_prompts_detected")

    def test_unknown_entrypoint_and_invalid_payload(self):
        (self.root / "vm/special-vm.sh").write_text("qm create 100\n")
        row = scanner.scan(self.root, "vm", "special-vm", self.root / "core")[0]
        self.assertEqual(row["assessment"], "custom_entrypoint")
        (self.root / "ct/bad.sh").write_text(
            "source \"core/build.func\"\nstart\nbuild_container\n")
        (self.root / "install/bad-install.sh").write_text("if true; then\n")
        row = scanner.scan(self.root, "lxc", "bad", self.root / "core")[0]
        self.assertEqual(row["assessment"], "syntax_error")
        self.assertIn("install_payload_syntax_error", row["flags"])

    def test_no_core_not_assumed_compatible(self):
        (self.root / "ct/debian.sh").write_text(
            "source \"core/build.func\"\nstart\nbuild_container\n")
        row = scanner.scan(self.root, "lxc", "debian")[0]
        self.assertEqual(row["assessment"], "custom_entrypoint")

    def test_invalid_slug(self):
        with self.assertRaises(ValueError):
            scanner.scan(self.root, slug="../oops")

    def test_report_records_unverified_status(self):
        report = scanner.markdown([], "scripts-sha", "core-sha")
        self.assertIn("No scripts were executed or certified", report)


if __name__ == "__main__":
    unittest.main()
