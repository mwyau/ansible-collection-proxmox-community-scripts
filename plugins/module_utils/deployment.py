"""Noninteractive deployment planning: pure, testable, no guest creation.

Execution is reserved for the Ansible deploy role, after separate source,
identity, node and operator-approval checks.
"""
from __future__ import annotations

import re
import ipaddress
from .core import ProxmoxError, detect_script

SHA = re.compile(r"^[0-9a-f]{40}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,62}$")

# Common Core mappings confirmed against the respective shared engines.
# Keep the mappings explicit: unknown properties must fail, never be ignored.
LXC_FIELDS = {
    "cores": "var_cpu", "memory": "var_ram", "disk_size": "var_disk",
    "hostname": "var_hostname", "bridge": "var_brg", "vlan": "var_vlan",
    "storage": "var_container_storage", "template_storage": "var_template_storage",
    "os": "var_os", "os_version": "var_version", "privileged": "var_unprivileged",
    "ipv4": "var_net", "gateway": "var_gateway",
    "ipv6_method": "var_ipv6_method",
    "mac": "var_mac", "mtu": "var_mtu", "dns": "var_ns",
    "searchdomain": "var_searchdomain", "timezone": "var_timezone",
    "tags": "var_tags",
    "protection": "var_protection", "nesting": "var_nesting",
    "tun": "var_tun", "fuse": "var_fuse", "keyctl": "var_keyctl",
    "gpu": "var_gpu", "mknod": "var_mknod", "mount_fs": "var_mount_fs",
    "apt_cacher": "var_apt_cacher", "apt_cacher_ip": "var_apt_cacher_ip",
    "inherit_host_ca": "var_inherit_host_ca",
    "sdn_vnet": "var_sdn_vnet", "http_proxy": "var_http_proxy",
    "http_no_proxy": "var_http_no_proxy",
}
VM_FIELDS = {
    "cores": "VM_CORES", "memory": "VM_RAM", "disk_size": "VM_DISK_SIZE",
    "hostname": "VM_HOSTNAME", "bridge": "VM_BRIDGE", "vlan": "VM_VLAN",
    "storage": "VM_STORAGE", "mac": "VM_MAC", "mtu": "VM_MTU",
    "cpu_type": "VM_CPU", "machine": "VM_MACHINE", "start": "VM_START",
    "disk_cache": "VM_DISK_CACHE", "timezone": "VM_TIMEZONE",
}

# Extra variables are script-specific, not a second general hardware API.
# Allow ordinary shell environment identifiers (including APP_... names),
# but never let them change the installation target, source, shell runtime,
# or a setting supported by the normalized creation interface.
ENV_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CONTROL_ENV = {
    "PATH", "HOME", "SHELL", "ENV", "BASH_ENV", "BASHOPTS", "SHELLOPTS",
    "IFS", "CDPATH", "GLOBIGNORE", "PROMPT_COMMAND", "TERM",
    "mode", "MODE", "PHS_SILENT", "VM_VMID", "VM_UNATTENDED",
    "var_ctid", "var_unattended", "VM_CLOUD_INIT", "var_ssh",
    "var_ssh_authorized_key", "VM_SETTINGS_MODE", "VM_CREATED",
}
CONTROL_PREFIXES = (
    "COMMUNITY_SCRIPTS_", "PHS_", "LD_", "DYLD_", "BASH_FUNC_",
    "ANSIBLE_", "PYTHON", "GIT_", "CLOUDINIT_",
)


def validate_script_vars(kind, script_vars, standard_env):
    """Validate app-specific environment entries with strict name/size limits.

    Scalar values are passed as environment strings, never interpolated into
    a shell command. Shell startup injection and Core safety controls are
    forbidden, even when the corresponding normalized field was omitted.
    """
    if kind not in ("lxc", "vm"):
        raise ProxmoxError("Invalid guest kind")
    if not isinstance(script_vars, dict) or len(script_vars) > 64:
        raise ProxmoxError("script_vars must be a map with up to 64 entries")
    reserved = CONTROL_ENV | set(LXC_FIELDS.values()) | set(VM_FIELDS.values())
    result = {}
    total = 0
    for key, value in script_vars.items():
        if (not isinstance(key, str) or len(key) > 128 or
                not ENV_IDENTIFIER.fullmatch(key) or key in reserved or
                any(key.startswith(prefix) for prefix in CONTROL_PREFIXES)):
            raise ProxmoxError("Invalid, protected, or normalized script_vars key")
        if key in standard_env:
            raise ProxmoxError("script_vars cannot override a configured field")
        if value is None or isinstance(value, (dict, list, tuple, bool)):
            raise ProxmoxError("script_vars values must be string or number; express booleans explicitly")
        converted = str(value)
        if any(char in converted for char in ("\x00", "\n", "\r")):
            raise ProxmoxError("script_vars values contain forbidden control characters")
        total += len(key.encode("utf-8")) + len(converted.encode("utf-8"))
        if total > 32768:
            raise ProxmoxError("script_vars exceed 32 KiB")
        result[key] = converted
    return result

NUMERIC = frozenset({"cores", "memory", "disk_size", "vlan", "mtu"})
BOOL = frozenset({"privileged", "start"})
BINARY = frozenset({"nesting", "keyctl", "mknod"})
LXC_YESNO = frozenset({"tun", "fuse", "protection", "gpu", "apt_cacher", "inherit_host_ca"})
# vm_apply_env_overrides evaluates VM_CPU only as host vs its default.
VM_CPU_TYPES = frozenset({"host"})
VM_CACHE = {"writethrough": "cache=writethrough,", "none": "cache=none,"}
VM_MACHINES = frozenset({"q35", "i440fx"})



def validate_spec(kind, script, vmid, scripts_ref, core_ref, settings, require_pins=True):
    if kind not in ("lxc", "vm"):
        raise ProxmoxError("kind must be lxc or vm")
    if not isinstance(script, str) or not SLUG.fullmatch(script):
        raise ProxmoxError("script must be a safe Community Scripts slug")
    if isinstance(vmid, bool) or not isinstance(vmid, int) or not 100 <= vmid <= 999999999:
        raise ProxmoxError("VMID must be an integer in Proxmox guest range")
    for label, value in (("scripts_ref", scripts_ref), ("core_ref", core_ref)):
        if require_pins and (not isinstance(value, str) or not SHA.fullmatch(value)):
            raise ProxmoxError("%s must be an immutable 40-character Git SHA" % label)
    if not isinstance(settings, dict):
        raise ProxmoxError("settings must be a mapping")
    fields = LXC_FIELDS if kind == "lxc" else VM_FIELDS
    unknown = set(settings) - set(fields)
    if unknown:
        raise ProxmoxError("Unsupported %s creation fields: %s" % (kind, ", ".join(sorted(unknown))))
    for key, value in settings.items():
        if key in BOOL and value not in (True, False, "true", "false", "yes", "no", 0, 1, "0", "1"):
            raise ProxmoxError("Invalid boolean creation field: %s" % key)
        if value is None or isinstance(value, (dict, list)):
            raise ProxmoxError("Creation setting %s requires a scalar" % key)
        if key in BINARY and value not in (0, 1, "0", "1", False, True):
            raise ProxmoxError("Invalid binary creation field: %s" % key)
        if key == "mac" and not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", str(value)):
            raise ProxmoxError("Invalid MAC address")
        if key in LXC_YESNO and value not in (True, False, "true", "false", "yes", "no", 0, 1, "0", "1"):
            raise ProxmoxError("Invalid yes/no creation field: %s" % key)
        if kind == "vm" and key == "cpu_type" and value not in VM_CPU_TYPES:
            raise ProxmoxError("VM cpu_type supports only 'host' via shared Core")
        if kind == "vm" and key == "disk_cache" and value not in VM_CACHE:
            raise ProxmoxError("VM disk_cache must be none or writethrough")
        if kind == "vm" and key == "machine" and value not in VM_MACHINES:
            raise ProxmoxError("VM machine must be q35 or i440fx")
        if key == "ipv6_method" and value not in ("none", "auto", "dhcp"):
            raise ProxmoxError("Static IPv6 requires verified upstream Core wiring")
        if key in NUMERIC:
            if isinstance(value, bool) or not str(value).isdigit() or int(value) < (0 if key == "vlan" else 1):
                raise ProxmoxError("Invalid numeric creation field: %s" % key)
            if key == "vlan" and int(value) not in range(1, 4095):
                raise ProxmoxError("VLAN must be in 1-4094; omit vlan to use an untagged interface")
            if key == "mtu" and not 576 <= int(value) <= 65535:
                raise ProxmoxError("MTU must be 576-65535")
            if key == "cores" and int(value) > 128:
                raise ProxmoxError("cores must be <= 128")
            if key == "memory" and int(value) < 256:
                raise ProxmoxError("memory must be at least 256 MiB")
        if key == "dns" and kind == "lxc":
            try:
                ipaddress.ip_address(str(value))
            except ValueError:
                raise ProxmoxError("LXC dns must be an IP address") from None
        if key == "apt_cacher_ip":
            # Core accepts an HTTP(S) URL, hostname[:port] or IP address.
            if (not isinstance(value, str) or len(value) > 512 or
                    not re.fullmatch(r"(?:https?://)?[A-Za-z0-9.:\[\]_-]+(?:/[A-Za-z0-9._/+~-]*)?", value)):
                raise ProxmoxError("apt_cacher_ip must be a host, IP or HTTP(S) URL")
        if key == "mount_fs" and not re.fullmatch(r"[a-zA-Z0-9_+-]+(?:,[a-zA-Z0-9_+-]+)*", str(value)):
            raise ProxmoxError("mount_fs must be a comma-separated filesystem list")
        if key == "timezone" and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_+.-]*(?:/[A-Za-z0-9_+.-]+)*", str(value)):
            raise ProxmoxError("Invalid timezone name")
        if key == "ipv4" and value != "dhcp":
            try:
                ipaddress.ip_interface(str(value))
            except ValueError:
                raise ProxmoxError("ipv4 must be dhcp or IP/CIDR") from None
        if key == "gateway":
            try:
                ipaddress.ip_address(str(value))
            except ValueError:
                raise ProxmoxError("gateway must be an IP address") from None
        if key == "os" and not re.fullmatch(r"[a-z][a-z0-9-]*", str(value)):
            raise ProxmoxError("Invalid OS family")
        if key == "os_version" and not re.fullmatch(r"[A-Za-z0-9.]+", str(value)):
            raise ProxmoxError("Invalid OS version")
        if key == "hostname" and not NAME.fullmatch(str(value)):
            raise ProxmoxError("Invalid hostname")
        if isinstance(value, str) and ("\x00" in value or "\n" in value or "\r" in value):
            raise ProxmoxError("Control characters forbidden in %s" % key)
    return fields


def create_environment(kind, vmid, scripts_ref, core_ref, settings, fields=None, script_vars=None):
    fields = fields or (LXC_FIELDS if kind == "lxc" else VM_FIELDS)
    environment = {
        "COMMUNITY_SCRIPTS_URL":
            "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/" + scripts_ref,
        "COMMUNITY_SCRIPTS_CORE_URL":
            "https://raw.githubusercontent.com/community-scripts/core/" + core_ref,
        "PHS_SILENT": "1",
        "TERM": "dumb",
    }
    if kind == "lxc":
        environment.update({"mode": "generated", "MODE": "generated",
                            "var_ctid": str(vmid), "var_unattended": "yes"})
    else:
        environment.update({"VM_UNATTENDED": "1", "VM_VMID": str(vmid)})
    for key, value in settings.items():
        if key == "privileged":
            environment[fields[key]] = "0" if value in (True, "true", "yes", 1, "1") else "1"
        elif key == "start":
            environment[fields[key]] = "yes" if value in (True, "true", "yes", 1, "1") else "no"
        elif key in LXC_YESNO:
            environment[fields[key]] = "yes" if value in (True, "true", "yes", 1, "1") else "no"
        elif key in BINARY:
            environment[fields[key]] = "1" if value in (True, "true", "yes", 1, "1") else "0"
        elif key == "disk_cache" and kind == "vm":
            environment[fields[key]] = VM_CACHE[value]
        elif key == "disk_size" and kind == "vm":
            environment[fields[key]] = str(value) + "G"
        else:
            environment[fields[key]] = str(value)
    environment.update(validate_script_vars(kind, script_vars or {}, environment))
    return environment


def deployment_decision(resources, vmid, kind, script, existing_config=None,
                        allow_unknown_existing=False):
    """Classify an existing VMID without creating or mutating any guest."""
    matches = [r for r in resources if r.get("vmid") == vmid]
    if len(matches) > 1:
        raise ProxmoxError("Duplicate VMID in cluster inventory")
    if not matches:
        return {"exists": False, "needs_create": True, "changed": True}
    resource = matches[0]
    expected_type = "lxc" if kind == "lxc" else "qemu"
    if resource.get("type") != expected_type:
        raise ProxmoxError("VMID collision: existing resource type differs")
    if existing_config is None:
        raise ProxmoxError("Existing resource must be inspected before adoption")
    found = detect_script(existing_config, expected_type)
    if found != script:
        if found is not None or not allow_unknown_existing:
            raise ProxmoxError(
                "VMID already exists without matching, verified script identity"
            )
        return {"exists": True, "needs_create": False, "changed": False,
                "resource": resource, "detected_script": None,
                "identity_requires_host_check": True}
    return {"exists": True, "needs_create": False, "changed": False,
            "resource": resource, "detected_script": found}


SSH_KEY = re.compile(r"^(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-[A-Za-z0-9-]+) [A-Za-z0-9+/=]+(?: [^\r\n]+)?$")
CI_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def guest_access_environment(kind, ssh=None, cloud_init=None, vmid=None, key_directory=None):
    """Translate a shared SSH + optional cloud-init schema into Core env vars.

    For QEMU, public keys are supplied as a PVE-host file consumed by
    vm/cloud-init.func. The caller is responsible for copying that file
    before execution. Never assume an appliance image includes sshd.
    """
    ssh = {} if ssh is None else ssh
    cloud_init = {} if cloud_init is None else cloud_init
    if not isinstance(ssh, dict) or set(ssh) - {"enabled", "public_keys"}:
        raise ProxmoxError("ssh allows only enabled and public_keys")
    if not isinstance(cloud_init, dict) or set(cloud_init) - {
        "enabled", "user", "network_mode", "ip", "gateway", "dns"
    }:
        raise ProxmoxError("Unsupported cloud_init option")
    enabled = ssh.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise ProxmoxError("ssh.enabled must be true, false, or omitted")
    keys = ssh.get("public_keys", [])
    if not isinstance(keys, list) or len(keys) > 8 or any(
        not isinstance(k, str) or len(k) > 8192 or not SSH_KEY.fullmatch(k)
        for k in keys
    ):
        raise ProxmoxError("ssh.public_keys must contain up to 8 OpenSSH public keys")
    if len(keys) != len(set(keys)):
        raise ProxmoxError("Duplicate SSH public keys")
    if keys and enabled is False:
        raise ProxmoxError("Cannot install public keys with ssh.enabled=false")
    if kind == "lxc":
        if cloud_init:
            raise ProxmoxError("Cloud-init settings apply only to VMs")
        env = {}
        if enabled is not None or keys:
            env["var_ssh"] = "yes" if enabled or keys else "no"
        if keys:
            env["var_ssh_authorized_key"] = "\n".join(keys)
        return {"environment": env, "public_keys": keys, "cloud_init_requested": False}
    if kind != "vm":
        raise ProxmoxError("Unsupported guest kind")
    if enabled is False:
        raise ProxmoxError("VM SSH service disabling is guest-specific, not a cloud-init option")
    if enabled is True and not keys:
        raise ProxmoxError("VM ssh.enabled=true requires at least one public key")
    ci_enabled = cloud_init.get("enabled", False)
    if not isinstance(ci_enabled, bool):
        raise ProxmoxError("cloud_init.enabled must be a boolean")
    if (keys or enabled is True or set(cloud_init) - {"enabled"}) and not ci_enabled:
        raise ProxmoxError("VM SSH keys and cloud-init fields require cloud_init.enabled=true")
    if ci_enabled and enabled is False:
        raise ProxmoxError("cloud-init with ssh.enabled=false is not a supported SSH policy")
    # Omitted cloud-init must not override script defaults or CLOUDINIT_REQUIRED.
    env = {} if not cloud_init else {"VM_CLOUD_INIT": "yes" if ci_enabled else "no"}
    if not ci_enabled:
        return {"environment": env, "public_keys": [], "cloud_init_requested": False}
    if cloud_init.get("user") is not None:
        user = cloud_init["user"]
        if not isinstance(user, str) or not CI_USER.fullmatch(user):
            raise ProxmoxError("Invalid cloud-init username")
        env["CLOUDINIT_USER"] = user
    mode = cloud_init.get("network_mode", "dhcp")
    if mode not in ("dhcp", "static"):
        raise ProxmoxError("cloud_init.network_mode must be dhcp or static")
    env["CLOUDINIT_NETWORK_MODE"] = mode
    if mode == "static":
        try:
            ipaddress.ip_interface(cloud_init["ip"])
            ipaddress.ip_address(cloud_init["gateway"])
        except (KeyError, ValueError, TypeError):
            raise ProxmoxError("Static cloud-init requires a valid IP/CIDR and gateway") from None
        env["CLOUDINIT_IP"] = cloud_init["ip"]
        env["CLOUDINIT_GW"] = cloud_init["gateway"]
    elif cloud_init.get("ip") or cloud_init.get("gateway"):
        raise ProxmoxError("Static cloud-init IP/gateway provided in DHCP mode")
    if "dns" in cloud_init:
        dns = cloud_init["dns"]
        if not isinstance(dns, list) or not 1 <= len(dns) <= 4:
            raise ProxmoxError("cloud_init.dns must be a list of 1-4 IP addresses")
        try:
            for address in dns:
                ipaddress.ip_address(address)
        except (ValueError, TypeError):
            raise ProxmoxError("cloud_init.dns contains an invalid address") from None
        env["CLOUDINIT_DNS"] = " ".join(dns)
    if keys:
        if not key_directory or vmid is None:
            raise ProxmoxError("VM cloud-init keys require a host key directory and VMID")
        if not re.fullmatch(r"/[A-Za-z0-9/_.-]+", key_directory) or ".." in key_directory:
            raise ProxmoxError("Invalid SSH key staging directory")
        env["CLOUDINIT_SSH_KEYS"] = key_directory.rstrip("/") + "/vm-" + str(vmid) + ".pub"
    return {"environment": env, "public_keys": keys, "cloud_init_requested": True}
