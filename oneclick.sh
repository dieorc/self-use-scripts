#!/usr/bin/env bash
# Run from a complete authenticated Git checkout of this private repository.
set -euo pipefail
umask 077
[[ $EUID == 0 ]] || { echo '请以 root 运行：sudo bash oneclick.sh' >&2; exit 1; }
[[ $(uname -s) == Linux && -d /run/systemd/system ]] || { echo '需要 Linux + systemd' >&2; exit 1; }
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
for file in install.sh snell_quota.py manage.sh psm-snell; do
    [[ -f "$base/$file" ]] || { echo '请下载/克隆完整仓库后运行，勿只下载此文件' >&2; exit 1; }
done
case "${1:-}" in
    -h|--help)
        echo 'sudo bash oneclick.sh [已取得的官方Snell V5二进制路径]'
        echo '无参数时复用已安装V5，或从官方固定下载V5.0.1；支持Debian/Ubuntu amd64/arm64。'
        exit 0 ;;
esac
[[ -r /etc/os-release ]] || { echo '缺少系统发行版信息' >&2; exit 1; }
. /etc/os-release
case "${ID:-}" in debian|ubuntu) ;; *) echo '一键依赖安装支持Debian/Ubuntu；其他systemd系统请自行装依赖后运行install.sh' >&2; exit 1 ;; esac
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 nftables iproute2 tzdata curl unzip passwd ca-certificates util-linux
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
core="${1:-}"
if [[ -z "$core" ]]; then
    for candidate in /usr/local/lib/psm-snell-quota/snell-server /usr/local/bin/snell-server; do
        if [[ -x "$candidate" ]] && "$candidate" --v 2>&1 | grep -qE 'v5\.[0-9]+\.[0-9]+'; then
            core="$candidate"
            break
        fi
    done
fi
if [[ -z "$core" ]]; then
    case "$(uname -m)" in x86_64) arch=amd64 ;; aarch64|arm64) arch=aarch64 ;; *) echo '自动下载仅支持amd64/arm64' >&2; exit 1 ;; esac
    url="https://dl.nssurge.com/snell/snell-server-v5.0.1-linux-${arch}.zip"
    echo '从Surge官方取得固定Snell V5.0.1。下载哈希会保存在本机；不声称有发布者签名。'
    curl --fail --location --retry 3 --connect-timeout 15 --max-time 180 \
        --proto '=https' --proto-redir '=https' --tlsv1.2 -o "$tmp/snell.zip" "$url"
    # Extract exactly the executable, never archive-provided paths or scripts.
    unzip -p "$tmp/snell.zip" snell-server > "$tmp/snell-server"
    [[ -s "$tmp/snell-server" ]] || { echo '官方压缩包未包含预期二进制' >&2; exit 1; }
    if [[ -n "${SNELL_SHA256:-}" ]]; then
        [[ "$SNELL_SHA256" =~ ^[0-9a-fA-F]{64}$ ]] || { echo 'SNELL_SHA256格式错误' >&2; exit 1; }
        printf '%s  %s\n' "$SNELL_SHA256" "$tmp/snell-server" | sha256sum --check --status
    fi
    chmod 755 "$tmp/snell-server"
    core="$tmp/snell-server"
fi
cd -- "$base"
python3 -m unittest discover -s tests -q
bash install.sh "$core"
echo '安装完成。输入 psm-snell 打开管理菜单。首次使用需添加用户并放行对应TCP/UDP端口。'
