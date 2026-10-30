# Ansible for Proxmox Community Scripts

A developing, independent Ansible collection to discover and manage Proxmox VE LXCs and VMs created by [Community Scripts](https://github.com/community-scripts/ProxmoxVE).

**Collection:** `mwyau.proxmox_community_scripts` (development namespace; not yet published). **Repository:** `mwyau/ansible-proxmox-community-scripts`.

## Intended capabilities
- Discover available `ct/` and `vm/` scripts from a specific upstream Git ref without hard-coded application lists.
- Inspect existing Proxmox resources and detect script provenance where available.
- Reconcile existing CPU, RAM and other safe hardware fields idempotently through the Proxmox API.
- Grow root/boot disks without shrinking or replacing existing storage.
- Provide experimental opt-in SSH installation and LXC application updates; live Proxmox validation remains required.

**Current development status:** API-backed discovery/reconciliation, experimental opt-in creation and LXC updates, and static per-script compatibility checks. No live Proxmox integration tests have passed yet; review `PLAN.md` for release gates.

## Authentication model
Use a Proxmox HTTPS API token for normal resource reads and changes. Configure API credentials through Ansible Vault or controller environment variables; certificate verification should remain enabled. Host-side installation scripts still require SSH to a PVE host with suitable elevated privileges. The collection never needs host SSH for API-only read/reconciliation.

An API token does not grant arbitrary host shell execution. Do not grant root shell capability to an API-only inventory playbook.

## Project layout
- `galaxy.yml`: native collection identity
- `plugins/modules/`: user-facing modules
- `plugins/module_utils/`: small testable utilities
- `examples/`: example playbooks (never real credentials)
- `PLAN.md`: full design, implementation phases and safety guarantees
- `TESTING.md`: CI and disposable Proxmox integration test procedures
- `AGENTS.md`: coding-agent constraints

## Local development
Run `python -m unittest discover -s tests -v` and `python -m compileall -q plugins`. With `ansible-core` installed, run `ansible-galaxy collection build` from the repository root. Integration tests must target disposable Proxmox resources.

Not affiliated with Proxmox Server Solutions or the Community Scripts maintainers. Proxmox is a trademark of its respective owner. MIT licensed.


## Upstream script validation in GitHub Actions
The `Upstream script compatibility` workflow can be triggered manually with `kind=lxc` or `kind=vm` and an optional single `slug`. It also scans all `ct/` and `vm/` scripts weekly and on pull requests.

The workflow clones upstream scripts and Core. It parses the shared engine entry points, scans matching `install/*-install.sh` payloads and potential prompt sites, checks shell syntax using `bash -n`, and uploads `compatibility.json` and `compatibility.md`. No downloaded installer or updater is executed. Both upstream Git revisions are recorded; syntax failures fail the workflow.

Individual script example after cloning upstream:
```bash
python scripts/scan_community_scripts.py --source upstream-scripts \
  --core upstream-core --kind lxc --script adguard --output out
```
The categories distinguish shared Core entry points, application prompts that appear update-only or wizard-only, installation-input candidates, and custom entry points. Function scopes are approximate; none of these categories certifies unattended behavior. For testing on a disposable Proxmox VM, including nested KVM only for VM guests, see [TESTING.md](TESTING.md).

## Application updates
The upstream Proxmox-host `tools/pve/update-apps.sh` can select individual LXCs with `var_container=<CTID>` and uses `var_unattended=yes` for unattended execution. Use a controlled Ansible SSH connection to the PVE host with privilege escalation, and a reviewed pinned updater source. An API token is insufficient for this host-side command.

**Caution:** Its `var_dry_run=yes` path is not fully side-effect-free: the current script can start stopped containers, repair legacy update URLs, and write logs before version checks. Do not use it to implement Ansible check mode. The updater can also change guest software and host CPU/RAM allocations; keep application updates separate from hardware reconciliation. VM application updating remains unsupported without an application-specific documented contract.



## Retired scripts
Script filenames alone do not imply deployability: upstream leaves `ct/` retirement/rename stubs in Git. The read-only compatibility scanner recognizes high-confidence stubs (explicit removal/rename notice plus terminal nonzero exit and no build entry point) and **excludes them from the main compatibility counts and JSON `scripts` list**. The separate `excluded_retired` list retains evidence and any successor slug. At the tested upstream revision it excludes BookLore, LiteLLM, MinIO and MusicSeerr (renamed to DroppedNeedle).

`script_catalog` skips these known retired slugs in bulk listings using a conservative packaged snapshot, and returns `excluded_retired` metadata. When a specific script is selected, it fetches the immutable Git blob at the requested revision and checks its actual content, so a restored script can be recognized without modifying the exclusion list. Full-catalog results are **unverified discovery candidates**, not a claim that every listed application is installable. The snapshot must be refreshed when preparing a release and an actual creation path must independently check the selected source and upstream disabled/deleted status before executing anything. A newly retired script not yet in the packaged snapshot may still appear in the bulk listing.


## Pinned deployment role (experimental)

The collection now includes a guarded `mwyau.proxmox_community_scripts.deploy` role and a read-only `deployment_plan` module. The planner checks cluster-wide VMID availability and existing script identity, and maps common Core fields to `var_*` for LXC and `VM_*` for QEMU. New guest creation requires two **full, immutable Git commit hashes** (one for scripts, one for Core); existing-guest inspection does not.

The role runs on an SSH-connected PVE host. Its API reads are delegated to the Ansible controller; only installation requires elevated host SSH. For a missing VMID it inspects the exact pinned script blob, rejects known retired scripts, clones both repositories to a protected host directory, repeats the API collision check, and invokes the installer without a controlling terminal with a bounded timeout. It verifies the resulting VMID, type, node, and Proxmox script identity after execution.

**Installation is off by default.** Both `deploy_execute: true` and `deploy_accept_unverified_script: true` must be set to enable it outside `--check`. That second opt-in acknowledges that source syntax and retired-script checks cannot prove successful unattended installation. Use only disposable PVE guests until the live integration matrix is passing. The role never silently adopts existing resources, deletes guests, or reruns the installer when a matching VMID exists.

Run `ansible-playbook --check` first using [examples/deploy.yml](examples/deploy.yml). To change hardware on an existing verified guest, use `deploy_existing_settings` and `deploy_existing_disk`, or the standalone `resource` module.

**Remaining limitations:** no live PVE execution has been tested; some real scripts may still prompt or lack expected provenance metadata. The upstream LXC Core can reassign a colliding requested VMID in a concurrent race, so the role has a second preflight and postflight identity checks but cannot guarantee atomic reservation. There is no automatic cleanup or rollback after partial installation. The source catalog does not yet enforce upstream website disabled/deleted states, so a successful source check is not deployment certification.


## Unified application management (experimental)
The preferred entrypoint is the `mwyau.proxmox_community_scripts.application` role, which accepts `action: inspect | present | reconcile | update`, one `kind` (`lxc` or `vm`), `script`, VMID, node, credentials, and normalized `settings`. See [examples/application.yml](examples/application.yml).

- **Inspect:** Reads type, VMID, node, running state, configuration, disk and pending settings from the Proxmox HTTPS API. No guest SSH or cloud-init credentials are needed.
- **Present:** Validates an existing instance or proposes/executes a pinned installation (SSH to PVE with explicit opt-in). Existing guest hardware is never changed just because user defaults are set. `community.proxmox.proxmox` for LXC CPU/RAM/swap, `community.proxmox.proxmox_kvm` for VM CPU/RAM, and `community.proxmox.proxmox_disk` for VM disk growth; the guarded API handles LXC rootfs growth. Unknown disk keys and attempts to shrink fail.
- **Reconcile:** Uses `community.proxmox.proxmox` for LXC CPU/RAM/swap, `community.proxmox.proxmox_kvm` for VM CPU/RAM, and `community.proxmox.proxmox_disk` for VM disk growth; the guarded API handles LXC rootfs growth. Explicitly applies hardware settings from the individual guest's `settings` (not `guest_defaults`) to an existing, positively identified guest through the thin `hardware` role. CPU/RAM/swap and grow-only disk updates do not reboot the guest automatically. Existing VM cloud-init changes additionally require `configure_existing_cloud_init: true`.
- **Update:** A separate explicit application software update request. LXCs use the upstream `tools/pve/update-apps.sh` over Ansible SSH to the PVE node; **VM software updates remain app-specific and are not generically supported**. The guest itself requires no SSH key: `pct exec` verifies `/usr/bin/update`.

The normal `settings` keys for creation include `cores`, `memory` (MiB), `disk_size` (GiB), `hostname`, `bridge`, `vlan`, `storage`, and type-appropriate OS/network settings. `cores`, `memory`, LXC `swap`, and disk growth are reconciled on existing resources; installation-only settings are **not** reapplied. VM disk identity defaults to `scsi0`, LXC to `rootfs`; set `disk_key` for another *existing* VM disk.

`script_vars` is a bounded, creation-only escape hatch accepting arbitrary valid environment names (including `var_*`, `VM_*`, and app-specific names). It accepts at most 64 entries and 32 KiB, rejects control characters and protected identity/unattended/source/shell overrides, and refuses any normalized settings keys. It does not guarantee that a given upstream script supports the variable. Supply sensitive values with Ansible Vault and `no_log`; never commit passwords.

### Software update requests and idempotency
An explicit update uses `action: update`, a unique `update_request_id`, and `update_apply: true`. Backups default to enabled and require `update_backup_storage`; disabling backups requires `update_accept_no_backup: true`. The updater targets exactly one existing running LXC, validates its `/usr/bin/update` script identity, sets unattended/skip-confirm/no-auto-reboot options, and never invokes upstream `var_dry_run` in Ansible check mode.

Each request ID is serialized with a host-side `flock` and marked complete **only after the updater exits successfully**. Repeating the same request on the same PVE node skips execution. This is *request-level* idempotency, not a promise that the installed application has a known version; manually increment the request ID for the next update. The marker is host-local and does not automatically migrate between PVE nodes. A failed or interrupted update may partially modify a guest and requires human inspection before retrying. The role compares selected Proxmox CPU, RAM, swap, rootfs and network config before/after and fails if the upstream updater changes them, without automatically reverting guest changes.

`ansible-playbook --check` performs read-only discovery/planning and never executes a Community Scripts installer/updater. Since the upstream updater's own dry-run can start stopped LXCs or rewrite legacy updater files, no strictly read-only application version prediction is claimed.

### Access and cloud-init
The Proxmox API token is used for resource discovery and hardware state; host SSH with elevated privileges is required for scripts and `pct exec`. Individual LXC SSH credentials are not needed. For VMs, use Proxmox API/guest agent for status and network information; SSH/Cloud-init are only needed for guest configuration. Guest cloud-init is **not universal** (for example, appliance VMs may not support it). Manage `ciuser`, `sshkeys`, `ipconfig`, and cloud-init disks using `community.proxmox.proxmox_kvm` only for compatible VM images, not by assuming every Community Script supports them.

**Status:** CI and mocked tests only. No real guest has yet been created, updated, resized or restarted using these roles. Keep both installer and software-updater execution disabled outside disposable test environments until the live validation suite passes.


## Consistent guest SSH and Cloud-Init options

The public `application` role now accepts the same `ssh` schema for LXC and VM:
```yaml
ssh:
  enabled: true
  public_keys:
    - "ssh-ed25519 AAAA... user@machine"
```
Public keys are optional and are **never** generated from a private key or silently imported from the Proxmox host. Up to eight OpenSSH public keys are accepted; duplicates and malformed keys fail. If `enabled` is omitted, an LXC keeps upstream SSH defaults unless keys are explicitly supplied (in which case LXC SSH is enabled). `enabled: false` explicitly disables LXC SSH at creation, and conflicts with provided public keys.

For **LXC creation**, these normalized settings are passed to Community Scripts Core as `var_ssh` and `var_ssh_authorized_key`, including multiline keys. Existing LXC configuration is managed using Ansible's existing `community.proxmox.proxmox_pct_remote` connection and `ansible.posix.authorized_key` as shown in [examples/guest_ssh.yml](examples/guest_ssh.yml). This avoids requiring a guest SSH server for management.

For **VM creation**, SSH key provisioning requires a **supported cloud-init image** and explicit:
```yaml
cloud_init:
  enabled: true
  user: ubuntu
  network_mode: dhcp
  dns: ["1.1.1.1"]
```
The planner sets `VM_CLOUD_INIT` and `CLOUDINIT_*` settings. The role stages authorized public keys as a root-protected PVE file and passes its pathname through `CLOUDINIT_SSH_KEYS`, as expected by Core. The selected VM script must expose the shared cloud-init hook, otherwise creation fails before root execution. Cloud-init omission does not force a `VM_CLOUD_INIT=no` override; that would break images requiring cloud-init.

**Cloud-init does not guarantee an SSH server exists in the VM.** The collection cannot generically enable/disable SSH in an arbitrary appliance OS. VM `ssh.enabled=false` and `ssh.enabled=true` without keys are rejected rather than silently ignored. For existing VMs with native cloud-init disks, `configure_existing_cloud_init: true` explicitly applies supported changes through `community.proxmox.proxmox_kvm`, after a verified-identity gate and requiring the VM to be stopped. No automatic reboot or cloud-init drive creation is attempted.

See [examples/ssh_cloud_init.yml](examples/ssh_cloud_init.yml). These creation and existing-VM paths have passed static and mocked tests only; real cloud-init guest behavior has not yet been verified.

## Existing Community Scripts guest provenance

The read-only `provenance_info` module and `provenance` role combine API metadata with an optional LXC `/usr/bin/update` read through PVE host SSH/`pct exec`. No LXC guest SSH key or daemon is required. The resulting identity is one of `verified`, `unknown`, or `conflicting`, with exact evidence sources. On newer LXCs, `SCRIPT_SLUG` identifies the app while `UPDATE_SCRIPT_NAME` may be an OS or another update target and is **not** automatically treated as the app. Legacy `/ct/<slug>.sh` entrypoints are also recognized. For VMs, the source URL in PVE description is recognized; generic category tags or a random remaining tag alone do not establish identity.

`action: inspect`, existing-guest `present` checks and the `hardware` adapter now use the host-assisted provenance role. If an existing LXC is stopped and has no identifying API metadata, it remains unknown; the role **does not start it** to identify it. Conflicting evidence always fails. Identifying metadata is source evidence, not cryptographic attestation.

Application OS/package updates, guest SSH configuration, and software-version discovery are separate concerns. No arbitrary VM guest shell execution is performed.

The `guest_ssh` role also exposes the **same `enabled` and `public_keys` mapping** for an existing LXC. Run it against a guest inventory entry through `community.proxmox.proxmox_pct_remote`, rather than trying to SSH into the LXC itself. It uses standard `ansible.builtin.package`, `ansible.builtin.service`, and `ansible.posix.authorized_key`; Debian/Ubuntu and Alpine are supported for now. `enabled: false` stops and disables the service but does not delete installed keys. Key updates are additive, not exclusive. It requires an explicit `enabled` value and does not manage VM appliance SSH internals.

The `guest_ssh` role can also manage a Debian/Ubuntu/Alpine VM **after** a normal Ansible connection has been established (for example with a guest SSH key or a working QEMU Guest Agent connection). It cannot bootstrap SSH on an arbitrary appliance VM whose operating system does not provide a supported management method.

## Concise role interface and manual script identity

The `application` role uses unprefixed options: `action`, `api_host`, `api_token_id`, `api_token_secret`, `node`, `kind`, `ctid` for LXC or `vmid` for VM, `script`, `settings`, `ssh`, `cloud_init`, and `script_override`. The internal deploy, hardware and update roles retain their distinct prefixes to avoid clashes. **Existing guests do not need scripts/Core revision hashes.** Creating a missing guest still requires full, immutable `scripts_ref` and `core_ref`.

For an existing LXC/VM whose original script cannot be established from the Proxmox description/tags or a running LXC's `/usr/bin/update` file:

```yaml
- role: mwyau.proxmox_community_scripts.application
  vars:
    action: present
    api_host: pve.example.internal
    api_token_id: "{{ proxmox_token_id }}"
    api_token_secret: "{{ proxmox_token_secret }}"
    node: pve1
    ctid: 120
    kind: lxc
    script: adguard
    script_override: adguard
    settings:
      cores: 2
      memory: 2048
```

`script_override` is an **explicit operator assertion**, not proof of source. It is accepted only when detected identity is unknown (or matches the supplied identity), must match `script`, and never overrides conflicting positive evidence. The PVE-reported guest type and VMID remain authoritative; it cannot turn a VM into an LXC or select a different guest. API hardware planning, configuration, cloud-init and inspection report the distinction between `verified` and `overridden` identity. This override is **not** an installation provenance shortcut. It is **not permitted with `action: update`**: the LXC software updater must independently validate a real update entrypoint.

If `script_override` is not supplied, unknown guests are inspected safely but mutation is refused. See [examples/adopt_existing.yml](examples/adopt_existing.yml).

## One shared LXC / VM settings vocabulary

Use `ctid` for LXC and `vmid` for VM; Proxmox stores both identifiers in one cluster-global VMID namespace. Both otherwise use the same `cores`, `memory` (MiB), `disk_size` (GiB), `bridge`, `storage`, `hostname`, `vlan`, `mac`, and `mtu` when supported by the selected installer. Public settings are *not* shell variable names.

| Public | LXC Core | VM Core |
| --- | --- | --- |
| `ctid` / `vmid` | `var_ctid` | `VM_VMID` |
| `cores` | `var_cpu` | `VM_CORES` |
| `memory` | `var_ram` | `VM_RAM` |
| `disk_size` | `var_disk` (GiB) | `VM_DISK_SIZE` (e.g. `32G`) |
| `hostname` | `var_hostname` | `VM_HOSTNAME` |
| `bridge` | `var_brg` | `VM_BRIDGE` |
| `storage` | `var_container_storage` | `VM_STORAGE` |
| `vlan`, `mac`, `mtu` | `var_vlan`, `var_mac`, `var_mtu` | `VM_VLAN`, `VM_MAC`, `VM_MTU` |

The VM-only `cpu_type: host`, `machine: q35 | i440fx`, `disk_cache: none | writethrough` and `start: true | false` have constrained mappings. For LXC, `privileged` inversely maps to `var_unprivileged`, `nesting`/`keyctl` use `0/1`, and `fuse`/`tun`/`protection` use `yes/no`. Unsupported values are rejected instead of being silently ignored. Use `ssh.public_keys` rather than `settings.ssh_public_key`; the latter is deliberately not accepted.

**Compatibility is two-stage.** A weekly/PR check reads the real shared Core files and fails if a normalized mapping disappears. For an explicitly selected VM script, the catalog records whether it uses the common unattended entrypoint and which mapped working variables occur in its source. New VM creation rejects requested settings for which no script reference is found. This is a conservative *static* safeguard, not execution proof: each installer can still impose its own defaults, image layout and minimum hardware sizes. For example, LXC Core may raise CPU/RAM/disk above requested values if the application declares higher minimum requirements.

Static IPv6 for an LXC via `settings.ipv6_static` remains intentionally disabled until the Core defaults-to-PVE backend handoff is confirmed; `ipv6_method: auto | dhcp | none` is supported. Advanced `script_vars` bypasses this normalized schema only at explicit operator risk, not as a certified common option.

See [examples/application.yml](examples/application.yml) and the source audit workflow for supported settings.

### Custom installer environment (creation only)

`script_vars` passes a bounded mapping of names to scalar environment strings to the selected upstream installer. Names must be shell-compatible identifiers; they can be app-specific instead of starting with `var_` or `VM_`. Example:

```yaml
kind: vm
vmid: 300
script: ubuntu-vm
settings:
  cores: 4
  disk_size: 32
script_vars:
  VM_ISO_STORAGE: local
  APP_CUSTOM_OPTION: enabled
  APP_API_TOKEN: "{{ vault_app_api_token }}"
```

LXC accepts the same `script_vars` field, for example `APP_CUSTOM_OPTION`. Standard hardware/resource parameters must always go under `settings`. SSH keys and cloud-init must use `ssh` and `cloud_init`. Protected source/guest identifiers (`var_ctid`, `VM_VMID`), unattended settings, normalized Core parameter keys and shell/environment injection controls (`PATH`, `BASH_ENV`, `LD_*`, etc.) cannot be overridden. Duplicate or invalid names and control-character values fail before execution. Maximum: 64 entries, 32 KiB. Raw environment injection cannot guarantee that the chosen app script reads a variable; verify support using its pinned source. Never inject shell code, and keep secrets in Ansible Vault; the role's installer task is `no_log`.

Common additional LXC options supported in `settings` include `gpu`, `mknod`, `mount_fs`, `apt_cacher`, `apt_cacher_ip`, `inherit_host_ca`, and `timezone`. VM supports `timezone` through the shared Core helper, but only scripts calling the corresponding helper can apply it. Advanced VM options such as `VM_ISO_STORAGE` can be passed through `script_vars` when the selected script supports them. Some Core controls (including scripts and secrets) intentionally are not normalized as general hardware settings.

## Minimal guest declarations and user defaults

`hostname` is **optional**. For an LXC, Core defaults to an application-derived name; for a VM, the named script provides its default `HN` (for example, `ubuntu-vm` uses `ubuntu`). A VM's PVE display name does not by itself guarantee the hostname inside an appliance image. Do not pass a hostname unless you intend to override the script default.

Define common **resource settings** once in Ansible inventory (for example, `group_vars/pve.yml`):

```yaml
guest_defaults:
  all:
    bridge: vmbr0
    storage: local-lvm
  lxc:
    cores: 2
    memory: 2048  # MiB
    disk_size: 8  # GiB
  vm:
    cores: 4
    memory: 4096  # MiB
    disk_size: 32 # GiB
```

Precedence, **by individual setting key**, is: `settings` on that guest → `guest_defaults[kind]` → `guest_defaults.all` → original upstream script default. The Ansible role sends **no environment variable** for an omitted key, allowing Core or the application script to decide. Defaults layers are flat maps of normalized `settings` fields, not raw Core variables.

An individual guest can now be declared as:

```yaml
kind: vm
vmid: 220
script: ubuntu-vm
```

**This is a guest declaration, not a standalone executable Ansible playbook.** The `application` role still needs `action: present`, PVE `node`, API credentials, an Ansible SSH inventory pointing to the PVE host, and both pinned `scripts_ref`/`core_ref` Git SHAs **when creation is required**. Because the creation path has not passed real-host integration tests, it deliberately defaults to `install: false` and `accept_unverified_install: false`. Both execution opt-ins must be explicitly enabled on an isolated test host. Put shared infrastructure variables in inventory/group_vars; there is no reason to repeat credentials or pins for every guest.

For already existing guests, neither pinned source revision is required. `action: present` uses user defaults **only when creating a missing guest**. It never reconciles existing hardware. To apply hardware changes, use `action: reconcile` with explicit per-guest CPU/RAM/swap/socket/disk settings. `guest_defaults` does not implicitly change pre-existing guests. Values not in any defaults layer and not explicitly provided remain governed by the existing guest's configuration or the upstream installer. Application-specific raw environment entries belong in `script_vars`, using their exact original names.

### Lifecycle actions and safety

- `inspect`: read-only state and provenance.
- `present`: ensure an LXC/VM exists; applies `guest_defaults` only when **creating** it, never updates hardware on an existing guest.
- `reconcile`: explicitly apply supported hardware settings given in that guest's own `settings`, not inherited `guest_defaults`. The guest must already exist and pass provenance/type checks; VM Cloud-Init configuration additionally needs explicit `configure_existing_cloud_init: true` and appropriate disk/state.
- `update`: explicit LXC application update request, independent of hardware configuration.

The former `manage_hardware` toggle has been removed: it was too easy to apply fleet-wide defaults to existing containers unintentionally. No action automatically deletes, shrinks disks or reboots guests. `script_vars` remains the full-name passthrough for application installer variables (e.g. `var_x`, `VM_X`, `APP_X`).


## Current API names (bpg/proxmox compatibility)
The **public** `application` role expects `endpoint`, `api_token` (`id=secret`), `insecure` (false by default), `node_name`, and a single `vm_id` for both kinds. Normalized creation settings include `datastore_id`, `vlan_id`, `mac_address`, `unprivileged`, and VM `started`. In particular, `settings.unprivileged=true` means `var_unprivileged=1` in Core. The older names `ctid`, `vmid`, `node`, `api_host`, `api_token_id`, `api_token_secret`, `validate_certs`, `storage`, `vlan`, `mac`, `privileged`, and `start` are **not** accepted in the public application role / normalized creation settings. Lower-level Ansible modules retain their established API arguments. This section supersedes earlier public-facade examples or design notes.
