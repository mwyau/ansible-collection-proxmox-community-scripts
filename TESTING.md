# Testing strategy

The GitHub Actions scanner checks source structure and syntax. **It never installs or runs an upstream script.** A supported-script claim requires a separate recorded Proxmox integration result.

## Test tiers

| Tier | Environment | What it proves |
| --- | --- | --- |
| 0 | Python unittest on GitHub-hosted Ubuntu | Deterministic planning, error handling, strict identity and idempotent no-op decisions |
| 1 | GitHub-hosted Ubuntu + upstream Git checkout | All `ct/` and `vm/` syntax, shared Core entrypoint, installer payload syntax, referenced parameters, apparent prompt sites, and upstream revision |
| 2 | Mock Proxmox REST service and SSH-command adapters | Correct API requests, async job polling, no-op repetition, refusal of ID collisions/shrinks, check-mode nonmutation; **not actual PVE behavior** |
| 3 | Disposable Proxmox guest on a virtualization host | Real LXC/VM creation, exact VMID, config diff/restart, disk growth, network and storage, re-run, optional explicit updater |
| 4 | Pinned matrix across Proxmox releases and storage backends | Version/storage compatibility, only after Tier 3 is stable |

Static scan categories are **not** success/failure of unattended installation. The source audit treats the nearest function as approximate context, not formal Bash control-flow analysis. Application update prompts and advanced-only prompts are recorded separately from install-time prompt candidates, but all candidate classifications need validation.

## Run static checks

GitHub Actions: **Upstream script compatibility** (weekly, PR, or manually dispatched once the workflow is available on the default branch). The dispatch accepts `kind`, optional `slug`, and upstream scripts `ref`. It records both Core and application Git commit IDs and emits `out/compatibility.json` and `out/compatibility.md`. Syntax errors fail the workflow. This workflow does not run privileged software or require any Proxmox secrets.

Local single-script example after checking out both upstream repositories:

```bash
python scripts/scan_community_scripts.py \
    --source upstream-scripts --core upstream-core \
    --kind lxc --script adguard \
    --scripts-rev "$(git -C upstream-scripts rev-parse HEAD)" \
    --core-rev "$(git -C upstream-core rev-parse HEAD)" \
    --strict-syntax --output out
```

Review the `prompt_sites`, `flags`, and `defaulted_variables` for each application; compare actual declared Core variables before enabling creation.

## Disposable Proxmox integration host

Preferred: a dedicated **Proxmox VE VM** on an existing Proxmox host (or KVM/libvirt on a separate Linux workstation). Keep it on a restricted test VLAN with internet access as needed for installation. For a small initial lab, allocate approximately 4 vCPU, 8 GiB RAM, and 64–100 GiB of thin-provisioned storage; some applications need much more.

- For testing LXCs inside the Proxmox VM, the nested PVE guest needs working LXC/cgroups/storage/network support but does not require second-level KVM acceleration.
- For testing QEMU VMs inside the Proxmox VM, enable nested virtualization on the outer hypervisor and use a CPU configuration that exposes virtualization extensions to the PVE guest (for example `cpu: host`). Verify `vmx` or `svm` inside the PVE VM, and test that KVM is available. Nested VM performance and passthrough behavior may differ from bare metal.
- Record Proxmox version and host CPU/storage backend. Prefer a simple test bridge, one local VM storage pool, and a template-capable storage pool.
- Snapshot the **outer** Proxmox VM at a clean installation checkpoint. Do not grant the test scripts access to production CTIDs, storage, or network ranges.
- Run the Ansible controller outside the PVE VM; allow API access for reconciliation and separate SSH access only for installer/updater tests.
- Do not test scripts that require GPU passthrough, USB devices, public DNS, real credentials, or external services without specific isolated fixtures.

## Per-script end-to-end acceptance protocol

1. Pin the application script revision and the Core revision. Ensure script metadata matches the requested slug; document any application-specific input.
2. On a clean test PVE host, run script discovery and a read-only resource inspection. Confirm no installer has been executed.
3. Check that the VMID is absent and free across the PVE cluster. Run creation with a strict timeout and without a TTY. **Fail if a prompt occurs**; do not supply synthetic answers to a UI.
4. Confirm exact type/VMID, app identity, CPU, memory, disk, networking, tags/description, update entrypoint (LXC only), and expected application service or boot behavior.
5. Run Ansible again with the same desired values. It must report `changed: false` and must not rerun the upstream installer.
6. Increase CPU/RAM and grow a specifically identified disk; verify API task completion and actual resulting config. Re-run unchanged. Test attempted disk shrink and conflicting identity, both of which must fail before mutation.
7. In a separate, explicitly approved update scenario, test the LXC updater with backup and no automatic reboot; verify host and guest state after the operation. **Do not use the upstream updater's `var_dry_run=yes` as Ansible check mode**; the current implementation can still start containers and modify updater files.
8. Record test result, PVE version, storage backend, script/Core commit hashes, parameters, logs (without secrets), and cleanup status. Destroy only resources created by the test and revert the outer VM snapshot to reset host-side effects.

For CI, run Tier 0–2 on GitHub-hosted runners. Run Tier 3 manually or on a **trusted, isolated self-hosted runner** using an ephemeral PVE test environment. Do not expose PVE credentials or a privileged self-hosted runner to public PR code; require an explicit trusted manual trigger. Never run hundreds of real installations on every PR.

## Work prioritization

- Start with one standard LXC (Debian/Ubuntu), one application LXC, and one standard VM (Debian/Ubuntu). These validate the shared adapters.
- Investigate scripts classified as nonstandard entrypoints and application install-input candidates before calling them supported.
- When Core changes, rerun a representative adapter matrix plus scripts containing affected features; when a single app changes, rerun that app's static checks and selected integration test.
- Store versioned test evidence per application, not a universal boolean compatibility claim.


## Retirement-regression test
The scanner excludes exit-only retirement stubs from `compatibility.json.scripts` and writes them to `compatibility.json.excluded_retired` with the successor slug if found. Fixtures test explicit removal notices, rename notices, revival, and a normal installer containing a guarded error message. The bulk catalog filters the currently known retirements, while a specific script selection validates its pinned Git blob. The source status of any newly retired application must be rechecked before an installer is run.


## Experimental deployment role tests

`tests/test_deployment.py` covers normalized common LXC/VM settings, immutable revision checks, missing resources, recognized existing resources, resource type conflicts, unknown identity, and deliberate refusal of unsupported creation fields. GitHub Actions builds the collection and syntax-checks `examples/deploy.yml` without contacting PVE.

Dry-run usage: `ansible-playbook -i inventory examples/deploy.yml --check`. This performs API and GitHub source reads but skips SSH installation and host mutations. A missing VMID is reported as a **predicted** change; it does not reserve the ID. For real tests, configure an isolated nested PVE node and set both execution opt-in fields. The role is **not production tested**.

A real installation may fail after allocating resources. Do not interpret failed creation as a harmless no-op, and never automatically retry a failed installer until cluster state and unexpected VMIDs have been inspected. Core's LXC automatic-next-ID fallback makes atomic collision prevention an upstream integration requirement.


## Application management checks
Run the source/unit/role syntax tests in CI; `tests/test_update_once.py` uses a fake `pct` command and a harmless updater fixture, exercising first-run execution, same-request no-op, and identity rejection without Proxmox.

For live testing, first validate `action: inspect` and `--check` against a disposable LXC and VM. Next test existing CPU/RAM changes, pending reboot indications, VM disk growth through `community.proxmox.proxmox_disk`, and LXC rootfs growth through the guarded API. Confirm second-run `changed=false`. For `action: update`, test an explicit request ID with backup storage, retry with the same ID (no-op), a second ID, an unavailable app, stopped guest, a missing/incorrect `/usr/bin/update` and a simulated partial failure. Check that updating one LXC never touches another VMID, and detect hardware drift.

Do not treat a successful GitHub-hosted runner test as a successful real PVE deployment. Host SSH, Proxmox API ACLs, storage types, guest agent support, and cloud-init applicability still require integration verification. A `community.proxmox` module may have limited/no check mode; the wrapper intentionally performs only our read-only API planning in `--check`.


## SSH, Cloud-Init and legacy provenance tests
`tests/test_provenance_access.py` covers standard and legacy LXC updater identities, conflicting VM/LXC source evidence, malformed keys, multiple guest-creation option schemas, and cloud-init validation. The full collection CI checks Ansible syntax for the examples.

On an isolated PVE installation, verify fresh LXC SSH disabled by default; `ssh.enabled=true` with an authorized public key; two authorized keys; and no guest SSH dependency for `proxmox_pct_remote`. Validate VM cloud-init only for an image whose script calls the shared cloud-init hook. Confirm username, first-boot key access, DHCP/static IP, DNS, and that an incompatible appliance script fails early. On an existing VM, test the opt-in update while stopped with an existing cloud-init disk and a repeated run for idempotency.

Verify a running pre-existing LXC with only `/usr/bin/update` provenance is accepted for safe hardware planning, but a conflicting description is rejected. A stopped unknown LXC must not be started implicitly, and no guessed VM script tag should be accepted as identity.

Test `guest_ssh` with the LXC connection plugin on a stopped-vs-running guest, Debian/Ubuntu and Alpine, repeated runs, one and multiple keys, and explicit disable. It requires a controller with Paramiko and a PVE SSH identity authorized to execute `pct`; root access inside the guest is provided through that PVE connection rather than a guest key.

## Manual script override regression
Test three independent cases: unknown source + matching override is accepted for read-only planning and explicitly managed hardware; known source + conflicting override is rejected before mutation; mismatched guest kind/VMID is always rejected regardless of override. Check that `identity_status=overridden` is not reported as `verified`. An absent guest still requires immutable source refs, even if `script_override` is supplied. Existing guests must work without them. The host-side updater's own provenance check remains mandatory.

## Shared LXC/VM variable contract
Run `python -m scripts.verify_core_mapping --core upstream-core` against a pinned clone of community-scripts/core. The PR compatibility workflow already performs this test and fails on absent shared Core variable bindings. `tests/test_core_mapping.py` exercises synthetic Core and VM scripts. `tests/test_deployment.py` checks exact value encoding including binary/yes-no LXC options, VM CPU mode/cache, normalized `disk_size` and refusal of unknown keys. This remains static verification only: disposable PVE still must verify the *effective* properties for each VM script; a variable reference alone can occur in a message or default without being applied to qm create/set.

## Public identifiers and arbitrary app vars
Test LXC with `ctid` alone, VM with `vmid` alone, and reject dual identifiers, missing identifiers and kind mismatch before contacting Proxmox. Confirm internal API normalization still uses `vmid`. For custom environment, test `script_vars` with VM, LXC and application-specific variable names, and refuse raw overrides of guest IDs, `VM_UNATTENDED`, `PHS_SILENT`, Core hardware keys, `BASH_ENV`, `PATH`, `LD_PRELOAD`, `CLOUDINIT_*`, and other protected controls. Check bounds and that all secrets remain suppressed in Ansible logs. Live scripts may still ignore arbitrary variable names.


## Guest defaults and minimum guest declarations
CI executes `tests/guest_defaults.yml` on localhost using the actual `application` role's isolated defaults resolver. It checks shared, per-kind, and explicit guest settings precedence, plus the empty-map case. `test_omitted_settings_never_override_script_defaults` confirms that neither an LXC nor VM receives CPU/RAM/disk/hostname environment overrides when all normalized settings are omitted. This check does not execute any upstream installer and cannot certify default hardware values on a live Proxmox host.

## Lifecycle semantics regression
Confirm `action: present` calls only the guarded install-if-missing role and never the hardware adapter, regardless of `guest_defaults`. Confirm `action: reconcile` requires explicit per-guest CPU/memory/swap/sockets/disk_size or a separately approved existing-VM cloud-init change; it must never use inherited defaults. `action: update` must not touch hardware. No implicit reboot or disk shrinking.
