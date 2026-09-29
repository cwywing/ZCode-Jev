# ZCode-Jev

[![Python](https://img.shields.io/badge/Python-3.7%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#安装三步)
[![MCP](https://img.shields.io/badge/MCP-stdio%20%2F%20JSON--RPC%202.0-green)](#安装三步)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 把 [TypeSafe AI 的 Jev 轻量决策模型](https://docs.typesafe.ai/api)接入 ZCode 的**决策外脑**工具包——
> 在任务生命周期的关键关口做"问一嘴"式的廉价判断，让主模型省下推理预算专注写代码。

**零依赖** · 纯标准库实现 MCP stdio 协议，无需 `pip install` · **离线可用** · 无密钥/断网/限流自动回退，工作流永不卡死

## 目录

- [这是什么](#这是什么)
- [五个关口](#五个关口)
- [特性](#特性)
- [目录结构](#目录结构)
- [安装（三步）](#安装三步)
- [验证](#验证)
- [配置项（环境变量）](#配置项环境变量)
- [一个任务的完整流程示例](#一个任务的完整流程示例)
- [接入新仓库](#接入新仓库)
- [边界与安全](#边界与安全)
- [故障排查](#故障排查)
- [卸载](#卸载)
- [背景：相对原 Codex 方案的修正](#背景相对原-codex-方案的修正)
- [许可证](#许可证)

## 这是什么

Jev 是 TypeSafe AI 的轻量决策模型，专做"要不要问、危险不危险、完成没完成"这类廉价判断。
本工具包把它接入 ZCode：一个 MCP server 提供 5 个决策工具（ZCode 里显示为 `mcp__jev__*`），
配合 3 个 skill 与一份全局规则，把判断变成纪律，覆盖任务生命周期的四个关口。

## 五个关口

| 关口 | 工具 | 判断内容 |
|---|---|---|
| 开工前 | `jev_route` | 复杂度分级 quick / medium / high / xhigh，防止小任务过度探索 |
| 规划期 | `jev_grill` | 候选澄清问题批量过滤，只把必须拍板的呈现给用户 |
| 危险操作前 | `jev_risk` | 是否有数据丢失 / 服务中断 / 不可逆风险 |
| 测试期 | `jev_review` | 检查点重要性 / 是否留证 / 最佳证据类型，最小高价值证据集 |
| 收工前 | `jev_complete` | 是否真正完成（含概率与四档完成质量） |

## 特性

- **零依赖 MCP server**：纯标准库实现 MCP stdio 协议（换行分隔 JSON-RPC 2.0），Python 3.7+ 直接跑，无需 pip install
- **离线回退**：无密钥 / 断网 / 限流 / 超时时返回 `{"jev": "offline", "fallback_advice": ...}`，永不因 Jev 不可用而卡死
- **密钥护栏**：输入命中疑似密钥 / Token / 私钥特征时直接拒绝调用，永不向 Jev 发送密钥
- **三家 provider 可选**：OpenRouter / TypeSafe 官方 / defapi.org 中转站，自动识别或显式锁定，429/529 自动退避重试
- **配套纪律**：`grill-me`（严格规划门 + 执行锁）、`jev-test`（测试取证治理）、`jev-complete`（最终完成门），外加并入 `AGENTS.md` 的全局调用规则
- **跨平台**：Windows / macOS / Linux 通用，Mac 自带 python3 即可

## 目录结构

```
ZCode-Jev/
├── jev_mcp.py                # MCP server（零依赖，5 个工具，跨平台）
├── AGENTS-jev.md             # 全量规则参考（并入 AGENTS.md 生效）
├── mcp-config.example.json   # MCP 注册配置片段（含字段说明与三 provider 说明）
├── install.ps1               # 安装辅助·Windows（默认只打印清单，-InstallSkills 才复制）
├── install.sh                # 安装辅助·macOS/Linux（--install-skills 才复制）
├── docs/
│   ├── 适用性评估.md          # 先评估再接入；没有结论不改目标仓库 AGENTS.md
│   ├── 接入指南.md            # 评估通过后：作用域怎么选、真实仓库怎么验
│   └── 场景引导.md            # 通用四条规则地图（固定，不按仓库改）
├── templates/
│   ├── jev-adoption.md       # 适用性结论模板（填完放目标仓库 docs/）
│   └── AGENTS-jev.overlay.md # 项目覆盖模板（实例化成目标仓库 AGENTS.md 的一节）
├── skills/
│   ├── grill-me/SKILL.md     # 严格规划门（PLANNING_LOCKED 执行锁）
│   ├── jev-test/SKILL.md     # 测试与取证治理
│   └── jev-complete/SKILL.md # 最终完成门
└── scripts/
    ├── smoke_test.py         # 冒烟测试（不起 ZCode，直接对 server 说 JSON-RPC）
    └── online_test.py        # 在线联调测试（含 TypeSafe 401 预检）
```

## 安装（三步）

### 第 1 步：注册 MCP server

把 `mcp-config.example.json` 里 `servers.jev` 一项合并进 `~/.zcode/cli/config.json` 的 `mcp.servers`
（保留已有内容；ZCode 的 server schema 是严格的，未知字段会让整个 server 被丢弃），并把
`env.OPENROUTER_API_KEY` 换成你的 OpenRouter 密钥。也可以在 ZCode 的 **Settings → MCP** 界面添加
stdio server。两个平台的差异只在 command 和路径：

- **Windows**：`command: python`，`args: <你的安装路径>\ZCode-Jev\jev_mcp.py`
- **macOS/Linux**：`command: python3`，`args: /Users/你的用户名/ZCode-Jev/jev_mcp.py`（Unix 风格路径）

没有密钥也可以先装——所有工具会走离线回退，返回自行判定的建议。

### 第 2 步：安装 skills

Windows（PowerShell）：

```powershell
cd <你的安装路径>\ZCode-Jev
.\install.ps1 -InstallSkills        # 复制三个 skill 到 ~\.agents\skills\（已存在则跳过）
```

macOS / Linux：

```bash
cd ~/ZCode-Jev
./install.sh --install-skills       # 复制三个 skill 到 ~/.agents/skills/（已存在则跳过）
```

装到 `~/.agents/skills/` 是用户级、跨项目生效，且与 Codex/Claude 等读 `.agents` 的工具共享；
只想在某项目用时改复制到 `<repo>/.agents/skills/`。注意 ZCode 同名 skill 先到先得，完整优先级是
`~/.zcode/skills/` > `~/.agents/skills/` > 项目 `.zcode/skills/` > 项目 `.agents/skills/`——
如果 `~/.zcode/skills/` 里已有同名 `grill-me` 等，装到 `.agents` 会被遮蔽而不生效，装后不触发时先查这层。

### 第 3 步：并入全局规则

把 `AGENTS-jev.md` 内容追加进 `~/.zcode/AGENTS.md`（全局）或某仓库的 `AGENTS.md`（单仓库）。

完成后**重启 ZCode**。

## 验证

Windows：

```powershell
cd <你的安装路径>\ZCode-Jev
python scripts\smoke_test.py       # 20 项应全部 PASS（协议/工具清单/离线回退/密钥护栏/参数校验/故障注入）
```

macOS / Linux：`python3 scripts/smoke_test.py`（脚本本身跨平台，无 Windows 专属代码）。

ZCode 侧：Settings → MCP 里 `jev` 显示已连接、5 个工具；会话里调用任一工具，
无密钥时返回 `{"jev": "offline", ...}`，配好密钥后返回 `{"jev": "ok", ...}`。

## 配置项（环境变量）

| 变量 | 必填 | 说明 |
|---|---|---|
| `OPENROUTER_API_KEY` | 三选一 | OpenRouter 密钥（[openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) 获取），走 `https://openrouter.ai/api/alpha/decisions`，模型默认 `~typesafe/jev-latest` |
| `TYPESAFE_API_KEY` | 三选一 | **Jev 官方（TypeSafe）密钥**（[console.typesafe.ai/keys](https://console.typesafe.ai/keys) 获取），走 `https://api.typesafe.ai/v1/systemone`，模型默认 `jev-latest` |
| `DEFAPI_API_KEY` | 三选一 | **defapi.org 中转站密钥**（`dk-` 开头，[defapi.org](https://defapi.org) 注册获取、需预充余额），走 `https://api.defapi.org/api/v1/decisions`，模型默认 `typesafe/jev-1.13`，报文与官方格式一致 |
| `JEV_PROVIDER` | 否 | 显式锁定 `openrouter` / `typesafe` / `defapi`；不设时自动按已配置的密钥选择（优先级：OpenRouter > TypeSafe > defapi）。三家 key 互不通用 |
| `JEV_MODEL` | 否 | 覆盖默认模型 |
| `JEV_ENDPOINT` | 否 | 强制覆盖端点 URL（调试用） |
| `JEV_TIMEOUT` | 否 | HTTP 超时秒数，默认 30 |

## 一个任务的完整流程示例

1. 用户提需求 → 触发 `grill-me`：调 `jev_route` 定级展示 → 只读调查仓库 → 候选问题批量过
   `jev_grill`，只把 `ask_user` 的呈现给用户（优先用提问工具，没有就用带推荐的编号文本；推荐项放第一）→ 产出编号完整计划
   → 🔒 等用户说"**开始执行**"
2. 执行中：TodoWrite 跟踪；遇到 `TRUNCATE` 之类危险操作先 `jev_risk`，`dangerous=true` 必须用户确认
3. 测试期：`jev-test` + `jev_review` 批量评审检查点，按最小证据集取证，失败按 BEFORE→FIX→AFTER 留证
4. 收工：`jev-complete` 逐项对账批准范围（git diff 核实实现）→ `jev_complete` → 四态收口
   （COMPLETE / COMPLETE_WITH_NOTES / PARTIAL / BLOCKED）

## 接入新仓库

**单仓库/多仓库接入请走 [docs/接入指南.md](docs/接入指南.md)**：先做[适用性评估](docs/适用性评估.md)（四档结论，逐门勾选），
再按作用域落地 MCP（用户级）/规则（仓库级 overlay）/skills（按复用范围）。不要把 `AGENTS-jev.md`
整份塞进 `~/.zcode/AGENTS.md`——全局注入每个仓库每次会话。

### 已接入仓库台账

> 每接入一个仓库在此登记一行。结论文件在目标仓库 `docs/jev-adoption.md`，路径往往很深，
> 浅层扫描/子智能体常够不着——台账保证在这里一层就能找到全部实例。

| 仓库 | 位置 | 结论 | 启用的门 | 评估日期 | 复评 |
|---|---|---|---|---|---|
| EvairSIM/laravel | WSL `~/wwwroot/EvairSIM/laravel` | 四门全开 | route + grill + review + risk + complete | 2026-09-28 | 2026-12-28 |

## 边界与安全

- **永不向 Jev 发送密钥**：server 端有正则护栏（sk-/ghp_/xox/AKIA/PRIVATE KEY/api_key= 等），命中直接拒绝；调用方也应只发摘要。
- Jev 是辅助信号：不覆盖用户授权、ZCode 权限机制、测试安全与生产保护；与用户指示冲突时以用户为准。
- 离线回退永远可用：所有工具无密钥/断网/限流时返回 `fallback_advice`，工作流不中断。

## 故障排查

- **401 认证失败**：TypeSafe 收到了 key 但不认——按频率排：复制截断/带了空格引号、拿别家（OpenRouter 等）的 key 来用、key 已被吊销。处理：到 [console.typesafe.ai/keys](https://console.typesafe.ai/keys) 新建 key 完整替换（`online_test.py` 对 TypeSafe 会先做 `/v1/models` 轻量预检并直接给出判定）。参考：[jevaiguide 401 指南](https://jevaiguide.com/errors/401-unauthorized/)。
- **403**：请求根本没带上 key 或头格式错（必须是 `Authorization: Bearer <key>`）。
- **离线原因里写"不会借用"**：`JEV_PROVIDER` 锁定了一家，但配的是另一家的 key——两家 key 不通用，把 key 放进对应槽位或去掉 `JEV_PROVIDER` 让它自动选。
- **429/529**：限流/过载，server 已内置一次退避重试；持续出现稍后再试。

## 卸载

1. 从 `~/.zcode/cli/config.json` 的 `mcp.servers` 删除 `jev`
2. 删除 `~/.agents/skills/` 下的 `grill-me`、`jev-test`、`jev-complete`
3. 从 `~/.zcode/AGENTS.md` 删掉并入的 Jev 规则段落
4. 删除本仓库目录

## 背景：相对原 Codex 方案的修正

本工具包源自一份 Codex 的 Jev 方案（WXWork 传输的 `Codex` 目录）的深度阅读与重构，原方案有四个硬伤，全部修复：

1. **`jev_grill` 只有引用没有实现** —— `grill-me` skill 强制要求所有候选问题过 `jev_grill`，但原 MCP server 只实现了 route/complete/risk 三个工具，规划过滤环节空转。本版补齐。
2. **server 代码不可运行** —— 原件 `from mcp.server import MCPServer` 及 `@mcp.tool()` 在官方 SDK 里不存在，属于示意伪代码。本版用纯标准库实现 MCP stdio 协议（换行分隔 JSON-RPC 2.0），**零依赖、无需 pip install**，Python 3.7+ 直接跑（本机 3.7.4 与 3.10 双版本冒烟通过）。
3. **测试检查点评审没有承接工具** —— 原 `jev-test` skill 说"用可用的 Jev 测试/证据决策能力评审检查点"，但没有对应工具。本版新增 `jev_review` 补上闭环。
4. **无离线策略** —— 原件在缺密钥时直接 `RuntimeError`，会打断工作流。本版无密钥/网络失败/限流/超时时返回 `{"jev": "offline", "fallback_advice": ...}`，调用方按建议自行决策并注明，永不因 Jev 不可用而卡死。

另有两处勘误说明：原方案 `"type": "noul"` **不是**笔误——noul 是 Jev 的三种决策原语之一（Choice / Score / Noul，Noul 即是否型判断）；本版报文格式已对齐 TypeSafe 官方文档（noul 返回 0–1 概率，choice 返回 `choice/probabilities/confidence`，score 返回 `score/legend/probabilities/confidence`），429/529 自动退避重试一次。新增密钥护栏：输入命中疑似密钥/Token/私钥特征时直接拒绝调用。

## 许可证

[MIT](LICENSE) © 2026 chanss
