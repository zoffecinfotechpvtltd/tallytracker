(() => {
  "use strict";

  const API = "";
  const POLL_MS = 30000;
  const PAGE_SIZE = 50;

  const state = {
    entities: [],
    entitiesPage: { page: 1, pageSize: PAGE_SIZE, total: 0 },
    stock: [],
    stockPage: { page: 1, pageSize: PAGE_SIZE, total: 0 },
    typeFilter: "",
    search: "",
    sort: { column: "name", dir: "asc" },
    lowStockOnly: false,
    detailChart: null,
    activeTab: "entities",
    overviewData: null,
    followupStatus: "pending",
    openEntityId: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const fmtMoney = (v) => "₹" + Number(v || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtNum = (v) => Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 });

  function relativeTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const diffMs = Date.now() - d.getTime();
    const mins = Math.round(diffMs / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins} min ago`;
    const hours = Math.round(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.round(hours / 24);
    return `${days}d ago`;
  }

  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  async function fetchJSON(url, opts) {
    const res = await fetch(API + url, opts);
    if (!res.ok) throw new Error(`${url} -> ${res.status}`);
    return res.json();
  }

  const DEFAULT_COMPANY_SUBTITLE = "Precision in every entry. Confidence in every balance.";

  function applySyncEnvelope(envelope) {
    const offline = !envelope.tally_reachable;
    $("#sync-dot").classList.toggle("offline", offline);
    $("#sync-text").textContent = offline
      ? `Offline — last synced ${relativeTime(envelope.last_synced_at)}`
      : `Synced ${relativeTime(envelope.last_synced_at)}`;

    const company = envelope.company_name;
    $("#company-name").textContent =
      company && company !== "Your Company Name" ? company : DEFAULT_COMPANY_SUBTITLE;

    const banner = $("#offline-banner");
    if (offline) {
      banner.classList.remove("hidden");
      $("#offline-since").textContent = envelope.last_synced_at
        ? new Date(envelope.last_synced_at).toLocaleString()
        : "unknown";
    } else {
      banner.classList.add("hidden");
    }
  }

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // ---------------- Overview ----------------

  async function loadOverview() {
    const envelope = await fetchJSON("/api/overview");
    applySyncEnvelope(envelope);
    state.overviewData = envelope.data;
    renderOverviewTiles();
  }

  function renderOverviewTiles() {
    const d = state.overviewData;
    if (!d) return;
    $("#tile-receivables").textContent = fmtMoney(d.total_receivables);
    $("#tile-payables").textContent = fmtMoney(d.total_payables);
    const net = $("#tile-net");
    net.textContent = fmtMoney(d.net_position);
    net.className = "tile-value " + (d.net_position >= 0 ? "debit" : "credit");
    $("#tile-overdue").textContent = d.overdue_entity_count;
  }

  // ---------------- Entities ----------------

  async function loadEntities() {
    const params = new URLSearchParams();
    if (state.typeFilter) params.set("type", state.typeFilter);
    if (state.search) params.set("search", state.search);
    params.set("sort", state.sort.column === "balance" ? "balance_desc" : "name_asc");
    params.set("page", String(state.entitiesPage.page));
    params.set("page_size", String(state.entitiesPage.pageSize));
    const envelope = await fetchJSON("/api/entities?" + params.toString());
    applySyncEnvelope(envelope);
    state.entities = envelope.data;
    state.entitiesPage.total = envelope.total ?? envelope.data.length;
    renderEntities();
    renderPager("entities", state.entitiesPage);
  }

  function renderEntities() {
    const tbody = $("#entities-tbody");
    tbody.innerHTML = "";
    if (state.entities.length === 0) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="6">No entities match.</td></tr>`;
      return;
    }
    for (const r of state.entities) {
      const tr = document.createElement("tr");
      tr.className = "clickable" + (r.overdue_bill_count > 0 ? " row-overdue" : "");
      tr.dataset.id = r.id;
      tr.innerHTML = `
        <td class="truncate" title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</td>
        <td>${r.type ? escapeHtml(r.type) : "—"}</td>
        <td class="num">${fmtMoney(r.current_balance)} <span class="pill ${r.balance_type === "Cr" ? "cr" : "dr"}">${r.balance_type || "-"}</span></td>
        <td class="num">${r.open_bill_count}</td>
        <td class="num">${r.overdue_bill_count}</td>
        <td>${relativeTime(r.last_changed_at)}</td>
      `;
      tr.addEventListener("click", () => openEntityDetail(r.id));
      tbody.appendChild(tr);
    }
  }

  // ---------------- Stock ----------------

  async function loadStock() {
    const params = new URLSearchParams();
    if (state.lowStockOnly) params.set("low_stock_only", "true");
    params.set("page", String(state.stockPage.page));
    params.set("page_size", String(state.stockPage.pageSize));
    const envelope = await fetchJSON("/api/stock?" + params.toString());
    applySyncEnvelope(envelope);
    state.stock = envelope.data;
    state.stockPage.total = envelope.total ?? envelope.data.length;
    renderStock();
    renderPager("stock", state.stockPage);
  }

  function renderStock() {
    const tbody = $("#stock-tbody");
    tbody.innerHTML = "";
    if (state.stock.length === 0) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="4">No stock items.</td></tr>`;
      return;
    }
    for (const item of state.stock) {
      const tr = document.createElement("tr");
      if (item.low_stock) tr.className = "row-low-stock";
      tr.innerHTML = `
        <td class="truncate" title="${escapeHtml(item.item_name)}">${escapeHtml(item.item_name)}</td>
        <td class="num">${fmtNum(item.qty)}</td>
        <td>${escapeHtml(item.unit || "")}</td>
        <td class="num">${fmtMoney(item.value)}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  // ---------------- Pagination (shared) ----------------

  function renderPager(kind, pageState) {
    const totalPages = Math.max(1, Math.ceil(pageState.total / pageState.pageSize));
    const wrap = $(`#${kind}-pager`);
    wrap.querySelector('[data-action="prev"]').disabled = pageState.page <= 1;
    wrap.querySelector('[data-action="next"]').disabled = pageState.page >= totalPages;
    $(`#${kind}-pager-info`).textContent = `Page ${pageState.page} of ${totalPages} (${pageState.total})`;
  }

  // ---------------- Tabs ----------------

  function switchTab(tab) {
    state.activeTab = tab;
    document.querySelectorAll(".tab-btn").forEach((b) => {
      const isActive = b.dataset.tab === tab;
      b.classList.toggle("active", isActive);
      b.setAttribute("aria-selected", String(isActive));
    });
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.classList.toggle("hidden", p.dataset.tabPanel !== tab);
    });
  }

  // ---------------- Changes ----------------

  async function loadChanges() {
    const envelope = await fetchJSON("/api/changes?limit=50");
    applySyncEnvelope(envelope);
    const list = $("#changes-list");
    list.innerHTML = "";
    if (envelope.data.length === 0) {
      list.innerHTML = `<li class="empty-row">No changes yet.</li>`;
      return;
    }
    for (const c of envelope.data) {
      const li = document.createElement("li");
      li.innerHTML = `<span class="change-msg">${escapeHtml(c.message)}</span><span class="change-time">${relativeTime(c.detected_at)}</span>`;
      list.appendChild(li);
    }
  }

  // ---------------- Entity detail ----------------

  async function openEntityDetail(id) {
    state.openEntityId = id;
    const envelope = await fetchJSON(`/api/entities/${id}`);
    if (state.openEntityId !== id) return; // user moved on before this resolved
    applySyncEnvelope(envelope);
    const { entity, bills, balance_history, followups } = envelope.data;

    $("#detail-name").textContent = entity.name;
    $("#detail-balance").innerHTML = `${fmtMoney(entity.current_balance)} <span class="pill ${entity.balance_type === "Cr" ? "cr" : "dr"}">${entity.balance_type || "-"}</span>`;

    const billsBody = $("#detail-bills-tbody");
    billsBody.innerHTML = bills.length
      ? bills.map((b) => `
        <tr class="${b.status === "overdue" ? "row-overdue" : ""}">
          <td>${escapeHtml(b.bill_ref)}</td>
          <td>${b.bill_date || "—"}</td>
          <td>${b.due_date || "—"}</td>
          <td class="num">${fmtMoney(b.amount_outstanding)}</td>
          <td><span class="status-badge ${b.status}">${b.status}</span></td>
        </tr>`).join("")
      : `<tr class="empty-row"><td colspan="5">No bills.</td></tr>`;

    renderDetailChart(balance_history);

    const fuList = $("#detail-followups");
    fuList.innerHTML = followups.length
      ? followups.map((f) => `
        <li><span class="fu-status">${f.status}</span>${escapeHtml(f.note)}<span class="fu-time">${relativeTime(f.created_at)}</span></li>`).join("")
      : `<li class="empty-row">No followups yet.</li>`;

    resetFollowupStatus();
    $("#followup-form").dataset.entityId = id;
    $("#entity-detail-overlay").classList.remove("hidden");

    loadEntityVouchers(id);
  }

  async function loadEntityVouchers(id) {
    const tbody = $("#detail-vouchers-tbody");
    tbody.innerHTML = `<tr class="empty-row"><td colspan="5">Loading…</td></tr>`;
    try {
      const envelope = await fetchJSON(`/api/entities/${id}/vouchers`);
      if (state.openEntityId !== id) return;
      if (!envelope.tally_reachable) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="5">Tally offline — can't load transactions right now.</td></tr>`;
        return;
      }
      const vouchers = envelope.data;
      tbody.innerHTML = vouchers.length
        ? vouchers.map((v) => `
          <tr>
            <td>${v.date || "—"}</td>
            <td>${escapeHtml(v.voucher_type)}</td>
            <td>${escapeHtml(v.voucher_number)}</td>
            <td class="num">${fmtMoney(v.amount)}</td>
            <td class="truncate" title="${escapeHtml(v.narration)}">${escapeHtml(v.narration)}</td>
          </tr>`).join("")
        : `<tr class="empty-row"><td colspan="5">No transactions found.</td></tr>`;
    } catch (e) {
      if (state.openEntityId !== id) return;
      tbody.innerHTML = `<tr class="empty-row"><td colspan="5">Couldn't load transactions.</td></tr>`;
    }
  }

  function renderDetailChart(history) {
    const canvas = $("#detail-chart");
    if (state.detailChart) { state.detailChart.destroy(); state.detailChart = null; }
    if (!window.Chart || history.length === 0) return;
    state.detailChart = new Chart(canvas, {
      type: "line",
      data: {
        labels: history.map((h) => new Date(h.taken_at).toLocaleDateString()),
        datasets: [{
          label: "Balance",
          data: history.map((h) => h.balance),
          borderColor: "#a3352b",
          backgroundColor: "rgba(163,53,43,0.08)",
          tension: 0.15,
          pointRadius: 2,
          fill: true,
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true } },
      },
    });
  }

  function closeEntityDetail() {
    state.openEntityId = null;
    $("#entity-detail-overlay").classList.add("hidden");
  }

  // ---------------- Followup status (custom, no native <select>) ----------------

  function resetFollowupStatus() {
    state.followupStatus = "pending";
    document.querySelectorAll("#followup-status-seg .seg-btn").forEach((b) => {
      const active = b.dataset.status === "pending";
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", String(active));
    });
  }

  async function submitFollowup(e) {
    e.preventDefault();
    const entityId = $("#followup-form").dataset.entityId;
    const note = $("#followup-note").value.trim();
    const status = state.followupStatus;
    if (!note) return;
    const created = await fetchJSON(`/api/entities/${entityId}/followup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note, status }),
    });
    const fuList = $("#detail-followups");
    if (fuList.querySelector(".empty-row")) fuList.innerHTML = "";
    const li = document.createElement("li");
    li.innerHTML = `<span class="fu-status">${created.status}</span>${escapeHtml(created.note)}<span class="fu-time">just now</span>`;
    fuList.prepend(li);
    $("#followup-note").value = "";
  }

  // ---------------- Refresh / polling ----------------

  async function pollAll() {
    await Promise.all([loadOverview(), loadEntities(), loadStock(), loadChanges()]);
  }

  async function refreshNow() {
    const btn = $("#refresh-btn");
    btn.disabled = true;
    $("#refresh-label").textContent = "Syncing…";
    try {
      await fetchJSON("/api/refresh", { method: "POST" });
      await pollAll();
    } catch (e) {
      console.error("refresh failed", e);
    } finally {
      btn.disabled = false;
      $("#refresh-label").textContent = "Refresh now";
    }
  }

  // ---------------- Wiring ----------------

  function wireEvents() {
    $("#refresh-btn").addEventListener("click", refreshNow);

    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });

    const debouncedSearch = debounce(() => {
      state.entitiesPage.page = 1;
      loadEntities();
    }, 300);
    $("#entity-search").addEventListener("input", (e) => {
      state.search = e.target.value;
      debouncedSearch();
    });

    document.querySelectorAll("#type-filter .seg-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#type-filter .seg-btn").forEach((b) => {
          b.classList.remove("active");
          b.setAttribute("aria-selected", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-selected", "true");
        state.typeFilter = btn.dataset.type;
        state.entitiesPage.page = 1;
        loadEntities();
      });
    });

    document.querySelectorAll("#entities-table thead th[data-sort]").forEach((th) => {
      th.addEventListener("click", () => {
        const column = th.dataset.sort;
        if (state.sort.column === column) {
          state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
        } else {
          state.sort = { column, dir: "asc" };
        }
        document.querySelectorAll("#entities-table thead th").forEach((h) => h.classList.remove("sorted", "asc"));
        th.classList.add("sorted");
        if (state.sort.dir === "asc") th.classList.add("asc");
        state.entitiesPage.page = 1;
        loadEntities();
      });
    });

    $("#entities-pager").addEventListener("click", (e) => {
      const btn = e.target.closest(".pager-btn");
      if (!btn || btn.disabled) return;
      state.entitiesPage.page += btn.dataset.action === "next" ? 1 : -1;
      loadEntities();
    });

    $("#stock-pager").addEventListener("click", (e) => {
      const btn = e.target.closest(".pager-btn");
      if (!btn || btn.disabled) return;
      state.stockPage.page += btn.dataset.action === "next" ? 1 : -1;
      loadStock();
    });

    $("#low-stock-toggle").addEventListener("change", (e) => {
      state.lowStockOnly = e.target.checked;
      state.stockPage.page = 1;
      loadStock();
    });

    $("#detail-close").addEventListener("click", closeEntityDetail);
    $("#detail-scrim").addEventListener("click", closeEntityDetail);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeEntityDetail();
    });

    document.querySelectorAll("#followup-status-seg .seg-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#followup-status-seg .seg-btn").forEach((b) => {
          b.classList.remove("active");
          b.setAttribute("aria-selected", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-selected", "true");
        state.followupStatus = btn.dataset.status;
      });
    });

    $("#followup-form").addEventListener("submit", submitFollowup);
  }

  async function init() {
    wireEvents();
    await pollAll();
    setInterval(pollAll, POLL_MS);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
