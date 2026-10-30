#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Inventory Proxmox LXC/QEMU guests with conservative script discovery."""
from __future__ import annotations

DOCUMENTATION = r'''
---
module: resources_info
short_description: Discover existing LXC and QEMU resources and identifiable scripts
description:
  - Lists Proxmox guests through the authenticated HTTPS API.
  - Can read each guest configuration for tags, description and hardware values.
  - Returns unknown when script provenance is not conclusive.
options:
  api_host:
    type: str
    required: true
    description: Proxmox API hostname or HTTPS origin.
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
    description: Validate the Proxmox HTTPS server certificate.
  kind:
    type: str
    choices: [lxc, vm, all]
    default: all
    description: Which guest types to list.
  inspect_config:
    type: bool
    default: true
    description: Fetch each guest configuration for more precise script and hardware discovery.
  timeout:
    type: int
    default: 20
    description: API request timeout in seconds.
author:
  - Albert Yau
'''

EXAMPLES = r'''
- name: Discover existing guests and possible script identity
  mwyau.proxmox_community_scripts.resources_info:
    api_host: pve.example.internal
    api_token_id: "{{ proxmox_token_id }}"
    api_token_secret: "{{ proxmox_token_secret }}"
  register: guests
'''

RETURN = r'''
resources:
  description: Guests with VMID, node, kind, detected script or null, and optionally config.
  type: list
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mwyau.proxmox_community_scripts.plugins.module_utils.core import (
    ProxmoxAPI, ProxmoxError, resource_path, detect_script
)


def run():
    module = AnsibleModule(
        argument_spec={
            "api_host": {"type": "str", "required": True},
            "api_token_id": {"type": "str", "required": True, "no_log": True},
            "api_token_secret": {"type": "str", "required": True, "no_log": True},
            "validate_certs": {"type": "bool", "default": True},
            "kind": {"type": "str", "choices": ["lxc", "vm", "all"], "default": "all"},
            "inspect_config": {"type": "bool", "default": True},
            "timeout": {"type": "int", "default": 20},
        }, supports_check_mode=True,
    )
    p = module.params
    try:
        api = ProxmoxAPI(
            p["api_host"], p["api_token_id"], p["api_token_secret"],
            verify_tls=p["validate_certs"], timeout=p["timeout"],
        )
        resources = api.request("GET", "/cluster/resources?type=vm")
        if not isinstance(resources, list):
            raise ProxmoxError("Unexpected Proxmox resource listing")
        results = []
        expected = {"lxc"} if p["kind"] == "lxc" else {"qemu"} if p["kind"] == "vm" else {"lxc", "qemu"}
        for entry in resources:
            if entry.get("type") not in expected:
                continue
            data = {
                "vmid": entry.get("vmid"), "node": entry.get("node"),
                "kind": "vm" if entry["type"] == "qemu" else "lxc",
                "name": entry.get("name"), "status": entry.get("status"),
                "detected_script": None,
            }
            if p["inspect_config"]:
                config = api.request("GET", resource_path(entry) + "/config")
                if not isinstance(config, dict):
                    raise ProxmoxError("Unexpected resource config response")
                data["config"] = config
                data["detected_script"] = detect_script(config, entry["type"])
            results.append(data)
        module.exit_json(changed=False, resources=sorted(results, key=lambda item: int(item["vmid"])))
    except ProxmoxError as exc:
        module.fail_json(msg=str(exc))


if __name__ == "__main__":
    run()
