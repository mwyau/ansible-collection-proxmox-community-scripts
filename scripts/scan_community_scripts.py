#!/usr/bin/env python3
"""Read-only static audit of Community Scripts and their shared Core.

Parse shell syntax with bash -n; never source or execute installer scripts.
Assess architecture and prompt risks, not unattended installation success.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

# The same detector is used when verifying a selected catalog entry.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins' / 'module_utils'))
from retirement import retired_info

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
VARS = re.compile(r"\b(?:var_[A-Za-z0-9_]+|VM_[A-Z0-9_]+)\b")
PROMPT = re.compile(
    r"\b(msg_menu|vm_dialog|whiptail|dialog|prompt_confirm|prompt_input|read\s+(?:-[rpsn]+\s+)*-[rp])\b"
)
FUNCTION = re.compile(r"^\s*(?:function\s+)?([A-Za-z_]\w*)\s*(?:\(\s*\))?\s*\{")
LXC_CORE = re.compile(r"core/build\.func")
VM_CORE = re.compile(r"pve/vm-core\.func")


def syntax(path):
    result = subprocess.run(["bash", "-n", str(path)], capture_output=True,
                            text=True, check=False, timeout=15)
    return {"syntax_ok": result.returncode == 0,
            "syntax_error": result.stderr.strip()[:500] if result.returncode else None}


def prompt_sites(lines, filename):
    """Evidence locations with approximate function names, not proof of reachability."""
    scope = "unknown"
    result = []
    for number, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        match = FUNCTION.match(line)
        if match:
            scope = match.group(1)
        match = PROMPT.search(line)
        if match:
            result.append({"file": filename, "line": number,
                           "operation": match.group(1).split()[0],
                           "near_function": scope, "sample": stripped[:120]})
    return result


def core_contract(root):
    if root is None:
        return {"lxc": False, "vm": False}
    lxc = root / "core" / "core.func"
    vm = root / "pve" / "vm-core.func"
    lxc_text = lxc.read_text(errors="replace") if lxc.is_file() else ""
    vm_text = vm.read_text(errors="replace") if vm.is_file() else ""
    return {"lxc": "is_unattended()" in lxc_text,
            "vm": all(x in vm_text for x in
                      ("vm_start_script()", "vm_apply_env_overrides()", "VM_UNATTENDED"))}


def analyze(path, kind, root=None, contract=None):
    body = path.read_text(encoding="utf-8", errors="replace")
    lines = body.splitlines()
    result = syntax(path)
    retirement = retired_info(body, kind)
    engine = bool((LXC_CORE if kind == "lxc" else VM_CORE).search(body))
    lifecycle = (bool(re.search(r"(?m)^\s*start\s*$", body)) and
                 "build_container" in body if kind == "lxc"
                 else bool(re.search(r"\bvm_start_script\b", body)))
    shared = engine and lifecycle and bool((contract or {}).get(kind))
    prompts = prompt_sites(lines, path.name)
    payload = None
    if kind == "lxc" and root is not None:
        candidate = root / "install" / (path.stem + "-install.sh")
        if candidate.is_file():
            payload = {"path": "install/" + candidate.name, **syntax(candidate)}
            prompts += prompt_sites(candidate.read_text(encoding="utf-8", errors="replace").splitlines(),
                                    payload["path"])
    direct = [p for p in prompts if p["operation"] in ("whiptail", "dialog")]
    app = [p for p in prompts if p["operation"] in
           ("msg_menu", "vm_dialog", "prompt_input", "read")]
    flags = []
    if not engine:
        flags.append("no_recognized_shared_engine")
    elif not lifecycle:
        flags.append("nonstandard_engine_entrypoint")
    if direct:
        flags.append("direct_dialog_review")
    if app:
        flags.append("application_input_review")
    if kind == "lxc" and re.search(r"var_os\s*=\s*\$\(msg_menu", body):
        flags.append("set_var_os_for_os_menu")
    if kind == "lxc" and payload is None:
        flags.append("standard_install_payload_not_found")
    if payload and not payload["syntax_ok"]:
        flags.append("install_payload_syntax_error")
    # Approximate phase from the nearest function declaration. This does not
    # prove control-flow reachability; keep the original call sites in JSON.
    def prompt_phase(site):
        name = site["near_function"].lower()
        if name.startswith(("update_", "update")):
            return "update"
        if name in ("advanced_settings", "vm_prompt_vmid", "vm_prompt_cloud_init"):
            return "interactive_wizard"
        return "installation_or_unknown"

    phase_counts = Counter(prompt_phase(site) for site in prompts)
    if not result["syntax_ok"] or (payload and not payload["syntax_ok"]):
        assessment = "syntax_error"
    elif retirement:
        assessment = "retired"
    elif not shared:
        assessment = "custom_entrypoint"
    elif not prompts:
        assessment = "shared_engine_no_app_prompts_detected"
    elif phase_counts["installation_or_unknown"]:
        assessment = "shared_engine_install_input_review"
    elif phase_counts["interactive_wizard"]:
        assessment = "shared_engine_wizard_prompt_review"
    else:
        assessment = "shared_engine_update_prompts_only"
    result.update({
        "kind": kind, "slug": path.stem, "engine": (
            "lxc_core" if kind == "lxc" and engine else
            "vm_core" if kind == "vm" and engine else "unknown"),
        "standard_entrypoint": lifecycle, "shared_engine_unattended_contract": shared,
        "assessment": assessment, "retirement": retirement, "flags": flags, "prompt_sites": prompts,
        "prompt_phase_counts": dict(phase_counts),
        "variables": sorted(set(VARS.findall(body))),
        "defaulted_variables": sorted(set(re.findall(
            r"\b(var_[A-Za-z0-9_]+|VM_[A-Z0-9_]+)\s*=", body))),
        "install_payload": payload,
        "has_prompt_calls": bool(prompts),
        "has_unattended_hint": "VM_UNATTENDED" in body if kind == "vm" else "var_unattended" in body,
        "live_validation_required": True,
    })
    return result


def scan(root, kind="all", slug=None, core=None):
    if kind not in ("lxc", "vm", "all"):
        raise ValueError("Invalid kind")
    if slug is not None and not SLUG.fullmatch(slug):
        raise ValueError("Invalid script name")
    contract = core_contract(core)
    rows = []
    for item in (("lxc", "vm") if kind == "all" else (kind,)):
        folder = root / ("ct" if item == "lxc" else "vm")
        if not folder.is_dir():
            raise ValueError("Missing scripts directory " + str(folder))
        paths = [folder / (slug + ".sh")] if slug else sorted(folder.glob("*.sh"))
        rows.extend(analyze(path, item, root, contract) for path in paths
                    if path.is_file() and SLUG.fullmatch(path.stem))
    if slug and not rows:
        raise ValueError("Script not found: " + slug)
    return rows


def markdown(rows, revision, core_revision, retired=None):
    retired = retired or []
    counts = Counter(row["assessment"] for row in rows)
    labels = ("shared_engine_no_app_prompts_detected",
              "shared_engine_update_prompts_only",
              "shared_engine_wizard_prompt_review",
              "shared_engine_install_input_review",
              "custom_entrypoint", "syntax_error")
    lines = [
        "# Upstream script compatibility", "",
        "Scripts SHA: " + revision + "  ", "Core SHA: " + core_revision, "",
        "**Source analysis only. No scripts were executed or certified.**", "",
        "Retired scripts excluded: **%d**." % len(retired), "",
        "| Architecture and prompt category | Count |", "| --- | ---: |",
    ]
    for label in labels:
        lines.append("| %s | %s |" % (label.replace("_", " "), counts[label]))
    lines.extend(["", "A shared-engine result indicates the script uses a Core "
                  "entry point with an unattended branch, not that deployment will succeed.",
                  "", "| Kind | Script | Engine | Assessment | Prompts | Flags |",
                  "| --- | --- | --- | --- | ---: | --- |"])
    for row in rows[:150]:
        lines.append("| %s | %s | %s | %s | %d | %s |" % (
            row["kind"], row["slug"], row["engine"], row["assessment"],
            len(row["prompt_sites"]), ", ".join(row["flags"])))
    if len(rows) > 150:
        lines.append("First 150 shown; see JSON artifact for all scripts.")
    if retired:
        lines.extend(["", "## Excluded retired scripts", "", "| Kind | Slug | Reason | Successor |", "| --- | --- | --- | --- |"])
        for row in retired:
            record = row["retirement"]
            lines.append("| %s | %s | %s | %s |" % (row["kind"], row["slug"], record["reason"], record["successor"] or "—"))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--core", type=Path)
    parser.add_argument("--kind", choices=("all", "lxc", "vm"), default="all")
    parser.add_argument("--script")
    parser.add_argument("--scripts-rev", default="unknown")
    parser.add_argument("--core-rev", default="unknown")
    parser.add_argument("--output", type=Path, default=Path("out"))
    parser.add_argument("--strict-syntax", action="store_true")
    parser.add_argument("--include-retired", action="store_true", help="Include retired stubs in the main script list")
    args = parser.parse_args()
    all_rows = scan(args.source, args.kind, args.script, args.core)
    retired = [r for r in all_rows if r["retirement"]]
    rows = all_rows if args.include_retired else [r for r in all_rows if not r["retirement"]]
    core_syntax = []
    if args.core:
        for path in sorted(args.core.rglob("*.func")):
            core_syntax.append({"path": str(path), **syntax(path)})
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "compatibility.json").write_text(json.dumps({
        "scripts_revision": args.scripts_rev, "core_revision": args.core_rev,
        "scripts": rows, "excluded_retired": retired, "core": core_syntax, "validation": "static_only",
    }, indent=2) + "\n")
    report = markdown(rows, args.scripts_rev, args.core_rev, retired)
    (args.output / "compatibility.md").write_text(report)
    print("\n".join(report.splitlines()[:13]))
    if args.strict_syntax and any(not row["syntax_ok"] for row in all_rows + core_syntax):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
