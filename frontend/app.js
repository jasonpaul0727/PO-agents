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

$("#pdf-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  setWorkflowBadge("");
  $("#pdf-preview").src = URL.createObjectURL(file);
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch("/api/process", { method: "POST", body: form });
  if (!resp.ok) {
    alert("Process failed: " + (await resp.text()));
    return;
  }
  const body = await resp.json();
  renderSteps(body.steps);
  updateWorkflowBadge(body.steps);
  currentOrder = body.order;
  renderDraft(currentOrder);
});

function renderSteps(steps) {
  $("#steps").innerHTML = steps
    .map((s) => `<li class="${s.ok ? "done" : ""}">${s.step}</li>`)
    .join("");
}

function renderDraft(order) {
  for (const k of ["customer", "po_number", "ship_to", "ship_from_warehouse", "ship_date", "carrier"]) {
    const el = document.querySelector(`[name=${k}]`);
    if (el) el.value = order.header[k] ?? "";
  }
  $("[name=order_note]").value = order.order_note ?? "";
  $("#order-total").textContent = order.order_total != null ? `$${order.order_total.toFixed(2)}` : "—";
  $("#status").textContent = order.status;
  $("#btn-release").disabled = order.status !== "ready_to_submit";
  $("#items").innerHTML = order.line_items.map(itemRow).join("");
}

function itemRow(li, idx) {
  const unknown = (currentOrder.issues || []).some(
    (i) => i.code === "UNKNOWN_ITEM" && i.field === `line_items[${idx}].item_number`
  );
  const price = li.unit_price != null ? `$${li.unit_price.toFixed(2)}` : "—";
  const lineTotal = li.line_total != null ? `$${li.line_total.toFixed(2)}` : "—";
  return `
    <div class="item ${unknown ? "unknown" : ""}" data-idx="${idx}">
      <div class="ids">${li.item_number}</div>
      <div>Order ${li.order_quantity} | Unit ${price} | Line ${lineTotal} | Stock ${li.warehouse_quantity}</div>
      <div class="commit-row">
        Commit auto ${li.inventory_commit} →
        manual <input type="number" min="0" max="${li.warehouse_quantity}"
          value="${li.manual_commit ?? li.inventory_commit}" data-field="manual_commit" />
        → ships ${li.committed_quantity} | cut ${li.difference}
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
        <span>${li.on_the_way_quantity}</span>
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
  if (body.released) alert("Released to warehouse.");
}

$("#btn-release").addEventListener("click", submitDraft);
$("#btn-save").addEventListener("click", () => { currentOrder = collectDraft(); renderDraft(currentOrder); });
$("#btn-revise").addEventListener("click", () => { $("#status").textContent = "revise"; });
