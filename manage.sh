#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo '请以 root 运行'; exit 1; }
while true; do
    cat <<'MENU'

Snell V5 独立用户与月流量管理
 1. 添加用户            2. 查看流量与账期
 3. 导出 Surge 节点     4. 修改额度/提醒阈值
 5. 暂停用户            6. 恢复用户
 7. 删除用户            8. 配置 Telegram 通知
 9. 查看运行日志       10. 重启服务并结算流量
 0. 退出
MENU
    read -rp '选择: ' choice || exit 0
    case "$choice" in
        1)
            read -rp '用户名（小写字母/数字/下划线）: ' name
            read -rp '独立端口（1024–32767，例如21001）: ' port
            read -rp '月额度（例如100G）: ' quota
            read -rp '账期日（1–31，默认18）: ' day
            read -rp '时区（默认Asia/Shanghai）: ' timezone
            read -rp '提醒百分比（默认90）: ' warn
            psm-snell add "$name" --port "$port" --quota "$quota" --day "${day:-18}" \
                --tz "${timezone:-Asia/Shanghai}" --warn "${warn:-90}" || true
            ;;
        2) psm-snell status || true ;;
        3)
            read -rp '用户名: ' name
            read -rp '服务器IP或域名: ' server
            psm-snell export "$name" --server "$server" || true
            ;;
        4)
            read -rp '用户名: ' name
            read -rp '新月额度（例如100G）: ' quota
            read -rp '提醒百分比（默认90）: ' warn
            psm-snell update "$name" --quota "$quota" --warn "${warn:-90}" || true
            ;;
        5|6|7)
            read -rp '用户名: ' name
            case "$choice" in 5) action=disable ;; 6) action=enable ;; 7) action=delete ;; esac
            if [[ "$action" == delete ]]; then
                read -rp "删除 $name 的凭据和配置，保留计费账本？输入yes: " confirm
                [[ "$confirm" == yes ]] || continue
            fi
            psm-snell "$action" "$name" || true
            ;;
        8) psm-snell telegram || true ;;
        9) journalctl -u psm-snell-quota -n 40 --no-pager || true ;;
        10) psm-snell restart || true ;;
        0) exit 0 ;;
        *) echo '请输入菜单中的编号' ;;
    esac
done
