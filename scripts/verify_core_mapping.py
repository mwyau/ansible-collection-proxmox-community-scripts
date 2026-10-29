"""Verify normalized Community Scripts mappings against pinned shared Core source.

Static contract checking only: passing does not certify each installer or
prove VM image creation will honor the mapped setting.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from plugins.module_utils.deployment import LXC_FIELDS, VM_FIELDS

LXC_GUEST = ("var_ssh", "var_ssh_authorized_key")
VM_CLOUD = ("CLOUDINIT_USER", "CLOUDINIT_NETWORK_MODE", "CLOUDINIT_IP",
            "CLOUDINIT_GW", "CLOUDINIT_DNS", "CLOUDINIT_SSH_KEYS")


def check_core(core_root):
    root = Path(core_root)
    lxc = (root / "ui/defaults.func").read_text()
    vm = (root / "pve/vm-core.func").read_text()
    cloud = (root / "vm/cloud-init.func").read_text()

    # The function must *consume* the overrides, not merely document them.
    vm_fn = vm.split("vm_apply_env_overrides() {", 1)[-1].split("\n}", 1)[0]
    if vm_fn == vm:
        raise ValueError("VM shared override function not found")
    vm_start = vm.split("vm_start_script() {", 1)[-1].split("\n}", 1)[0]
    missing = []
    for key in sorted(set(LXC_FIELDS.values()) | set(LXC_GUEST)):
        if not re.search(r"\b" + re.escape(key) + r"\b", lxc):
            missing.append("lxc:" + key)
    # VM_TIMEZONE is consumed by vm_timezone_default() rather than
    # vm_apply_env_overrides(); both are shared Core functionality.
    for key in sorted(set(VM_FIELDS.values())):
        source = vm if key == "VM_TIMEZONE" else vm_fn
        if not re.search(r"\b" + re.escape(key) + r"\b", source):
            missing.append("vm:" + key)
    for key in VM_CLOUD:
        if not re.search(r"\b" + key + r"\b", cloud):
            missing.append("cloud_init:" + key)
    if "VM_CLOUD_INIT" not in vm or "VM_UNATTENDED" not in vm_start or "vm_apply_env_overrides" not in vm_start:
        missing.append("vm:unattended_dispatch")
    if "ipv6_static" in LXC_FIELDS or "ssh_public_key" in LXC_FIELDS:
        missing.append("lxc:ambiguous_public_field")
    return {"ok": not missing, "missing": missing,
            "lxc_fields": dict(LXC_FIELDS), "vm_fields": dict(VM_FIELDS),
            "scope": "shared_core_static_contract_only"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", required=True, type=Path)
    args = parser.parse_args()
    result = check_core(args.core)
    print(json.dumps(result, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
