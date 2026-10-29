#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Read GitHub directory metadata for Community Scripts (no execution)."""
from __future__ import annotations

DOCUMENTATION = r'''
---
module: script_catalog
short_description: Discover current Community Scripts LXC and VM script files
description:
  - Reads upstream GitHub contents metadata at an explicit ref without running scripts.
  - New filenames are discovered dynamically; the result does not imply unattended support.
  - Excludes known retirement stubs from directory-wide results using the packaged snapshot.
  - For an explicitly selected slug, verifies the source blob at its listed Git SHA.
  - Unverified directory-wide entries are discovery candidates, not installation approvals.
  - Compares optional baseline blob SHAs to report newly added, removed, or changed scripts.
options:
  kind:
    type: str
    choices: [lxc, vm, all]
    default: all
    description: List LXC, VM, or both script directories.
  ref:
    type: str
    default: main
    description: Git branch, tag or commit; pin immutable refs for deployment.
  script:
    type: str
    description: Optional script slug to select.
  baseline:
    type: dict
    default: {}
    description: Optional map of kind/slug to prior blob SHA, for a read-only change report.
  github_token:
    type: str
    no_log: true
    description: Optional GitHub API token for rate limiting.
  timeout:
    type: int
    default: 20
    description: GitHub API request timeout in seconds.
author:
  - Albert Yau
'''

EXAMPLES = r'''
- name: Discover upstream LXC and VM scripts
  mwyau.proxmox_community_scripts.script_catalog:
    kind: all
    ref: main
  register: catalog

- name: Inspect a script at a pinned revision
  mwyau.proxmox_community_scripts.script_catalog:
    kind: lxc
    ref: "0123456789abcdef0123456789abcdef01234567"
    script: adguard
'''

RETURN = r'''
scripts:
  description: Script entries keyed by kind/slug with source URL and Git blob SHA.
  returned: always
  type: dict
excluded_retired:
  description: Retired script entries filtered from the result.
  returned: always
  type: dict
diff:
  description: Added, removed and changed scripts against the optional baseline.
  returned: always
  type: dict
'''

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mwyau.proxmox_community_scripts.plugins.module_utils.vm_contract import vm_script_evidence
from ansible_collections.mwyau.proxmox_community_scripts.plugins.module_utils.catalog import (
    SAFE_REF, SAFE_SLUG, parse_directory, catalog_diff, exclude_retired
)


def run():
    module = AnsibleModule(
        argument_spec={
            "kind": {"type": "str", "choices": ["lxc", "vm", "all"], "default": "all"},
            "ref": {"type": "str", "default": "main"},
            "script": {"type": "str"},
            "baseline": {"type": "dict", "default": {}},
            "github_token": {"type": "str", "no_log": True},
            "timeout": {"type": "int", "default": 20},
        },
        supports_check_mode=True,
    )
    p = module.params
    if not SAFE_REF.fullmatch(p["ref"]) or ".." in p["ref"]:
        module.fail_json(msg="Invalid Git ref")
    if p["script"] and not SAFE_SLUG.fullmatch(p["script"]):
        module.fail_json(msg="Invalid script slug")
    scripts = {}
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ansible-proxmox-community-scripts"}
    if p["github_token"]:
        headers["Authorization"] = "Bearer " + p["github_token"]
    for kind in (["lxc", "vm"] if p["kind"] == "all" else [p["kind"]]):
        directory = "ct" if kind == "lxc" else "vm"
        url = (
            "https://api.github.com/repos/community-scripts/ProxmoxVE/contents/"
            + directory + "?" + urlencode({"ref": p["ref"]})
        )
        try:
            with urlopen(Request(url, headers=headers), timeout=p["timeout"]) as response:
                entries = json.load(response)
            catalog = parse_directory(entries, kind, p["ref"])
        except (HTTPError, URLError, ValueError, OSError) as exc:
            module.fail_json(msg="GitHub catalog request for %s failed (%s)" % (directory, type(exc).__name__))
        for slug, item in catalog.items():
            if not p["script"] or p["script"] == slug:
                scripts[kind + "/" + slug] = item
    if p["script"] and not scripts:
        module.fail_json(msg="Script slug not found at the requested upstream ref")

    # A directory listing contains Git blob hashes, not application status.
    # Fetch only selected script blobs by immutable SHA; a bulk listing uses
    # the conservative bundled retired snapshot and labels other entries
    # as unverified discovery candidates. Never run downloaded source.
    def read_source(entry):
        url = ("https://api.github.com/repos/community-scripts/ProxmoxVE/git/blobs/"
               + entry["blob_sha"])
        with urlopen(Request(url, headers=headers), timeout=p["timeout"]) as response:
            data = json.load(response)
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            raise ValueError("Unexpected blob encoding")
        raw = base64.b64decode(data["content"], validate=False)
        if len(raw) > 2_000_000:
            raise ValueError("Script blob unexpectedly large")
        return raw.decode("utf-8")

    try:
        scripts, excluded_retired = exclude_retired(
            scripts, source_lookup=read_source if p["script"] else None
        )
    except (HTTPError, URLError, ValueError, OSError, UnicodeError, KeyError) as exc:
        module.fail_json(msg="Could not verify selected source (%s)" % type(exc).__name__)
    if p["script"]:
        for key, entry in scripts.items():
            try:
                source = read_source(entry)
            except (HTTPError, URLError, ValueError, OSError, UnicodeError, KeyError) as exc:
                module.fail_json(msg="Cannot verify script capabilities (%s)" % type(exc).__name__)
            # Explicit opt-in only: VM script needs an actual Cloud-Init setup call.
            entry["capabilities"] = {
                **(vm_script_evidence(source) if entry["kind"] == "vm" else {}),
                "source_inspected": True,
            }
    try:
        diff = catalog_diff(scripts, p["baseline"]) if p["baseline"] else {"added": [], "removed": [], "updated": []}
    except ValueError as exc:
        module.fail_json(msg=str(exc))
    module.exit_json(changed=False, scripts=scripts, excluded_retired=excluded_retired,
                     diff=diff, ref=p["ref"])


if __name__ == "__main__":
    run()
