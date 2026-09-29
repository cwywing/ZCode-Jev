# Jev 决策外脑（项目覆盖）

> 复制本模板，实例化成目标仓库 `AGENTS.md` 里的一节。只保留实际启用的门对应的段落，
> 通用规则见工具包 `docs/场景引导.md`（四条固定规则 + 离线行为 + 工具全名）。

Jev 是轻量决策模型（MCP 工具 `jev_route` / `jev_grill` / `jev_review` / `jev_risk` / `jev_complete`，
会话内全名 `mcp__jev__*`），只做判断不写代码，是**辅助信号**：永远不替代用户授权、权限机制与本仓库规范。
适用性结论见 `docs/jev-adoption.md`。

## 本仓库的极简任务（直接做，不调 Jev）

- （例：改文案/翻译文案）
- （例：改单个常量或配置值，不涉及错误码/枚举映射）
- （例：改注释、改 README）

## 开工分级（如启用）

非琐碎任务先 `jev_route`，结果作为 <本仓库任务分级，如 P0/P1/P2> 的**输入信号**，最终定级仍以仓库规范为准。
quick 级按仓库"允许简化规范"的等级处理，直接执行。

## 规划门（如启用）

澄清问题多、影响面大的任务用 `grill-me`：

- 候选问题批量过 `jev_grill`，只把 `ask_user` 的呈现给用户（优先提问工具，无则带推荐的编号文本）
- 计划落到 <本仓库计划文档位置，如 docs/plans/YYYY-MM-DD-*.md>，遵循现有命名与结构
- 执行锁：明确"开始执行 / 执行第 N 项"或规划模式批准后才实施

## 测试取证（如启用）

`jev-test` + `jev_review` 只做检查点与证据取舍；**证据规范以本仓库现有规范为准**（如 tests/ 分组策略、
测试数据 seeding 指南、只跑相关测试的规则），不另建一套。

## 危险操作（本仓库具体清单，操作前 `jev_risk`，dangerous=true 必须用户确认）

- （例：生产执行 `php artisan migrate` / `migrate:rollback`）
- （例：TRUNCATE / 大量 DELETE / 清理数据表）
- （例：修改 .env / 生产配置 / 部署工作流）
- （例：git force push / 历史改写）
- （例：删除或覆盖大量文件）
- 离线时从严自行判定并注明。

## 完成门（如启用）

宣布完成前过 `jev-complete`，与仓库变更控制要求对账：影响范围 / 风险等级 / 回滚方案 /
迁移状态声明（如有）。四态收口：COMPLETE / COMPLETE_WITH_NOTES / PARTIAL / BLOCKED。
完成门覆盖范围：<如 app/ 与 database/migrations/>；**不覆盖**：<如 docs/、脚本>。

## 离线行为

Jev 返回 `jev: "offline"` 时按 `fallback_advice` 自行判定，结果中注明"Jev 离线，自行判定"，不重试。
永不向 Jev 发送密钥、Token、生产敏感数据。
