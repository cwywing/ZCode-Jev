# Jev 自动决策规则（ZCode 版）

> 用法：把本文件内容并入 `~/.zcode/AGENTS.md`（全局生效）或某个仓库的 `AGENTS.md`（仅该仓库生效）。
> 依赖：MCP server `jev`（见 mcp-config.example.json），提供 5 个工具
> `jev_route / jev_grill / jev_review / jev_risk / jev_complete`。

Jev 是轻量级任务决策模型，只做判断不写代码。它是**辅助信号**，永远不替代用户授权、ZCode 权限机制与测试安全。

> 工具全名对照（会话/子智能体白名单里用全名，短名可能不命中）：
> `mcp__jev__jev_route` / `mcp__jev__jev_grill` / `mcp__jev__jev_review` / `mcp__jev__jev_risk` / `mcp__jev__jev_complete`。下文用短名简称。

## 开始任务

明显极简的任务直接执行，不调用 Jev，例如：改文字、改变量名、非常小的单文件修改、简单明确的查询。

除此以外的软件开发任务，在进行大范围代码读取、深入分析、修改或创建子 Agent **之前**，先调用 `jev_route`：

- 只发精简任务摘要（≤10 行：做什么、涉及模块、风险点），不发送整个代码库
- 按返回等级校准工作强度：
  - `quick`：保持非常精简，避免过度探索
  - `medium`：正常开发流程
  - `high`：认真分析、验证关键边界条件
  - `xhigh`：复杂架构/疑难问题，最高强度推理
- 不要为简单任务做不必要的大范围代码库探索

## 规划期

需要多轮澄清的非琐碎规划任务，使用 `grill-me` skill：

- 候选澄清问题**批量**过 `jev_grill` 过滤，只把 `ask_user` 的问题呈现给用户——优先用提问工具（AskUserQuestion 等），当前环境没有提问工具时退化为带推荐的编号文本；推荐选项放第一位
- 计划获批前保持 PLANNING_LOCKED，不解锁不实施

## 测试期

实质性测试/验证/回归阶段，使用 `jev-test` skill：

- 候选测试检查点**批量**过 `jev_review`，按重要性/留证决策/证据类型取舍取证
- 目标是最小高价值证据集，不是最大化截图

## 危险操作前

准备执行以下操作前调用 `jev_risk`：

- DROP / TRUNCATE / 大量 DELETE
- 大量文件删除
- force push
- 生产环境变更
- 可能造成数据丢失的操作

`dangerous=true` 时必须先获得用户**显式确认**才可执行；`dangerous=false` 也仍要遵守 ZCode 权限机制。

## 完成检查

以下任务在宣布完成之前，走 `jev-complete` skill 并调用 `jev_complete`：

- 多文件重要修改
- 安全相关代码
- 数据库逻辑
- 复杂 Bug
- 部署和基础设施
- 用户要求全面检查并修复

## 边界（始终生效）

1. **永不向 Jev 发送**：API key、密码、Token、Cookie、私钥、数据库凭证、任何密钥与敏感生产数据——改发摘要。（server 端也有护栏，命中疑似密钥会直接拒绝。）
2. Jev 结论与用户指示冲突时，以用户为准。
3. Jev 返回 `jev: "offline"` 时按 `fallback_advice` 自行判断，并在给用户的结果中注明"Jev 离线，自行判定"，不要反复重试。
4. 批量优先：同类决策合并成一次调用（问题过滤、检查点评审均 ≤20 个/批），禁止逐条调用浪费往返。
