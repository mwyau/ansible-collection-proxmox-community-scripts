"""Read-only Community Scripts provenance assessment.

Native PVE metadata may be changed by users. A legacy /usr/bin/update file is
additional evidence, not cryptographic attestation. Conflicting evidence must
never be automatically adopted.
"""
import re

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SCRIPT_URL = re.compile(
    r"(?:https?://)?(?:www\.)?community-scripts\.org/scripts/([a-z0-9][a-z0-9-]*)",
    re.I,
)
UPDATE_NAME = re.compile(
    r"""(?m)^\s*(?:export\s+)?(?:SCRIPT_SLUG|UPDATE_SCRIPT_NAME)=["']?([a-z0-9][a-z0-9-]*)["']?\s*$"""
)
UPDATE_CT = re.compile(r"/ct/([a-z0-9][a-z0-9-]*)\.sh(?=[^a-z0-9-]|$)", re.I)
# Strongest source: explicitly declared script slug from generated entrypoint.
UPDATE_SLUG = re.compile(
    r"""(?m)^\s*(?:export\s+)?SCRIPT_SLUG=["']?([a-z0-9][a-z0-9-]*)["']?\s*$"""
)
UPDATE_SCRIPT_NAME = re.compile(
    r"""(?m)^\s*(?:export\s+)?UPDATE_SCRIPT_NAME=["']?([a-z0-9][a-z0-9-]*)["']?\s*$"""
)


def provenance(config, kind, update_entrypoint=None, expected_script=None):
    """Return evidence, candidate, and status: verified/unknown/conflicting.

    Explicit SCRIPT_SLUG takes precedence within the generated updater; a
    separately named UPDATE_SCRIPT_NAME is sometimes an OS name (Debian),
    not the application. Treat a standalone update script name as weak context.
    """
    if kind not in ("lxc", "qemu", "vm"):
        raise ValueError("kind must be lxc or vm")
    if expected_script is not None and not SLUG.fullmatch(expected_script):
        raise ValueError("Invalid expected script slug")
    kind = "qemu" if kind == "vm" else kind
    if not isinstance(config, dict):
        raise ValueError("config must be a dictionary")
    strong = []
    context = []
    description = str(config.get("description") or "")
    for match in SCRIPT_URL.finditer(description):
        strong.append({"source": "proxmox_description", "slug": match.group(1).lower()})
    tags = {x.lower() for x in str(config.get("tags") or "").split(";") if x}
    if kind == "qemu" and {"community-script", "app-deployer"} <= tags:
        # Other tags are arbitrary. Preserve potential slugs as hints only.
        for tag in tags:
            if tag.startswith("script-") and SLUG.fullmatch(tag[7:]):
                strong.append({"source": "vm_script_tag", "slug": tag[7:]})
            elif tag not in {"community-script", "app-deployer", "ansible_managed"}:
                if SLUG.fullmatch(tag):
                    context.append({"source": "vm_app_deployer_tag_hint", "slug": tag})
    if kind == "lxc" and update_entrypoint is not None:
        if not isinstance(update_entrypoint, str):
            raise ValueError("update_entrypoint must be text")
        if len(update_entrypoint) > 64 * 1024:
            raise ValueError("Unexpectedly large updater file")
        generated = UPDATE_SLUG.findall(update_entrypoint)
        for slug in generated:
            strong.append({"source": "lxc_update_script_slug", "slug": slug})
        if not generated:
            for slug in UPDATE_CT.findall(update_entrypoint):
                strong.append({"source": "lxc_update_legacy_url", "slug": slug.lower()})
        for slug in UPDATE_SCRIPT_NAME.findall(update_entrypoint):
            context.append({"source": "lxc_update_target", "slug": slug})
    candidates = sorted({item["slug"] for item in strong})
    if len(candidates) > 1 or (expected_script and candidates and candidates[0] != expected_script):
        status = "conflicting"
    elif candidates:
        status = "verified"
    else:
        status = "unknown"
    return {
        "status": status,
        "script": candidates[0] if len(candidates) == 1 else None,
        "expected_script": expected_script,
        "evidence": strong,
        "context": context,
        "requires_adoption": status == "unknown",
        "warning": ("Metadata and updater content are not cryptographic installation proof."
                    if status == "verified" else None),
    }


def apply_script_override(assessment, override, expected_script=None):
    """Accept an explicit operator-supplied slug only when detection is unknown.

    It never changes what the API or guest actually reported, and it never
    bypasses conflicting positive evidence. Hardware changes remain a
    separately authorized Ansible operation.
    """
    if not isinstance(assessment, dict) or assessment.get("status") not in (
        "verified", "unknown", "conflicting"
    ):
        raise ValueError("Invalid provenance assessment")
    if override in (None, ""):
        return assessment
    if not isinstance(override, str) or not SLUG.fullmatch(override):
        raise ValueError("script_override must be a valid script slug")
    if expected_script and override != expected_script:
        raise ValueError("script_override must match requested script")
    if assessment["status"] == "conflicting":
        raise ValueError("Cannot override conflicting script identity evidence")
    if assessment["status"] == "verified":
        if assessment["script"] != override:
            raise ValueError("Cannot override verified script identity")
        return assessment
    return {
        **assessment,
        "status": "overridden",
        "script": override,
        "override": {"script": override, "source": "operator"},
        "requires_adoption": False,
        "warning": "Operator-supplied identity; upstream script provenance remains unverified.",
    }
