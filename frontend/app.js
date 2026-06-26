const $ = (sel) => document.querySelector(sel);
let currentOrder = null;

const drawer = $("#workflow-drawer");
const overlay = $("#drawer-overlay");
const toggleBtn = $("#workflow-toggle");

function openDrawer() {
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  toggleBtn.setAttribute("aria-expanded", "true");
  overlay.hidden = false;
  requestAnimationFrame(() => overlay.classList.add("visible"));
  setToggleArrow(true);
}

function closeDrawer() {
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  toggleBtn.setAttribute("aria-expanded", "false");
  overlay.classList.remove("visible");
  setTimeout(() => { overlay.hidden = true; }, 200);
  setToggleArrow(false);
}

function toggleDrawer() {
  if (drawer.classList.contains("open")) closeDrawer();
  else openDrawer();
}

function setToggleArrow(isOpen) {
  const arrow = isOpen ? "◂" : "▸";
  const badge = toggleBtn.dataset.badge || "";
  toggleBtn.textContent = `Agent Workflow ${arrow}${badge ? " " + badge : ""}`;
}

function setWorkflowBadge(badge) {
  toggleBtn.dataset.badge = badge || "";
  setToggleArrow(drawer.classList.contains("open"));
}

function updateWorkflowBadge(steps) {
  const total = steps.length;
  const okCount = steps.filter((s) => s.ok).length;
  setWorkflowBadge(okCount === total ? `${okCount}/${total} ✓` : `${okCount}/${total}`);
}

toggleBtn.addEventListener("click", toggleDrawer);
overlay.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && drawer.classList.contains("open")) closeDrawer();
});

// ---------- Toast ----------
function showToast(message, tone = "green") {
  const host = $("#toast-host");
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

// ---------- PDF preview / dropzone ----------
async function showPreview(file) {
  // Render server-side to a PNG so it shows regardless of the browser's PDF settings.
  try {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch("/api/preview", { method: "POST", body: form });
    if (resp.ok) {
      showPreviewUrl(URL.createObjectURL(await resp.blob()));
      return;
    }
  } catch (err) {
    /* fall through to a plain message */
  }
  showToast("无法生成 PDF 预览", "orange");
}

function showPreviewUrl(url) {
  $("#pdf-preview").src = url;
  $("#dropzone").hidden = true;
  $("#preview-wrap").hidden = false;
}

// ---------- Workflow timeline ----------
const PIPELINE_STEPS = ["intake", "extraction", "validation", "exception", "draft"];

function renderStepsPending() {
  $("#steps").innerHTML = PIPELINE_STEPS
    .map((s, i) => `<li data-step="${s}" class="${i === 0 ? "processing" : ""}">${s}</li>`)
    .join("");
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function animateSteps(steps) {
  // Reveal each returned step in order with a small stagger for a sense of progress.
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    const li = document.querySelector(`#steps li[data-step="${s.step}"]`);
    if (li) {
      li.classList.remove("processing");
      li.classList.add(s.ok ? "done" : "error");
    }
    const next = steps[i + 1];
    if (next) {
      const nextLi = document.querySelector(`#steps li[data-step="${next.step}"]`);
      if (nextLi) nextLi.classList.add("processing");
    }
    await sleep(180);
  }
}

// ---------- Process pipeline ----------
async function processFile(file) {
  if (!file) return;
  if (file.type !== "application/pdf") {
    showToast("请上传 PDF 文件", "red");
    return;
  }
  showPreview(file);
  setWorkflowBadge("");
  renderStepsPending();
  openDrawer();

  let body;
  try {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch("/api/process", { method: "POST", body: form });
    if (!resp.ok) {
      showToast("处理失败:" + (await resp.text()), "red");
      return;
    }
    body = await resp.json();
  } catch (err) {
    showToast("网络错误,请重试", "red");
    return;
  }

  await animateSteps(body.steps);
  updateWorkflowBadge(body.steps);
  currentOrder = body.order;
  renderDraft(currentOrder);
}

// ---------- Demo data (no API cost) ----------
function demoOrder() {
  const SHORT = [5, 8];      // these items are short on stock
  const UNKNOWN = 3;         // ITEM-003 contains '3' -> not seeded -> not found
  const items = [];
  for (let i = 1; i <= 10; i++) {
    const id = "ITEM-" + String(i).padStart(3, "0");
    const order_quantity = i * 10;
    const unit_price = 5 + i;
    const unknown = i === UNKNOWN;
    const warehouse_quantity = unknown
      ? 0
      : SHORT.includes(i)
      ? order_quantity - 15
      : order_quantity + 50;
    const inventory_commit = unknown ? 0 : Math.min(order_quantity, warehouse_quantity);
    const committed_quantity = inventory_commit;
    items.push({
      item_number: id,
      customer_item_number: String(7000 + i), // Ollies' own number, maps back to ITEM-00x
      order_quantity,
      unit_price,
      line_total: order_quantity * unit_price,
      warehouse_quantity,
      inventory_commit,
      manual_commit: null,
      committed_quantity,
      difference: order_quantity - committed_quantity,
      cut_reason_type: null,
      on_the_way_quantity: 0,
      on_the_way_tracking_no: null,
      note: null,
    });
  }
  return {
    header: {
      customer: "Ollies",
      po_number: "PO-DEMO-001",
      ship_to: "123 Main St, Los Angeles",
      ship_from_warehouse: "LA-WH",
      ship_date: null,
      carrier: "UPS",
      requested_date: "2026-07-01",
    },
    line_items: items,
    order_total: items.reduce((sum, li) => sum + li.line_total, 0),
    issues: [
      { severity: "error", code: "UNKNOWN_ITEM", message: "Not found", field: "line_items[2].item_number" },
    ],
    order_note: null,
    status: "needs_review",
    human_summary: "10 line item(s) — demo data (no API call)",
  };
}

async function loadDemo() {
  const steps = PIPELINE_STEPS.map((s) => ({ step: s, ok: true }));
  showPreviewUrl("/static/demo.png"); // show a sample PO image in the left column
  setWorkflowBadge("");
  renderStepsPending();
  openDrawer();
  await animateSteps(steps);
  updateWorkflowBadge(steps);
  currentOrder = demoOrder();
  renderDraft(currentOrder);
  showToast("已加载演示单据(未调用 API)", "green");
}

$("#btn-demo").addEventListener("click", loadDemo);
$("#pdf-input").addEventListener("change", (e) => processFile(e.target.files[0]));
$("#btn-change-pdf").addEventListener("click", () => $("#pdf-input").click());

// Drag & drop onto the PDF column
const pdfCol = $("#col-pdf");
["dragenter", "dragover"].forEach((evt) =>
  pdfCol.addEventListener(evt, (e) => { e.preventDefault(); pdfCol.classList.add("dragging"); })
);
["dragleave", "drop"].forEach((evt) =>
  pdfCol.addEventListener(evt, (e) => { e.preventDefault(); pdfCol.classList.remove("dragging"); })
);
pdfCol.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) processFile(file);
});

const STATUS_META = {
  ready_to_submit: { label: "Ready to Submit", tone: "tone-green" },
  released_to_warehouse: { label: "Released to Warehouse", tone: "tone-green" },
  needs_review: { label: "Needs Review", tone: "tone-orange" },
  revise: { label: "Revise", tone: "tone-orange" },
};

function renderStatus(status) {
  const el = $("#status");
  const meta = STATUS_META[status] || { label: status || "—", tone: "" };
  el.textContent = meta.label;
  el.className = meta.tone;
}

function renderDraft(order) {
  for (const k of ["customer", "po_number", "ship_to", "ship_from_warehouse", "ship_date", "carrier"]) {
    const el = document.querySelector(`[name=${k}]`);
    if (el) el.value = order.header[k] ?? "";
  }
  $("[name=order_note]").value = order.order_note ?? "";
  $("#order-total").textContent = order.order_total != null ? `$${order.order_total.toFixed(2)}` : "—";
  renderStatus(order.status);
  $("#btn-release").disabled = order.status !== "ready_to_submit";
  syncAddCustomerBtn();
  $("#items").innerHTML = order.line_items.map(itemRow).join("");
}

function syncAddCustomerBtn() {
  const unknown = (currentOrder?.issues || []).some((i) => i.code === "UNKNOWN_CUSTOMER");
  $("#btn-add-customer").hidden = !unknown;
}

$("#btn-add-customer").addEventListener("click", async () => {
  const name = ($("[name=customer]").value || "").trim();
  if (!name) { showToast("请先填写客户名", "orange"); return; }
  try {
    const resp = await fetch("/api/add-customer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!resp.ok) { showToast("登记失败:" + (await resp.text()), "red"); return; }
  } catch (err) {
    showToast("网络错误,请重试", "red");
    return;
  }
  currentOrder.issues = (currentOrder.issues || []).filter((i) => i.code !== "UNKNOWN_CUSTOMER");
  showToast(`已登记新客户:${name}`, "green");
  refreshStatusFromIssues();
});

function itemRow(li, idx) {
  const unknown = (currentOrder.issues || []).some(
    (i) => i.code === "UNKNOWN_ITEM" && i.field === `line_items[${idx}].item_number`
  );
  const price = li.unit_price != null ? `$${li.unit_price.toFixed(2)}` : "—";
  const lineTotal = li.line_total != null ? `$${li.line_total.toFixed(2)}` : "—";
  return `
    <div class="item ${unknown ? "unknown" : ""}" data-idx="${idx}">
      <div class="ids-row">
        <input class="cust-input" value="${li.customer_item_number ?? ""}" data-field="customer_item_number"
          placeholder="客户料号" aria-label="客户料号" />
        <span class="map-arrow" aria-hidden="true">→</span>
        <input class="ids-input" value="${li.item_number ?? ""}" data-field="item_number"
          placeholder="我方料号" aria-label="我方料号" />
        ${unknown ? `<span class="ids-warn">⚠ Not found</span>` : ""}
      </div>
      <div>Order ${li.order_quantity} | Unit ${price} | Line ${lineTotal} | Stock ${li.warehouse_quantity}</div>
      <div class="commit-row">
        Commit auto ${li.inventory_commit} →
        manual <input type="number" min="0" max="${li.warehouse_quantity}"
          value="${li.manual_commit ?? li.inventory_commit}" data-field="manual_commit" />
        → ships <span data-out="ships">${li.committed_quantity}</span> | cut <span data-out="cut">${li.difference}</span>
      </div>
      <div class="shortfall" data-out="shortfall" ${li.difference > 0 ? "" : "hidden"}>
        ⚠ 仓库不足:订 ${li.order_quantity} / 库存 ${li.warehouse_quantity},缺 <span data-out="cut2">${li.difference}</span> 件 — 请手动调整 commit,并填 cut 原因 / 在途
      </div>
      <div class="commit-row">
        Cut reason
        <select data-field="cut_reason_type">
          ${["", "缺货", "已停产", "客户要求", "货损", "其他"]
            .map((o) => `<option ${o === (li.cut_reason_type ?? "") ? "selected" : ""}>${o}</option>`)
            .join("")}
        </select>
      </div>
      <div class="commit-row">
        On the way <input type="range" min="0" max="${li.difference}"
          value="${li.on_the_way_quantity}" data-field="on_the_way_quantity" />
        <span data-out="otw">${li.on_the_way_quantity}</span>
        <input placeholder="tracking #" value="${li.on_the_way_tracking_no ?? ""}"
          data-field="on_the_way_tracking_no" />
      </div>
      <input class="note" placeholder="📝 note" value="${li.note ?? ""}" data-field="note" />
    </div>`;
}

function collectDraft() {
  const header = {};
  for (const k of ["customer", "po_number", "ship_to", "ship_from_warehouse", "ship_date", "carrier"]) {
    header[k] = document.querySelector(`[name=${k}]`).value || null;
  }
  const line_items = currentOrder.line_items.map((li, idx) => {
    const row = document.querySelector(`.item[data-idx="${idx}"]`);
    const get = (f) => row.querySelector(`[data-field=${f}]`);
    const manual = get("manual_commit").value;
    return {
      ...li,
      item_number: get("item_number").value.trim(),
      customer_item_number: get("customer_item_number").value.trim() || null,
      manual_commit: manual === "" ? null : Number(manual),
      cut_reason_type: get("cut_reason_type").value || null,
      on_the_way_quantity: Number(get("on_the_way_quantity").value),
      on_the_way_tracking_no: get("on_the_way_tracking_no").value || null,
      note: get("note").value || null,
    };
  });
  return { ...currentOrder, header, line_items, order_note: $("[name=order_note]").value || null };
}

async function submitDraft() {
  const resp = await fetch("/api/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collectDraft()),
  });
  const body = await resp.json();
  currentOrder = body.order;
  renderDraft(currentOrder);
  if (body.released) showToast("✓ 已放行至仓库", "green");
  else showToast("仍需复核,未放行", "orange");
}

$("#btn-release").addEventListener("click", submitDraft);
$("#btn-save").addEventListener("click", () => { currentOrder = collectDraft(); renderDraft(currentOrder); });
$("#btn-revise").addEventListener("click", () => renderStatus("revise"));

function currentCustomer() {
  return ($("[name=customer]").value || (currentOrder && currentOrder.header.customer) || "").trim();
}

// Re-derive a line's stock / auto-commit / shortfall from a lookup response, the
// same way the backend exception+draft agents would, then re-render + refresh status.
function applyLineLookup(idx, data) {
  const li = currentOrder.line_items[idx];
  li.warehouse_quantity = data.warehouse_quantity ?? 0;
  li.inventory_commit = data.inventory_commit ?? 0;
  li.manual_commit = null;
  li.committed_quantity = li.inventory_commit;
  li.difference = li.order_quantity - li.committed_quantity;
  li.on_the_way_quantity = 0;
  li.cut_reason_type = null;
  updateLineIssue(idx, data.found);
  renderRow(idx);
  refreshStatusFromIssues();
}

// Edit OUR item number: check the item master directly. If this line had a
// previously-unresolved customer number, remember the mapping (learn-as-you-go).
$("#items").addEventListener("change", async (e) => {
  const input = e.target;
  if (!input.classList || !input.classList.contains("ids-input")) return;
  const idx = Number(input.closest(".item").dataset.idx);
  const li = currentOrder.line_items[idx];
  li.item_number = input.value.trim();

  let data;
  try {
    const resp = await fetch(
      `/api/check-item?item_number=${encodeURIComponent(li.item_number)}&order_quantity=${li.order_quantity}`
    );
    data = await resp.json();
  } catch (err) {
    return; // network hiccup: leave current state untouched
  }
  applyLineLookup(idx, data);

  // Persist the mapping immediately (on blur, NOT on release). This also lets a
  // manual entry OVERRIDE a rule-based customer (e.g. Ollies), because the table
  // is consulted before the rule on the next lookup.
  const customer = currentCustomer();
  if (data.found && li.customer_item_number && customer) {
    const wasNew = li._pendingMap;
    li._pendingMap = false;
    try {
      await fetch("/api/map-item", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer,
          customer_item_number: li.customer_item_number,
          item_number: li.item_number,
        }),
      });
      const verb = wasNew ? "已记住" : "已更新映射";
      showToast(`${verb}:${customer} ${li.customer_item_number} → ${li.item_number}`, "green");
    } catch (err) {
      /* mapping save failed: not fatal, operator can retry */
    }
  }
});

// Edit the CUSTOMER's item number: resolve it to our number. If unmatched, flag the
// line so the operator's manual entry gets remembered (learn-as-you-go).
$("#items").addEventListener("change", async (e) => {
  const input = e.target;
  if (!input.classList || !input.classList.contains("cust-input")) return;
  const idx = Number(input.closest(".item").dataset.idx);
  const li = currentOrder.line_items[idx];
  const custNo = input.value.trim();
  li.customer_item_number = custNo;
  if (!custNo) return;

  const customer = currentCustomer();
  let data;
  try {
    const resp = await fetch(
      `/api/resolve-item?customer=${encodeURIComponent(customer)}` +
        `&customer_item_number=${encodeURIComponent(custNo)}&order_quantity=${li.order_quantity}`
    );
    data = await resp.json();
  } catch (err) {
    return;
  }
  if (!data.resolved) {
    li._pendingMap = true;
    showToast(`未匹配 ${custNo}(${customer || "该客户"}):请在右框填我方料号,系统会自动记住`, "orange");
    return;
  }

  li._pendingMap = false;
  li.item_number = data.item_number;
  applyLineLookup(idx, data);
});

// Live recompute of ships / cut / shortfall when manual commit changes, and live
// on-the-way value as the slider moves. (These were static, server-rendered text.)
$("#items").addEventListener("input", (e) => {
  const field = e.target.dataset && e.target.dataset.field;
  const row = e.target.closest ? e.target.closest(".item") : null;
  if (!row) return;
  const idx = Number(row.dataset.idx);
  if (field === "manual_commit") {
    recomputeCommit(idx);
  } else if (field === "on_the_way_quantity") {
    currentOrder.line_items[idx].on_the_way_quantity = Number(e.target.value);
    const otw = row.querySelector('[data-out="otw"]');
    if (otw) otw.textContent = e.target.value;
  }
});

function recomputeCommit(idx) {
  const li = currentOrder.line_items[idx];
  const row = document.querySelector(`.item[data-idx="${idx}"]`);
  if (!row) return;
  const manual = row.querySelector('[data-field="manual_commit"]').value;
  li.manual_commit = manual === "" ? null : Number(manual);
  li.committed_quantity = li.manual_commit != null ? li.manual_commit : li.inventory_commit;
  li.difference = Math.max(0, li.order_quantity - li.committed_quantity);

  row.querySelector('[data-out="ships"]').textContent = li.committed_quantity;
  row.querySelector('[data-out="cut"]').textContent = li.difference;

  const sf = row.querySelector('[data-out="shortfall"]');
  if (sf) {
    sf.hidden = li.difference <= 0;
    const cut2 = row.querySelector('[data-out="cut2"]');
    if (cut2) cut2.textContent = li.difference;
  }

  // On-the-way is capped at the shortfall — re-enable the slider and clamp it.
  const otwEl = row.querySelector('[data-field="on_the_way_quantity"]');
  if (otwEl) {
    otwEl.max = li.difference;
    if (Number(otwEl.value) > li.difference) otwEl.value = li.difference;
    li.on_the_way_quantity = Number(otwEl.value);
    const otwOut = row.querySelector('[data-out="otw"]');
    if (otwOut) otwOut.textContent = li.on_the_way_quantity;
  }
}

function updateLineIssue(idx, found) {
  const field = `line_items[${idx}].item_number`;
  currentOrder.issues = (currentOrder.issues || []).filter(
    (i) => !(i.code === "UNKNOWN_ITEM" && i.field === field)
  );
  if (!found) {
    currentOrder.issues.push({ severity: "error", code: "UNKNOWN_ITEM", message: "Not found", field });
  }
}

function renderRow(idx) {
  const row = document.querySelector(`.item[data-idx="${idx}"]`);
  if (row) row.outerHTML = itemRow(currentOrder.line_items[idx], idx);
}

function refreshStatusFromIssues() {
  const hasError = (currentOrder.issues || []).some((i) => i.severity === "error");
  currentOrder.status = hasError ? "needs_review" : "ready_to_submit";
  renderStatus(currentOrder.status);
  $("#btn-release").disabled = currentOrder.status !== "ready_to_submit";
  syncAddCustomerBtn();
}
