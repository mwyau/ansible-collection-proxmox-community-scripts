# Agent instructions

This is a native Ansible collection for Proxmox VE Community Scripts. The canonical collection FQCN is `mwyau.proxmox_community_scripts`. The GitHub repository is `mwyau/ansible-proxmox-community-scripts`.

## Objective
Make Community Scripts installations discoverable and reproducible, with idempotent management of existing LXC and QEMU resources, including hardware and grow-only disk changes.

## Read before editing
Read `PLAN.md`, `README.md`, and upstream `community-scripts/core` and `community-scripts/ProxmoxVE` source for the relevant feature. Upstream contracts evolve. Never claim every script supports an override without source and integration evidence. Follow the repository owner's writing conventions at https://github.com/mwyau/write-like-a-scientist/blob/main/AGENTS.md.

## Safety invariants
- Never execute scripts as root through `curl | bash` without verified source/ref and explicit user opt-in. Prefer downloading and verifying immutable revisions.
- Never infer application identity from VMID, hostname, or a generic `community-script` tag alone. Conflicting identity must fail; missing identity requires an explicit adoption decision.
- Never silently allocate a different VMID, destroy/recreate a resource, shrink a disk, overwrite network interfaces, or remove existing tags.
- Treat API reads and check mode as side-effect-free. Check mode must report proposed changes without applying them.
- Use HTTPS with certificate verification by default; do not log API tokens, passwords, credentials or sensitive installer arguments.
- Do not rerun installation scripts to reconcile hardware. VM application updates are not generically supported.
- Preserve unknown PVE configuration keys and existing disks. Validate disk target and size before requesting growth.
- Disallow interactive prompts in unattended deployment; fail rather than hang.
- Declare support per script and per parameter based on tested Core behavior, not filename patterns alone.
- Keep separate ownership for host infrastructure, application installation, and in-guest configuration.

## Architecture
- `plugins/modules/`: public Ansible entrypoints with complete DOCUMENTATION/EXAMPLES/RETURN metadata.
- `plugins/module_utils/`: small, testable Python helpers for Proxmox HTTPS API access, comparisons and catalog resolution.
- `tests/`: stdlib unittest for pure algorithms and mocked network calls; no live Proxmox required in CI.
- `examples/`: safe examples using environment/Vault-backed credentials.
- `PLAN.md`: source of truth for phases and constraints.
- Use the standard `community.proxmox` collection where that yields better lifecycle correctness; avoid inventing a competing general Proxmox provider.

## Workflow
1. Work on a feature branch; do not commit directly to `main`.
2. Inspect existing changes and read current upstream references.
3. Add or update tests for normal, repeated, conflicting, absent, check-mode and failure cases.
4. Run `python -m unittest discover -s tests -v`, `python -m compileall -q plugins`, and collection build and documentation checks when Ansible is available.
5. Review the diff for changes that could modify/destroy live resources or leak credentials.
6. Record what was actually tested. Never claim live PVE integration tests without running them.
7. Push without force; open a PR for review. Do not auto-merge.

Keep documentation concise, precise, and explicit about tested versus planned capabilities.


## Script validation
The upstream compatibility workflow and `scripts/scan_community_scripts.py` are **static-only**: execute `bash -n` on script files but never source or run downloaded installers/updaters in GitHub Actions. A syntax pass or presence of `VM_UNATTENDED` is not proof of unattended support. Record both upstream revision IDs and require disposable PVE tests for each script before certifying deployment.

The host-side LXC updater's `var_dry_run=yes` is not a strict no-op: it may start containers or repair legacy update files. Never call it from Ansible check mode. Do not let an application updater silently overwrite independently managed hardware settings.


## Deployment role
The experimental `deploy` role may execute Community Scripts as root over Ansible SSH; its default `deploy_execute: false` and `deploy_accept_unverified_script: false` are safety controls. Never remove or bypass either without explicit operator intent and a real disposable-host validation. Preserve exact SHA source pinning, second VMID collision check, bounded `setsid` execution, and mandatory postflight identity check. Failures may leave orphaned resources; do not automatically delete or retry. Check-mode runs API/source reads only, never host installer commands.


## Unified application role and updates
The user-facing interface is `roles/application` with actions `inspect`, `present`, `reconcile`, `update`. The `hardware` role delegates supported mutations to `community.proxmox`, but runs a strict read-only identity/diff gate first. Do not call third-party modules during check mode unless their check-mode guarantees have been reviewed. LXC application updates are explicit operations, not automatically triggered by running a `present` task. Require a request ID, backup policy, source pin, positive in-guest updater identity, and root-owned host lock/marker. The upstream updater is potentially mutating even in its own dry-run mode; never run it on Ansible check. Hardware drift after update must be surfaced rather than silently accepted.


## Provenance and guest access
Keep normalized `ssh` and VM-only `cloud_init` semantics. Do not silently promise SSH availability in an appliance VM. Do not source unknown guest scripts: read the LXC `/usr/bin/update` file as text only using host-side `pct exec`; stop on source disagreement. Maintain positive identity checks before existing hardware or cloud-init mutation, and do not power on stopped guests for discovery. Prefer `community.proxmox` and standard Ansible modules over custom transport or SSH/key implementations. Any change to core variable names must be checked against current upstream source and regression tests.

The `guest_ssh` role is deliberately a thin wrapper around standard Ansible package, service, and authorized_key modules. Do not replace it with raw shell commands. When using `community.proxmox.proxmox_pct_remote`, SSH connects to the PVE host, not the guest. Never automatically disable SSH or delete keys in `action: present` without an explicitly requested guest policy.

## Public role variables and explicit identity overrides
The `application` role must use short caller-facing options, not `application_*`. Internal subroles retain scoped names. A `script_override` can apply only when source provenance is unknown; require exact agreement with requested `script`. Never treat an overridden identity as verified, accept conflicting source metadata, ignore a Proxmox type/VMID mismatch, or use the override to bypass app-updater or new-install checks. Existing guest management requires no source ref; new installations require immutable script and Core SHAs.

## Public Core mapping contract
Use ctid for LXCs and vmid for VMs in the public application role. Internally use the PVE vmid API field. Keep one vocabulary otherwise: cores, memory (MiB), disk_size (GiB), bridge, storage, hostname, vlan, mac, mtu. Translate into LXC var_* and VM VM_* only at the boundary. The two Core engines have different expected value encodings; never assume boolean values are interchangeable. For named VM creation, inspect the selected script for shared unattended execution and actual use of requested fields, fail on absent evidence, and avoid claiming that source inspection proves deployment. Do not reintroduce settings.disk or unverified static IPv6 fields.

Keep `script_vars` as a creation-only raw environment escape hatch (valid shell names, strict protected names, bounded number/size, no control characters, and no logging of Vault secrets). It must not permit app code to override managed Proxmox IDs, normalized resource keys, source pinning or unattended controls. Fail on unsupported types; do not pretend raw variable names imply application support.


## Minimal declarations and user defaults
The `application` role exposes `guest_defaults.all`, `guest_defaults.lxc`, and `guest_defaults.vm` as flat normalized settings maps. Resolution order: explicit `settings` > guest-kind defaults > shared defaults; omit absent values to preserve the selected Community Script's own defaults. Do not invent a hostname. `script_vars` is exact-name, creation-only raw environment passthrough; do not add or strip `var_` or `VM_` prefixes. Do not relax the root installer execution opt-in just to make minimal guest declarations work.

## Public lifecycle contract
The `application` role uses `inspect`, `present`, `reconcile`, `update`. The earlier `manage_hardware` toggle was removed: `present` ensures existence but never reconciles existing guest hardware. `guest_defaults` applies to creation only. `reconcile` changes only explicitly supplied per-guest hardware `settings` and never relies on `guest_defaults`. Do not silently change existing resources or add an automatic reboot. Keep `script_vars` as the exact upstream variable-name passthrough.
