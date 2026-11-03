# 本次实际测试记录

日期：2026-11-03（Asia/Shanghai）。Linux 计量与官方 V5 安装已完成自动验收，真实客户端和 Telegram 网络验收待部署后执行。

| 检查 | 本次结果 | 证明范围 |
|---|---|---|
| 实际克隆并阅读 proxy-stack 源码 | 已完成，固定提交 `d9a6c61121956996959b09176f02df627af1fe4b` | 上游用户、Snell、端口计量、账期和入口实现依据 |
| Python unittest | 32 项通过，Windows 及 Ubuntu Python 3.9/3.12/3.14 | 账期/闰年/短月/DST、额度预留、独立用户、正常结算、内核恢复、保守恢复、超额停用、禁用保留用量、服务收尾、Telegram重试与脱敏 |
| Python 编译 | 通过 | 控制器、逻辑测试、Linux 计量测试语法 |
| Bash `bash -n` | `install.sh`、`oneclick.sh`、`manage.sh`、`psm-snell` 均通过，Git Bash | 脚本语法，未在此电脑执行 Linux 安装 |
| `git apply --check` | 固定上游提交通过 | 可选 PSM 入口补丁可干净应用 |
| Linux 命名空间/真实 nft 测试 | Ubuntu 24.04 实际通过 `tests/linux_netfilter.py` | 真实 TCP/UDP、IPv4/IPv6、独立账户、无关端口隔离、额度拦截、到期截止和恢复 |
| 官方 Snell V5/systemd 安装检查 | Ubuntu 24.04 实际通过 `tests/systemd_smoke.sh` | 官方 V5.0.1 下载、一键安装、两个实例监听、独立PSK、权限、暂停/恢复、修改额度、重启、重复安装升级、删除用户 |
| 官方 Snell V5/Surge QUIC 端到端 | 待 VPS 与真实 Surge 客户端验收 | 自动测试未模拟 Surge 的真实代理会话，不把服务端监听测试当作 QUIC 验证 |
| Telegram 真实投递 | 本次未执行，无用户 bot 凭据 | 已验证模拟成功/失败/重试与敏感信息脱敏，真实权限与网络需部署后测试 |
| GitHub Actions | 已推送私有仓库并实际运行成功 | 逻辑矩阵、内核计量隔离、官方 V5 安装三个 job 类别均成功 |

v0.2.2 新增独立 `bootstrap.sh`：本地 40 项测试通过（原 32 项 + 8 项归档完整性/路径/类型/大小检查）。CI 安装任务使用完整 Git 归档调用同一个 bootstrap 入口，再验证官方 V5 与服务管理。匿名 GitHub 下载端需要仓库公开后额外核验；新增入口的 CI 结果可在仓库最新 Actions 中查看。

逻辑测试环境：Windows、Python 3.14.5；仅为测试在项目 `work/test-deps` 安装 tzdata 2026.6，通过 PYTHONPATH 使用。部署 Linux 使用系统 tzdata，无需这个本地测试目录。

通过记录：[GitHub Actions #6](https://github.com/dieorc/self-use-scripts/actions/runs/41598050851)，代码提交 `54092894af1e9f8504a3f5349311c83b34b74e48`。该记录验证完整安装与服务生命周期；后续菜单重启入口复核可在仓库 Actions 查看。

本次没有修改用户原有 PSM 文件或私人 VPS。安装测试只在 GitHub 临时 runner 上进行，结束时停止测试服务。源码已上传 `dieorc/self-use-scripts` 私有仓库。包内不包含官方闭源 Snell 二进制，也不包含任何实际用户 PSK、Telegram token 或 chat_id。

验收顺序：先运行 Linux 隔离计量测试，再部署小额度测试用户，最后完成 README 中的官方 Snell/Surge、超额、跨账期、重启和通知验收。通过后再给正式账户分配额度。
