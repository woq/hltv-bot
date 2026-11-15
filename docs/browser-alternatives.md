# 长期会话浏览器备选调研（2026-11）

> 对照现行 **VPS headed Google Chrome + Xvfb + CDP attach**（`deploy/chrome-session/`）。  
> 落地架构见 [chrome-gateway.md](chrome-gateway.md)、[chrome-keeper-step1.md](chrome-keeper-step1.md)、[scorebot-transport.md](scorebot-transport.md)、[cloudflare.md](cloudflare.md)。  
> 本文只做备选审查，**不改默认栈**。

主线 `main` 已接回 headed Chrome keeper + `HLTV_HTTP=chrome`；`archive/chrome-full` 是旧页内 Scorebot 产品面。换引擎时成功标准不变：

1. **过 CF**：Turnstile / challenge-platform 能过，idle tab 自续 `__cf_bm`
2. **真进程 WS**：Scorebot `wss` 必须从已过 CF 的 page 发出（抄 cookie Upgrade 经常 403）
3. **过夜**：keeper 按比赛日挂着，不是每场 launch；`Restart=no`
4. **2G VPS**：Chrome `MemoryMax≈900M`、bot `400M`；或明确改成异地浏览器 + JSON 中继
5. **attach-only**：bot 不 Popen 浏览器、deploy 不 restart 浏览器

## 总表

| 备选 | 引擎 | 控制面 | 过夜 keeper | CF / Turnstile | 页内 Scorebot WS | 相对现行 Chrome | 裁决 |
|---|---|---|---|---|---|---|---|
| **现行 Google Chrome** | Blink | CDP `:9222` | 是（本机） | 已验证 headed + VNC | 已验证 | 基线 | **继续用** |
| Camoufox | Firefox 魔改 | Playwright / Juggler | 本机可，Docker 不稳 | 主机有时过；容器/Xvfb 常见失败 | 理论上页内可，要重写控制面 | 纸面省 RAM；改 CDP→BiDi | **观察；2G 扛不住再试** |
| Lightpanda | 自研 (Zig) | 部分 CDP | 可常驻但无意义 | 指纹差，缺 WebGL/Canvas | libcurl WS，更差 | 已实测否 | **否** |
| Obscura | Rust + V8 | CDP | 可 | 文档写明不做交互挑战 | 非真浏览器 TLS/指纹 | 轻量抓取器 | **否** |
| Playwright WebKit | WebKit | Playwright | 可 | 同 WPE：指纹/GPU 过不了 | 可，但进不了页 | 已放弃 WebKitGTK | **否** |
| 原版 Firefox | Gecko | BiDi / Marionette（CDP 已删） | 本机可 | CF 对 FF 更凶 | 要重写 keeper | 不如 Camoufox | **否** |
| Browserbase | 云 Chromium | CDP | **最长约 6h** | 托管 Chrome，通常可 | 远程页内 WS + 中继 | 方案 C 云版；计费 | **不适合过夜；应急异地可看** |
| Browserless | 云/自建 Chrome | CDP | 云 Scale **≤60min**；自建≈Chrome | 同 Chrome | 同 Chrome | 云会话太短；自建多一层 | **云否；自建无增益** |
| Steel | 云 Chromium | CDP | Launch 15m / Scale 1h / **Ent 24h** | Stealth 仅 Enterprise | 同 Browserbase | 过夜要 Ent | **默认否；Ent 再比价** |
| CloakBrowser | 魔改 Chromium | CDP `:9222` | 本机可 | 宣称过 Turnstile；长会话 CDP 流量有坑 | 可复用现有 CDP 形状 | 最接近 drop-in | **首选备胎（本机）** |

第三方横向（[stealth gist](https://gist.github.com/uinstinct/eb6608a6f42ea797526cc9acc2c38649)，非本仓实测）：CloakBrowser 唯一清过 live Cloudflare 站点；Camoufox 次之；Lightpanda / Obscura 不适合商业反爬。

---

## 本仓已经否掉的（不要回头）

| 项 | 出处 | 原因一句话 |
|---|---|---|
| Lightpanda | [scorebot-transport.md](scorebot-transport.md) §3 | HTTP/WS 走 libcurl；UA/`Sec-Ch-Ua` 自曝；无 TLS impersonate |
| WebKitGTK / WPE | 同上 | Turnstile 要 WebGL/canvas；无 GPU + WebKit 隐私 → 卡 `Just a moment` |
| 每次 headless / 无头+profile | [cloudflare.md](cloudflare.md) | 过不了或难过 JS challenge |
| 抄 cookie 做 Scorebot Upgrade | transport | poll 有时行，WS 403 常态 |
| RFC 8441 H2 WS | transport | curl_cffi 与 CF 边缘都不给这条路 |
| Firefox / Camoufox（2026-09） | [chrome-gateway.md](chrome-gateway.md) 方案 E | CF 更凶；BiDi ≠ 现有 CDP；纸面省 ~100M 不值改栈 |

---

## 1. Camoufox

**是什么**：去臃肿的 Firefox，C++ 层改指纹；Playwright 驱动；官方称 ~200MB vs Chrome 800MB+。

**和本仓的关系**

- 控制面是 Juggler / Playwright，**不是**现在的 `hltv_bot/cdp.py`（`/json/list`、`Network.getAllCookies`、`Runtime.addBinding`）。
- Docker / 小 Xvfb（含默认 `1x1`）上 Turnstile 失败报告多（如 error `600010`）；主机 headed 有时能过。本仓 keeper 正是 **Xvfb 无 GPU**，和痛点重合。
- TLS/JA3 在 NSS，Camoufox 明确不做伪造；代理信誉与容器字体/渲染差仍会被扫到。
- 维护曾有长空窗，树已推到 152.x beta；检测报告要按新版本复测。

**裁决**：内存诱人，但要重写 keeper + 在无 GPU Xvfb 上证明 Turnstile。只在「Chrome RSS 把 2G 打穿」时做 PoC；默认不换。

---

## 2. Lightpanda

**是什么**：轻量无头浏览器，CDP 子集，可本地或 Lightpanda Cloud；Cloud 还能 `browser=chrome` 租真 Chrome。

**裁决**：**否**（本仓已否）。自研引擎缺 WebGL / Canvas 像素 / Audio / 字体光栅；指纹扫描直接挂。页内 WS 也不是「真 Chrome 进程」。Cloud 若只租 `browser=chrome`，本质是付费远程 Chrome（见下「云」），不是 Lightpanda 引擎本身。

---

## 3. Obscura

**是什么**：Rust 无头引擎 + V8，`obscura serve --stealth` 提供 CDP；TLS 仿 Chrome（wreq）。

**官方边界**（Configure-stealth）：**不做** Cloudflare 交互挑战、DataDome/Akamai 主动挑战、CAPTCHA。`--stealth` 挡的是基础 TLS/UA/tracker；Kasada 类仍会炸。

**裁决**：**否**。HLTV 卡在 Turnstile + 真进程 WS，Obscura 两项都不覆盖。

---

## 4. Playwright WebKit

**是什么**：Playwright 自带的 WebKit 构建，方便跨引擎 E2E。

**和本仓**

- 已放弃的 WebKitGTK/WPE 同族：Turnstile 依赖可指纹的 WebGL；WebKit 隐私/嵌入式路径常表现为「renderer spoofed」或卡死挑战页。
- Cloudflare 文档写明：**自动化框架（含 Playwright）不支持解生产挑战**。
- 无现成 CDP HTTP `/json/*` 形状；keeper / scorebot chrome 路径要整段换 Playwright。

**裁决**：**否**。不重复 WPE 实验。

---

## 5. 原版 Firefox

**是什么**：发行版 Firefox，headed + profile。

**和本仓**

- Firefox **已移除实验性 CDP**；自动化走 WebDriver BiDi / Marionette → 现有 Python CDP 客户端作废。
- [chrome-gateway.md](chrome-gateway.md) 方案 E：同架构换 Gecko，CF 更凶，BiDi 生态不如 CDP，纸面省内存不值。
- 若只为「有个真浏览器续 cookie」，Camoufox 至少带反指纹；原版 FF 没有优势。

**裁决**：**否**。

---

## 6. Browserbase（云）

**是什么**：托管 Chromium，CDP / Playwright connect；`keepAlive` + 自定义 timeout。

**硬限制**

- 会话最长约 **6 小时**（再长要拆会话或重建 profile）。
- CDP 空闲约 **10 分钟**无双向流量会断；安静 keeper 要每 ≤5 分钟发轻量 CDP。
- 浏览器小时计费；过夜 ≈ 每天满跑计费，且 6h 墙挡不住「比赛日 10:00→次日 10:00」。

**架构含义**（= gateway 方案 C）

- 只拉远程 cookie 回 VPS 做 Upgrade → **仍常 403**（真进程不在本机）。
- 真 WS 必须在 **远端 page** 里连 scorebot，再中继 JSON 到 bot → Kill 多一跳延迟，运维多一套会话续命。

**裁决**：不适合本仓过夜 keeper。可作「本机 Chrome 挂了、短时应急」或「故意把浏览器挪出 2G 盒」时的候选，要另写中继，不是 drop-in。

---

## 7. Browserless（云 / 自建）

**是什么**：Chrome-as-a-service；云套餐会话上限随档位（Scale 常见 **60 分钟**）；也有自建镜像。

**裁决**

- **云**：**否**（会话远短于过夜；还要付费）。
- **自建**：底下仍是 Chrome + CDP，等于在 `hltv-chrome` 外包一层 API。本仓已有 systemd + Xvfb + noVNC，**无增益**。

---

## 8. Steel（云）

**是什么**：会话 API + CDP；可 `persistProfile`；可选代理 / 打码。

**硬限制**

| 档位 | 最长会话 |
|---|---|
| Launch | 15 分钟 |
| Scale | 1 小时 |
| Enterprise | 最长约 24 小时 |

Stealth Browser 标在 **Enterprise**。按量浏览器小时（公开档约 $0.08–0.10/h 量级）。

**裁决**：默认档不够过夜；Enterprise 24h 才摸到「比赛日」边缘，仍是远程方案 C + 费用。未谈 Ent 前 **否**。

---

## 9. CloakBrowser（本机备胎）

**是什么**：源码级打补丁的 Chromium；`pip`/`npm` 或 Docker `cloakserve` 暴露 **CDP 9222**；可当 Playwright 替换，也可纯 CDP。

**为什么值得单列**

- 控制面最接近现行：`connect_over_cdp` / 手写 CDP 都可能复用 `HLTV_CDP_URL`。
- 宣称非交互 / managed Turnstile 可过；第三方对比里唯一清过 live CF 站。
- 仍是 Blink，页内 `WebSocket` Origin 仍是 `https://www.hltv.org`。

**风险 / 约束（对长期 keeper）**

1. **Managed Turnstile** 仍要 **headed**；checkbox 忌裸 CDP `mouse`（官方建议 OS 级点击或键盘 Tab/Space）。本仓现状是 **人 VNC 一次**，与此兼容。
2. 长会话 + 持续 CDP 流量可能拉低 Turnstile 信任（社区：Celery 复用浏览器 vs 短脚本）。Keeper 应保持 **低频导出、少瞎 reload**——与现设计一致。
3. RAM 仍是 Chromium 量级，**不是**为了省 2G；动机是「更稳过 CF / 少人工」，不是瘦身。
4. 供应链：依赖第三方魔改二进制与许可证（Free/Pro）；升级节奏跟上游 Chrome 走。
5. 运维：`Restart=no`、不转 9222、profile 持久——规则与 `google-chrome-stable` 相同。

**裁决**：**本机唯一值得做 PoC 的备胎**。验收对齐现有：

- Xvfb headed；`curl 127.0.0.1:9222/json/list` 有 keeper tab
- 停人手 `/cookie` 后 `__cf_bm` 仍转；`cf_clearance` 在
- （若开 scorebot chrome）页内 WS 101，卡片底栏 `ws`
- `smem` RSS 与现 Chrome 可比，不爆 `MemoryMax`

未过验收前 **不**替换 `hltv-chrome.service` 的 `ExecStart`。

---

## 决策树（以后问「要不要换浏览器」）

```
需要过夜 keeper + 页内 Scorebot WS？
├─ 是，且必须本机同 IP / 同进程
│   ├─ 现行 Google Chrome 稳定 → 不动
│   ├─ CF 过不去或人工 VNC 过频 → PoC CloakBrowser（同 CDP）
│   └─ 只剩内存炸了 → 再评估 Camoufox（接受重写 BiDi）
├─ 是，但 2G 扛不住任何 Chromium
│   └─ 异地真 Chrome + JSON 中继（gateway C）
│       Browserbase（≤6h，要拆会话）/ Steel Ent（≤24h）/ 自建第二台
└─ 否，只要列表 HTML
    └─ 保持 HLTV_HTTP=curl；Chrome 可关
```

明确 **不要** 再开：Lightpanda 引擎、Obscura、Playwright WebKit、原版 Firefox、Browserless 云过夜、只抄云 cookie 回本机 Upgrade。

---

## 与现有文档的关系

| 文档 | 角色 |
|---|---|
| [chrome-gateway.md](chrome-gateway.md) | 2026-09 选定真 Chrome 的评估 |
| [chrome-keeper-step1.md](chrome-keeper-step1.md) | keeper 实现设计（当时排除 Firefox/Camoufox） |
| [scorebot-transport.md](scorebot-transport.md) | 现行传输；已否 Lightpanda / WPE |
| [cloudflare.md](cloudflare.md) | Cookie / TLS 操作说明 |
| **本文** | 长期会话备选清单与 2026-11 复审 |

修订记录：2026-11-15 初稿（Camoufox、Lightpanda、Obscura、PW WebKit、Firefox、Browserbase、Browserless、Steel、CloakBrowser）。
