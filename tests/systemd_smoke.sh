#!/usr/bin/env bash
# Installs official V5 only on a disposable GitHub-hosted Linux runner.
set -euo pipefail
umask 077
[[ $EUID == 0 && ${GITHUB_ACTIONS:-} == true && ${RUNNER_ENVIRONMENT:-} == github-hosted ]] || {
    echo 'Refusing: disposable GitHub-hosted runner only' >&2; exit 1;
}
[[ ! -e /etc/psm-snell-quota && ! -e /var/lib/psm-snell-quota ]] || {
    echo 'Refusing: an existing installation is present' >&2; exit 1;
}
cleanup() {
    local rc=$?
    if (( rc != 0 )); then
        journalctl -u psm-snell-quota -n 40 --no-pager || true
    fi
    systemctl disable --now psm-snell-quota.service >/dev/null 2>&1 || true
    exit "$rc"
}
trap cleanup EXIT
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
bash oneclick.sh
psm-snell add smoke_a --port 21001 --quota 2M --day 18 --tz Asia/Shanghai --lease 512K
psm-snell add smoke_b --port 21002 --quota 10M --day 31 --tz Europe/Berlin --lease 512K
for attempt in {1..15}; do
    if systemctl is-active --quiet psmq-snell@smoke_a && systemctl is-active --quiet psmq-snell@smoke_b \
        && ss -Hltn 'sport = :21001' | grep -q . && ss -Hltn 'sport = :21002' | grep -q .; then
        break
    fi
    sleep 1
done
systemctl is-active --quiet psm-snell-quota psmq-snell@smoke_a psmq-snell@smoke_b
ss -Hltn 'sport = :21001' | grep -q .
ss -Hltn 'sport = :21002' | grep -q .
psm-snell status
python3 - <<'PY'
import json, os, stat
from pathlib import Path
u=json.loads(Path('/etc/psm-snell-quota/users.json').read_text())['users']
assert len(u)==2 and len({x['psk'] for x in u})==2
assert all(len(x['psk'])==32 for x in u)
for p in ('/etc/psm-snell-quota/users.json','/var/lib/psm-snell-quota/ledger.json'):
    assert stat.S_IMODE(os.stat(p).st_mode)==0o600
    assert os.stat(p).st_uid==0
PY
psm-snell disable smoke_b
sleep 2
! systemctl is-active --quiet psmq-snell@smoke_b
systemctl is-active --quiet psmq-snell@smoke_a
psm-snell enable smoke_b
sleep 2
systemctl is-active --quiet psmq-snell@smoke_b
psm-snell update smoke_a --quota 3M --warn 80
sleep 2
systemctl is-active --quiet psmq-snell@smoke_a
psm-snell restart
sleep 2
systemctl is-active --quiet psmq-snell@smoke_a psmq-snell@smoke_b
systemctl restart psm-snell-quota
sleep 2
systemctl is-active --quiet psmq-snell@smoke_a psmq-snell@smoke_b
# Upgrade using the installed core exercises idempotent same-file handling.
bash install.sh /usr/local/lib/psm-snell-quota/snell-server
sleep 2
systemctl is-active --quiet psmq-snell@smoke_a psmq-snell@smoke_b
psm-snell delete smoke_b
sleep 2
! systemctl is-active --quiet psmq-snell@smoke_b
systemctl is-active --quiet psmq-snell@smoke_a
echo 'PASS: one-click installation, official V5 listeners, independent PSKs, permissions, disable/enable, quota update, restart, upgrade and deletion'
