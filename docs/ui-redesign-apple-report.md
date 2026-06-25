# PO Intake Agent — UI/UX 重新设计报告（Apple 设计视角）

> 日期：2026-06-25 · 范围：`frontend/index.html` · `frontend/styles.css` · `frontend/app.js`
> 目标：把一个"能用的原型"提升为一款符合 Apple HIG（Human Interface Guidelines）质感的操作员工具。

---

## 0. 一句话结论

你现在的界面**信息架构是对的**（三栏 master-detail 很适合这类录单工具），但**视觉与交互还停留在浏览器默认控件阶段**。Apple 的做法不是"加装饰"，而是**减噪声、立层级、给反馈**。本报告给出可直接落地的设计令牌（tokens）、逐区域改造方案和分阶段路线图。

---

## 1. 现状评估（改造前）

从代码还原出的真实界面：

```
┌─────────────────────────────────────────────────────────────┐
│ PO Intake Agent                          [Agent Workflow ▸]  │
├──────────────┬──────────────────┬───────────────────────────┤
│ Original PO  │ Order Draft      │ Items                     │
│              │                  │                           │
│ [选择文件]   │ Customer [____]  │ ITEM-1002                 │
│ ┌──────────┐ │ PO Number[____]  │ Order 40 | Unit $5 | ...  │
│ │  PDF     │ │ Ship To  [____]  │ Commit auto 40 → [40] →   │
│ │ iframe   │ │ Ship From[____]  │ Cut reason [缺货 ▾]       │
│ │          │ │ Ship Date[____]  │ On the way [——●——] [#]    │
│ └──────────┘ │ Carrier  [____]  │ [📝 note]                 │
│              │ Order Total: $—  │                           │
│              │ Status: —        │                           │
│              │ [Revise][Save][Release to Warehouse]          │
└──────────────┴──────────────────┴───────────────────────────┘
```

| 维度 | 现状 | 问题 |
|---|---|---|
| 字体 | `system-ui, sans-serif`，13–18px | 没有清晰的字阶层级，标题只有 18px，正文和标签同字号 |
| 颜色 | 黑字 + `#ddd/#e2e2e2` 灰边 + 个别 `#b00020` 红 | 没有语义色系统，状态全靠文字 |
| 间距 | 4–12px 手填，无栅格 | 节奏不统一，控件挤在一起 |
| 控件 | 浏览器默认 input/select/range/file | 跨平台外观不一致、不精致、点击区域小 |
| 状态反馈 | `Status: needs_review`（纯文字） | 最关键的"能不能放行"信息没有视觉权重 |
| 反馈/动效 | 仅 drawer 滑入；上传后 `alert()` | 上传→处理→出结果的过程没有进度感；`alert` 很出戏 |
| 错误展示 | item 后缀 `⚠ Not found` | 异常没有聚合，操作员要自己扫 |
| 空状态 | 无 | 首次进入三栏都是空的，没有引导 |

**核心判断**：这是个典型的"工程师做的功能原型"。它把后端的数据字段**直接平铺**到界面上（`Commit auto 40 → manual → ships → cut`），这是数据库视角，不是操作员视角。Apple 的第一刀就是**从"展示字段"转向"完成任务"**。

---

## 2. Apple 设计四原则如何映射到本项目

Apple HIG 的核心：**Clarity（清晰）· Deference（克制）· Depth（层次）**，再加上 **Feedback（反馈）**。

1. **Clarity｜清晰** — 一眼看懂"这单能不能放行"。状态、金额、异常数应该是全屏视觉焦点。
2. **Deference｜内容优先** — PDF 原件和订单数据是主角；边框、按钮、标签都应"退后"。去掉所有 1px 灰框，改用留白和极浅的分隔。
3. **Depth｜层次** — 用**材质/阴影/圆角**表达层级：卡片浮于背景，drawer/弹层用毛玻璃。处理流程用动效表达因果。
4. **Feedback｜反馈** — 上传后实时显示 5 个 agent 的逐步进度（你已经有 `steps` 数据！），不要用 `alert`。

---

## 3. 设计令牌（Design Tokens）

直接可用的一套，贴合 Apple 系统风格。建议放进 `:root` CSS 变量。

### 3.1 字体（Typography）
采用 Apple 系统字体栈，San Francisco 在 Apple 设备上自动命中。

```css
--font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Text",
             "SF Pro Display", system-ui, sans-serif;
--font-mono: ui-monospace, "SF Mono", "JetBrains Mono", monospace; /* PO号/金额 */
```

字阶（8pt 节奏，对应 HIG Text Styles）：

| 角色 | 字号/行高 | 字重 | 用途 |
|---|---|---|---|
| Large Title | 28 / 34 | 700 | 页面主标题 |
| Title 3 | 20 / 25 | 600 | 栏目标题（Original PO 等）|
| Headline | 17 / 22 | 600 | 客户名、PO号 |
| Body | 15 / 20 | 400 | 正文/输入值 |
| Footnote | 13 / 18 | 400 | 字段标签、辅助说明 |
| Caption | 11 / 13 | 500 | 角标、单位 |

> 关键：**标签用 Footnote 灰色，值用 Body/Headline 黑色**——制造"标签弱、值强"的层级，这是 Apple 表单的标志性手法。

### 3.2 颜色（Color，语义化 + 自动深色模式）

```css
:root {
  --label:           #1d1d1f;   /* 主文字 */
  --label-secondary: #6e6e73;   /* 次级文字/标签 */
  --separator:       rgba(60,60,67,0.12);
  --bg:              #f5f5f7;    /* 页面背景，浅灰让卡片浮起 */
  --bg-elevated:     #ffffff;    /* 卡片 */
  --fill-quaternary: rgba(120,120,128,0.08); /* 输入框底 */
  --accent:          #0071e3;    /* Apple 蓝，主操作 */
  --green:           #34c759;    /* ready / released */
  --orange:          #ff9f0a;    /* needs_review / warning */
  --red:             #ff3b30;    /* error / unknown item */
}
@media (prefers-color-scheme: dark) {
  :root {
    --label:#f5f5f7; --label-secondary:#aeaeb2;
    --bg:#000; --bg-elevated:#1c1c1e;
    --separator:rgba(84,84,88,0.36);
    --fill-quaternary:rgba(118,118,128,0.24);
  }
}
```

状态色系直接绑定到业务：`ready_to_submit→green`、`needs_review→orange`、`UNKNOWN_ITEM/DUP_PO→red`。

### 3.3 间距 / 圆角 / 材质

```css
--space: 8px;              /* 一切间距是 8 的倍数：8/16/24/32 */
--radius-card: 16px;       /* 卡片 */
--radius-control: 10px;    /* 按钮/输入 */
--radius-pill: 980px;      /* 胶囊状态徽章 */
--shadow-card: 0 1px 3px rgba(0,0,0,.06), 0 8px 24px rgba(0,0,0,.04);
--material: saturate(180%) blur(20px);  /* 毛玻璃 backdrop-filter */
```

---

## 4. 逐区域改造方案

### 4.1 顶栏（Header）→ 半透明工具栏 + 大标题
- 顶栏改成 **sticky + 毛玻璃**（`backdrop-filter: var(--material)`），下方一条 `--separator` 细线，**去掉硬边框**。
- 标题用 Large Title。右侧 `Agent Workflow ▸` 改成**带角标的圆形/胶囊按钮**，角标显示 `5/5 ✓`（你已有 `updateWorkflowBadge`），用 SF Symbols 风格的对勾。

### 4.2 第一栏 Original PO → 拖拽上传 + 沉浸式预览
- 文件未上传时，**不是一个裸 `<input type=file>`**，而是一个 **Drop Zone 空状态**：虚线圆角卡片 + 文档图标 + "拖入 PDF 或点击上传"。这是 Apple 风格空状态（图标 + 一句引导）。
- 上传后 iframe 预览**去掉边框**，加 `--radius-card` 和卡片阴影，让 PDF 像"纸"一样浮在浅灰背景上。

### 4.3 第二栏 Order Draft → 分组 Inset 表单
Apple 设置类表单的标准做法：**分组、圆角内嵌（inset grouped）、行内分隔线**。

```
┌─ 客户信息 ───────────────────┐
│ Customer        ACME Corp    │  ← 标签灰、值黑、右对齐
│ ─────────────────────────── │
│ PO Number       PO-1001      │
└──────────────────────────────┘
┌─ 物流 ───────────────────────┐
│ Ship To / From / Date / Carrier ...
└──────────────────────────────┘
```

- 把 6 个 header 字段**按语义分两组**（客户信息 / 物流信息），而不是一长列。
- **Order Total** 提为视觉重点：右上角大号等宽字体 `$200.00`。
- **Status** 从纯文字升级为**胶囊徽章**：
  - `Ready to Submit` → 绿色实心胶囊
  - `Needs Review` → 橙色胶囊 + 下面列出**异常清单**（聚合 `issues`，例如 `重复 PO`、`缺少客户`）
- **三个按钮重排主次**（Apple 永远只有一个主操作）：
  - 主：`Release to Warehouse`（实心蓝胶囊，disabled 时降透明度——你已有该逻辑）
  - 次：`Save`（浅灰填充）
  - 文字按钮：`Revise`（无填充，蓝字）

### 4.4 第三栏 Items → 从"字段流水账"到"卡片化行项"
这是改动最大、价值最高的一栏。现在一行里塞了 `Commit auto 40 → manual → ships → cut` 这种数据库直译，操作员认知负担很高。

改造为**每个 item 一张卡片**，分三层信息：
1. **主信息行**：`ITEM-1002` （Headline）+ 右侧库存充足/缺货的**彩色状态点**。
2. **数量摘要**：`订 40 · 发 40 · 缺 0`，缺货数为 0 时不显示"cut reason / on the way"这些次级控件（**渐进披露**）。
3. **次级操作（仅在有缺口时展开）**：手动 commit 步进器、cut reason、在途数量、tracking。用 `<details>` 或点击展开，默认收起。
- 未知 item（`UNKNOWN_ITEM`）整张卡片**左侧加红色 4px 标识条** + 顶部红色"未找到"徽章，而不是一个小后缀。
- `manual_commit` 的 `number input` 换成 **stepper（− 40 +）**；`on the way` 的 range 保留但配数字气泡。

### 4.5 Agent Workflow Drawer → 实时处理时间线
你已经有逐步 `steps` 数据，这是做出"高级感"的最好机会：
- 上传后 drawer **自动短暂滑出**，5 个 agent（intake→extraction→validation→exception→draft）以**时间线（timeline）**逐个点亮：未开始=灰、进行中=蓝色脉冲、完成=绿勾。
- 用 spring 动效（`cubic-bezier(.2,.8,.2,1)`）让每一步"啪"地完成，制造因果感。
- **彻底删掉 `alert()`**，放行成功改为顶部滑入的 **Toast**（绿色 + 对勾 + "已放行至仓库"），3 秒自动消失。

---

## 5. 交互与动效（Motion）
Apple 的动效是**告知，不是炫技**：
- 统一缓动：`--ease: cubic-bezier(0.2, 0.8, 0.2, 1)`，时长 200–350ms。
- 状态变化（status 徽章变色、item 展开）加 250ms 过渡。
- 按钮按下 `transform: scale(0.97)` + 透明度，给"实体感"。
- 上传处理中：第一栏 PDF 卡片上盖一层**进度态**，而不是页面卡住无反馈。
- `prefers-reduced-motion` 下全部降级为淡入淡出（无障碍要求）。

---

## 6. 信息架构：要不要做成多个界面？
你提到"现在只有一个界面"。**我的建议：保持单窗口**，这恰恰是 Apple 对操作型工具的偏好（一个 PO = 一个工作台，所见即所得）。但建议补 3 个**状态界面**而非新页面：
1. **空状态**（首次进入）：居中插画 + "上传一份采购订单开始"。
2. **处理中状态**：workflow 时间线占据视觉中心。
3. **结果状态**：当前三栏布局。

未来若要扩展，唯一值得加的"第二界面"是 **历史订单列表 / 收件箱**（master-detail：左列 PO 列表，右侧当前工作台），符合 Apple Mail/Notes 的范式。但这是 v2，不在本次必须范围。

---

## 7. 无障碍（Accessibility）— Apple 的硬性标准
- 所有可点击控件 **≥ 44×44pt** 命中区域（当前默认 input 偏小）。
- 颜色对比 **≥ 4.5:1**；状态**不能只靠颜色**，徽章必须带文字/图标（你现在 status 是文字，符合；但 item 状态点要补文字）。
- 输入框补 `:focus-visible` 蓝色光环（当前无聚焦态）。
- 完整键盘可达 + `aria-live` 播报处理结果（drawer 已有 `aria-*`，继续保持）。
- 深色模式自动适配（见 §3.2）。

---

## 8. 分阶段落地路线图

| 阶段 | 内容 | 工作量 | 收益 |
|---|---|---|---|
| **P1 视觉地基** | 注入 design tokens（字体/色/间距/圆角）、去硬边框改卡片+阴影、status 改胶囊徽章、按钮分主次 | 半天 | 立刻"换一个档次" |
| **P2 反馈体验** | 删 `alert` 改 Toast、workflow 实时时间线动效、上传 drop zone + 空状态 | 1 天 | 处理过程有"高级感" |
| **P3 Items 重构** | 行项卡片化、渐进披露次级控件、stepper、未知项红条 | 1–1.5 天 | 真正降低操作员认知负担 |
| **P4 打磨** | 深色模式、无障碍、reduced-motion、微动效 | 半天 | 收尾质感 |

**建议先做 P1**：改的是 CSS 和少量 DOM 结构，风险低、视觉回报最大，做完就能直观看到"Apple 味"。

---

## 9. 落地说明
- 当前 `app.js` 用 `innerHTML` 模板渲染（`itemRow`、`renderDraft`），P1/P2 大多只动 `styles.css` + 少量 class，**不需要重写逻辑**。
- P3 行项卡片需要改 `itemRow` 模板结构（加分层 + `<details>` 渐进披露）和对应 CSS。
- 全程**纯 HTML/CSS/JS，无需引入框架**，保持你现在的零依赖前端。

> 需要我直接进入 **P1 实现**（落地 design tokens + 卡片化 + 状态徽章 + 按钮主次），还是先就某个区域（比如 Items 卡片或 Workflow 时间线）出一版具体的代码方案？
