"""Conservative static VM script evidence for shared Core overrides."""
import re

# Core variable -> script's post-override working variable.
VM_USAGE = {
    "cores": "CORE_COUNT", "memory": "RAM_SIZE", "disk_size": "DISK_SIZE",
    "hostname": "HN", "bridge": "BRG", "vlan": "VLAN",
    "storage": "STORAGE", "mac": "MAC", "mtu": "MTU",
    "cpu_type": "CPU_TYPE", "machine": "MACHINE", "start": "vm_start_vm",
    "disk_cache": "DISK_CACHE", "timezone": "vm_timezone_default",
}


def vm_script_evidence(source):
    """Source presence proves only *possible* consumption, never correct behavior.

    A shared VM override requires vm_start_script plus per-script usage of the
    working variable. Real QEMU creation must still be tested separately.
    """
    if not isinstance(source, str):
        raise TypeError("VM script source must be text")
    lines = [line for line in source.splitlines()
             if not line.lstrip().startswith("#")]
    text = "\n".join(lines)
    engine = "pve/vm-core.func" in text
    entrypoint = bool(re.search(r"\bvm_start_script\s+(?!\()", text))
    used = {key: bool(re.search(r"\b" + re.escape(variable) + r"\b", text))
            for key, variable in VM_USAGE.items()}
    return {
        "uses_shared_unattended": engine and entrypoint,
        "field_references": used,
        "unverified_fields": sorted(k for k, found in used.items() if not found),
        "cloud_init_hook": (
            "vm_prompt_cloud_init" in text and
            ("vm_provision" in text or "setup_cloud_init" in text)
        ),
        "validation": "static_source_evidence_only",
    }
