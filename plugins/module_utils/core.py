"""Pure Proxmox API and resource-planning helpers.

No Ansible dependency here so reconciliation decisions can be unit tested.
"""
from __future__ import annotations

import json
import re
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, quote
from urllib.request import Request, urlopen


class ProxmoxError(Exception):
    """Expected API, validation or safety failure."""


class ProxmoxAPI:
    def __init__(self, host, token_id, token_secret, verify_tls=True, timeout=20):
        host = host.rstrip("/")
        if "://" not in host:
            host = "https://" + host
        parts = urlsplit(host)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ProxmoxError("api_host must be a host or HTTPS origin with no path or credentials")
        if not parts.port:
            host += ":8006"
        self.base = host + "/api2/json"
        self.token = "PVEAPIToken=" + token_id + "=" + token_secret
        self.context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
        self.timeout = timeout

    def request(self, method, path, data=None):
        if not path.startswith("/") or "//" in path or ".." in path:
            raise ProxmoxError("Invalid Proxmox API path")
        body = urlencode(data, doseq=True).encode("utf-8") if data is not None else None
        req = Request(
            self.base + path,
            data=body,
            headers={"Authorization": self.token, "Accept": "application/json",
                     "Content-Type": "application/x-www-form-urlencoded"},
            method=method,
        )
        try:
            with urlopen(req, context=self.context, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as exc:
            # Do not echo request bodies, tokens or raw response contents.
            raise ProxmoxError("Proxmox API HTTP %s for %s" % (exc.code, path)) from None
        except (URLError, OSError, ValueError) as exc:
            raise ProxmoxError("Proxmox API connection or response error: %s" % type(exc).__name__) from None
        if not isinstance(payload, dict) or "data" not in payload:
            raise ProxmoxError("Proxmox API returned an unexpected response")
        return payload["data"]


def locate_resource(resources, vmid, kind=None, node=None):
    """Resolve an exact VMID from /cluster/resources?type=vm."""
    matches = [entry for entry in resources if int(entry.get("vmid", -1)) == int(vmid)]
    if not matches:
        raise ProxmoxError("VMID %s does not exist; creation is not implemented" % vmid)
    if len(matches) != 1:
        raise ProxmoxError("VMID %s has ambiguous cluster inventory" % vmid)
    found = matches[0]
    if found.get("type") not in ("lxc", "qemu"):
        raise ProxmoxError("VMID is not an LXC or QEMU guest")
    if kind and found["type"] != ("qemu" if kind == "vm" else kind):
        raise ProxmoxError("VMID %s has a different resource type" % vmid)
    if node and found.get("node") != node:
        raise ProxmoxError("VMID %s is on node %s, not %s" % (vmid, found.get("node"), node))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", found.get("node", "")):
        raise ProxmoxError("Invalid node name from Proxmox")
    return found


def resource_path(entry):
    return "/nodes/%s/%s/%d" % (quote(entry["node"], safe=""), entry["type"], int(entry["vmid"]))


def detect_script(config, kind):
    """Return script only when native PVE metadata gives unambiguous evidence."""
    try:
        from .provenance import provenance
    except ImportError:  # local unit tests import core as a top-level module
        from provenance import provenance
    identity = provenance(config, kind)
    if identity["status"] == "conflicting":
        raise ProxmoxError("Conflicting script identity metadata")
    return identity["script"]


def verify_identity(config, kind, expected_script=None, adopt=False, update_entrypoint=None):
    """Validate API metadata plus optional read-only LXC updater evidence."""
    try:
        from .provenance import provenance
    except ImportError:  # local unit tests import core as a top-level module
        from provenance import provenance
    try:
        identity = provenance(config, kind, update_entrypoint, expected_script)
    except (ValueError, TypeError) as exc:
        raise ProxmoxError(str(exc)) from None
    if identity["status"] == "conflicting":
        raise ProxmoxError("Installed script identity conflicts with expected_script")
    if identity["status"] == "unknown" and not adopt:
        raise ProxmoxError("Script identity is unverified; obtain LXC updater evidence or explicitly adopt")
    if not expected_script and not adopt:
        raise ProxmoxError("Reconciliation requires expected_script or explicit adoption")
    return identity["script"]


LXC_FIELDS = {
    "cores", "memory", "swap", "cpulimit", "cpuunits", "onboot",
    "hostname", "nameserver", "searchdomain", "protection",
    "description", "tags",
}
VM_FIELDS = {
    "cores", "sockets", "cpu", "memory", "balloon", "onboot",
    "agent", "numa", "description", "tags", "name",
}
NUMERIC_FIELDS = {"cores", "memory", "swap", "cpulimit", "cpuunits", "sockets", "balloon", "onboot", "protection", "numa"}
SAFE_DISK_KEYS = re.compile(r"^(?:rootfs|(?:scsi|virtio|sata|ide)\d+)$")
SIZE_RE = re.compile(r"(?:^|,)size=(\d+(?:\.\d+)?)([KMGT])(?:,|$)", re.I)


def _equal(actual, desired, field):
    if field == "tags":
        return set(filter(None, str(actual or "").split(";"))) == set(filter(None, str(desired or "").split(";")))
    if field in NUMERIC_FIELDS:
        try:
            return float(actual) == float(desired)
        except (ValueError, TypeError):
            return False
    return str(actual if actual is not None else "") == str(desired)


def disk_size_gib(disk_config):
    match = SIZE_RE.search(str(disk_config))
    if not match:
        raise ProxmoxError("Cannot determine allocated disk size from Proxmox config")
    value = float(match.group(1))
    return value * {"K": 1 / 1024 / 1024, "M": 1 / 1024, "G": 1, "T": 1024}[match.group(2).upper()]


def plan_changes(config, kind, settings=None, disk=None):
    """Return a non-destructive, normalized plan; never alter config input."""
    if kind not in ("lxc", "qemu"):
        raise ProxmoxError("Unsupported kind")
    settings = settings or {}
    disk = disk or {}
    allowed = LXC_FIELDS if kind == "lxc" else VM_FIELDS
    unknown = set(settings) - allowed
    if unknown:
        raise ProxmoxError("Unsupported %s mutable settings: %s" % (kind, ", ".join(sorted(unknown))))
    update = {}
    for key, desired in settings.items():
        if desired is None or isinstance(desired, (dict, list)):
            raise ProxmoxError("Setting %s must be a scalar, not null or a nested value" % key)
        if key in NUMERIC_FIELDS:
            try:
                number = float(desired)
            except (TypeError, ValueError):
                raise ProxmoxError("Setting %s must be numeric" % key) from None
            if number < 0 or (key in ("cores", "memory", "sockets") and number == 0):
                raise ProxmoxError("Invalid nonpositive setting %s" % key)
        if key == "tags":
            # Additive: never discard unrelated tags including source metadata.
            existing = set(filter(None, str(config.get("tags") or "").split(";")))
            requested = set(filter(None, str(desired).split(";")))
            desired = ";".join(sorted(existing | requested))
        if not _equal(config.get(key), desired, key):
            update[key] = desired
    resize = None
    if disk:
        if set(disk) != {"key", "size_gb"}:
            raise ProxmoxError("disk requires exactly key and size_gb")
        key = str(disk["key"])
        if not SAFE_DISK_KEYS.fullmatch(key) or (kind == "lxc" and key != "rootfs") or (kind == "qemu" and key == "rootfs"):
            raise ProxmoxError("Invalid disk key for resource type")
        if key not in config:
            raise ProxmoxError("Disk %s is not present in resource configuration" % key)
        try:
            target = int(disk["size_gb"])
        except (ValueError, TypeError):
            raise ProxmoxError("disk.size_gb must be a positive integer") from None
        if target <= 0 or str(target) != str(disk["size_gb"]):
            raise ProxmoxError("disk.size_gb must be a positive integer")
        validate_disk_for_resize(config[key], kind, key)
        actual = disk_size_gib(config[key])
        if target + 1e-8 < actual:
            raise ProxmoxError("Refusing disk shrink: existing %.3f GiB > desired %s GiB" % (actual, target))
        if target > actual + 1e-8:
            resize = {"key": key, "size_gb": target, "current_gb": actual}
    return {"settings": update, "resize": resize, "changed": bool(update or resize)}


def wait_for_task(api, node, upid, timeout=300, poll_interval=2):
    """Wait for a Proxmox task UPID; synchronous/empty responses need no polling."""
    if not isinstance(upid, str) or not upid:
        return None
    if not re.fullmatch(r"UPID:[A-Za-z0-9_.-]+:[A-Za-z0-9:_.@!+-]+", upid):
        raise ProxmoxError("Unexpected asynchronous task identifier")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", node):
        raise ProxmoxError("Invalid task node")
    deadline = time.monotonic() + timeout
    path = "/nodes/%s/tasks/%s/status" % (quote(node, safe=""), quote(upid, safe=""))
    while True:
        status = api.request("GET", path)
        if not isinstance(status, dict) or status.get("status") not in ("running", "stopped"):
            raise ProxmoxError("Unexpected Proxmox task status")
        if status["status"] == "stopped":
            if status.get("exitstatus") != "OK":
                raise ProxmoxError("Proxmox task failed: %s" % status.get("exitstatus", "unknown"))
            return status
        if time.monotonic() >= deadline:
            raise ProxmoxError("Proxmox task completion timeout; inspect task status before retrying")
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))


def pending_status(rows, desired_settings=None):
    """Represent effective vs pending PVE configuration without guessing reboot policy.

    /pending returns entries {key, value, pending?, delete?}. A pending value
    means PVE accepted the desired configuration but it is not yet in effect.
    """
    if not isinstance(rows, list):
        raise ProxmoxError("Unexpected Proxmox pending configuration response")
    result = {}
    for entry in rows:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise ProxmoxError("Unexpected Proxmox pending configuration item")
        if "pending" in entry or entry.get("delete"):
            result[entry["key"]] = {
                "current": entry.get("value"),
                "pending": entry.get("pending"),
                "delete": bool(entry.get("delete")),
            }
    desired = desired_settings or {}
    pending_desired = {
        key: value for key, value in result.items()
        if key in desired and not value["delete"]
        and _equal(value.get("pending"), desired[key], key)
    }
    return {
        "pending": result,
        "pending_desired": pending_desired,
        "restart_required_for_requested_settings": bool(pending_desired),
    }


def validate_disk_for_resize(value, kind, key):
    """Only resize a backed volume; reject placeholders and passthrough disks."""
    parts = str(value).split(",")
    volume = parts[0].removeprefix("volume=")
    if (":" not in volume or volume in ("none", "cloudinit") or
            volume.startswith(("/dev/", "/")) or "media=cdrom" in str(value)):
        raise ProxmoxError("Disk %s is not an attached storage volume eligible for safe growth" % key)
    if kind == "qemu" and "cloudinit" in volume:
        raise ProxmoxError("Cannot resize cloud-init placeholder disk")
    return True


def effective_desired_config(config, pending, settings):
    """Treat a matching pending value as satisfied for idempotent planning.

    PVE may keep an accepted CPU/RAM change pending until restart. This does
    not pretend that the active running VM has the new effective value.
    """
    if not isinstance(config, dict) or not isinstance(pending, dict):
        raise ProxmoxError("Invalid config/pending representation")
    result = dict(config)
    for field, value in pending.get("pending_desired", {}).items():
        if field in settings and not value.get("delete"):
            result[field] = settings[field]
    return result
