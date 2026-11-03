#!/usr/bin/env python3
"""Snell V5 port-isolated quota controller. Python 3.9+, Linux/systemd/nftables."""
import argparse
import calendar
import contextlib
import datetime as dt
import getpass
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path('/etc/psm-snell-quota')
STATE = Path('/var/lib/psm-snell-quota')
UNIT = 'psm-snell-quota.service'
BIN = '/usr/local/lib/psm-snell-quota/snell-server'
LEASE = 256 * 1024**2
UTC = dt.timezone.utc


class CommandError(RuntimeError):
    """Safe diagnostic: executable/operation/exit code, never command input."""


def run(*args, input=None, check=True):
    p = subprocess.run(args, input=input, text=True, capture_output=True, timeout=30)
    if check and p.returncode:
        # Never include command input (may contain PSKs) or external error bodies.
        raise CommandError('command failed: ' + ' '.join(args[:3]) + f' (exit {p.returncode})')
    return p


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        d = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(d)
        finally:
            os.close(d)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read(path, default=None):
    if not path.exists():
        if default is not None:
            return default
        raise RuntimeError('required state missing: ' + str(path))
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise RuntimeError('expected root-only regular file: ' + str(path))
    return json.loads(path.read_text(encoding='utf-8'))


@contextlib.contextmanager
def locked(filename='lock'):
    import fcntl
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / filename).open('a') as f:
        os.chmod(STATE / filename, 0o600)
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def size(s):
    m = re.fullmatch(r'([1-9][0-9]*)([KMGT]?)(?:I?B)?', s.upper())
    if not m:
        raise argparse.ArgumentTypeError('positive integer bytes or 100G/500M required')
    n = int(m[1]) * 1024 ** (' KMGT'.index(m[2]) if m[2] else 0)
    if n > 2**60:
        raise argparse.ArgumentTypeError('quota too large')
    return n


def boundary(year, month, day, tz):
    """Local midnight; first occurrence on folds, first valid minute on gaps."""
    naive = dt.datetime(year, month, min(day, calendar.monthrange(year, month)[1]))
    for minute in range(48 * 60):
        local = (naive + dt.timedelta(minutes=minute)).replace(tzinfo=tz, fold=0)
        if local.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == local.replace(tzinfo=None):
            return local.astimezone(UTC)
    raise ValueError('timezone boundary cannot be resolved')


def shift(year, month, delta):
    n = year * 12 + month - 1 + delta
    return n // 12, n % 12 + 1


def cycle(now, day, zone):
    tz = ZoneInfo(zone)
    local = now.astimezone(tz)
    y, m = local.year, local.month
    start = boundary(y, m, day, tz)
    if now < start:
        y, m = shift(y, m, -1)
        start = boundary(y, m, day, tz)
    ny, nm = shift(y, m, 1)
    return start.isoformat(), int(boundary(ny, nm, day, tz).timestamp())


def table(name):
    return 'psmq_' + name.replace('-', '_')


def rules(u, allowance, end, uid, replace=False, generation='test'):
    """Only the direct client leg, shared quota for v4/v6 and TCP/UDP."""
    t, port = table(u['name']), u['port']
    lines = [f'delete table inet {t}'] if replace else []
    qname = 'budget_' + generation
    lines += [f'table inet {t} {{', f'quota {qname} {{ until {max(1, allowance)} bytes used 0 bytes; }}']
    for hook in ('input', 'output'):
        lines += [f'chain {hook} {{ type filter hook {hook} priority 10; policy accept;']
        for proto in ('tcp', 'udp'):
            if hook == 'input':
                match = f'iifname != "lo" {proto} dport {port}'
                eligible = 'ct direction original'
            else:
                match = f'oifname != "lo" meta skuid {uid} {proto} sport {port}'
                eligible = 'ct direction reply'
            if allowance > 0:
                lines += [f'{match} {eligible} meta time < {end} quota name "{qname}" accept']
            # Catch notrack/expired/over-quota packets as well.
            lines += [f'{match} drop']
        lines += ['}']
    lines += ['}']
    return '\n'.join(lines) + '\n'


def quota_used(name, generation):
    p = run('nft', '-j', 'list', 'quota', 'inet', table(name), 'budget_' + generation)
    objects = json.loads(p.stdout)['nftables']
    q = next(x['quota'] for x in objects if 'quota' in x)
    return int(q.get('used', 0))


def apply_rules(u, allowance, end, uid, generation):
    exists = run('nft', 'list', 'table', 'inet', table(u['name']), check=False).returncode == 0
    run('nft', '-f', '-', input=rules(u, allowance, end, uid, exists, generation))


def service(name, action, check=True):
    return run('systemctl', action, f'psmq-snell@{name}.service', check=check)


def stop_controller():
    # Let the controller drain child start jobs while its own unit stays active.
    # Stopping the parent transaction first can race BindsTo child activation.
    run('systemctl', 'kill', '--kill-whom=main', '--signal=SIGTERM', UNIT, check=False)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        state = run('systemctl', 'show', '--property=ActiveState,SubState', '--value', UNIT).stdout.split()
        if any(x in state for x in ('inactive', 'failed', 'auto-restart')):
            run('systemctl', 'stop', UNIT)
            return
        time.sleep(.2)
    raise RuntimeError('controller did not finish draining; no configuration changes made')


def stop_all(users):
    if users:
        # One transaction, including when a corrupt state prevents per-user recovery.
        run('systemctl', 'stop', *[f'psmq-snell@{u["name"]}.service' for u in users], check=False)


def start_controller():
    # Intentional maintenance must not consume the crash-loop restart allowance.
    run('systemctl', 'reset-failed', UNIT, check=False)
    run('systemctl', 'start', UNIT)


def event(db, key, message):
    if any(e['key'] == key for e in db['events']):
        return
    db['events'].append({'key': key, 'text': message[:2000], 'tries': 0, 'next': 0})
    # Keep a bounded outbox; never include credentials in messages.
    db['events'] = db['events'][-500:]
    print(message, flush=True)


def notify(db):
    secret_path = ROOT / 'telegram.json'
    if not secret_path.exists():
        return
    try:
        secret = read(secret_path)
        if not isinstance(secret['token'], str) or not isinstance(secret['chat_id'], str):
            raise ValueError('invalid telegram settings')
    except Exception:
        print('Telegram settings invalid/unreadable; messages remain queued', flush=True)
        return
    now = time.time()
    # At most one request per loop, after quota processing. Durable, at-least-once.
    item = next((e for e in db['events'] if e['next'] <= now), None)
    if item is None:
        return
    payload = json.dumps({'chat_id': secret['chat_id'], 'text': item['text']}).encode()
    try:
        req = urllib.request.Request('https://api.telegram.org/bot' + secret['token'] + '/sendMessage',
                                     data=payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=3) as r:
            if not json.load(r).get('ok'):
                raise RuntimeError('telegram rejected message')
        db['events'].remove(item)
    except Exception:
        # urllib exceptions can contain the secret URL. Do not print them.
        item['tries'] += 1
        item['next'] = now + min(3600, 5 * 2**min(item['tries'], 10))
        print('Telegram delivery failed; queued for retry (details redacted)', flush=True)


def fresh_db():
    return {'version': 1, 'users': {}, 'events': []}


def emergency(message=None):
    """Separate outbox when the main ledger/config cannot be read or written."""
    try:
        path = STATE / 'emergency.json'
        db = read(path, fresh_db())
        if message:
            event(db, 'emergency:' + str(int(time.time())), message)
            atomic(path, db)
        notify(db)
        if path.exists() or db['events']:
            atomic(path, db)
    except Exception:
        print('Emergency notification unavailable; inspect the local service journal', flush=True)


def roll(db, u, now):
    key, end = cycle(now, u['day'], u['tz'])
    s = db['users'].get(u['name'])
    if s is None:
        s = {'cycle': key, 'booked': 0, 'base': 0, 'lease': 0, 'warned': False, 'exceeded': False}
        db['users'][u['name']] = s
    elif key > s['cycle']:
        previous = s['cycle']
        s.update(cycle=key, booked=0, base=0, lease=0, warned=False, exceeded=False)
        event(db, f'{u["name"]}:{key}:reset', f'RESET {u["name"]}: {previous} -> {key}')
    elif key < s['cycle']:
        raise RuntimeError('clock moved behind persisted billing cycle')
    return s, end


def reserve(s, u):
    """Durably book before the caller installs a fresh kernel quota."""
    s['base'] = s['booked']
    s['lease'] = min(u['lease'], max(0, u['quota'] - s['base']))
    s['booked'] = s['base'] + s['lease']
    import secrets
    s['generation'] = secrets.token_hex(12)
    return s['lease']


def daemon():
    import pwd
    emergency()
    uid = pwd.getpwnam('snellquota').pw_uid
    cfg = read(ROOT / 'users.json')
    users = cfg['users']
    stop_all(users)
    # Refuse to initialize a lost ledger; otherwise deletion could grant fresh quota.
    db = read(STATE / 'ledger.json')
    stopping = [False]
    signal.signal(signal.SIGTERM, lambda *_: stopping.__setitem__(0, True))
    signal.signal(signal.SIGINT, lambda *_: stopping.__setitem__(0, True))
    initialized = set()
    started = set()
    clean = False
    try:
        while not stopping[0]:
            now = dt.datetime.now(UTC)
            for u in users:
                if stopping[0]:
                    break
                name = u['name']
                old_cycle = db['users'].get(name, {}).get('cycle')
                s, end = roll(db, u, now)
                changed = old_cycle is not None and old_cycle != s['cycle']
                if changed:
                    service(name, 'stop')
                    initialized.discard(name)
                    started.discard(name)
                if name not in initialized:
                    # A surviving generation-matched kernel object is authoritative
                    # after all instances have stopped. Reboot/lost table: spend lease.
                    if s['lease']:
                        try:
                            s['booked'] = s['base'] + min(s['lease'], quota_used(name, s['generation']))
                        except Exception:
                            event(db, name + ':' + s['cycle'] + ':recovery:' + str(s['booked']),
                                  f'ANOMALY {name}: kernel quota lost; up to {s["lease"]} bytes reserved conservatively')
                    if u.get('enabled', True):
                        amount = reserve(s, u)
                    else:
                        s['base'], s['lease'] = s['booked'], 0
                        import secrets
                        s['generation'] = secrets.token_hex(12)
                        amount = 0
                    atomic(STATE / 'ledger.json', db)
                    apply_rules(u, amount, end, uid, s['generation'])
                    initialized.add(name)
                used = min(s['lease'], quota_used(name, s['generation']))
                total = s['base'] + used
                if total >= u['quota']:
                    service(name, 'stop')
                    if not s['exceeded']:
                        event(db, f'{name}:{s["cycle"]}:exceeded', f'EXCEEDED {name}: {total}/{u["quota"]} bytes; stopped')
                        s['exceeded'] = True
                elif used >= s['lease'] and u.get('enabled', True):
                    # Old gate is exhausted. Replacing it cannot admit unbooked bytes.
                    amount = reserve(s, u)
                    atomic(STATE / 'ledger.json', db)
                    apply_rules(u, amount, end, uid, s['generation'])
                if total >= u['quota'] * u['warn'] / 100 and not s['warned']:
                    event(db, f'{name}:{s["cycle"]}:warning', f'WARNING {name}: {total}/{u["quota"]} bytes ({u["warn"]}%)')
                    s['warned'] = True
                if total < u['quota'] and u.get('enabled', True) and not stopping[0]:
                    if service(name, 'is-active', check=False).returncode:
                        if name in started:
                            event(db, f'{name}:{s["cycle"]}:inactive', f'ANOMALY {name}: instance inactive; attempting start')
                        service(name, 'start')
                    started.add(name)
            atomic(STATE / 'ledger.json', db)
            notify(db)
            atomic(STATE / 'ledger.json', db)
            if not stopping[0]:
                time.sleep(1)
        clean = True
    except Exception as e:
        # Sanitize exceptions: no subprocess output, URLs, PSKs, or tokens.
        event(db, 'controller:' + str(int(time.time())), 'ANOMALY controller halted: ' + type(e).__name__)
        raise
    finally:
        stop_all(users)
        if clean:
            for u in users:
                if u['name'] not in initialized:
                    continue
                s = db['users'][u['name']]
                s['booked'] = s['base'] + min(s['lease'], quota_used(u['name'], s['generation']))
                s['base'], s['lease'] = s['booked'], 0
        atomic(STATE / 'ledger.json', db)
        if not clean:
            notify(db)
            atomic(STATE / 'ledger.json', db)


def validate_user(name, port, day, zone, warn):
    # Hyphens forbidden: table names and systemd instances remain 1:1.
    if not re.fullmatch('[a-z][a-z0-9_]{0,23}', name):
        raise ValueError('name: lowercase letter followed by <=23 lowercase letters/digits/underscores')
    if not 1024 <= port <= 32767 or not 1 <= day <= 31 or not 1 <= warn <= 99:
        raise ValueError('port 1024..32767, reset day 1..31, warning 1..99 required')
    ZoneInfo(zone)
    ephemeral = Path('/proc/sys/net/ipv4/ip_local_port_range').read_text().split()
    if int(ephemeral[0]) <= port <= int(ephemeral[1]):
        raise ValueError('port overlaps system ephemeral range')


def mutate(args):
    # Deliberately stop all instances before changing credentials/accounting settings.
    stop_controller()
    try:
        with locked():
            cfg = read(ROOT / 'users.json')
            db = read(STATE / 'ledger.json')
            if args.command == 'add':
                validate_user(args.name, args.port, args.day, args.tz, args.warn)
                if any(u['name'] == args.name or u['port'] == args.port for u in cfg['users']):
                    raise ValueError('duplicate name or port')
                for flag in ('-ltn', '-lun'):
                    if run('ss', '-H', flag, f'sport = :{args.port}').stdout.strip():
                        raise ValueError('port is already listening')
                import secrets
                u = dict(name=args.name, port=args.port, quota=args.quota, day=args.day,
                         tz=args.tz, warn=args.warn, lease=args.lease, psk=secrets.token_hex(16))
                conf = ROOT / 'instances' / (args.name + '.conf')
                conf.write_text(f'[snell-server]\nlisten = ::0:{args.port}\npsk = {u["psk"]}\nipv6 = true\n', encoding='utf-8')
                import grp
                os.chown(conf, 0, grp.getgrnam('snellquota').gr_gid)
                os.chmod(conf, 0o640)
                # Ledger entry first: interruption may leave an unused entry, never free usage.
                roll(db, u, dt.datetime.now(UTC))
                atomic(STATE / 'ledger.json', db)
                cfg['users'].append(u)
                atomic(ROOT / 'users.json', cfg)
            elif args.command == 'delete':
                u = next(u for u in cfg['users'] if u['name'] == args.name)
                service(u['name'], 'stop')
                cfg['users'].remove(u)
                atomic(ROOT / 'users.json', cfg)
                run('nft', 'delete', 'table', 'inet', table(u['name']), check=False)
                (ROOT / 'instances' / (u['name'] + '.conf')).unlink(missing_ok=True)
                # Keep tombstone in ledger: re-adding a name in the same cycle retains usage.
            elif args.command in ('enable', 'disable', 'update'):
                u = next(u for u in cfg['users'] if u['name'] == args.name)
                if args.command == 'update':
                    for key in ('quota', 'warn', 'lease'):
                        value = getattr(args, key)
                        if value is not None:
                            if key == 'warn' and not 1 <= value <= 99:
                                raise ValueError('warning must be 1..99')
                            u[key] = value
                else:
                    u['enabled'] = args.command == 'enable'
                atomic(ROOT / 'users.json', cfg)
            elif args.command == 'telegram':
                token = getpass.getpass('Telegram bot token (hidden): ').strip()
                chat = getpass.getpass('Telegram chat_id (hidden): ').strip()
                if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token) or not re.fullmatch(r'-?[0-9]+', chat):
                    raise ValueError('invalid token/chat_id format')
                atomic(ROOT / 'telegram.json', {'token': token, 'chat_id': chat})
                event(db, 'telegram-test:' + str(int(time.time())), 'TEST Snell quota notifications configured')
                atomic(STATE / 'ledger.json', db)
    finally:
        # Automatic crash restarts still retain systemd's normal rate limit.
        start_controller()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    add = sub.add_parser('add')
    add.add_argument('name')
    add.add_argument('--port', required=True, type=int)
    add.add_argument('--quota', required=True, type=size)
    add.add_argument('--day', type=int, default=18)
    add.add_argument('--tz', default='Asia/Shanghai')
    add.add_argument('--warn', type=int, default=90)
    add.add_argument('--lease', type=size, default=LEASE)
    delete = sub.add_parser('delete')
    delete.add_argument('name')
    for command in ('enable', 'disable', 'update'):
        child = sub.add_parser(command)
        child.add_argument('name')
        if command == 'update':
            child.add_argument('--quota', type=size)
            child.add_argument('--warn', type=int)
            child.add_argument('--lease', type=size)
    sub.add_parser('telegram')
    sub.add_parser('status')
    export = sub.add_parser('export')
    export.add_argument('name')
    export.add_argument('--server', required=True)
    sub.add_parser('daemon')
    sub.add_parser('quiesce', help='drain and stop the controller before maintenance')
    sub.add_parser('restart', help='settle usage and restart all managed instances')
    a = p.parse_args()
    if os.geteuid() != 0:
        p.error('run as root')
    os.umask(0o077)
    if a.command in ('add', 'delete', 'telegram', 'enable', 'disable', 'update'):
        with locked('admin.lock'):
            mutate(a)
    elif a.command == 'daemon':
        with locked():
            daemon()
    elif a.command == 'quiesce':
        stop_controller()
    elif a.command == 'restart':
        with locked('admin.lock'):
            stop_controller()
            start_controller()
    elif a.command == 'export':
        u = next(u for u in read(ROOT / 'users.json')['users'] if u['name'] == a.name)
        if not re.fullmatch(r'[A-Za-z0-9.:[\]-]+', a.server):
            raise ValueError('invalid server address')
        print(f'{u["name"]} = snell, {a.server}, {u["port"]}, psk={u["psk"]}, version=5, reuse=true')
    else:
        db = read(STATE / 'ledger.json')
        for u in read(ROOT / 'users.json')['users']:
            s = db['users'][u['name']]
            try:
                used = s['base'] + min(s['lease'], quota_used(u['name'], s['generation'])) if s['lease'] else s['booked']
                quality = 'live'
            except Exception:
                used, quality = s['booked'], 'reserved-upper-bound; kernel gate unavailable'
            print(json.dumps(dict(name=u['name'], port=u['port'], used=used, quota=u['quota'],
                                  cycle=s['cycle'], day=u['day'], tz=u['tz'], enabled=u.get('enabled', True), measurement=quality)))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Exception messages from network libraries can contain credentials.
        detail = ': ' + str(exc) if isinstance(exc, CommandError) else ''
        print('Failed: ' + type(exc).__name__ + detail + '; check configuration, ledger and service journal.', file=sys.stderr)
        if len(sys.argv) > 1 and sys.argv[1] == 'daemon':
            emergency('ANOMALY controller startup/runtime failed: ' + type(exc).__name__)
        sys.exit(1)
