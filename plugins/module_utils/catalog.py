"""Self-contained Ansible runtime catalog adapter.

Bulk upstream scans and advisory recipe status live in proxmox-community-scripts-iac-common.
This small parser stays bundled so Ansible Galaxy installations work offline.
"""
import re

try:
    from .retirement import retired_info
except ImportError:
    from retirement import retired_info

# Verified source-based retirement snapshot at ProxmoxVE 502bd98c.
# This is a conservative catalog cache, not a claim that other files are active.
# A selected script is always checked from source at its requested ref.
KNOWN_RETIRED = {
    "lxc/booklore": {"reason": "removed", "successor": None},
    "lxc/litellm": {"reason": "removed", "successor": None},
    "lxc/minio": {"reason": "removed", "successor": None},
    "lxc/musicseerr": {"reason": "renamed", "successor": "droppedneedle"},
}


def exclude_retired(scripts, source_lookup=None):
    """Return candidates and excluded entries, fail-closed for known retired slugs.

    source_lookup is an optional callback used for precise, revision-specific
    verification of named scripts; catalog listing alone cannot prove status.
    """
    included = {}
    excluded = {}
    for name, entry in scripts.items():
        result = None
        if source_lookup is not None:
            source = source_lookup(entry)
            result = retired_info(source, entry["kind"])
        if result is None and name in KNOWN_RETIRED:
            # If actual source is verified and no longer retired, permit revival.
            if source_lookup is None:
                result = {"status": "retired", **KNOWN_RETIRED[name]}
        if result:
            excluded[name] = {**entry, **result}
        else:
            included[name] = {**entry, "retirement_check": "source" if source_lookup else "catalog_cache"}
    return included, excluded

SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]+$")


def parse_directory(entries, kind, ref):
    if kind not in ("lxc", "vm"):
        raise ValueError("kind must be lxc or vm")
    if not SAFE_REF.fullmatch(ref) or ".." in ref:
        raise ValueError("Unsafe Git reference")
    if not isinstance(entries, list):
        raise ValueError("Unexpected GitHub contents listing")
    directory = "ct" if kind == "lxc" else "vm"
    result = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "file":
            continue
        filename = entry.get("name", "")
        if not filename.endswith(".sh"):
            continue
        slug = filename[:-3]
        if not SAFE_SLUG.fullmatch(slug):
            continue
        if entry.get("path") != directory + "/" + filename:
            continue
        sha = entry.get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
            continue
        result[slug] = {
            "kind": kind, "slug": slug, "blob_sha": sha,
            "path": entry["path"], "ref": ref,
            "source_url": "https://github.com/community-scripts/ProxmoxVE/blob/" + ref + "/" + entry["path"],
        }
    return result


def catalog_diff(current, baseline):
    """Compare blob revisions without installing/updating applications."""
    if not isinstance(baseline, dict):
        raise ValueError("baseline must map script slug to Git blob SHA")
    added = sorted(set(current) - set(baseline))
    removed = sorted(set(baseline) - set(current))
    updated = sorted(name for name in current.keys() & baseline.keys()
                     if current[name]["blob_sha"] != baseline[name])
    return {"added": added, "removed": removed, "updated": updated}
