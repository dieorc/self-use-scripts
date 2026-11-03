#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
[[ $EUID == 0 ]] || { echo 'Run as root' >&2; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'Linux + systemd required' >&2; exit 1; }
for cmd in python3 nft ss systemctl useradd groupadd getent sha256sum; do
    command -v "$cmd" >/dev/null || { echo "Missing dependency: $cmd" >&2; exit 1; }
done
python3 -c 'from zoneinfo import ZoneInfo; ZoneInfo("Asia/Shanghai")'
# Feature check without modifying the active firewall.
python3 - <<'PY' | nft -c -f -
import importlib.util, time
s = importlib.util.spec_from_file_location('q', 'snell_quota.py')
q = importlib.util.module_from_spec(s)
s.loader.exec_module(q)
print(q.rules({'name':'preflight', 'port':21000}, 1024, int(time.time()) + 3600, 0))
PY
core="${1:-/usr/local/bin/snell-server}"
[[ -x "$core" ]] || { echo 'Pass the path to an official Snell V5 binary' >&2; exit 1; }
version=$("$core" --v 2>&1 || true)
[[ "$version" =~ v5\.[0-9]+\.[0-9]+ ]] || { echo 'Expected an official V5 binary; refusing other versions' >&2; exit 1; }
# Stop before upgrades, preserving the current ledger and settling live counters.
if systemctl cat psm-snell-quota.service >/dev/null 2>&1; then
    python3 snell_quota.py quiesce
fi
getent group snellquota >/dev/null || groupadd --system snellquota
getent passwd snellquota >/dev/null || useradd --system --gid snellquota --no-create-home --shell /usr/sbin/nologin snellquota
install -d -m 750 -o root -g snellquota /etc/psm-snell-quota /etc/psm-snell-quota/instances
install -d -m 700 /var/lib/psm-snell-quota
install -d -m 755 /usr/local/lib/psm-snell-quota
if [[ ! "$core" -ef /usr/local/lib/psm-snell-quota/snell-server ]]; then
    install -m 755 "$core" /usr/local/lib/psm-snell-quota/snell-server
fi
install -m 755 snell_quota.py /usr/local/lib/psm-snell-quota/snell_quota.py
install -m 755 manage.sh /usr/local/lib/psm-snell-quota/manage.sh
install -m 755 psm-snell /usr/local/bin/psm-snell
install -m 644 systemd/*.service /etc/systemd/system/
# A missing ledger on an existing installation is an error, never a fresh quota.
if [[ ! -e /etc/psm-snell-quota/users.json ]]; then
    [[ ! -e /var/lib/psm-snell-quota/ledger.json ]] || { echo 'Orphan ledger: investigate before initialization' >&2; exit 1; }
    printf '%s\n' '{"version":1,"users":{},"events":[]}' > /var/lib/psm-snell-quota/ledger.json
    printf '%s\n' '{"users":[]}' > /etc/psm-snell-quota/users.json
fi
[[ -f /var/lib/psm-snell-quota/ledger.json ]] || { echo 'Ledger missing; restore a consistent backup' >&2; exit 1; }
chmod 600 /etc/psm-snell-quota/users.json /var/lib/psm-snell-quota/ledger.json
sha256sum /usr/local/lib/psm-snell-quota/snell-server > /var/lib/psm-snell-quota/core.sha256
systemctl daemon-reload
systemctl reset-failed psm-snell-quota.service
systemctl enable --now psm-snell-quota.service
echo 'Installed. Next: psm-snell add alice --port 21001 --quota 100G --day 18 --tz Asia/Shanghai'
