# ERP 首页(App Launcher)— 设计文档

> 日期:2026-06-29 · 范围:`frontend/home.html`(新)· `frontend/home.js`(新)· `frontend/styles.css`(追加)· `backend/app.py`(路由)
> 目标:为多模块 ERP 提供一个 Apple App-Launcher 风格的首页,作为各工作流(PO Intake 等)的统一入口。

---

## 0. 背景与目标

当前应用只有单一页面 —— PO Intake 三栏工作台(`/` → `index.html`)。系统正在扩展为多模块 ERP(Create Sample Request、Ship/Carrier、客户/物料主数据等)。需要一个**首页**作为这些工作流的统一入口。

本设计仅新增首页与路由改动,**不改动现有 PO Intake 工作台的任何业务逻辑**,只是把它的访问路径从 `/` 改为 `/intake`。

设计风格沿用 `styles.css` 中已建立的 Apple 设计令牌(字体 / 颜色 / 间距 / 圆角 / 毛玻璃 / 缓动 / 深色模式),保证全站视觉一致。

---

## 1. 文件与路由结构

| 文件 | 改动 |
|---|---|
| `frontend/home.html` | **新增** —— 首页结构(顶栏 + 问候 + 启动器网格 + toast host) |
| `frontend/home.js` | **新增** —— 问候语切换 + 占位卡片点击 toast |
| `frontend/styles.css` | **追加** 一段 `/* Home */` 样式,不修改现有规则 |
| `backend/app.py` | 路由调整(见下) |

### 路由

| 方法 / 路径 | 改动后行为 |
|---|---|
| `GET /` | 返回 `home.html`(新首页) |
| `GET /intake` | 返回 `index.html`(现有 PO 工作台,原样) |
| `/static/*` | 不变 |
| `/api/*` | 全部不变 |

`no_store_static` 中间件当前对 `/static` 和 `/` 生效,需要把 `/intake` 也纳入 no-store 路径(与 `/` 同等对待),避免缓存导致页面陈旧。

---

## 2. 页面结构(home.html)

```
┌─ 顶栏(sticky + 毛玻璃 backdrop-filter)─────────┐
│  ◆ Acme ERP                                     │
├──────────────────────────────────────────────┤
│  Good afternoon            (Large Title 28/700) │
│  选择一个工作流开始          (Footnote 灰)        │
│                                                 │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐  │
│  │ ▢ 📄   │ │ ▢ 🧪   │ │ ▢ 🚚   │ │ ▢ 👥   │  │
│  │ PO     │ │ Sample │ │ Ship / │ │ Master │  │
│  │ Intake │ │ Request│ │ Carrier│ │ Data   │  │
│  │ 录入采购 │ │ 创建样品 │ │ 发货承运 │ │客户/物料 │  │
│  │  ●可用  │ │ 即将上线 │ │ 即将上线 │ │ 即将上线 │  │
│  └────────┘ └────────┘ └────────┘ └────────┘  │
└──────────────────────────────────────────────┘
              (下方 toast-host,aria-live)
```

DOM 大致结构:

```html
<header class="home-bar">
  <div class="brand">◆ Acme ERP</div>
</header>
<main class="home">
  <h1 id="greeting" class="home-title">Good afternoon</h1>
  <p class="home-subtitle">选择一个工作流开始</p>
  <nav class="launcher" aria-label="模块">
    <!-- 4 张卡片 -->
  </nav>
</main>
<div id="toast-host" aria-live="polite"></div>
```

---

## 3. 模块卡片(launcher tile)

四张卡片,数据可在 `home.js` 用一个数组描述,渲染时根据 `status` 决定标签与行为(也可直接写死在 HTML;以可读性优先,采用静态 HTML + JS 仅绑事件)。

| 模块 | 图标 | 副标题 | 状态 | 行为 |
|---|---|---|---|---|
| PO Intake | 📄 | 录入采购订单 | `available` | `<a href="/intake">`,绿色胶囊「可用」 |
| Sample Request | 🧪 | 创建样品申请 | `soon` | `<button>`,灰胶囊「即将上线」,点击 toast |
| Ship / Carrier | 🚚 | 发货与承运管理 | `soon` | 同上 |
| Master Data | 👥 | 客户与物料主数据 | `soon` | 同上 |

**卡片结构(三层信息)**:
1. squircle 图标砖(圆角方块,浅色 `--fill` 填充背景,内置 emoji 图标)
2. 模块名(Headline,17/600)
3. 一行中文副标题(Footnote,`--label-secondary` 灰)
4. 右下/底部状态胶囊(pill):`可用`=绿(`--green`/`--green-bg`),`即将上线`=灰(`--fill-strong`/`--label-secondary`)

**可用卡** = `<a>`;**占位卡** = `<button type="button" data-soon>`,点击触发 toast「该模块即将上线」。
不为占位模块创建任何空白页面。

---

## 4. Apple 质感细节(均复用现有令牌)

- **顶栏**:`position: sticky; top:0`,`backdrop-filter: var(--material)` 毛玻璃,底部 `1px var(--separator)` 细线,无硬边框。
- **网格**:`display:grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 24px`(8pt 节奏)。窄屏自动回落到 2 列 / 1 列。
- **卡片**:`--bg-elevated` 底、`--radius-card`(16px)、`--shadow-card` 阴影,浮于 `--bg` 浅灰背景。
- **交互**:hover `translateY(-2px)` + 阴影加深;按下 `transform: scale(0.97)`;统一 `--ease`,时长 200–250ms。
- **问候语**:`home.js` 按本地时间切换 `Good morning`(<12)/`Good afternoon`(12–18)/`Good evening`(≥18),纯前端,无网络。
- **Toast**:沿用现有 toast 视觉(顶部滑入,3 秒自动消失);占位卡复用之。

---

## 5. 无障碍(Accessibility)

- 卡片命中区 ≥ 44×44pt。
- `:focus-visible` 蓝色光环(`--accent`)。
- 状态不只靠颜色:胶囊带文字(「可用」/「即将上线」)。
- 可用卡为语义化 `<a>`,占位卡为 `<button>` 并带 `aria-label`。
- `toast-host` 用 `aria-live="polite"` 播报。
- 深色模式自动跟随系统(继承令牌);`prefers-reduced-motion` 下动效降级为淡入,无位移。

---

## 6. 测试

- **后端**(`tests/test_app.py` 同风格):
  - `GET /` 返回 200 且响应体含首页标识(如 `Acme ERP` / `launcher`)。
  - `GET /intake` 返回 200 且含 PO 工作台标识(如 `Order Draft`)。
  - 两条路径响应头含 `Cache-Control: no-store`。
- **前端**:无构建、纯静态,人工/gstack 验证:首页加载、问候语按时段、PO Intake 卡片跳转 `/intake`、占位卡片 toast、窄屏网格回落、深色模式。

---

## 7. 不做(YAGNI)

- 不做设置 / 用户头像 / 手动主题切换(深色模式已自动跟随系统)。
- 不做 KPI / 统计数字(选定启动器风格,且无统计接口)。
- 占位模块不建空白页,仅 toast 提示。
- 不引入任何前端框架,保持零依赖。

---

## 8. 落地顺序

1. `backend/app.py` 路由(`/` → home,`/intake` → index,no-store 纳入 `/intake`)+ 后端测试。
2. `frontend/home.html` 结构。
3. `styles.css` 追加 `/* Home */` 样式。
4. `frontend/home.js` 问候语 + 占位 toast。
5. gstack 视觉走查(浅色 / 深色 / 窄屏)。
