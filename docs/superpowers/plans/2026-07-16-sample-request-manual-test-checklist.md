# Sample-Request Manual Test Checklist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `backend/sample_request/TESTING.md` — a 6-case manual email-testing checklist for the live Gmail pipeline — and point the README's smoke-checklist section at it.

**Architecture:** Docs-only change. TESTING.md is a checkbox-driven runbook covering the full state machine (pending → draft_created → released → shipped), idempotency, follow-up escalation, bad-tracking rejection, dirty-input parsing, and agent mode. The README's existing "Manual smoke checklist" section (which Case 1 supersedes) is replaced by a link.

**Tech Stack:** Markdown only. No source, test, or dependency changes.

## Global Constraints

- **Working directory:** the git worktree at `.claude/worktrees/test-checklist` (branch `worktree-test-checklist`, based on `auto/overnight-tasks` @ 3813daa).
- **Git:** run git commands from **Windows Git Bash** inside the worktree directory (`\\wsl.localhost\Ubuntu-24.04\home\paul2\workspace\po-agents\.claude\worktrees\test-checklist`). WSL git cannot resolve this worktree's `.git` pointer — do not use it.
- **Python/CLI verification:** run via WSL with the **main checkout's venv** from the worktree dir:
  `wsl -d Ubuntu-24.04 -- bash -lc 'cd ~/workspace/po-agents/.claude/worktrees/test-checklist && ~/workspace/po-agents/.venv/bin/python3 -m backend.sample_request tick --help'`
- **Docs only:** do not modify any `.py` file or anything outside `backend/sample_request/TESTING.md` and `backend/sample_request/README.md`.
- **No personal email addresses in the docs.** Refer to the warehouse address as「`.env` 里的 `SAMPLE_REQUEST_WAREHOUSE_EMAIL`」and the sales inbox as「OAuth 授权的 Gmail 账号」.
- **Valid UPS test strings** (18 chars: `1Z` + 16 alphanumeric): `1ZA123456789012345`, `1ZB098765432109876`. Invalid example: `12345`. Never use 19-char strings.
- **Behavioral facts the checklist asserts (verified against `cli.py` — do not weaken or embellish):**
  - Parse failure: email keeps `pending-release`, `ingest_failure_counts` +1 per tick, on the 3rd failure `needs-attention` is added (`_record_pending_message_error`, cli.py:91-115).
  - Follow-up clock: measured from `last_contact_at` (release or last follow-up); one follow-up per elapsed threshold, escalation level = `len(follow_ups) + 1` (cli.py:305-333).
  - Already-ingested email is skipped, not re-drafted (cli.py:124-138).
  - Trailing-cost note: workflow tick ≈ $0.005 (one parse call, only when a pending email exists); agent tick ≈ $0.10–0.30.
- Document language: Chinese prose, bash command blocks in English (matches the audience; repo already mixes languages in REPORT.md).

---

### Task 1: TESTING.md checklist + README pointer

**Files:**
- Create: `backend/sample_request/TESTING.md`
- Modify: `backend/sample_request/README.md` (the "## Manual smoke checklist" section, lines 108-137)

**Interfaces:**
- Consumes: nothing from other tasks (single-task plan).
- Produces: `backend/sample_request/TESTING.md` (linked from README).

- [ ] **Step 1: Create `backend/sample_request/TESTING.md` with exactly this content**

````markdown
# 手动测试清单 — sample-request 邮件全链路

> 按推荐顺序执行：**Case 1 → 5 → 4 → 3 → 2 → 6**（Case 1 的产物会被 5/4/3 复用）。
> 花费参考：workflow tick 约 $0.005（仅当有待解析邮件时产生）；agent tick（Case 6）约 $0.10–0.30。

## 角色与前提

| 角色 | 邮箱 | 作用 |
|---|---|---|
| 客户 | 任意邮箱（用销售邮箱自发也行） | 发 sample request 邮件到销售邮箱 |
| 销售 | OAuth 授权的 Gmail 账号 | 系统监控的收件箱 |
| 仓库 | `.env` 里的 `SAMPLE_REQUEST_WAREHOUSE_EMAIL` | 收 release 草稿；回运单号 |

触发条件：邮件**主题必须含 `sample request`**（Gmail filter 靠它打 `sample-request/pending-release` 标签）。

## 命令速查（全部在 `~/workspace/po-agents` 下执行）

```bash
.venv/bin/python3 -m backend.sample_request tick --dry-run   # 干跑，不写 Gmail
.venv/bin/python3 -m backend.sample_request tick             # 真跑 workflow 模式
.venv/bin/python3 -m backend.sample_request tick --agent     # agent 模式（贵，Case 6 才用）
.venv/bin/python3 -m backend.sample_request status           # 状态表
tail -10 logs/sample_request_tick.log                        # tick 日志
# 最新一次 dry-run 的解析结果：
jq '.requests[] | {subject, parsed}' "$(ls -t .sample_requests_state.json.dryrun.* | head -1)"
```

没装 jq 用：`python3 -m json.tool "$(ls -t .sample_requests_state.json.dryrun.* | head -1)" | less`

## 测试前准备

- [ ] 暂停 cron：`crontab -e`，在 sample-request 那行行首加 `#`（避免定时 tick 和手动 tick 抢邮件）
- [ ] 确认 Gmail filter 存在：主题含 "sample request" → 自动打 `sample-request/pending-release`
- [ ] 记录基线：跑一次 `status`，记下当前已有的请求数和状态

---

## Case 1：主链路全流程（必测）

一封邮件走完 pending → draft_created → released → shipped 整个状态机。

- [ ] 1. 以客户身份给销售邮箱发邮件
      主题：`Sample request — test 1`
      正文：`Please send 3 cases of Item #190 orange bowls to Mike Chen, 1412 W 37th Pl, Los Angeles CA 90007`
- [ ] 2. Gmail 里确认标签 `sample-request/pending-release` 已打上（filter 生效）
- [ ] 3. 干跑 `tick --dry-run`，用命令速查里的 jq 命令核对解析结果：
      - `recipient` = `Mike Chen`？
      - `address` = `1412 W 37th Pl, Los Angeles CA 90007`？
      - `items` ≈ `[{name: "orange bowls"（近似）, qty: 3, qty_unit: "cases", item_number: "190"}]`？
      三项全对才继续；有错记入「问题记录」并停在这
- [ ] 4. 真跑 `tick`，确认三件事：
      - Gmail Drafts 出现给仓库邮箱的草稿（主题 `Release Request: ...`）
      - 原邮件标签变为 `sample-request/draft-ready`
      - `status` 显示该请求为 `draft_created`
- [ ] 5. 打开草稿，人工点 **Send**
- [ ] 6. 再跑 `tick`，确认：
      - `status` 变 `released`
      - 原邮件标签变 `sample-request/released`
- [ ] 7. 用仓库账号回复该 thread，正文含：`Shipped! Tracking: 1ZA123456789012345`
- [ ] 8. 再跑 `tick`，确认：
      - `status` 变 `shipped`，`ups_tracking_no` = `1ZA123456789012345`
      - 标签变 `sample-request/shipped`

## Case 5：幂等性（嵌在 Case 1 中途做）

同一封邮件不会被重复处理（已入 state 的邮件会被跳过，cli.py 的 ingest skip 逻辑）。

- [ ] 在 Case 1 第 4 步之后、第 5 步之前，立刻再跑一次 `tick`
- [ ] 确认：Drafts 里**没有**第二个草稿；`status` 请求数不变；日志出现 `ingest skip: already in state` 或无新 ingest

## Case 4：超时催单

released 超过阈值（默认 4h，从「最后一次联系」起算）无仓库回复 → 自动在仓库 thread 催单。

- [ ] 准备：需要一个 `released` 且仓库未回复的请求（再发一封主题 `Sample request — test 4` 的邮件，走到 Case 1 第 6 步为止）
- [ ] 不想等 4 小时，用临时阈值（0.02h ≈ 72 秒，发完 release 等 2 分钟再跑）：
      `SAMPLE_REQUEST_FOLLOWUP_HOURS=0.02 .venv/bin/python3 -m backend.sample_request tick`
- [ ] 确认：仓库 thread 自动多一条催单回复；`status` 里该请求 follow_ups 数 = 1
- [ ] **立刻**再跑一次同命令，确认这次**不发**第二封（时钟从上一封催单重新起算，间隔未到）
- [ ] 再等 2 分钟跑一次，确认发出第 2 封且措辞升级（escalation 第 2 级）

## Case 3：假运单号不触发发货

- [ ] 准备：复用 Case 4 那个 `released` 请求（别让它先 shipped）
- [ ] 用仓库账号回复正文：`Tracking: 12345`（不符合 UPS `1Z`+16 位格式）
- [ ] 跑 `tick`（注意别带 0.02 阈值，避免顺手触发催单干扰观察），确认：`status` 保持 `released`，没有误标 shipped
- [ ] 收尾：再回复一条正确运单 `Tracking: 1ZB098765432109876`，跑 `tick`，确认这次变 `shipped`

## Case 2：脏输入解析

- [ ] 发邮件，主题 `Sample request — test 2`，正文：`send me some samples please`（无收件人/地址/物品）
- [ ] 干跑 `tick --dry-run`，观察解析结果，记录走了哪个分支：
      - **分支 A**（解析成功但字段稀疏）：parsed 里 recipient/address 为空串或占位、items 为空 → 真跑后会照常建草稿，人工审草稿时兜底
      - **分支 B**（解析抛错）：日志出现 `parser failed`；邮件**保持** `pending-release`（下轮重试）
- [ ] 若是分支 B：连续再真跑 2 次 `tick`（共 3 次失败），确认第 3 次后邮件被打上 `sample-request/needs-attention` 标签（失败计数跨 tick 持久化）
- [ ] 把实际行为记入「问题记录」——本 case 的重点是「不崩 + 行为可解释」，两个分支都算通过

## Case 6：agent 模式对比

- [ ] 发一封同 Case 1 格式的新邮件，主题 `Sample request — test 6`
- [ ] Gmail 确认 `pending-release` 标签后跑：`tick --agent`（约 $0.10–0.30）
- [ ] 确认与 workflow 模式等价的效果：草稿建了、标签变 `draft-ready`、`status` 显示 `draft_created`
- [ ] 看日志观察 Claude 的工具调用顺序（对照 `AGENT.md` 的 12 工具清单）

## 测试后清理

- [ ] 恢复 cron（去掉 `#`）
- [ ] 删 dry-run 旁车文件：`rm -f .sample_requests_state.json.dryrun.*`
- [ ] Gmail 里归档/删除测试邮件和多余草稿（可选）
- [ ] 「问题记录」里的条目整理成 issue 或修复计划

## 问题记录

| Case | 现象 | 期望 | 备注 |
|---|---|---|---|
|      |      |      |      |
````

- [ ] **Step 2: Replace the README's "Manual smoke checklist" section**

In `backend/sample_request/README.md`, replace the entire section from the line `## Manual smoke checklist` down to (but not including) the line `## Operational notes` with:

```markdown
## Manual smoke checklist

See [TESTING.md](TESTING.md) for the full 6-case manual test checklist
(happy path, idempotency, follow-up escalation, bad tracking, dirty input,
agent mode), including recommended execution order and cleanup steps.

```

(Keep exactly one blank line before `## Operational notes`.)

- [ ] **Step 3: Verify referenced commands and paths are real**

```bash
wsl -d Ubuntu-24.04 -- bash -lc 'cd ~/workspace/po-agents/.claude/worktrees/test-checklist && ~/workspace/po-agents/.venv/bin/python3 -m backend.sample_request tick --help'
```
Expected: usage output showing `[--dry-run | --agent]`.

```bash
wsl -d Ubuntu-24.04 -- bash -lc 'cd ~/workspace/po-agents/.claude/worktrees/test-checklist && grep -c "TESTING.md" backend/sample_request/README.md && ls backend/sample_request/TESTING.md'
```
Expected: `1` (or more) and the TESTING.md path printed.

Also confirm no source files changed:
```bash
git -C . status --short
```
Expected: only `backend/sample_request/TESTING.md` (new) and `backend/sample_request/README.md` (modified).

- [ ] **Step 4: Commit**

```bash
git add backend/sample_request/TESTING.md backend/sample_request/README.md
git commit -m "docs(sample_request): 6-case manual email test checklist (TESTING.md) + README pointer"
```
