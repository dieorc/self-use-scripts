# self-use-scripts

自用脚本：PSM Snell V5 独立用户额度扩展

已提供实际 Python CLI、中文菜单、一键安装入口、systemd 服务、测试及可选 PSM 入口补丁。已在 GitHub Actions 的 Ubuntu 24.04 上通过 Python 3.9/3.12/3.14 逻辑测试、真实 nftables 计量隔离测试，以及官方 Snell V5 安装和 systemd 生命周期检查。真实 Surge 客户端（尤其 QUIC）、VPS 实际网络及 Telegram 投递仍按本文做端到端验收。

## 一键安装与中文菜单（v0.2.2）

仓库设为 **Public（公开）** 后，在 Debian/Ubuntu VPS 上以 root 执行这一条命令，无需 Git 或 GitHub 登录：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/dieorc/self-use-scripts/main/bootstrap.sh)
```

`bootstrap.sh` 是独立入口：下载完整项目 ZIP，检查路径、文件类型和 SHA256 清单，再调用安装器。归档校验用于发现损坏和遗漏，不是发布者签名。它不会下载或使用 GitHub token。安装后输入 `psm-snell` 打开中文菜单。首次使用需自行添加用户，并放行对应的 TCP/UDP 端口。

如需仅下载并校验，可给入口传入 `--verify-only`；仍可能准备 Python/curl 等依赖，但不安装或启动代理服务。`PSMQ_REF` 可指定分支或提交，以固定所安装的源码版本。

完整仓库已下载到 VPS 时，也可直接以 root 运行：

```bash
bash oneclick.sh
psm-snell
```

`oneclick.sh` 支持 Debian/Ubuntu amd64/arm64：自动安装依赖、复用现有官方 V5 或从 Surge 官方固定取得 V5.0.1、执行逻辑测试及 nft 功能预检，再安装服务。它不会自动创建用户或打开防火墙。已有自己的官方 V5 文件时可用 `bash oneclick.sh /path/to/snell-server`。若已有可信二进制哈希，可设置 `SNELL_SHA256` 对自动下载后的二进制校验；这个值不是 Telegram/GitHub 令牌。

不带参数的 `psm-snell` 打开中文管理菜单；带子命令时仍为原 Python CLI，systemd 启动方式兼容。菜单覆盖添加、查看额度、导出、修改额度、暂停/恢复/删除、Telegram、日志和重启。修改配置仍会正常结算并短暂断开受管连接。

仓库的可见性由所有者在 GitHub 设置中管理。**如果仍为 Private（私有），上面的匿名 curl 命令会返回 404**；公开源码后即可使用。代码仓库只保存脚本和文档，真实 PSK、Telegram token/chat_id、流量账本只在 VPS 本地保存。保留私有时，可用已有 GitHub SSH 认证的 root 账户克隆：

```bash
git clone git@github.com:dieorc/self-use-scripts.git /root/self-use-scripts && bash /root/self-use-scripts/oneclick.sh
```

或先用 GitHub CLI 登录并克隆，再运行本地入口。不要将 GitHub token 嵌入 URL、命令行或此仓库。公开部署时可重新运行同一 curl 命令更新；Git 部署可用 `git pull --ff-only` 后重新执行 `oneclick.sh`，已有用户和账本保留。

仓库附 GitHub Actions：Python 3.9/3.12/3.14 逻辑测试，以及 Ubuntu 24.04 上真实 nftables 网络隔离测试。还包含官方 V5 下载、双实例监听和暂停/恢复/升级的临时机安装测试。已通过的运行记录见 TEST-REPORT.md；这些检查仍未替代真实 Surge 客户端与 Telegram 投递验收。

## 1. 上游检查与实现依据

实际检查的仓库：https://github.com/jinqians/proxy-stack

固定检查提交：`d9a6c61121956996959b09176f02df627af1fe4b`，提交时间 2026-10-07；检查日期 2026-11-03。安装入口 `https://psm.jinqians.com` 为上游远程安装入口，本扩展采用本地审阅后安装，不修改该远程入口。

| 实际源码位置 | 发现 | 本扩展的处理 |
|---|---|---|
| `lib/users.sh:12–30, 313–321` | 通用账户合并未纳入 Snell；现有逐用户额度依赖 Xray，按自然月重置 | 采用每人独立官方 Snell 进程、端口、PSK |
| `lib/snell.sh:6–10, 140–156` | 官方二进制、INI 配置与 systemd/OpenRC 管理；默认文件只有一个 PSK | 保留官方 V5 二进制及 INI 方式，另建独立实例模板 |
| `lib/traffic.sh:272–306, 432–469, 989–995` | 已有节点月度重置和 TCP/UDP 端口计量；重置日输入限制为 1–28，使用系统时区 | 独立账本、IANA 时区、1–31 日，短月取最后一天 |
| `manager.sh:14` | 已有命令分发入口 | 可选增加 `psm snell-quota ...`，原有命令不变 |

官方依据：

- [Surge Snell 服务端说明](https://kb.nssurge.com/surge-knowledge-base/release-notes/snell)：V5 存在 UDP-over-UDP QUIC 模式；其他 UDP 仍可走 TCP；官方公开文档没有列出可依赖的逐用户服务端统计 API。这里不把它推断为原生多用户计费能力。
- [Surge Snell 客户端参数](https://manual.nssurge.com/policies/snell.html)：明确 PSK 与版本配置。导出固定 `version=5`。
- [nftables named quota](https://wiki.nftables.org/wiki-nftables/index.php/Quotas)：同一个命名 quota 可以被多个规则共享。
- [nftables 官方手册](https://netfilter.org/projects/nftables/manpage.html)：`inet` 覆盖 IPv4/IPv6，`ct direction` 区分连接方向，`meta time` 的整数是 UNIX 时间戳。

官方 V5 为闭源服务端。本次没有对其未公开接口做可用性假设，也没有把其他实现标称的 Snell 兼容性当作官方功能。即使今后的第三方内核支持多用户，也无需更换当前实现的计量依据。

## 2. 计量口径与隔离

每个用户占用一个专用 TCP/UDP 端口、一份随机 32 字符 PSK、一份配置和一个服务实例。同一端口禁止交给其他服务使用。

内核每个用户建一个 `inet psmq_NAME` 表，一个命名 quota 同时用于四条放行规则：

- INPUT：非 loopback 接口，TCP 或 UDP 目标端口为用户端口，conntrack 原始方向。
- OUTPUT：非 loopback 接口，Snell 专用系统账户的 socket，源端口为用户端口，conntrack 回复方向。
- 上述方向命中但额度用尽、账期结束或缺少连接跟踪的包会被 DROP。

因此只计客户端 ↔ Snell 这一段，不把代理进程 ↔ 目标网站再加一遍。SSH、其他端口、系统更新和其他用户使用不同表。服务端临时端口范围内的端口禁止用于用户监听，以避免与出站临时端口冲突。IPv4/IPv6、TCP/UDP 合并扣同一用户额度。

这是指定客户端端口的网络层字节口径，包含协议开销、重传、连接建立及到该端口的无效探测；不是只统计成功认证后的应用净载荷。公开官方二进制缺少已核实的认证后逐用户统计接口，故本实现明确选择该口径。某端口受到扫描会消耗该用户额度；若需要只向认证用户结算净载荷，应更换提供可核实内部统计的服务端实现，并重新做客户端兼容性测试。此处的字节数也不保证与 VPS 供应商账单逐字节一致。

支持边界：Linux systemd、Python 3.9+、nftables 及 conntrack、glibc 官方 Snell V5、主机直接监听、启用 IPv6 双栈。建议 Debian 12/13 或 Ubuntu 22.04/24.04。当前包未实现 Alpine/OpenRC、容器转发、Nginx/ShadowTLS 前置、其他网络命名空间或流量 offload 接入；这些拓扑不能直接套用本计量规则。不要给用户端口添加 NOTRACK。初次使用保持主机默认临时端口范围，监听端口选择 1024–32767 内未使用的端口。IPv6 被禁用的机器需先启用双栈；本包按上游 `::0:PORT` 生成配置。

## 3. 账期与重启

`--day 18 --tz Asia/Shanghai` 表示每月北京时间 18 日 00:00 开新账期。31 日遇到 2 月使用 28/29 日，下一月恢复到 31 日。夏令时重叠选择第一次午夜；午夜不存在时顺延到第一个有效分钟。跨过多个停机月份时直接进入当前账期；已消耗额度不累积到新账期。时钟退回此前账期时停用控制器并通知，避免重复发放额度，需修正系统时间后重启。

旧账期的内核规则有绝对截止时间：即使控制器暂时阻塞，过期额度也不继续放行。新账期由控制器下一轮重建 quota 并恢复用户服务，存在短暂断流。正常轮询每 1 秒一次，系统服务操作及 Telegram 请求可能增加恢复延迟。

为处理断电，采用额度预留而非简单定时保存计数：先把本段额度写入账本并 fsync，再安装允许放行这段字节的内核 quota。默认每段 256 MiB，耗尽后短暂等待控制器发放下一段，月额度是最后上限。最后一段取剩余额度，因此不会额外赠送整段额度。内核在超额包到达时拦截，不等待 Telegram 或轮询。

- 正常停止/重启：先停止实例，再读取内核计数，结算实际消耗。
- 控制器异常退出但内核 quota 仍在：通过每段随机 generation 精确匹配并恢复内核读数。
- 断电或 quota 丢失：将未结算预留段保守视为已使用；每用户每次此类事件最多多计一个预留段。可用 `--lease 16M` 降低差额，但小段在高速连接中更频繁触发短暂停顿。重启次数多时差额会累积。
- 账本缺失/损坏：停止实例，拒绝初始化成零使用量。需要从一致备份恢复。`users.json` 也必须保留。
- 运行中检测到 quota 丢失/统计失败：停止所有受管实例并报告异常。外部 root 执行 `flush ruleset` 到检测之间可能有短暂窗口；避免让其他防火墙管理器删除本扩展表。

这套恢复方案防止额度因计数器清零而回退。对于要求突然断电也零差额的商业净流量计费，需要更强的服务端计量及持久化基础设施。

## 4. 安装

先把整个目录上传到 VPS，例如 `/root/psm-snell-quota`。以下以 Debian/Ubuntu 为例，以 root 执行：

```bash
apt-get update
apt-get install -y python3 nftables iproute2 tzdata unzip curl
cd /root/psm-snell-quota
python3 -m unittest discover -s tests -v
```

已有 PSM 官方 V5 时：

```bash
/usr/local/bin/snell-server --v
bash install.sh /usr/local/bin/snell-server
```

如果现有二进制是 V4/V6，单独取得固定 V5.0.1，不替换原二进制。AMD64 示例：

```bash
mkdir -p /root/snell-v5-download
cd /root/snell-v5-download
curl --fail --location --proto '=https' --tlsv1.2 \
  -o snell-v5.0.1.zip https://dl.nssurge.com/snell/snell-server-v5.0.1-linux-amd64.zip
unzip snell-v5.0.1.zip
chmod 755 snell-server
./snell-server --v
sha256sum snell-server
cd /root/psm-snell-quota
bash install.sh /root/snell-v5-download/snell-server
```

ARM64 将 URL 中 `amd64` 改为 `aarch64`。下载文件自行保留来源和哈希；本安装器只核验版本字符串并记录实际复制的 SHA-256，没有声称得到发布者签名验证。只使用你信任的官方二进制。

安装器在写入前使用 `nft -c` 检查所需规则能力；检查失败时先升级/修复 nftables 和内核。它不会清空既有防火墙，不自动打开云安全组。复制的 core 位于专用目录，因此 PSM 后续更新原 core 不会自动切换本扩展版本。空配置安装后暂不运行任何 Snell 用户实例。

## 5. 日常命令

```bash
psm-snell add alice --port 21001 --quota 100G --day 18 --tz Asia/Shanghai --warn 90
psm-snell add bob --port 21002 --quota 50G --day 31 --tz Europe/Berlin --warn 80 --lease 16M
psm-snell status
psm-snell export alice --server YOUR_SERVER_IP
psm-snell update alice --quota 150G --warn 85
psm-snell disable bob
psm-snell enable bob
psm-snell delete bob
```

1G = 1024³ 字节。`status` 不输出 PSK；`export` 是明确的凭据导出命令，请在可信终端执行。禁用用户在下一账期仍保持手动禁用；只因超额停用的用户会自动恢复。

创建后账期日/时区固定，避免更改账期意外赠送额度。本版本的 `update` 仅修改额度、提醒阈值和预留段大小，保留已用流量。若确需改账期，安排在旧账期结算后停用并迁移到新账户，旧账本保留。删除再以相同名字添加会保留同账期使用量，不用于清零。

配置变更命令会先通知控制器收尾，等待已发起的服务操作完成、停止实例并结算，再更改配置并恢复；现有连接会中断。维护时可用 `psm-snell quiesce` 安全停止，或用 `psm-snell restart` 完成结算后重启。正常管理操作会清理启动次数计数；无人值守的故障重启仍保留 systemd 速率保护。日常查询与导出不会中断连接。CLI 管理操作使用独立互斥锁串行执行。添加前检查 TCP/UDP 端口监听冲突，之后不要把同端口分配给其他应用。

在云安全组与主机防火墙放行各自的 TCP 和 UDP 端口。例如已有 UFW 的主机可以：

```bash
ufw allow 21001/tcp
ufw allow 21001/udp
```

只在已使用 UFW 的情况下使用上述命令；本包不切换防火墙管理器。原有 `psm user`、`psm traffic`、订阅与迁移功能不会自动收录新账户，也不要对这些端口再启用另一套额度停用规则。

## 6. Telegram 通知与权限

```bash
psm-snell telegram
```

按提示隐藏输入 bot token 和数字 chat_id，不作为命令行参数传递。你需先向自己的 bot 发起会话，或把 bot 加入目标群并给予发送消息权限。配置后会排队发送测试消息。仅提供通知，不接收 Telegram 远程控制命令。

超额、账期重置、达到阈值及实例/控制器异常进入持久化 outbox。Telegram 失败不会阻止额度拦截，采用指数退避重试；每轮最多发一条，单次请求超时 3 秒。最多保留 500 条排队事件，极长离线超过容量时丢弃最旧消息；也可从本机 journal 查运行记录。崩溃发生在发送成功与保存之间时可能重复通知，属于至少一次投递。

| 文件/目录 | 权限与用途 |
|---|---|
| `/etc/psm-snell-quota/telegram.json` | root:root 0600，token/chat_id |
| `/etc/psm-snell-quota/users.json` | root:root 0600，用户参数和 PSK |
| `/etc/psm-snell-quota/instances/*.conf` | root:snellquota 0640，实例读取 PSK |
| `/etc/psm-snell-quota`、`instances` | root:snellquota 0750 |
| `/var/lib/psm-snell-quota` | root 0700，账本、锁、core 哈希 |
| `ledger.json` | root 0600，原子替换 + 文件/目录 fsync |

Snell 实例以无登录权限的 `snellquota` 账户运行，控制器以 root 操作内核规则和 systemd。生成的 PSK 长度为 32 个随机十六进制字符。Telegram 请求通过 HTTPS，应用日志不打印包含 token 的异常 URL；通知也不包含 PSK。不要开启会记录完整 HTTPS URL 的外部调试代理。

## 7. 可选 PSM 命令入口

`psm-entry.patch` 只给上游 `manager.sh` 增加命令分支，不改变菜单、用户模型及流量模块。对上面固定提交生成：

```bash
cd /path/to/proxy-stack
git apply --check /root/psm-snell-quota/psm-entry.patch
git apply /root/psm-snell-quota/psm-entry.patch
psm snell-quota status
psm snell-quota add charlie --port 21003 --quota 20G --day 18 --tz Asia/Shanghai
```

安装目录不受 git 管理时可先复制备份再使用 `patch --dry-run -p1 < ...`，检查后才应用。上游更新可能覆盖该分支，独立的 `psm-snell` 始终可用。无需给入口补丁权限即可使用独立 CLI。

## 8. 测试与 Linux 验收

逻辑测试：

```bash
python3 -m unittest discover -s tests -v
for script in install.sh oneclick.sh manage.sh psm-snell tests/systemd_smoke.sh; do bash -n "$script"; done
```

真实内核测试必须在 Linux root 下运行（建议先用测试 VPS）：

```bash
apt-get install -y util-linux iproute2 nftables python3
sudo unshare --net python3 tests/linux_netfilter.py
```

测试会拒绝在宿主网络命名空间运行，在新网络命名空间内创建 veth 与另一个客户端命名空间，实际检查规则加载、TCP/UDP、IPv4/IPv6、共享额度、两账户隔离、无关端口、额度拦截、截止时间及重新放行。它使用回显服务验证计量路径，不宣称验证了 Snell 协议。退出时删除客户端命名空间；其余规则随隔离命名空间销毁，不操作生产 ruleset。

安装后检查服务和权限：

```bash
systemctl status psm-snell-quota
systemctl status psmq-snell@alice
journalctl -u psm-snell-quota --since today
stat -c '%a %U:%G %n' /etc/psm-snell-quota/*.json /var/lib/psm-snell-quota/ledger.json
ss -lntup | grep ':21001'
nft -j list table inet psmq_alice
```

官方 Snell/Surge 端到端验收需实际完成：

1. 建 alice/bob 两个测试账户，额度设 2M/10M，预留段设 512K。先确保两人能使用不同 PSK/端口访问网站，错误 PSK无法建立代理连接。
2. 仅用 alice 下载测试文件，观察 alice 增长、bob 不变；从 VPS 另开 SSH、运行系统下载，观察两者均不增长。
3. 同时验证 IPv4 和 IPv6 客户端。用 Surge 实际发起 HTTP/3，确认官方 V5 QUIC UDP socket 与本包预期一致，UDP 入站和回复实际被扣到相同 quota；另验证普通 UDP-over-TCP。只测试 TCP 无法完成这一步。
4. 耗尽 alice，确认 TCP/UDP 均失效、bob 正常、超额消息到达；查看 alice 服务已停止。因为计入协议开销，2M 净文件可能在完整下载前触及 2M 网络层额度。
5. 在测试 VPS 设置即将发生的账期（按创建时所选日/时区），等待实际边界，确认旧 quota 到时阻断、新账期恢复且只触发一次重置。切勿为了测试修改生产机器时间。
6. 正常 `systemctl restart psm-snell-quota`，确认已用量不清零；在测试机强制重启验证预留差额，确认不会得到免费额度。
7. 暂时断开 Telegram 网络，在本地超额后观察仍停用且 outbox 留存，恢复网络后收到通知。停止一个实例，验证异常通知及恢复动作。
8. 测试删除某个 `psmq_` 表时的故障处理只能在测试机操作，确认控制器停服务并排队异常消息；不要执行全局 `flush ruleset`。

实际执行的检查与未执行项见 `TEST-REPORT.md`。

## 9. 备份、升级、回滚

备份前正常停止控制器，整套保存两个目录与专用 core 哈希；备份含凭据，保持 root-only 权限：

```bash
psm-snell quiesce
tar -czf /root/psm-snell-quota-backup.tgz /etc/psm-snell-quota /var/lib/psm-snell-quota
chmod 600 /root/psm-snell-quota-backup.tgz
systemctl start psm-snell-quota
```

升级扩展时重新执行安装脚本，保留已有配置及账本。不要只恢复旧账本而保留已提供的服务时段，那会回退已用量。

回滚停止并禁用本扩展，保留账本以便恢复：

```bash
psm-snell quiesce
systemctl disable psm-snell-quota
```

受管实例随控制器停止。确认所有实例都已停，再逐个删除本扩展的表，例如 `nft delete table inet psmq_alice`；不要删除其他表。原 PSM 节点使用自己的端口可继续工作。应用过入口补丁的，可在同一源码版本用 `git apply -R psm-entry.patch` 撤销。不要直接运行 PSM 的全量 Snell 卸载来清理本扩展；该上游操作可能移除你仍在使用的原节点。
