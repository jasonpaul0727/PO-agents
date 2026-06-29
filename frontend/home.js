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
