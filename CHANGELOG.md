# Changelog

## Unreleased

- Initialize native collection `mwyau.proxmox_community_scripts`.
- Add explicit architecture and agent safety instructions.
- Add dynamic Community Scripts catalog discovery from GitHub.
- Add API-only discovery and reconciliation of existing LXC/QEMU resources.
- Add grow-only disk planning, identity gates, and unit tests.
- Unattended creation and application updates remain planned; no live PVE validation yet.

\n- Add static-only upstream script compatibility scans, fixtures, and GitHub Actions reports.\n- Document guarded host-side LXC updater integration and unsafe upstream dry-run side effects.\n

- Add read-only pinned LXC/VM deployment planning and common Core property mappings.
- Add explicitly opted-in SSH deployment role with Git source pinning, VMID preflight/postflight verification, and safe check mode.
- Add unit tests and Ansible role syntax verification; live PVE creation tests are still outstanding.


- Add unified `application` and `hardware` roles with normalized inspect/present/update actions.
- Delegate existing CPU/RAM changes and QEMU disk growth to `community.proxmox`, with read-only API planning and LXC rootfs grow-only support.
- Add guarded, single-LXC application updates with positive `/usr/bin/update` provenance, backup, no reboot, host-side request lock and atomic completion marker.
- Add pending/runtime guest state reporting, strictly read-only diff plans, and bounded app-specific creation variables.
- Add updater mock tests and Ansible role syntax tests. No live PVE validation yet.


- Add unified SSH public-key and VM Cloud-Init creation settings with source capability checks.
- Add opt-in existing-VM Cloud-Init adapter backed by `community.proxmox.proxmox_kvm`.
- Add read-only API/host-assisted LXC provenance assessment and legacy guest identification through `/usr/bin/update`, including conflict detection.
- Add standard Ansible `proxmox_pct_remote` SSH/key maintenance example and tests.


- Use exact-name `script_vars` and add `guest_defaults` layering for normalized LXC/VM resource settings; preserve Core defaults for unspecified fields.
- Keep hostname optional and demonstrate inventory-scoped shared/per-type defaults.

- Restore `script_vars` as the exact-name installer-specific variable passthrough.
- Separate `present` (existence) from explicit `reconcile` (existing guest hardware configuration) and remove implicit `manage_hardware` handling.
