#!/usr/bin/env python3
"""Root-only real TCP/UDP/IPv4/IPv6 nft test, isolated with unshare -n.
Does NOT claim Snell protocol/Surge end-to-end validation.
"""
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

spec = importlib.util.spec_from_file_location('q', Path(__file__).resolve().parents[1] / 'snell_quota.py')
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)


def cmd(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def echo(family, kind, port):
    sock = socket.socket(family, kind)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if family == socket.AF_INET6:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    sock.bind(('::' if family == socket.AF_INET6 else '0.0.0.0', port))
    if kind == socket.SOCK_DGRAM:
        def loop():
            while True:
                data, peer = sock.recvfrom(2048)
                sock.sendto(data, peer)
    else:
        sock.listen()
        def loop():
            while True:
                client, _ = sock.accept()
                with client:
                    data = client.recv(2048)
                    if data:
                        client.sendall(data)
    threading.Thread(target=loop, daemon=True).start()


def request(port, ipv6=False, udp=True, expected=True):
    # Client is in a DIFFERENT namespace: traffic never traverses loopback.
    program = '''import socket,sys
s=socket.socket(int(sys.argv[1]),int(sys.argv[2])); s.settimeout(.5)
s.connect((sys.argv[3],int(sys.argv[4])))
s.sendall(b'x'*128)
assert s.recv(1024)==b'x'*128
'''
    p = subprocess.run(['ip', 'netns', 'exec', 'psmq_test_client', sys.executable, '-c', program,
                        str(socket.AF_INET6 if ipv6 else socket.AF_INET),
                        str(socket.SOCK_DGRAM if udp else socket.SOCK_STREAM),
                        'fd42:736d::1' if ipv6 else '192.0.2.1', str(port)], capture_output=True)
    assert (p.returncode == 0) == expected, p.stderr.decode(errors='replace')


def main():
    assert os.geteuid() == 0, 'root required'
    # Refuse execution in host network namespace, even if called without wrapper.
    assert os.readlink('/proc/self/ns/net') != os.readlink('/proc/1/ns/net'), 'use unshare --net'
    cmd('ip', 'netns', 'add', 'psmq_test_client')
    try:
        cmd('ip', 'link', 'add', 'qsrv', 'type', 'veth', 'peer', 'name', 'qcli')
        cmd('ip', 'link', 'set', 'qcli', 'netns', 'psmq_test_client')
        cmd('ip', 'addr', 'add', '192.0.2.1/24', 'dev', 'qsrv')
        cmd('ip', '-6', 'addr', 'add', 'fd42:736d::1/64', 'dev', 'qsrv', 'nodad')
        cmd('ip', 'link', 'set', 'qsrv', 'up')
        for args in [('addr', 'add', '192.0.2.2/24', 'dev', 'qcli'),
                     ('-6', 'addr', 'add', 'fd42:736d::2/64', 'dev', 'qcli', 'nodad'),
                     ('link', 'set', 'qcli', 'up'), ('link', 'set', 'lo', 'up')]:
            cmd('ip', '-n', 'psmq_test_client', *args)
        for port in (21001, 21002, 21003):
            for family in (socket.AF_INET, socket.AF_INET6):
                for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
                    echo(family, kind, port)
        alice = dict(name='alice', port=21001)
        bob = dict(name='bob', port=21002)
        end = int(time.time()) + 600
        q.apply_rules(alice, 1000000, end, 0, 'a')
        q.apply_rules(bob, 1000000, end, 0, 'b')
        for v6 in (False, True):
            for udp in (False, True):
                request(21001, v6, udp)
        before = q.quota_used('alice', 'a')
        assert before > 4 * 256, 'both legs plus headers must be counted'
        assert q.quota_used('bob', 'b') == 0
        request(21002)
        assert q.quota_used('bob', 'b') > 0
        time.sleep(.2)  # Allow final TCP ACKs before taking an idle baseline.
        before = q.quota_used('alice', 'a')
        for _ in range(5):
            request(21003)
        assert q.quota_used('alice', 'a') == before, 'unrelated traffic was charged'
        q.apply_rules(alice, 1, end, 0, 'full')
        request(21001, expected=False)
        request(21002)  # Other account remains available.
        q.apply_rules(alice, 10000, int(time.time()) - 1, 0, 'expired')
        request(21001, expected=False)
        q.apply_rules(alice, 10000, end, 0, 'newcycle')
        request(21001)
        assert q.quota_used('alice', 'newcycle') > 0
        print('PASS: real nft syntax, shared TCP/UDP IPv4/IPv6 quota, account isolation, unrelated traffic, exhaustion, deadline, restore')
    finally:
        cmd('ip', 'netns', 'delete', 'psmq_test_client')


if __name__ == '__main__':
    main()
