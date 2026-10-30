# Development plan

## Goal
Build `mwyau.proxmox_community_scripts`, an Ansible collection for discovery, safe installation and ongoing resource reconciliation of standard Community Scripts LXC (`ct/`) and QEMU VM (`vm/`) deployments.

**Current status:** development scaffold and API-only, existing-resource reconciliation first. Installation, application updates, and verified guest identity inspection are later milestones. This document is a plan, not a claim of completed features.

## Architectural decisions
1. Collection FQCN: `mwyau.proxmox_community_scripts`; GitHub home is `mwyau/ansible-proxmox-community-scripts`.
2. Split transport by privilege. Prefer Proxmox HTTPS API tokens for discovery, comparison, config changes, and resize. Use SSH plus controlled privilege escalation **only** for running host-side Community Scripts and `pct exec` operations. An API token cannot directly run arbitrary root shell scripts on PVE.
3. Inventory is live Proxmox API state. Store script provenance in an Ansible-owned manifest/metadata plus native Proxmox tags/description where safe. Do not treat generic tags as application identity.
4. Script discovery uses upstream `ct/` and `vm/` GitHub directory listings at a selectable revision; new scripts appear without code changes. Catalog discovery is not proof of unattended compatibility.
5. Pin script and Core revisions for **execution**. A moving `main` is permissible only for read-only discovery; upgrades are explicitly requested and reviewed.
6. Two adapters share an externally consistent schema: LXC `var_*` and VM `VM_*` are different engine contracts. Support optional app-specific overrides with careful quoting, allowlists, secret handling and per-script compatibility.
7. A reconciliation run must be idempotent. Repeated same desired state returns `changed=false`; conflicting IDs, script identity, storage topology, or unsupported mutation fail without destructive recovery.

## Upstream reference material
- Community Scripts applications: https://github.com/community-scripts/ProxmoxVE
- Shared engine: https://github.com/community-scripts/core
- Proxmox Ansible collection: https://github.com/ansible-collections/community.proxmox

## Supported property strategy
Use a normalized user interface with distinct **creation-only**, **mutable**, and **grow-only** fields. Read current engine declarations before adding a mapping. Do not present unsupported options as silently accepted.

| Domain | Normalized properties | LXC Core mapping | VM Core mapping | Reconcile existing |
| --- | --- | --- | --- | --- |
| Identity | vmid, hostname, script | `var_ctid`, `var_hostname` | VM-specific `VM_*` | vmid immutable; hostname where supported |
| Compute | cores, cpu limit/units, sockets, cpu type | `var_cpu` and Core options | `VM_CORES` and VM options | cores, type-relevant settings |
| Memory | memory, swap, balloon | `var_ram` | `VM_RAM` | memory, LXC swap, VM balloon |
| Disk | root/boot size, storage | `var_disk`, storage vars | `VM_DISK_SIZE`, `VM_STORAGE` | size grows only; storage move separate |
| Network | bridge, vlan, MAC, IPv4, IPv6, gateway, MTU | `var_brg`, `var_vlan`, etc. | VM vars vary | explicit safe patch later |
| Boot | onboot, start, protection, features | Core and PVE options | VM engine/PVE options | subset by type |
| Other | OS/version, template, timezone, ssh, tags, app overrides | `var_os`, `var_version`, `var_*` | per-script VM options | mostly install-only |

The matrix is an intended coverage map, **not** a claim that each variable exists in both engines. Build a checked compatibility table against real upstream scripts before enabling an option. Preserve explicit zero, false and empty values when meaningful.

## Milestones and acceptance tests

### M0 — Repository foundation
- Galaxy collection metadata, AGENTS, README, design plan, example and CI.
- Testable shared API client and catalog/reconciliation core.
- Unit and mocked API tests; no live host mutation from CI.

### M1 — Discovery and hardware reconciliation (first-class)
- Read `/cluster/resources` and full resource config to discover node, kind, VMID, tags, description and existing hardware.
- Identify VM script from exact Core metadata where possible; for LXC, optionally inspect `/usr/bin/update` via SSH/`pct exec`. A category tag alone is insufficient.
- Explicit `inspect` and `reconcile` actions, check mode, per-field diff, safe API application.
- CPU/RAM and type-specific config changes; grow LXC rootfs and VM named disk; refuse shrink and ambiguous disks.
- Check same-state repeated run, mismatched type, unknown provenance, denied access, partial failure and task-queued response.

### M2 — Unattended creation
- Validate catalog slug and script kind against a pinned revision. Read and pin Core revision separately.
- Run only approved scripts through SSH on PVE with privilege escalation, bounded timeout, controlled environment and safe redaction.
- Ensure explicit VMID is honored; fail on collision/auto-remapping; verify actual output and provenance.
- Per-script unattended compatibility gates; do not automate whiptail with keystrokes.
- API-based post-create inspect plus second-run unchanged; never create when ID already belongs to another resource.

### M3 — Common Core parameter breadth
- Audit and track LXC and VM options from upstream (and default behavior), including networking, storage, OS, passwords/keys, privilege and app-specific overrides.
- Prioritize common proven inputs. Explicitly reject options unknown to a chosen engine/script.
- Validate features requiring restarts, disk movements and network changes; stage dangerous mutations separately.
- Test representative Debian/Ubuntu LXCs and standalone/cloud-init/appliance VMs on disposable PVE 8/9 systems.

### M4 — Updates and catalog drift
- Refresh catalog to discover additions/removals/renames; report upstream script SHA/revision drift.
- Application software update as a separate explicit action. LXC updater runs with `pct exec` where installed and supported. VM guest updates are out of scope until a script-specific contract is documented.
- Never equate “upstream installer changed” with “update the installed application.”
- Add guarded version/compatibility reporting and provenance recording.

## Security, testing and release
- TLS verification on by default; API token with minimal ACL scope; separate SSH deploy identity with root execution carefully restricted.
- No credentials in playbooks, shell commands, verbose logs, collection results or CI output. Document Vault and controller environment variables.
- CI runs unit tests, module syntax and Galaxy build; live PVE tests are opt-in against disposable nested VMs or isolated test nodes. Tests must include repeat runs and disk-resize refusal.
- Publish pre-release documentation clearly. No automatic delete, auto-adopt, VMID reassignment or disk shrink.
- Consult upstream about a stable non-interactive JSON interface and machine-readable provenance.

## Open implementation questions (safe defaults)
- API user/token: operator-supplied, TLS-verified. Never create credentials automatically.
- SSH: optional for inspection, required for creation or LXC updater; no SSH private key stored by the collection.
- Adoption: explicit opt-in when installation identity is missing; conflicting identity always errors.
- Disk: grow only; named disk key required for QEMU, `rootfs` for LXC; no implicit guest filesystem resize guarantee.
- Resource ownership: never let two independent IaC controllers manage the same mutable fields.


## Updater integration and safety
Current LXC host updater: `ProxmoxVE/tools/pve/update-apps.sh`. It accepts `var_container` (single CTID or list), `var_unattended`, `var_backup`, `var_backup_storage`, `var_skip_confirm`, `var_auto_reboot`, and `var_dry_run`. The nominal upstream dry-run can still start stopped containers, rewrite legacy update URLs, and create logs. Never use that path for strictly read-only Ansible check mode. Hardware reconciliation remains independent of application updates. Plan a separate explicit `lxc_update` action with validated backup, stop/start policy, source integrity, and a post-update resource re-read.

## Layered compatibility verification
1. A GitHub Actions read-only scan enumerates `ct/*.sh`, `vm/*.sh`, matching LXC `install/*-install.sh` payloads, and shared Core functions at recorded revisions. It validates `bash -n`, identifies standard shared-engine entrypoints, installation and update prompt sites, and referenced/defaulted configuration variables.
2. Classify source-level findings as shared-engine/no application prompts, shared-engine/update-only prompts, shared-engine/wizard prompts, shared-engine/install-input review, custom entrypoint, or syntax error. These are architectural heuristics, not unattended deployment certifications. The estimated prompt scope (nearest function) must be verified manually.
3. Check mode, hardware mutations and task polling use mocked API tests in hosted GitHub Actions; no Proxmox credentials are necessary. An isolated nested Proxmox VM is used for real integration, not for routine GHA jobs.
4. For real integration, provision one app at a time with **no TTY**, verifying exact VMID, API metadata, guest health, repeat-run no-op, disk growth, attempted shrink denial, and cleanup. Include explicit script/Core revision evidence. Start with representative shared-engine LXC and VM examples, then test custom entrypoints and high-risk app prompts.
5. Track per-script validation evidence at a pinned revision. New script discovery must not automatically imply install/update eligibility.
6. See `TESTING.md` for the isolation model and step-by-step acceptance protocol. The weekly scan reports upstream additions, drift and syntax regressions without executing downloaded installers.



## Retired/disabled scripts
- Distinguish Git directory presence from installability. The static scanner detects exit-only retirement/rename stubs from source at an exact revision; retired entries are excluded from compatibility counts and kept in `excluded_retired` for audit.
- Full `script_catalog` listings use a conservative release-time cache to omit known retired slugs. Explicit slug lookup reads the immutable Git blob by its SHA to identify a changed or restored stub. Never treat the bulk listing as proof of active status.
- Before creation, reverify the selected source at the pinned revision and also consult upstream website status (is_deleted/is_disabled) when a stable endpoint is available; status checks must not silently fail open for automated provisioning.
- Keep the snapshot updated from the scheduled static scan during release preparation, without automatically rewriting project files or executing installers.


## M2 implementation status — experimental

- Implemented `deployment_plan`: read-only cluster VMID lookup, existing-identity gate, full-SHA revision validation and common LXC/VM environment mapping.
- Implemented `deploy` Ansible role: SSH-driven execution with root elevation, pinned source checkouts, a repeated collision check, bounded terminal-less installer invocation, postflight identity validation, explicit execution and unverified-script opt-in, and optional existing-guest reconciliation.
- The role accepts bounded application-specific environment variables through `script_vars`, including Vault-provided secrets. The common mapped fields are an initial subset; unsupported settings fail.
- Integration status: pure-Python tests and Galaxy/documentation/syntax CI only. **No actual LXC/VM installation tests completed.** Failures may leave partial resources that must be investigated manually.
- Mandatory next hardening: upstream script/Core release status gate that fails closed on deleted/disabled scripts; actual LXC guest `/usr/bin/update` provenance verification; exact resource discovery and VMID race detection on a disposable cluster; operator-safe rollback design; real guest/network/disk metrics and user-defined secrets with no logging.


## Application management and pending validation (2026-10-29)
- Provide a single `application` role with `inspect`, `present`, explicit `reconcile` and `update` actions. Existing guests use the `hardware` adapter and established `community.proxmox` modules where safe; our own API remains for read-only identity/pending-state planning and LXC rootfs growth.
- Prioritize **LXC application updates** through the pinned host-side updater. Require running LXC, positive updater provenance, backup storage by default, no automatic reboot, explicit execution approval, and a unique `update_request_id`. Host-local locking and completion markers provide per-request no-op repetition; they are not a version solver or cross-node transaction.
- Keep `script_vars` as a bounded opt-in creation-only pass-through; variable support remains app-specific. Never pass arbitrary Proxmox API configuration keys through the same channel.
- Show configured versus pending hardware state and require operator-controlled restarts. No automatic guest reboot after CPU/RAM updates.
- Dry-run is our read-only plan/check mode, not `var_dry_run=yes` of the upstream updater.
- Still open: end-to-end disposable PVE testing of API mutations, SSH provenance on running/stopped LXCs, update failure paths, idempotency across migrations and restarts, real guest filesystem expansion, upstream website disabled/deleted verification, a validated support matrix for the common parameter set, app-specific update-version probing, and safe cloud-init only for images that support it.


## Guest SSH, cloud-init and legacy provenance implementation
- Normalized `ssh.enabled` and `ssh.public_keys`, backed by LXC Core `var_ssh` and `var_ssh_authorized_key` at creation and VM Core's optional `VM_CLOUD_INIT` / `CLOUDINIT_*` with staged SSH public keys.
- VM cloud-init is opt-in, source gated on a shared cloud-init hook, and never assumed for appliance images. Existing stopped VM cloud-init configuration is explicitly opt-in, delegated to `community.proxmox.proxmox_kvm`, and requires an existing cloud-init disk.
- The `provenance_info` module and `provenance` role combine API metadata and read-only `pct exec ... cat /usr/bin/update` on running LXCs. Correctly prefer `SCRIPT_SLUG` over `UPDATE_SCRIPT_NAME` when the latter is an OS name. Conflict/unknown identity is not auto-adopted.
- Existing guest SSH maintenance should use existing `community.proxmox.proxmox_pct_remote` and `ansible.posix.authorized_key`, not a bespoke guest SSH implementation.
- Still requiring real Proxmox tests: VM cloud-init availability and first-boot behavior; LXC SSH service and multiple keys; VM cloud-init reapplication; stopped-LXC provenance without guest start; and hardened operator-approved adoption for truly unknown guests.

- For existing Debian/Ubuntu and Alpine LXCs, `guest_ssh` uses standard Ansible modules with the existing `community.proxmox.proxmox_pct_remote` connection; its schema matches `ssh` for creation. No custom SSH transport was added.

## Public role interface and manual adoption
- Prefer short public variables (`action`, `script`, `ctid` for LXC / `vmid` for VM, `settings`, `ssh`, `cloud_init`, etc.); internal role variables remain namespaced for implementation safety.
- `script_override` explicitly asserts one script identity only when no reliable source is detected. Never suppress contradictory positive evidence, type/node/VMID checks, or post-create validation. Preserve `overridden` provenance status distinct from `verified`.
- Reconciliation of an existing guest does not require script/Core Git hashes; a missing guest still requires both immutable revisions before any installation.
- Updaters must independently verify a usable guest-side update entrypoint; a manual hardware-adoption override cannot authorize execution of an unrelated application updater.

## Core variable mapping audit
- Standardize LXC `ctid` / VM `vmid`, plus shared `cores`, `memory` (MiB), `disk_size` (GiB), `bridge`, `storage`, `hostname`, `vlan`, `mac`, `mtu` for both guest kinds, translated through per-kind mapping tables.
- Validate actual Core variable references at the checked out Git SHA in CI with `scripts/verify_core_mapping.py`; treat a renamed variable as a breaking change.
- Require shared `vm_start_script` and per-field VM source references for requested VM parameters; static evidence is advisory and a preflight guard, not real installation certification.
- Fail closed on unsupported VM `cpu_type`, `disk_cache`, `machine` and non-operational LXC static IPv6. Refuse ambiguous `disk` setting; accept `disk_size` only.
- Pending: disposable PVE tests for app default CPU/RAM/disk minimums, cloud-init, network options, and guest disk/filesystem convergence.

## Public guest identifiers and custom installer environment
- LXC public option is `ctid`; VM public option is `vmid`. Require exactly the correct one, never accept both or silently default to a guest ID. Proxmox's `vmid` API field remains an internal implementation detail.
- Maintain a normalized Core settings surface for all verified common hardware/network variables plus documented LXC-specific extras. Advanced app vars use bounded `script_vars` with arbitrary valid shell environment names but strong reserved-name protections.
- `script_vars` must reject collisions with any normalized Core key even when omitted in `settings`, and block shell injection variables. Treat each raw app name as unverified support until the named script's source or live guest validates it. Never log supplied secrets.


## Shared user defaults and installer environment naming
- Rename the raw passthrough to `script_vars`: its keys are the *exact* environment names the pinned installer expects, without automatic prefixing.
- The public role accepts `guest_defaults: {all: {}, lxc: {}, vm: {}}` containing normalized `settings` maps. Merge per-guest `settings` over the matching kind layer, then the shared layer. Omit all non-requested keys so Core/application defaults remain authoritative.
- `hostname` is optional, and VM names may not imply an actual guest OS hostname. Do not create synthetic hostnames in Ansible.
- `action: present` uses user defaults for missing-guest creation only; it must not mutate existing guest hardware. Hardware drift reconciliation is an explicit `action: reconcile` with per-guest `settings`, not inherited defaults.
- The three-field `kind`/`ctid` or `vmid`/`script` record is only a declaration; explicit `action: present`, PVE connectivity and source refs/installation approvals for missing guests remain necessary.

## Reviewed lifecycle semantics
- Keep standard Ansible `present` semantics for existence only; do not mutate an already-existing guest's CPU/RAM/disk by inheriting defaults.
- Add explicit `reconcile` action for supported existing hardware mutations. Only per-guest `settings` can drive reconciliation; no silent fleet-default hardware resize. Existing VM cloud-init changes also require their separate opt-in.
- Remove the ambiguous `manage_hardware` toggle, previously defaulting to true. `inspect` and `update` remain distinct actions.

## Companion Terraform provider contract (2026-10-29)
Canonical shared input names: `api_host`, `api_token_id`, `api_token_secret`, `validate_certs`, `ctid` (LXC), `vmid` (VM), `node`, `kind`, `script`, `scripts_ref`, `core_ref`, `settings`, `guest_defaults`, `script_vars`, `update_request_id`, `update_scripts_ref`, `update_backup_storage` and `disk_key`. The versioned canonical mapping is `contracts/guest.v1.json`. Do not add legacy aliases. Terraform controls state and lifecycle for its own VMIDs; Ansible may separately configure software inside such guests without competing PVE hardware mutations. CI must check contract parity across repositories. No live PVE integration run is implied.

## Identity correction (2026-10-29)
Public guest identity depends on `kind`: LXC uses `ctid`, VM uses `vmid`. They are mutually exclusive. Terraform's computed `id` is reserved for stable state/import identities. All Proxmox API calls use a single normalized integer VMID internally.


## Current API names (bpg/proxmox compatibility)
The **public** `application` role expects `endpoint`, `api_token` (`id=secret`), `insecure` (false by default), `node_name`, and a single `vm_id` for both kinds. Normalized creation settings include `datastore_id`, `vlan_id`, `mac_address`, `unprivileged`, and VM `started`. In particular, `settings.unprivileged=true` means `var_unprivileged=1` in Core. The older names `ctid`, `vmid`, `node`, `api_host`, `api_token_id`, `api_token_secret`, `validate_certs`, `storage`, `vlan`, `mac`, `privileged`, and `start` are **not** accepted in the public application role / normalized creation settings. Lower-level Ansible modules retain their established API arguments. This section supersedes earlier public-facade examples or design notes.
