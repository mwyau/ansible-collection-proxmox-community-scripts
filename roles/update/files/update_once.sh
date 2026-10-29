#!/usr/bin/env bash
# One explicit update request, serialized on the PVE host.
set -euo pipefail
umask 077

if [[ $# -ne 5 ]]; then
  echo 'Expected VMID, slug, request ID, script path and state directory' >&2
  exit 2
fi
vmid="$1"
slug="$2"
request_id="$3"
source_script="$4"
state_dir="$5"

[[ "$vmid" =~ ^[1-9][0-9]{2,8}$ ]] || exit 2
[[ "$slug" =~ ^[a-z0-9][a-z0-9-]*$ ]] || exit 2
[[ "$request_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || exit 2
[[ -f "$source_script" && ! -L "$source_script" ]] || exit 2
[[ -d "$state_dir" && ! -L "$state_dir" ]] || exit 2

exec 9>"$state_dir/.update.lock"
flock -x 9
marker="$state_dir/$request_id.complete"
if [[ -f "$marker" ]]; then
  echo 'ALREADY_APPLIED'
  exit 0
fi

status="$(pct status "$vmid")"
[[ "$status" == 'status: running' ]] || {
  echo 'LXC is not running; refusing update' >&2
  exit 4
}
update_file="$(pct exec "$vmid" -- cat /usr/bin/update)"
if ! grep -Eq "^export SCRIPT_SLUG=[\"']?$slug[\"']?$|^export UPDATE_SCRIPT_NAME=[\"']?$slug[\"']?$|/ct/$slug\.sh" <<<"$update_file"; then
  echo 'LXC updater identity mismatch; refusing update' >&2
  exit 5
fi

# Source was pinned by the role. The script may download additional app code.
bash "$source_script"
tmp="$(mktemp "$state_dir/.complete.XXXXXXXX")"
printf 'vmid=%s\nscript=%s\nrequest_id=%s\n' "$vmid" "$slug" "$request_id" >"$tmp"
chmod 0600 "$tmp"
mv -n "$tmp" "$marker"
echo 'APPLIED'
