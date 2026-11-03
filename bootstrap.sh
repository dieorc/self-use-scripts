#!/usr/bin/env bash
# Standalone public curl entry point; no local checkout or Git login required.
set -euo pipefail
umask 077
verify_only=0
archive=''
while (( $# )); do
    case "$1" in
        --verify-only) verify_only=1; shift ;;
        --archive) [[ $# -ge 2 ]] || exit 2; archive=$2; shift 2 ;;
        -h|--help)
            echo 'bash bootstrap.sh [--verify-only] [--archive LOCAL.zip] [-- CORE_PATH]'
            echo '默认从公开GitHub仓库下载完整项目并安装；PSMQ_REF可指定提交。'
            exit 0 ;;
        --) shift; break ;;
        *) echo "未知选项: $1" >&2; exit 2 ;;
    esac
done
[[ $EUID == 0 ]] || { echo '请以root运行' >&2; exit 1; }
[[ $(uname -s) == Linux && -d /run/systemd/system ]] || { echo '需要Linux + systemd' >&2; exit 1; }
. /etc/os-release
case "${ID:-}" in debian|ubuntu) ;; *) echo 'curl入口支持Debian/Ubuntu' >&2; exit 1 ;; esac
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 curl ca-certificates
workdir=$(mktemp -d)
trap 'rm -rf -- "$workdir"' EXIT
if [[ -z "$archive" ]]; then
    ref="${PSMQ_REF:-main}"
    [[ "$ref" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo 'PSMQ_REF格式错误' >&2; exit 1; }
    archive="$workdir/source.zip"
    if ! curl --fail --location --retry 3 --connect-timeout 15 --max-time 180 \
        --proto '=https' --proto-redir '=https' --tlsv1.2 \
        -o "$archive" "https://codeload.github.com/dieorc/self-use-scripts/zip/$ref"; then
        echo '项目下载失败：请确认仓库已经公开且GitHub可访问。' >&2
        exit 1
    fi
fi
python3 - "$archive" "$workdir/source" <<'PY_BOOTSTRAP'
import hashlib
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile


def extract_archive(archive, destination, max_bytes=20 * 1024**2):
    destination = Path(destination)
    required = {'oneclick.sh', 'install.sh', 'snell_quota.py', 'manage.sh', 'psm-snell',
                'systemd/psm-snell-quota.service', 'systemd/psmq-snell@.service'}
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        if not members or len(members) > 1000 or sum(x.file_size for x in members) > max_bytes:
            raise ValueError('archive size/member limit exceeded')
        roots = set()
        files = {}
        for info in members:
            parts = PurePosixPath(info.filename).parts
            if not parts or info.filename.startswith('/') or '\\' in info.filename or '..' in parts:
                raise ValueError('unsafe archive path')
            roots.add(parts[0])
            if info.is_dir():
                continue
            if len(parts) < 2 or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG):
                raise ValueError('unsupported archive member')
            relative = '/'.join(parts[1:])
            if relative in files:
                raise ValueError('duplicate archive path')
            files[relative] = z.read(info)
        if len(roots) != 1 or not required.issubset(files) or 'SHA256SUMS' not in files:
            raise ValueError('incomplete project archive')
        checked = set()
        for line in files['SHA256SUMS'].decode('utf-8').splitlines():
            expected, relative = line.split('  ', 1)
            if not re.fullmatch('[0-9a-f]{64}', expected) or relative not in files or relative in checked:
                raise ValueError('invalid checksum manifest')
            if hashlib.sha256(files[relative]).hexdigest() != expected:
                raise ValueError('checksum mismatch: ' + relative)
            checked.add(relative)
        if set(files) - {'SHA256SUMS'} != checked:
            raise ValueError('unlisted archive file')
        # Write only after the entire archive and all checksums have passed.
        if destination.exists():
            raise ValueError('destination must be new')
        destination.mkdir(mode=0o700)
        for relative, data in files.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.write_bytes(data)


if __name__ == '__main__':
    extract_archive(sys.argv[1], sys.argv[2])
PY_BOOTSTRAP
echo '完整项目与SHA256清单校验通过。'
if (( verify_only )); then
    echo '仅校验完成，未安装或启动服务。'
    exit 0
fi
bash "$workdir/source/oneclick.sh" "$@"
