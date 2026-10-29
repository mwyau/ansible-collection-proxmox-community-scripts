#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Read-only planning for pinned Community Scripts deployment."""
from __future__ import annotations

DOCUMENTATION = r'''
---
module: deployment_plan
short_description: Plan creation or no-op of a pinned Community Scripts guest
description:
  - Inspects cluster VMIDs and verifies script identity on existing resources.
  - Produces validated common Core creation environment without executing scripts.
  - Requires immutable Git commit SHAs for the scripts and Core repositories.
  - No resource mutations occur, even outside Ansible check mode.
options:
  api_host:
    type: str
    required: true
    description: Proxmox HTTPS API origin or hostname.
  api_token_id:
    type: str
    required: true
    description: Full Proxmox API token identifier.
  api_token_secret:
    type: str
    required: true
    no_log: true
    description: Proxmox API token secret.
  validate_certs:
    type: bool
    default: true
    description: Validate the server certificate.
  vmid:
    type: int
    required: true
    description: Exact VMID to use; never automatically reassign.
  node:
    type: str
    required: true
    description: Required Proxmox node for creation or matching existing guest.
  kind:
    type: str
    choices: [lxc, vm]
    required: true
    description: Deployment kind.
  script:
    type: str
    required: true
    description: Community Scripts file basename without .sh.
  scripts_ref:
    type: str
    default: ''
    description: Immutable Git SHA for creation; optional when the guest exists.
  core_ref:
    type: str
    default: ''
    description: Immutable Git SHA for creation; optional when the guest exists.
  settings:
    type: dict
    default: {}
    description: Common installer fields such as cores, memory, disk_size, hostname, bridge and storage.
  script_vars:
    type: dict
    default: {}
    description: Opt-in app-specific Core variables for creation; secret values require Vault.
  allow_unknown_existing:
    type: bool
    default: false
    description: Read-only staging flag for host-assisted identification of legacy guests.
  ssh:
    type: dict
    default: {}
    description: Normalized SSH options with enabled and public_keys.
  cloud_init:
    type: dict
    default: {}
    description: VM-only cloud-init options (enabled, user, network_mode, ip, gateway, dns).
  ssh_key_directory:
    type: str
    default: /var/lib/ansible-community-scripts/keys
    description: Root-protected PVE host staging directory for VM cloud-init public keys.
  timeout:
    type: int
    default: 20
    description: HTTPS API request timeout.
author:
  - Albert Yau
'''

EXAMPLES = r'''
- name: Plan a pinned LXC installation without touching the host
  mwyau.proxmox_community_scripts.deployment_plan:
    api_host: pve.example.internal
    api_token_id: "{{ proxmox_token_id }}"
    api_token_secret: "{{ proxmox_token_secret }}"
    node: pve1
    kind: lxc
    vmid: 120
    script: adguard
    scripts_ref: "0123456789abcdef0123456789abcdef01234567"
    core_ref: "0123456789abcdef0123456789abcdef01234567"
    settings:
      cores: 2
      memory: 1024
      disk_size: 8
'''

RETURN = r'''
needs_create:
  type: bool
  returned: always
  description: Whether the requested VMID is absent and requires installation.
exists:
  type: bool
  returned: always
  description: Whether an identical script identity already occupies the VMID.
environment:
  type: dict
  returned: always
  description: Non-secret environment overrides for a guarded installer.
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mwyau.proxmox_community_scripts.plugins.module_utils.core import (
    ProxmoxAPI, ProxmoxError, resource_path,
)
from ansible_collections.mwyau.proxmox_community_scripts.plugins.module_utils.deployment import (
    validate_spec, create_environment, deployment_decision, guest_access_environment,
)


def run():
    module = AnsibleModule(
        argument_spec={
            "api_host": {"type": "str", "required": True},
            "api_token_id": {"type": "str", "required": True, "no_log": True},
            "api_token_secret": {"type": "str", "required": True, "no_log": True},
            "validate_certs": {"type": "bool", "default": True},
            "vmid": {"type": "int", "required": True},
            "node": {"type": "str", "required": True},
            "kind": {"type": "str", "choices": ["lxc", "vm"], "required": True},
            "script": {"type": "str", "required": True},
            "scripts_ref": {"type": "str", "default": ""},
            "core_ref": {"type": "str", "default": ""},
            "settings": {"type": "dict", "default": {}},
            "ssh": {"type": "dict", "default": {}},
            "allow_unknown_existing": {"type": "bool", "default": False},
            "cloud_init": {"type": "dict", "default": {}},
            "ssh_key_directory": {"type": "str", "default": "/var/lib/ansible-community-scripts/keys"},
            "script_vars": {"type": "dict", "default": {}, "no_log": True},
            "timeout": {"type": "int", "default": 20},
        }, supports_check_mode=True,
    )
    p = module.params
    try:
        fields = validate_spec(p["kind"], p["script"], p["vmid"],
                               p["scripts_ref"], p["core_ref"], p["settings"],
                               require_pins=False)
        if not p["node"] or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._"
                               for c in p["node"]):
            raise ProxmoxError("Invalid Proxmox node")
        api = ProxmoxAPI(p["api_host"], p["api_token_id"], p["api_token_secret"],
                         p["validate_certs"], p["timeout"])
        resources = api.request("GET", "/cluster/resources?type=vm")
        if not isinstance(resources, list):
            raise ProxmoxError("Unexpected cluster resources response")
        exact = [x for x in resources if x.get("vmid") == p["vmid"]]
        config = api.request("GET", resource_path(exact[0]) + "/config") if len(exact) == 1 else None
        result = deployment_decision(resources, p["vmid"], p["kind"], p["script"], config,
                                     allow_unknown_existing=p["allow_unknown_existing"])
        if result["exists"] and result["resource"]["node"] != p["node"]:
            raise ProxmoxError("Existing guest belongs to a different PVE node")
        guest_access = {"environment": {}, "public_keys": [],
                        "cloud_init_requested": False}
        env = {}
        if result["needs_create"]:
            fields = validate_spec(p["kind"], p["script"], p["vmid"],
                                   p["scripts_ref"], p["core_ref"], p["settings"],
                                   require_pins=True)
            guest_access = guest_access_environment(
                p["kind"], p["ssh"], p["cloud_init"], p["vmid"], p["ssh_key_directory"])
            env = create_environment(p["kind"], p["vmid"], p["scripts_ref"],
                                     p["core_ref"], p["settings"], fields,
                                     script_vars=p["script_vars"])
            clashes = set(env) & set(guest_access["environment"])
            if clashes:
                raise ProxmoxError("Script variables conflict with SSH/cloud-init settings: "
                                   + ", ".join(sorted(clashes)))
            env.update(guest_access["environment"])
        module.exit_json(**{**result, "would_create": result["needs_create"], "changed": False},
                         environment=env, guest_access=guest_access, node=p["node"],
                         script=p["script"], kind=p["kind"])
    except ProxmoxError as exc:
        module.fail_json(msg=str(exc), changed=False)


if __name__ == "__main__":
    run()
