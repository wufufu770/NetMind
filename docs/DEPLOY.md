# 部署指南

> 面向自托管。NetMind 始终开源免费（MIT），本文件只讲怎么把它**稳定地跑起来**。

## 1. 先决定一件事：谁来访问它

NetMind 能改网络设备的配置。**部署之前先确认访问边界**。

| 部署形态 | 配置 | 说明 |
|---|---|---|
| 只在本机用 | 不设 `NETMIND_ADMIN_TOKEN` | 此时**只有本机**能访问，远程一律 403。默认就是这个 |
| 局域网共享 | **必须**设 `NETMIND_ADMIN_TOKEN` | 配了之后所有接口（含 GET）都要 `Authorization: Bearer <token>` |
| 多人看、少数人改 | 管理员 + `NETMIND_READONLY_TOKEN` | 只读凭据可读全部接口，写操作一律 403 |
| 对外暴露 | 同上，**且**必须走 HTTPS 反代 | 见第 5 节 |

```bash
# 生成一个够长的 token
python3 -c "import secrets;print(secrets.token_urlsafe(32))"
```

```yaml
# docker-compose.yml
environment:
  - NETMIND_ADMIN_TOKEN=${NETMIND_ADMIN_TOKEN:?必须设置}
```

**不设 token 就不设防护。** 这不是「不安全但方便」的取舍——本项目选择了默认安全：
未配 token 时远程访问直接 403 并在响应里告诉你怎么修。`/healthz` 是唯一免认证的业务无关路径（给探活用）；`/metrics` 需要认证（里面是运行数据）。

想开放匿名只读，显式设 `NETMIND_ALLOW_ANON_READONLY=true`，且它**不会**连带放行写操作。

### 让人能看、但不能改

```bash
NETMIND_ADMIN_TOKEN=...        # 你自己，管下发
NETMIND_READONLY_TOKEN=...     # 别人，能看全部接口，写操作一律 403
```

只读凭据走**方法**分权而非按端点：GET/HEAD/OPTIONS 放行，POST/PUT/PATCH/DELETE
返回 403（凭据有效、角色不够——所以是 403 不是 401，客户端据此知道该找谁申请，
而不是无谓地换凭据）。换管理员 token 不影响只读凭据。

两点注意：
- 两个变量填成同一个值时按**管理员**算。你要的是能写，给个写不了的配置更糟。
- 层级内没有更细的划分：管理员能操作**所有**设备，只读持有者能读**所有**接口。
  「A 只能看路由器 1 不能看路由器 2」这类需求不支持。
- **前端目前不会按角色调整界面**。只读用户打开面板仍会看到下发、审批一类按钮，
  点了返回 403。拦截在服务端，权限不会被绕过，但界面上看不出来自己是只读身份——
  这一点比缺功能更让人困惑，已登记为待办。

## 2. 起起来

```bash
git clone https://github.com/wufufu770/NetMind && cd NetMind
export NETMIND_ADMIN_TOKEN=$(python3 -c "import secrets;print(secrets.token_urlsafe(32))")
docker compose up -d
curl -H "Authorization: Bearer $NETMIND_ADMIN_TOKEN" http://localhost:8000/api/system/status
```

面板在 <http://localhost:5173>。

## 3. ⚠️ 必须单 worker

**不要用 `uvicorn --workers N`。**

STORE 是进程内单例，落盘时拿的是进程内的 `threading.RLock`——它**只护本进程**。多 worker 共享同一个数据文件时会互相覆盖，最后写入的赢，先前写入的丢失。

这是并发压测暴露出来的已知限制，记录在 [`load-test-baseline.md`](load-test-baseline.md)。当前默认配置是单 worker，安全。

要横向扩展，先把 STORE 换成带文件锁的实现（或换 SQLite/PostgreSQL）——`store.py` 的 `to_json` / `_apply` 已经把数据访问收敛在一处，是留给替换的接缝。

## 4. 数据在哪、怎么保

数据文件默认在 `data/netmind_store.json`（可用 `NETMIND_DATA_FILE` 改），是**单个 JSON 文件**。

```bash
python3 scripts/data_ops.py verify     # 校验是否完好
python3 scripts/data_ops.py backup     # 备份（带时间戳）
python3 scripts/data_ops.py list       # 看有哪些备份
python3 scripts/data_ops.py restore <备份文件>
python3 scripts/data_ops.py drill      # 演练：备份→破坏→恢复→校验
```

**升级或迁移之前先 `backup`。** 恢复源坏了会被直接拒绝——用坏数据盖好数据比不恢复更糟。

落盘是原子的（写临时文件 → fsync → rename → fsync 目录项），掉电或 `kill -9` 不会留下半截 JSON；崩溃残留的临时文件会在下次启动时清理。

上限：2000 条日志 / 500 条 execution / 2000 条遥测，超出滚动丢弃。长期运行且需要完整历史的，请自行定期把 `data/` 里的内容导出归档。

## 5. 对外暴露时

- **必须 HTTPS**。Bearer token 是明文传的，HTTP 下等于裸奔。
- 反代时设 `NETMIND_TRUST_PROXY=true` 才会采信 `X-Forwarded-For`（**不设就不采信**——那个头可伪造，拿它判 loopback 等于把认证门敞开）。
- CORS 默认只允许 `http://localhost:5173`。要放开设 `NETMIND_CORS_ORIGINS`；不要图省事写 `*`（配了 `allow_credentials=True` 时浏览器会拒绝，且语义上就是「允许任意站点带凭据调我」）。

## 6. 探活与监控

```bash
curl http://localhost:8000/healthz            # 免认证
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/metrics
```

`/metrics` 给 p50/p95/p99（按路由）、4xx/5xx 计数、uptime。零外部依赖——自托管工具不该为了「看自己」再拉一个 Prometheus client 进来。

## 6.5 速率限制

默认开启，按来源限流（进程内令牌桶，零外部依赖）：

| 组 | 持续 | 突发 | 覆盖 |
|---|---|---|---|
| write | 5/s | 10 | POST / PUT / PATCH / DELETE |
| read | 50/s | 100 | GET / HEAD / OPTIONS |
| public | 5/s | 10 | `/healthz` 等探活路径 |

超限返回 429 + `Retry-After`。限流在**鉴权之前**——未授权的洪水请求同样要挡，让它先打到业务逻辑等于给攻击者一个免费的压力放大器。

**批量导入时关掉**：

```bash
NETMIND_RATE_LIMIT=off
```

一次导入几十条策略是正常运维动作，被 429 挡下是纯粹的伤害。

**已知限制**：限流状态**只在进程内**。多 worker 部署下每个 worker 各有一份桶，
实际阈值会放大到 worker 数倍——和第 3 节的单 worker 约束是同一个根因。

## 7. 接真实设备

默认 `NETMIND_DRIVER=simulation`，所有命令干跑，不碰任何设备。

```bash
NETMIND_DRIVER=ssh
NETMIND_ENABLE_REAL_COMMANDS=true      # 不设这个，所有真实执行仍然干跑
NETMIND_SSH_HOST=192.0.2.10
NETMIND_SSH_PORT=22
NETMIND_SSH_USERNAME=netmind
NETMIND_SSH_PASSWORD=...            # 生产请用密钥而非密码
NETMIND_SSH_DEVICE_TYPE=cisco_ios   # 见 GET /api/vendors
```

**先把干跑跑顺，再开真实执行。** 干跑会完整走一遍「生成 → 校验 → 提案 → 审批」链路，只是不下发。

支持哪些厂商、验证到什么程度，见 `GET /api/vendors`——每家带 `verified` / `declared` / `blocked` 等级。**只有 `verified` 的那家是在真实设备上跑通过的**，其余是映射与依赖齐备但未在真机验过。矩阵生成源是 `backend/app/diagnose/vendor_matrix.py`。

危险操作按**命令语义**拦截（`del-flows` / `iptables -F` / `link down` / `route del` / `addr del`），与设备名无关；回滚只放行带 NetMind 签发 cookie 的流表，或本系统 `ip route add` 下去、规格完全一致的路由（`ip route del` 没有 cookie 可挂，归属靠登记——命令文本可伪造，登记不可）。

## 8. 开启自动处置（默认关闭）

**默认不开启。** 处置命令长成 `tc qdisc del dev {iface} root`，接口猜错就等于对
错误的口下手——在多接口的真机上，那可能正是管理口。项目对设备采集一直坚持
「不知道就如实拒绝，不猜驱动」，处置更不该猜。

```bash
NETMIND_HEAL_IFACE=eth0                        # 必填；不填则自愈不动作
NETMIND_HEAL_BACKUP_ROUTE="10.9.0.0/24 via 192.0.2.9"   # 仅 link_down 需要
NETMIND_HEAL_MAX_ATTEMPTS=3                    # 连续失败上限，默认 3
```

未配置时自愈会返回 `target_configured: false` 并说明缺哪一项，`success=false`；
HealingAgent 这一步记为 `waiting`（等前置条件），**不会**记成成功。

次数按 `(诊断类型, 接口)` 独立记账并**落盘**——只在内存里的话重启一次就把上限
绕过去了。同一故障连续处置到上限就停止自动动作、转人工，确认根因后调大
`NETMIND_HEAL_MAX_ATTEMPTS` 或清理计数即可恢复。成功一次即清零；干跑不消耗
预算（设备根本没被动过，那不算「试过一次没成」）。

另外注意：`congestion` 的处置（清队列整形）**没有可用的自动回滚**——删了设备
原有整形但处置前没记参数，造不出等价的逆命令。没改善时会如实报「无法自动回滚」，
需人工确认。

## 9. 出了故障先看哪儿

| 症状 | 先查 |
|---|---|
| 起不来，日志报权限 | `NETMIND_ENABLE_REAL_COMMANDS` 与 `NETMIND_SSH_*` 是否配齐 |
| 远程访问 403 | 没配 `NETMIND_ADMIN_TOKEN`（这是默认行为，不是故障） |
| 远程访问 401 | token 配了但请求没带 `Authorization: Bearer <token>` |
| 面板能开但接口全 401 | 面板的 API 地址/token 没配 |
| 数据看着不对 | `python3 scripts/data_ops.py verify`，坏了就 `restore` |
| 接口偶发变慢 | 单 worker 下写操作持锁；见 `load-test-baseline.md` |
| 设备命令没生效 | 确认 `NETMIND_ENABLE_REAL_COMMANDS=true`；否则永远干跑 |
| 自愈不动作 | 确认 `NETMIND_HEAL_IFACE` 已配（默认关闭，见第 8 节）；未配时返回 `target_configured: false` |
| 自愈报「已连续处置 N 次」 | 达到上限，自动动作已停。确认根因后调大 `NETMIND_HEAL_MAX_ATTEMPTS` 或清理 `heal_attempts` |
| 回滚被拦 | `ovs-ofctl del-flows` 需带 NetMind 格式 cookie；`ip route del` 需该路由是本系统 `ip route add` 下去的 |
| 处置没改善但撤不回来 | `congestion` 结构性不可回滚（未记录原整形参数），需人工确认 |

更细的：`.netmind-loop/state.json` 有当前状态与门禁清单；`docs/commercial-readiness-audit.md` 有完整的成熟度盘点与已知风险。
