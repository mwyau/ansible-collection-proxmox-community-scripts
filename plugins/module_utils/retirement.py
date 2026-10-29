"""Conservative, read-only detection of retired Community Scripts entrypoints.

A missing build lifecycle is necessary but not sufficient: require an explicit
retirement/rename notice and an unconditional nonzero exit. This identifies
removal stubs without treating ordinary app updates as retired.
"""
import re

LXC_LIFECYCLE = re.compile(r"(?m)^\s*build_container(?:\s|$)")
VM_LIFECYCLE = re.compile(r"(?m)^\s*vm_start_script(?:\s|$)")
NONZERO_EXIT = re.compile(r"(?m)^exit\s+[1-9][0-9]*\s*(?:#.*)?$")
RETIRE_NOTICE = re.compile(
    r"(?im)^\s*msg_(?:warn|error)\s+"
    r"""(?:["'].*?(?:this\s+script\s+is\s+no\s+longer\s+available|
                        this\s+script\s+was\s+removed|
                        has\s+been\s+renamed\s+to)[^"']*["'])""",
    re.X,
)
SUCCESSOR = re.compile(r"(?i)\bhas\s+been\s+renamed\s+to\s+([A-Za-z][A-Za-z0-9_-]*)")
SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def retired_info(source, kind):
    """Return retirement metadata only on a high-confidence exit-only stub."""
    if kind not in ("lxc", "vm"):
        raise ValueError("kind must be lxc or vm")
    if not isinstance(source, str):
        raise TypeError("source must be text")
    lifecycle = LXC_LIFECYCLE if kind == "lxc" else VM_LIFECYCLE
    if lifecycle.search(source) or not NONZERO_EXIT.search(source):
        return None
    notice = RETIRE_NOTICE.search(source)
    if not notice:
        return None
    rename = SUCCESSOR.search(source)
    successor = rename.group(1).lower().replace("_", "-") if rename else None
    if successor and not SAFE_SLUG.fullmatch(successor):
        successor = None
    return {"status": "retired", "reason": "renamed" if successor else "removed",
            "successor": successor}
