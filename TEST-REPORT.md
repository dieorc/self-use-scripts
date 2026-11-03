# 本次实际测试记录

日期：2026-11-03（Asia/Shanghai）。本包为待 Linux 实机验收版。

| 检查 | 本次结果 | 证明范围 |
|---|---|---|
| 实际克隆并阅读 proxy-stack 源码 | 已完成，固定提交 `d9a6c61121956996959b09176f02df627af1fe4b` | 上游用户、Snell、端口计量、账期和入口实现依据 |
| Python unittest | 30 项通过 | 账期/闰年/短月/DST、额度预留、独立用户、正常结算、内核恢复、丢失计数后的保守恢复、超额停用、禁用保留用量、Telegram重试与脱敏 |
| Python 编译 | 通过 | 控制器、逻辑测试、Linux 计量测试语法 |
| Bash `bash -n` | `install.sh`、`oneclick.sh`、`manage.sh`、`psm-snell` 均通过，Git Bash | 脚本语法，未在此电脑执行 Linux 安装 |
| `git apply --check` | 固定上游提交通过 | 可选 PSM 入口补丁可干净应用 |
| Linux 命名空间/真实 nft 测试 | 本次未执行，已提供 `tests/linux_netfilter.py` | 在 Linux 执行后才证明真实内核规则、TCP/UDP、IPv4/IPv6 与其他流量隔离 |
| systemd 实例/官方 Snell V5/Surge QUIC 端到端 | 本次未执行，README 提供逐项验收步骤 | VPS 上实际运行后才能证明这部分兼容性 |
| Telegram 真实投递 | 本次未执行，无用户 bot 凭据 | 已验证模拟成功/失败/重试与敏感信息脱敏，真实权限与网络需部署后测试 |
| GitHub Actions | 已提供工作流，本次尚未运行 | 需要先成功推送仓库；不把编写工作流记为测试通过 |

逻辑测试环境：Windows、Python 3.14.5；仅为测试在项目 `work/test-deps` 安装 tzdata 2026.6，通过 PYTHONPATH 使用。部署 Linux 使用系统 tzdata，无需这个本地测试目录。

本次没有安装或启用服务器服务，没有修改用户原有 PSM 文件。v0.2.0 已准备一键安装入口、中文菜单及私有仓库发布材料，推送状态以聊天中实际 GitHub 返回结果为准。包内不包含官方闭源 Snell 二进制，也不包含任何实际用户 PSK、Telegram token 或 chat_id。

验收顺序：先运行 Linux 隔离计量测试，再部署小额度测试用户，最后完成 README 中的官方 Snell/Surge、超额、跨账期、重启和通知验收。通过后再给正式账户分配额度。
