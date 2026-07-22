# Sample-Request Agent Layer — 执行报告

**Branch:** `auto/overnight-tasks`（基于 `feat/sample-request-gmail-api` @ b087c3a）
**完成时间:** 2026-07-15
**执行模式:** SDD（niuma-yanxia-executor 实现 + yanxia-niuma-dev 审查，均 opus）
**最终状态:** ✅ 11/11 任务完成，全分支 review 通过，**Ready to merge**

## 任务清单解释（假设记录）

原始 prompt 的任务清单是占位符（`[任务一:...]`）。按"最保守解释"原则，
执行了本会话共同制定的 11 任务计划
`docs/superpowers/plans/2026-07-14-sample-request-agent-layer.md`
（给 sample-request 模块加 tool-using Claude agent 层）。详见 PLAN.md。

## 交付内容

- **`backend/sample_request/agent.py`**（新）— SYSTEM_PROMPT、AgentContext、
  12 个工具（5 read + 1 parse + 6 write）、`run_agent_tick` orchestrator
  （驱动 `client.beta.messages.tool_runner`，state 持久化，ok/partial/failed 语义）
- **`backend/sample_request/cli.py`** — 附加式改动：`TickResult.flagged` 字段 +
  `tick --agent` flag（与 `--dry-run` 互斥）；workflow 模式行为零变化
- **`backend/sample_request/tests/test_agent.py`**（新）— 28 个测试
  （单元 + orchestrator + CLI + 3 个 E2E 场景）
- **文档** — README "Execution Modes" 章节 + AGENT.md（架构图、工具清单、
  trade-off 表、cron 成本警告）

## 提交记录（14 commits，全部已推送 origin）

| Task | Commit | 内容 |
|---|---|---|
| — | 170683d | PLAN.md 执行计划 |
| 1 | 9a858b0 | scaffolding（SYSTEM_PROMPT / AgentContext / build_tools stub） |
| 2 | 2744332 | list_pending_emails, list_released_requests, get_state_summary |
| — | 31019a5 | 每任务推送规则写入 guardrails |
| 3 | b1e5a16 | read_warehouse_thread, check_sent_folder |
| 4 | 8b6db3c | parse_email_content + AgentContext.ant_client |
| — | 80bf5c7 | ledger 更新 |
| 5 | 7023363 | create_release_draft + LABEL_* 导入 |
| 6 | b48f56e | mark_release_sent, mark_shipped |
| 7 | 7e4fcbc | send_followup_reply, flag_needs_attention, record_failure（12 工具齐） |
| 8 | 17915ab | run_agent_tick + TickResult.flagged |
| 9 | 31939eb | --agent CLI flag |
| 10 | d23132d | E2E 三场景（ingest / ship-detection / followup） |
| 11 | e3c98c7 | README 章节 + AGENT.md |

## 测试

- **130 passed**（102 基线 + 28 新增），1 个预存 fastapi/httpx 警告（非本分支引入）
- 全套命令：`.venv/bin/pytest tests backend/sample_request/tests`
- 最终验证：12 工具注册确认；`tick --agent --dry-run` 正确报互斥错误

## 过程中的关键决策（假设/偏差记录）

1. **计数测试滚动替换** — 每个 task 删除上一个 `_after_task_N` 计数断言，
   新增当前的（计划的 append-only 计数与现实不符，按语义修正）。
2. **Task 6 `mark_shipped` 顺序修正** — 计划里 `find_request` 在前会让空 state
   的坏 tracking 报 KeyError 而非测试期望的 ValueError；改为委托
   `state.mark_shipped` 先做 regex 校验（review 确认正确）。
3. **Task 10 SDK 调用方式** — 计划不确定 `@beta_tool` 暴露方式；实测
   `BetaFunctionTool` 无 `.run()`，直接 `__call__` 可用，按此实现。
4. **Task 7 中断重派** — 用户 12:04 暂停（token 限额），16:04 定时唤醒后
   预检 HEAD 无分歧再继续，无重复工作。

## 挂账 Minor（全分支 review 裁决：均不阻塞合并）

1. **重复请求的幽灵草稿** — `create_release_draft` 在 `add_request` 抛重复错
   之前已建 Gmail 草稿；state 无损，路径难触发，代价一张可删草稿。
   后续可改为先查重再建草稿。
2. **`_iso_now` 与 `state.now_iso` 重复** — 计划指定的 2 行 helper，无碍。
3. **状态机不在 state 层强制** — `mark_shipped` 不校验前置状态是
   `released`（约束住在 prompt 里）。与 workflow 模式原语设计一致，by-design。
4. **`needs_attention_flagged` 恒为 0** — 无工具写入 `step=="flag_needs_attention"`
   的 tick_error；只读展示字段，非承重。

## 下一步（等你决定）

- 分支已推送 `origin/auto/overnight-tasks`，未合并、未开 PR（遵守"不碰 master"）。
- 可选项：开 PR / 本地合并 / 保持现状；agent 模式实跑需要真实
  credentials + `ANTHROPIC_API_KEY`（见 AGENT.md 成本警告，勿直接挂 2 分钟 cron）。
