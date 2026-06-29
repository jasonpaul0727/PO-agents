# ERP 首页(App Launcher)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个 Apple App-Launcher 风格的 ERP 首页,作为各工作流(PO Intake 等)的统一入口。

**Architecture:** 纯静态首页 `home.html` + 追加样式 + 极少量 `home.js`,复用现有 Apple 设计令牌。后端 FastAPI 把 `/` 改为返回首页,现有 PO 工作台移到 `/intake`。不改动任何业务逻辑。

**Tech Stack:** FastAPI(后端路由 + FileResponse)、原生 HTML/CSS/JS(零框架)、pytest + FastAPI TestClient。

## Global Constraints

- 设计令牌一律复用 `frontend/styles.css` `:root` 已有变量(`--accent` `--green` `--bg-elevated` `--radius-card` `--shadow-card` `--material` `--ease` 等),不新增颜色/字体常量。
- 不引入任何前端框架或依赖,保持零依赖。
- 不修改现有 PO Intake 业务逻辑(`index.html` / `app.js` 内容),只改其访问路径。
- 占位模块(Sample Request / Ship-Carrier / Master Data)不建空白页,点击仅弹 toast「该模块即将上线」。
- 品牌名占位用 `Acme ERP`。
- 无障碍:可用卡为 `<a>`,占位卡为 `<button>`;命中区 ≥ 44px;`:focus-visible` 蓝色光环;深色模式自动跟随系统;`prefers-reduced-motion` 降级。

---

### Task 1: 后端路由 + 首页骨架

把 `/` 指向新首页、PO 工作台移到 `/intake`,并让首页可被请求到(需要 `home.html` 存在)。本任务交付:路由改动 + `home.html` 完整结构 + 后端测试。

**Files:**
- Create: `frontend/home.html`
- Modify: `backend/app.py:29-41`(中间件 no-store 路径 + 两个路由)
- Test: `tests/test_app.py`(追加两个测试)

**Interfaces:**
- Consumes: 现有 `app`、`FRONTEND`(`backend/app.py`)、`TestClient`(测试)。
- Produces:
  - `GET /` → `frontend/home.html`(响应体含 `Acme ERP` 与 `launcher`,头含 `Cache-Control: no-store`)
  - `GET /intake` → `frontend/index.html`(响应体含 `Order Draft`,头含 `Cache-Control: no-store`)

- [ ] **Step 1: 写失败测试**

在 `tests/test_app.py` 末尾追加:

```python
def test_home_page_served_at_root():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Acme ERP" in resp.text
    assert "launcher" in resp.text
    assert resp.headers["cache-control"] == "no-store"


def test_intake_page_served_at_intake():
    client = TestClient(app)
    resp = client.get("/intake")
    assert resp.status_code == 200
    assert "Order Draft" in resp.text
    assert resp.headers["cache-control"] == "no-store"
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `python -m pytest tests/test_app.py::test_home_page_served_at_root tests/test_app.py::test_intake_page_served_at_intake -v`
Expected: FAIL —— `test_home_page_served_at_root` 因 `/` 仍返回 `index.html`(不含 `Acme ERP`/`launcher`)而断言失败;`test_intake_page_served_at_intake` 因 `/intake` 路由不存在返回 404 而失败。

- [ ] **Step 3: 创建 `frontend/home.html`**

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Acme ERP</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body class="home-body">
  <header class="home-bar">
    <div class="brand">◆ Acme ERP</div>
  </header>

  <main class="home">
    <h1 id="greeting" class="home-title">Good afternoon</h1>
    <p class="home-subtitle">选择一个工作流开始</p>

    <nav class="launcher" aria-label="模块">
      <a class="tile" href="/intake">
        <span class="tile-icon" aria-hidden="true">📄</span>
        <span class="tile-name">PO Intake</span>
        <span class="tile-sub">录入采购订单</span>
        <span class="tile-pill ok">可用</span>
      </a>

      <button type="button" class="tile" data-soon aria-label="Sample Request,即将上线">
        <span class="tile-icon" aria-hidden="true">🧪</span>
        <span class="tile-name">Sample Request</span>
        <span class="tile-sub">创建样品申请</span>
        <span class="tile-pill">即将上线</span>
      </button>

      <button type="button" class="tile" data-soon aria-label="Ship / Carrier,即将上线">
        <span class="tile-icon" aria-hidden="true">🚚</span>
        <span class="tile-name">Ship / Carrier</span>
        <span class="tile-sub">发货与承运管理</span>
        <span class="tile-pill">即将上线</span>
      </button>

      <button type="button" class="tile" data-soon aria-label="Master Data,即将上线">
        <span class="tile-icon" aria-hidden="true">👥</span>
        <span class="tile-name">Master Data</span>
        <span class="tile-sub">客户与物料主数据</span>
        <span class="tile-pill">即将上线</span>
      </button>
    </nav>
  </main>

  <div id="toast-host" aria-live="polite"></div>
  <script src="/static/home.js"></script>
</body>
</html>
```

- [ ] **Step 4: 改 `backend/app.py` 路由与中间件**

把中间件判断(`backend/app.py:34`)改为:

```python
    if request.url.path.startswith("/static") or request.url.path in ("/", "/intake"):
```

把 `index` 路由(`backend/app.py:39-41`)替换为:

```python
@app.get("/")
def index():
    return FileResponse(str(FRONTEND / "home.html"))


@app.get("/intake")
def intake():
    return FileResponse(str(FRONTEND / "index.html"))
```

- [ ] **Step 5: 运行测试,确认通过**

Run: `python -m pytest tests/test_app.py -v`
Expected: PASS(新增两条 + 原有用例全绿)

- [ ] **Step 6: 提交**

```bash
git add frontend/home.html backend/app.py tests/test_app.py
git commit -m "feat(home): serve launcher home at /, move PO intake to /intake"
```

---

### Task 2: 首页样式(styles.css 追加 Home 段)

为首页补齐 Apple 质感样式。纯静态视觉,用 gstack 走查验证。

**Files:**
- Modify: `frontend/styles.css`(文件末尾追加 `/* Home */` 段)

**Interfaces:**
- Consumes: `:root` 令牌、全局 `.toast` / `#toast-host` 样式(已存在)、Task 1 的 `home.html` class 名(`home-bar` `brand` `home` `home-title` `home-subtitle` `launcher` `tile` `tile-icon` `tile-name` `tile-sub` `tile-pill` `tile-pill.ok`)。
- Produces: 完整渲染的首页样式。

- [ ] **Step 1: 在 `frontend/styles.css` 末尾追加**

```css
/* ============================================================
   Home (app launcher)
   ============================================================ */
.home-body { min-height: 100vh; }

.home-bar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  padding: 0 24px;
  height: 52px;
  background: color-mix(in srgb, var(--bg-elevated) 72%, transparent);
  backdrop-filter: var(--material);
  -webkit-backdrop-filter: var(--material);
  border-bottom: 1px solid var(--separator);
}
.home-bar .brand {
  font-size: 17px;
  font-weight: 600;
  color: var(--label);
  letter-spacing: -0.01em;
}

.home {
  max-width: 1040px;
  margin: 0 auto;
  padding: 48px 24px 64px;
}
.home-title {
  font-size: 28px;
  line-height: 34px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin: 0;
  color: var(--label);
}
.home-subtitle {
  font-size: 13px;
  line-height: 18px;
  color: var(--label-secondary);
  margin: 6px 0 32px;
}

.launcher {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 24px;
}

.tile {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  min-height: 168px;
  padding: 20px;
  border: none;
  text-align: left;
  text-decoration: none;
  background: var(--bg-elevated);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  color: var(--label);
  cursor: pointer;
  font-family: inherit;
  transition: transform 200ms var(--ease), box-shadow 200ms var(--ease);
}
.tile:hover {
  transform: translateY(-2px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08), 0 14px 32px rgba(0, 0, 0, 0.10);
}
.tile:active { transform: scale(0.97); }
.tile:focus-visible {
  outline: none;
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 35%, transparent), var(--shadow-card);
}

.tile-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: 14px;
  background: var(--fill);
  font-size: 26px;
  margin-bottom: 8px;
}
.tile-name {
  font-size: 17px;
  line-height: 22px;
  font-weight: 600;
  color: var(--label);
}
.tile-sub {
  font-size: 13px;
  line-height: 18px;
  color: var(--label-secondary);
}
.tile-pill {
  margin-top: auto;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  background: var(--fill-strong);
  color: var(--label-secondary);
}
.tile-pill.ok {
  background: var(--green-bg);
  color: var(--green);
}

@media (prefers-reduced-motion: reduce) {
  .tile { transition: box-shadow 200ms var(--ease); }
  .tile:hover { transform: none; }
  .tile:active { transform: none; }
}
```

- [ ] **Step 2: gstack 视觉走查**

用 gstack 打开 `http://127.0.0.1:8000/`(先确保服务在跑:`uvicorn backend.app:app --reload`)。
Expected:
- 顶栏毛玻璃 + 细分隔线,品牌左对齐。
- 4 张卡片网格,squircle 图标砖,标题/副标题层级清晰,PO Intake 绿胶囊「可用」、其余灰胶囊「即将上线」。
- hover 卡片上浮、阴影加深。
- 浏览器缩窄到 ~600px:网格回落到 2 列 / 1 列不溢出。
- 切换系统深色模式:背景转黑、卡片转 `#1c1c1e`,文字反白(令牌自动生效)。

- [ ] **Step 3: 提交**

```bash
git add frontend/styles.css
git commit -m "feat(home): Apple-style launcher styles"
```

---

### Task 3: 首页交互(home.js)

问候语按时段切换 + 占位卡片点击 toast。

**Files:**
- Create: `frontend/home.js`

**Interfaces:**
- Consumes: `home.html` 中的 `#greeting`、`.tile[data-soon]`、`#toast-host`;全局 `.toast` 样式。
- Produces: 页面加载即设置问候语;点击占位卡弹「该模块即将上线」toast。

- [ ] **Step 1: 创建 `frontend/home.js`**

```javascript
// Home (app launcher) — greeting + placeholder toast. Zero dependencies.
(function () {
  // ---------- Greeting by local time ----------
  const hour = new Date().getHours();
  const greeting =
    hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const greetingEl = document.getElementById("greeting");
  if (greetingEl) greetingEl.textContent = greeting;

  // ---------- Toast (mirrors app.js) ----------
  function showToast(message, tone = "green") {
    const host = document.getElementById("toast-host");
    if (!host) return;
    const el = document.createElement("div");
    el.className = `toast tone-${tone}`;
    el.textContent = message;
    host.appendChild(el);
    requestAnimationFrame(() => el.classList.add("in"));
    setTimeout(() => {
      el.classList.remove("in");
      setTimeout(() => el.remove(), 250);
    }, 3000);
  }

  // ---------- Placeholder modules ----------
  document.querySelectorAll(".tile[data-soon]").forEach((btn) => {
    btn.addEventListener("click", () => showToast("该模块即将上线", "orange"));
  });
})();
```

- [ ] **Step 2: gstack 验证交互**

用 gstack 打开 `http://127.0.0.1:8000/`。
Expected:
- 问候语随当前时段显示(morning/afternoon/evening 之一)。
- 点击 PO Intake 卡片 → 跳转 `/intake`,显示现有 PO 工作台(`Order Draft` 三栏)。
- 点击 Sample Request / Ship-Carrier / Master Data → 顶部滑入橙色 toast「该模块即将上线」,3 秒消失,不跳转。
- 键盘 Tab 可聚焦每张卡片,出现蓝色 focus 光环;Enter 在占位卡上触发 toast。

- [ ] **Step 3: 提交**

```bash
git add frontend/home.js
git commit -m "feat(home): greeting + coming-soon toast for placeholder modules"
```

---

## Self-Review

**Spec coverage:**
- 文件与路由(spec §1)→ Task 1 ✓
- 页面结构 / DOM(spec §2)→ Task 1 `home.html` ✓
- 模块卡片与行为(spec §3)→ Task 1 标记 + Task 3 toast ✓
- Apple 质感(spec §4)→ Task 2 ✓
- 无障碍(spec §5)→ Task 1(语义标签/aria)+ Task 2(focus-visible、深色、reduced-motion)✓
- 测试(spec §6)→ Task 1 后端测试;前端 gstack 走查在 Task 2/3 ✓
- YAGNI(spec §7)→ 无设置/头像/KPI/空白页,Global Constraints 已固化 ✓
- 落地顺序(spec §8)→ 任务顺序一致 ✓

**Placeholder scan:** 无 TBD/TODO,所有代码步骤含完整代码。✓

**Type/名称一致性:** class 名在 `home.html`(Task 1)、CSS(Task 2)、`home.js`(Task 3)三处一致:`launcher` `tile` `tile-icon` `tile-name` `tile-sub` `tile-pill` `tile-pill.ok` `#greeting` `#toast-host` `[data-soon]`。`showToast(message, tone)` 签名与 `app.js` 一致。✓
