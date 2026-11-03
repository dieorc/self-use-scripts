import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import types

SPEC = importlib.util.spec_from_file_location('quota', Path(__file__).resolve().parents[1] / 'snell_quota.py')
q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(q)


def at(s):
    return dt.datetime.fromisoformat(s).astimezone(q.UTC)


class CalendarTests(unittest.TestCase):
    def test_shanghai_18_boundary(self):
        old, _ = q.cycle(at('2026-11-17T15:59:59+00:00'), 18, 'Asia/Shanghai')
        new, end = q.cycle(at('2026-11-17T16:00:00+00:00'), 18, 'Asia/Shanghai')
        self.assertEqual(old, '2026-10-17T16:00:00+00:00')
        self.assertEqual(new, '2026-11-17T16:00:00+00:00')
        self.assertEqual(end, int(at('2026-12-17T16:00:00+00:00').timestamp()))

    def test_31_clamps_and_returns_to_31(self):
        k, end = q.cycle(at('2026-02-28T12:00:00+00:00'), 31, 'UTC')
        self.assertEqual(k, '2026-02-28T00:00:00+00:00')
        self.assertEqual(end, int(at('2026-03-31T00:00:00+00:00').timestamp()))

    def test_leap_year(self):
        k, _ = q.cycle(at('2028-02-29T01:00:00+00:00'), 31, 'UTC')
        self.assertEqual(k, '2028-02-29T00:00:00+00:00')

    def test_year_rollover(self):
        k, end = q.cycle(at('2027-01-01T00:00:00+00:00'), 18, 'UTC')
        self.assertEqual(k, '2026-12-18T00:00:00+00:00')
        self.assertEqual(end, int(at('2027-01-18T00:00:00+00:00').timestamp()))

    def test_dst_changes_interval(self):
        k, end = q.cycle(at('2026-03-18T12:00:00+00:00'), 18, 'America/New_York')
        self.assertEqual(k, '2026-03-18T04:00:00+00:00')
        before, previous_end = q.cycle(at('2026-02-18T12:00:00+00:00'), 18, 'America/New_York')
        self.assertEqual(before, '2026-02-18T05:00:00+00:00')
        self.assertEqual(previous_end, int(at(k).timestamp()))

    def test_nonexistent_midnight(self):
        # Brazil moved from 23:59 to 01:00 on this historical date.
        b = q.boundary(2018, 11, 4, q.ZoneInfo('America/Sao_Paulo'))
        self.assertEqual(b, at('2018-11-04T03:00:00+00:00'))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.u = dict(name='alice', port=21001, day=18, tz='UTC', quota=1000, lease=256, warn=90)
        self.db = q.fresh_db()
        self.s, _ = q.roll(self.db, self.u, at('2026-11-20T00:00:00+00:00'))

    def test_reservation_before_gate(self):
        self.assertEqual(q.reserve(self.s, self.u), 256)
        self.assertEqual((self.s['base'], self.s['booked']), (0, 256))
        self.assertEqual(q.reserve(self.s, self.u), 256)
        self.assertEqual((self.s['base'], self.s['booked']), (256, 512))

    def test_final_reservation_and_exceeded(self):
        self.s['booked'] = 950
        self.assertEqual(q.reserve(self.s, self.u), 50)
        self.assertEqual(q.reserve(self.s, self.u), 0)
        self.assertEqual(self.s['booked'], 1000)

    def test_unclean_recovery_never_grants_free_bytes(self):
        q.reserve(self.s, self.u)
        recovered = json.loads(json.dumps(self.s))
        q.reserve(recovered, self.u)
        self.assertEqual(recovered['base'], 256)
        self.assertEqual(recovered['booked'], 512)

    def test_generation_changes_per_lease(self):
        q.reserve(self.s, self.u)
        first = self.s['generation']
        q.reserve(self.s, self.u)
        self.assertNotEqual(first, self.s['generation'])

    def test_new_cycle_recovers_full_account(self):
        self.s.update(booked=1000, base=1000, exceeded=True, warned=True)
        s, _ = q.roll(self.db, self.u, at('2026-12-18T00:00:00+00:00'))
        self.assertEqual(s['booked'], 0)
        self.assertFalse(s['exceeded'])
        self.assertFalse(s['warned'])
        q.roll(self.db, self.u, at('2026-12-18T00:01:00+00:00'))
        self.assertEqual(len(self.db['events']), 1)

    def test_multiple_missed_months_single_current_cycle(self):
        q.roll(self.db, self.u, at('2027-05-20T00:00:00+00:00'))
        self.assertEqual(self.s['cycle'], '2027-05-18T00:00:00+00:00')
        self.assertEqual(len(self.db['events']), 1)

    def test_clock_rollback_fails(self):
        with self.assertRaises(RuntimeError):
            q.roll(self.db, self.u, at('2026-10-20T00:00:00+00:00'))

    def test_same_cycle_preserves_usage(self):
        self.s['booked'] = 650
        q.roll(self.db, self.u, at('2026-12-17T23:59:59+00:00'))
        self.assertEqual(self.s['booked'], 650)

    def test_independent_users(self):
        self.s['booked'] = 999
        bob = dict(self.u, name='bob')
        other, _ = q.roll(self.db, bob, at('2026-11-20T00:00:00+00:00'))
        self.assertEqual(other['booked'], 0)


class RulesAndNotifyTests(unittest.TestCase):
    def test_rules_scope_and_shared_quota(self):
        rules = q.rules(dict(name='alice', port=21001), 1000, 1900000000, 995)
        self.assertEqual(rules.count('quota name "budget_test"'), 4)
        self.assertEqual(rules.count('meta time < 1900000000'), 4)
        self.assertEqual(rules.count('ct direction original'), 2)
        self.assertEqual(rules.count('ct direction reply'), 2)
        self.assertEqual(rules.count('meta skuid 995'), 4)
        self.assertNotIn('hook forward', rules)
        self.assertIn('table inet', rules)
        self.assertNotIn('flush ruleset', rules)

    def test_zero_quota_gate_drops(self):
        rules = q.rules(dict(name='alice', port=21001), 0, 1900000000, 995)
        self.assertNotIn('quota name', rules)
        self.assertEqual(rules.count(' drop'), 4)

    def test_quota_json_decoding(self):
        response = type('P', (), {'stdout': json.dumps({'nftables': [{'metainfo': {}}, {'quota': {'used': 456}}]})})()
        with patch.object(q, 'run', return_value=response) as call:
            self.assertEqual(q.quota_used('alice', 'generation'), 456)
            self.assertEqual(call.call_args.args[-1], 'budget_generation')

    def test_notification_retry_redacts_secret(self):
        db = q.fresh_db()
        q.event(db, 'one', 'EXCEEDED alice')
        with tempfile.TemporaryDirectory() as td, patch.object(q, 'ROOT', Path(td)):
            # Use real permission checks on Linux; stub file loading on Windows.
            (Path(td) / 'telegram.json').write_text('{}')
            with patch.object(q, 'read', return_value={'token': '123:SECRET', 'chat_id': '-1'}), \
                 patch.object(q.urllib.request, 'urlopen', side_effect=RuntimeError('123:SECRET')), \
                 patch('builtins.print') as out:
                q.notify(db)
                self.assertEqual(db['events'][0]['tries'], 1)
                self.assertNotIn('SECRET', str(out.call_args_list))
                self.assertGreater(db['events'][0]['next'], 0)

    def test_notification_success(self):
        db = q.fresh_db()
        q.event(db, 'one', 'RESET alice')
        import io
        with tempfile.TemporaryDirectory() as td, patch.object(q, 'ROOT', Path(td)):
            (Path(td) / 'telegram.json').write_text('{}')
            with patch.object(q, 'read', return_value={'token': '123:SECRET', 'chat_id': '-1'}), \
                 patch.object(q.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"ok":true}')):
                q.notify(db)
                self.assertEqual(db['events'], [])

    def test_bad_telegram_settings_preserve_queue(self):
        db = q.fresh_db()
        q.event(db, 'one', 'EXCEEDED alice')
        with tempfile.TemporaryDirectory() as td, patch.object(q, 'ROOT', Path(td)):
            (Path(td) / 'telegram.json').write_text('{}')
            with patch.object(q, 'read', side_effect=ValueError('invalid settings')), patch('builtins.print'):
                q.notify(db)
                self.assertEqual(len(db['events']), 1)

    def test_sizes(self):
        for text, result in [('100G', 100 * 1024**3), ('1', 1), ('32MiB', 32 * 1024**2)]:
            self.assertEqual(q.size(text), result)

    def test_invalid_sizes(self):
        for s in ('0', '-1', '2.5G', 'foo', '99999999999999999999T'):
            with self.assertRaises(Exception):
                q.size(s)


class ControllerTests(unittest.TestCase):
    def drive(self, config, db, usage, loops=1):
        handlers, saved, gates, actions = {}, [], [], []
        counter = [0]
        def save(path, value):
            saved.append(json.loads(json.dumps(value)))
        def gate(u, amount, end, uid, generation):
            assert saved[-1]['users'][u['name']]['booked'] >= amount
            gates.append((u['name'], amount))
        def sleep(_):
            counter[0] += 1
            if counter[0] >= loops:
                handlers[q.signal.SIGTERM](None, None)
        def service(name, action, check=True):
            actions.append((name, action))
            return types.SimpleNamespace(returncode=1 if action == 'is-active' else 0)
        pwd = types.SimpleNamespace(getpwnam=lambda _: types.SimpleNamespace(pw_uid=995))
        with patch.dict('sys.modules', {'pwd': pwd}), \
             patch.object(q, 'emergency'), \
             patch.object(q, 'read', side_effect=[config, db]), \
             patch.object(q, 'stop_all') as stopped, \
             patch.object(q.signal, 'signal', side_effect=lambda sig, fn: handlers.__setitem__(sig, fn)), \
             patch.object(q, 'atomic', side_effect=save), \
             patch.object(q, 'apply_rules', side_effect=gate), \
             patch.object(q, 'quota_used', side_effect=usage), \
             patch.object(q, 'service', side_effect=service), \
             patch.object(q, 'notify'), patch.object(q.time, 'sleep', side_effect=sleep):
            try:
                q.daemon()
            except RuntimeError:
                self.assertGreaterEqual(stopped.call_count, 2)
                raise
        return db, gates, actions, saved

    def user(self):
        return dict(name='alice', port=21001, day=18, tz='UTC', quota=1000, lease=256, warn=90)

    def test_normal_stop_settles_actual_bytes(self):
        u = self.user()
        db, gates, actions, _ = self.drive({'users':[u]}, q.fresh_db(), [23, 30])
        self.assertEqual(db['users']['alice']['booked'], 30)
        self.assertEqual(db['users']['alice']['lease'], 0)
        self.assertIn(('alice', 'start'), actions)
        self.assertEqual(gates, [('alice', 256)])

    def test_recover_surviving_kernel_generation(self):
        u, db = self.user(), q.fresh_db()
        s, _ = q.roll(db, u, dt.datetime.now(q.UTC))
        q.reserve(s, u)
        db, _, _, _ = self.drive({'users':[u]}, db, [40, 10, 20])
        self.assertEqual(db['users']['alice']['booked'], 60)

    def test_reboot_uses_reserved_upper_bound(self):
        u, db = self.user(), q.fresh_db()
        s, _ = q.roll(db, u, dt.datetime.now(q.UTC))
        q.reserve(s, u)
        db, _, _, _ = self.drive({'users':[u]}, db, [RuntimeError('missing kernel quota'), 10, 20])
        self.assertEqual(db['users']['alice']['booked'], 276)
        self.assertTrue(any('kernel quota lost' in e['text'] for e in db['events']))

    def test_full_quota_stops_instance(self):
        u = dict(self.user(), quota=100)
        db, _, actions, _ = self.drive({'users':[u]}, q.fresh_db(), [101, 200])
        self.assertIn(('alice', 'stop'), actions)
        self.assertNotIn(('alice', 'start'), actions)
        self.assertEqual(db['users']['alice']['booked'], 100)
        self.assertTrue(any('EXCEEDED' in e['text'] for e in db['events']))

    def test_exhausted_lease_replenishes(self):
        db, gates, _, _ = self.drive({'users':[self.user()]}, q.fresh_db(), [260, 10])
        self.assertEqual(gates, [('alice', 256), ('alice', 256)])
        self.assertEqual(db['users']['alice']['booked'], 266)

    def test_disabled_account_keeps_usage_and_stays_stopped(self):
        u, db = dict(self.user(), enabled=False), q.fresh_db()
        s, _ = q.roll(db, u, dt.datetime.now(q.UTC))
        s.update(base=321, booked=321)
        db, gates, actions, _ = self.drive({'users':[u]}, db, [0, 0])
        self.assertEqual(gates, [('alice', 0)])
        self.assertNotIn(('alice', 'start'), actions)
        self.assertEqual(db['users']['alice']['booked'], 321)

    def test_missing_runtime_quota_fails_closed(self):
        with self.assertRaises(RuntimeError):
            self.drive({'users':[self.user()]}, q.fresh_db(), [RuntimeError('quota removed')])


if __name__ == '__main__':
    unittest.main()
