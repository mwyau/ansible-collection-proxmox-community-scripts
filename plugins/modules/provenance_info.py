#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Resolve Community Scripts provenance from PVE metadata and optional LXC updater."""
DOCUMENTATION = r'''
---
module: provenance_info
short_description: Assess Community Scripts identity without mutating a guest
description:
  - Combines Proxmox description/tags with optionally inspected LXC /usr/bin/update text.
  - Reports verified, unknown, or conflicting provenance, including evidence sources.
  - Does not assume a generic Community Scripts tag proves a script identity.
  - This is source metadata evidence, not cryptographic attestation.
options:
  kind:
    type: str
    required: true
    choices: [lxc, vm]
    description: Guest kind.
  config:
    type: dict
    required: true
    description: Guest configuration fetched from Proxmox API.
  update_entrypoint:
    type: str
    description: Optional LXC /usr/bin/update contents, retrieved read-only through pct.
  script_override:
    type: str
    description: Explicit script slug for unknown provenance only; conflicting evidence still fails.
  expected_script:
    type: str
    description: Expected application script slug.
author:
  - Albert Yau
'''
EXAMPLES = r'''
- name: Assess a legacy LXC without modifying it
  mwyau.proxmox_community_scripts.provenance_info:
    kind: lxc
    config: "{{ inspected.config }}"
    update_entrypoint: "{{ updater_file.stdout | default(omit) }}"
    expected_script: adguard
'''
RETURN = r'''
provenance:
  type: dict
  returned: always
  description: Identity status, candidate slug, evidence and context.
'''
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mwyau.proxmox_community_scripts.plugins.module_utils.provenance import provenance, apply_script_override


def main():
    m = AnsibleModule(argument_spec={
        "kind": {"type": "str", "required": True, "choices": ["lxc", "vm"]},
        "config": {"type": "dict", "required": True},
        "update_entrypoint": {"type": "str", "no_log": True},
        "expected_script": {"type": "str"},
        "script_override": {"type": "str"},
    }, supports_check_mode=True)
    try:
        result = provenance(m.params["config"], m.params["kind"],
                            m.params["update_entrypoint"], m.params["expected_script"])
        result = apply_script_override(result, m.params["script_override"],
                                       m.params["expected_script"])
    except (ValueError, TypeError) as e:
        m.fail_json(msg=str(e))
    m.exit_json(changed=False, provenance=result)


if __name__ == "__main__":
    main()
