# 仓库维护

仓库：`dieorc/self-use-scripts`，保持私有。主要入口为 `oneclick.sh`，安装后输入 `psm-snell` 打开中文管理菜单。

首次发布保留 GitHub 初始化提交，在其后追加源码提交，不强制改写远端历史。账号授权通过 GitHub 连接器完成，不在聊天或源代码中提供 token。

维护前先运行：

```bash
python3 -m unittest discover -s tests -v
for script in install.sh oneclick.sh manage.sh psm-snell; do bash -n "$script"; done
```

`.gitignore` 已排除运行时凭据、账本、实例配置、压缩包和 Python 缓存。提交时只包含源代码、文档、服务定义和测试，不上传 `/etc/psm-snell-quota` 或 `/var/lib/psm-snell-quota`。

使用 GitHub CLI 维护时可查询：

```bash
gh repo view dieorc/self-use-scripts --json nameWithOwner,isPrivate,url
gh run list --repo dieorc/self-use-scripts --limit 5
```

GitHub Actions 在临时 runner 里测试代码和 Linux 计量路径；推送不会在私人 VPS 上安装或启动服务。真实 Surge 客户端、官方 Snell QUIC 路径、跨账期和突然断电仍按 README 单独验收。
