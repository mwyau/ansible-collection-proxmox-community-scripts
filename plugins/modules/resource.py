#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Inspect and safely reconcile EXISTING Proxmox LXC/QEMU hardware."""
from __future__ import annotations

DOCUMENTATION = r'''
---
module: resource
short_description: Inspect or reconcile an existing Community Scripts Proxmox resource
description:
  - Uses the Proxmox HTTPS API only; SSH is not required.
  - Resolves the requested VMID across the cluster and rejects kind/node mismatches.
  - Reconciles supported hardware settings and grow-only disks without rerunning installers.
  - Does not create resources or update installed applications.
options:
  api_host:
    type: str
    required: true
    description: HTTPS Proxmox API origin or hostname (port 8006 by default).
  api_token_id:
    type: str
    required: true
    description: Full token identifier, such as ansible@pve!hardware.
  api_token_secret:
    type: str
    required: true
    no_log: true
    description: Token secret; supply through Vault or an environment lookup.
  validate_certs:
    type: bool
    default: true
    description: Validate the Proxmox HTTPS server certificate.
  vmid:
    type: int
    required: true
    description: Existing resource ID; this module does not create guests.
  node:
    type: str
    description: Optional expected PVE node; auto-discovered if omitted.
  kind:
    type: str
    choices: [lxc, vm]
    description: Optional expected kind; auto-discovered if omitted.
  action:
    type: str
    choices: [inspect, plan, reconcile]
    default: inspect
    description: Read-only inspect, read-only diff planning, or apply supported mutations.
  expected_script:
    type: str
    description: Expected Community Scripts slug for positive identity verification.
  update_entrypoint:
    type: str
    no_log: true
    description: Optional read-only LXC /usr/bin/update contents for legacy identity verification.
  script_override:
    type: str
    description: Operator-asserted script slug when native and guest source evidence is unknown; cannot mask conflicts.
  adopt:
    type: bool
    default: false
    description:
      - Explicitly allow modifying a resource whose script identity cannot be proven.
      - Never overrides a positively detected conflicting identity.
  settings:
    type: dict
    default: {}
    description:
      - Mutable Proxmox fields. LXC supports cores, memory, swap, cpulimit,
        cpuunits, onboot, hostname, nameserver, searchdomain, protection,
        description, tags. QEMU supports cores, sockets, cpu, memory,
        balloon, onboot, agent, numa, description, tags, name.
      - Tags are additive and preserve existing values.
      - No network or disk-volume replacement is supported.
  disk:
    type: dict
    default: {}
    description:
      - Optional grow-only disk request, with key and size_gb.
      - For LXC use rootfs. For QEMU specify a configured disk, e.g. scsi0.
  timeout:
    type: int
    default: 20
    description: API request timeout in seconds.
author:
  - Albert Yau
'''

EXAMPLES = r'''
- name: Inspect existing LXC without changing it
  mwyau.proxmox_community_scripts.resource:
    api_host: pve.example.internal
    api_token_id: "{{ proxmox_token_id }}"
    api_token_secret: "{{ proxmox_token_secret }}"
    vmid: 120

- name: Reconcile known Community Scripts VM
  mwyau.proxmox_community_scripts.resource:
    api_host: pve.example.internal
    api_token_id: "{{ proxmox_token_id }}"
    api_token_secret: "{{ proxmox_token_secret }}"
    vmid: 121
    kind: vm
    action: reconcile
    expected_script: haos
    settings:
      cores: 4
      memory: 8192
    disk:
      key: scsi0
      size_gb: 64
'''

RETURN = r'''
resource:
  description: Matching cluster resource metadata.
  type: dict
  returned: always
config:
  description: Current pre-change Proxmox configuration.
  type: dict
  returned: always
detected_script:
  description: Script slug when unambiguously found in native metadata.
  type: str
  returned: when available
plan:
  description: Field-level proposed config update and disk resize.
  type: dict
  returned: always
runtime_state:
  description: Current guest runtime status from Proxmox.
  type: dict
  returned: always
pending_changes:
  description: Current and pending values, including restart-required indications.
  type: dict
  returned: always
tasks:
  description: Results of API operations after asynchronous task polling.
  type: list
  returned: when mutations are submitted
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.mwyau.proxmox_community_scripts.plugins.module_utils.provenance import provenance, apply_script_override
from ansible_collections.mwyau.proxmox_community_scripts.plugins.module_utils.core import (
    ProxmoxAPI, ProxmoxError, locate_resource, resource_path,
    detect_script, verify_identity, plan_changes, wait_for_task, pending_status, effective_desired_config,
)


def run():
    module = AnsibleModule(
        argument_spec={
            "api_host": {"type": "str", "required": True},
            "api_token_id": {"type": "str", "required": True, "no_log": True},
            "api_token_secret": {"type": "str", "required": True, "no_log": True},
            "validate_certs": {"type": "bool", "default": True},
            "vmid": {"type": "int", "required": True},
            "node": {"type": "str"},
            "kind": {"type": "str", "choices": ["lxc", "vm"]},
            "action": {"type": "str", "choices": ["inspect", "plan", "reconcile"], "default": "inspect"},
            "expected_script": {"type": "str"},
            "adopt": {"type": "bool", "default": False},
            "script_override": {"type": "str"},
            "update_entrypoint": {"type": "str", "no_log": True},
            "settings": {"type": "dict", "default": {}},
            "disk": {"type": "dict", "default": {}},
            "timeout": {"type": "int", "default": 20},
        },
        supports_check_mode=True,
    )
    args = module.params
    applied = []
    try:
        if args["vmid"] < 100 or args["vmid"] > 999999999:
            raise ProxmoxError("VMID is outside the supported PVE range")
        api = ProxmoxAPI(
            args["api_host"], args["api_token_id"], args["api_token_secret"],
            verify_tls=args["validate_certs"], timeout=args["timeout"]
        )
        resources = api.request("GET", "/cluster/resources?type=vm")
        if not isinstance(resources, list):
            raise ProxmoxError("Unexpected cluster resource listing")
        entry = locate_resource(resources, args["vmid"], args["kind"], args["node"])
        path = resource_path(entry)
        config = api.request("GET", path + "/config")
        if not isinstance(config, dict):
            raise ProxmoxError("Unexpected resource config response")
        assessment = apply_script_override(
            provenance(config, entry["type"], args["update_entrypoint"],
                       args["expected_script"]),
            args["script_override"], args["expected_script"])
        if assessment["status"] == "conflicting":
            raise ProxmoxError("Conflicting script identity evidence")
        detected = (assessment["script"] if assessment["status"] == "verified" else None)
        effective_script = assessment["script"]
        pending_before = pending_status(api.request("GET", path + "/pending"), args["settings"])
        runtime_state = api.request("GET", path + "/status/current")
        if not isinstance(runtime_state, dict):
            raise ProxmoxError("Unexpected resource runtime state")
        if args["expected_script"] and detected and detected != args["expected_script"]:
            raise ProxmoxError("Installed script identity conflicts with expected_script")

        if args["action"] == "inspect":
            if args["settings"] or args["disk"]:
                raise ProxmoxError("settings and disk require action=reconcile")
            module.exit_json(
                changed=False, resource=entry, config=config,
                detected_script=detected, effective_script=effective_script,
                identity_status=assessment["status"], runtime_state=runtime_state,
                pending_changes=pending_before,
                plan={"settings": {}, "resize": None, "changed": False},
            )

        verify_identity(config, entry["type"], args["expected_script"],
                        args["adopt"] or assessment["status"] == "overridden",
                        args["update_entrypoint"])
        plan = plan_changes(
            effective_desired_config(config, pending_before, args["settings"]),
            entry["type"], args["settings"], args["disk"])
        result = {
            "changed": plan["changed"], "resource": entry, "config": config,
            "detected_script": detected, "effective_script": effective_script,
            "identity_status": assessment["status"], "plan": plan, "tasks": [],
            "runtime_state": runtime_state, "pending_changes": pending_before,
        }
        if args["action"] == "plan":
            result["would_change"] = plan["changed"]
            result["changed"] = False
            module.exit_json(**result)
        if module.check_mode or not plan["changed"]:
            module.exit_json(**result)
        if plan["settings"]:
            update = dict(plan["settings"])
            if config.get("digest"):
                update["digest"] = config["digest"]
            task = api.request("PUT", path + "/config", update)
            applied.append({"operation": "config", "result": task})
            wait_for_task(api, entry["node"], task)
        if plan["resize"]:
            request = {
                "size": str(plan["resize"]["size_gb"]) + "G",
                "disk": plan["resize"]["key"],
            }
            # The prior configuration update may have changed its digest.
            # Re-read immediately before applying this independent resize.
            latest = api.request("GET", path + "/config")
            if not isinstance(latest, dict):
                raise ProxmoxError("Cannot re-read config before disk resize")
            if latest.get("digest"):
                request["digest"] = latest["digest"]
            task = api.request("PUT", path + "/resize", request)
            applied.append({"operation": "resize", "result": task})
            wait_for_task(api, entry["node"], task)
        result["tasks"] = applied
        after = api.request("GET", path + "/config")
        if not isinstance(after, dict):
            raise ProxmoxError("Cannot verify configuration after update")
        pending_after = pending_status(
            api.request("GET", path + "/pending"), args["settings"])
        remaining = plan_changes(
            effective_desired_config(after, pending_after, args["settings"]),
            entry["type"], args["settings"], args["disk"])
        result["config_after"] = after
        result["pending_changes_after"] = pending_after
        result["remaining"] = remaining
        if remaining["changed"]:
            raise ProxmoxError("Some requested changes remain pending or were not applied")
        module.exit_json(**result)
    except (ProxmoxError, ValueError, TypeError) as exc:
        module.fail_json(
            msg=str(exc), changed=bool(applied), tasks=applied,
            note="A prior operation may have succeeded; re-inspect before retrying" if applied else None,
        )


if __name__ == "__main__":
    run()
