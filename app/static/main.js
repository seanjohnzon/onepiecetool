const state = {
  sets: [],
  currentSet: null,
  offset: 0,
  limit: DEFAULT_LIMIT,
  total: 0,
  search: "",
};

const ALL_STANDARD_SETS = [
  "MASTER LIST",
  "OP-01", "OP-02", "OP-03", "OP-04", "OP-05", "OP-06", "OP-07",
  "OP-08", "OP-09", "OP-10", "OP-11", "OP-12", "OP-13", "PRB-01", "PRB-02"
];

async function fetchSets() {
  const res = await fetch("/cards/sets");
  if (!res.ok) { document.getElementById("cardsMeta").textContent = "Failed to load sets."; return; }
  const data = await res.json();
  const dbSets = data.sets || [];
  const extraSets = dbSets.filter(s => !ALL_STANDARD_SETS.includes(s));
  state.sets = [...ALL_STANDARD_SETS, ...extraSets];
  state.setsWithData = new Set(dbSets);
  if (!state.currentSet && state.sets.length) state.currentSet = "MASTER LIST";
  renderSetsNav();
  await loadCards(true);
}

function renderSetsNav() {
  const container = document.getElementById("setsNav");
  container.innerHTML = "";
  if (!state.sets.length) { container.textContent = "No sets loaded yet."; return; }
  state.sets.forEach((setCode) => {
    const btn = document.createElement("button");
    const hasData = setCode === "MASTER LIST" || (state.setsWithData && state.setsWithData.has(setCode));
    btn.className = `set-pill ${state.currentSet === setCode ? "active" : ""} ${!hasData ? "empty" : ""}`;
    btn.textContent = setCode;
    btn.onclick = () => { state.currentSet = setCode; state.offset = 0; loadCards(true); renderSetsNav(); };
    container.appendChild(btn);
  });
}

async function loadCards(resetOffset = false) {
  if (resetOffset) state.offset = 0;
  const params = new URLSearchParams();
  params.set("limit", state.limit);
  params.set("offset", state.offset);
  if (state.currentSet && state.currentSet !== "MASTER LIST") params.append("set_codes", state.currentSet);
  const searchVal = document.getElementById("searchTerm").value.trim();
  if (searchVal) params.set("search", searchVal);

  const priceMin = document.getElementById("filterPriceMin")?.value?.trim();
  const priceMax = document.getElementById("filterPriceMax")?.value?.trim();
  const rarityMin = document.getElementById("filterRarityMin")?.value?.trim();
  const valueMin = document.getElementById("filterValueMin")?.value?.trim();
  const variantType = document.getElementById("filterVariantType")?.value?.trim();
  const hasImage = document.getElementById("filterHasImage")?.value?.trim();
  const sortBy = document.getElementById("filterSortBy")?.value?.trim();
  const sortOrder = document.getElementById("filterSortOrder")?.value?.trim();

  if (priceMin) params.set("price_min", priceMin);
  if (priceMax) params.set("price_max", priceMax);
  if (rarityMin) params.set("rarity_min", rarityMin);
  if (valueMin) params.set("value_score_min", valueMin);
  if (variantType) params.set("variant_type", variantType);
  if (hasImage) params.set("has_image", hasImage);
  if (sortBy) params.set("sort_by", sortBy);
  if (sortOrder) params.set("sort_order", sortOrder);
  const res = await fetch(`/cards?${params.toString()}`);
  if (!res.ok) { document.getElementById("cardsMeta").textContent = "Failed to load cards."; return; }
  const data = await res.json();
  state.total = data.total;
  renderCards(data.items || []);
  const start = state.total === 0 ? 0 : state.offset + 1;
  const end = Math.min(state.offset + state.limit, state.total);
  document.getElementById("cardsMeta").textContent = state.total === 0 ? "No cards found." : `${state.currentSet || "All"} — Showing ${start}-${end} of ${state.total}`;
}

function renderCards(items) {
  const grid = document.getElementById("cardsGrid");
  if (!items.length) { grid.innerHTML = '<div class="small" style="grid-column: 1/-1;">No cards in this view.</div>'; return; }
  grid.innerHTML = items.map((item) => {
    const imgSrc = item.image_path || item.image_url || "/static/placeholder-card.svg";
    const valueScoreText = typeof item.value_score === "number" ? item.value_score.toFixed(2) : "—";
    const linkHtml = item.market_url ? `<a href="${item.market_url}" target="_blank" rel="noreferrer">Listing/Ref</a>` : "Links: (add later)";
    const variantLower = (item.variant || "").toLowerCase();
    const isAltArt = variantLower.includes("alt art") || variantLower.includes("alternate art");
    const isLeader = variantLower.includes("leader");
    const leaderBtnHtml = isAltArt ? `<button class="leader-toggle ${isLeader ? "active" : ""}" data-action="toggle-leader" data-id="${item.id}" data-is-leader="${isLeader}">${isLeader ? "★ Leader" : "Regular"}</button>` : "";
    return `<div class="card-tile" data-id="${item.id}">
      <div class="card-header"><div><div style="font-weight:700;">${item.card_name}</div><div class="small">${item.card_number} · ${item.set_code}</div></div><div class="badge">${item.variant || "Base"}</div></div>
      <div class="img-box"><img src="${imgSrc}" alt="Card image" /></div>
      <div class="small">Avg Price: <strong>$${item.price ?? "—"}</strong></div>
        <div class="small" style="color:#f5c542; font-weight:600;">🏆 Golden: ${item.golden_ratio_score ? item.golden_ratio_score.toFixed(1) : "—"}</div>
        <div class="small">📦 Supply: ${item.supply_score ? item.supply_score.toFixed(0) : "—"} | 📈 Demand: ${item.demand_score ? item.demand_score.toFixed(0) : "—"}</div>
        <div class="small">Sales/wk: ${item.sales_per_week ? item.sales_per_week.toFixed(1) : "—"} | Listings: ${item.active_listings ?? "—"}</div>
        <div class="small">Rarity: ${item.rarity_score ?? "—"} | Value: ${valueScoreText}</div>
      ${leaderBtnHtml}
      ${item.market_url ? `<div class="links"><a href="${item.market_url}" target="_blank" rel="noreferrer">📈 View on PriceCharting</a></div>` : ""}
    </div>`;
  }).join("");
}

async function createCard() {
  const statusEl = document.getElementById("createStatus");
  const payload = {
    set_code: document.getElementById("createSetCode").value.trim(),
    card_name: document.getElementById("createCardName").value.trim(),
    card_number: document.getElementById("createCardNumber").value.trim(),
    variant: document.getElementById("createVariant").value.trim() || null,
    price: document.getElementById("createPrice").value ? parseFloat(document.getElementById("createPrice").value) : null,
    rarity_score: document.getElementById("createRarity").value ? parseFloat(document.getElementById("createRarity").value) : null,
    market_url: document.getElementById("createMarketUrl").value.trim() || null,
    priority_manual: document.getElementById("createPriority").value ? Number(document.getElementById("createPriority").value) : null,
  };
  if (!payload.market_url && (!payload.set_code || !payload.card_name || !payload.card_number)) { statusEl.textContent = "Set code, name, and number are required unless a link is provided."; return; }
  const res = await fetch("/cards", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (res.ok) {
    statusEl.textContent = "Created.";
    const created = await res.json();
    if (created.set_code && !state.sets.includes(created.set_code)) { state.sets.push(created.set_code); state.setsWithData = state.setsWithData || new Set(); state.setsWithData.add(created.set_code); renderSetsNav(); }
    if (created.set_code && state.setsWithData) state.setsWithData.add(created.set_code);
    const shouldSync = document.getElementById("createSyncLink").checked;
    if (payload.market_url && shouldSync) await syncCard(created.id, payload.market_url); else await loadCards(true);
  } else { const data = await res.json(); statusEl.textContent = data.detail || "Failed to create."; }
}

function resetCreateStatusOnInput() {
  const clearStatus = () => { const el = document.getElementById("createStatus"); if (el) el.textContent = ""; };
  ["createSetCode","createCardName","createCardNumber","createVariant","createPrice","createRarity","createPriority","createMarketUrl"].forEach(id => { const el = document.getElementById(id); if (el) el.addEventListener("input", clearStatus); });
}

async function deleteCard(id) { const res = await fetch(`/cards/${id}`, { method: "DELETE" }); if (res.ok) await loadCards(); }

async function syncCard(id, url) {
  const params = new URLSearchParams();
  if (url) params.set("market_url", url);
  const res = await fetch(`/cards/${id}/market-sync${params.toString() ? "?" + params.toString() : ""}`, { method: "POST" });
  const statusEl = document.getElementById("cardsMeta");
  if (res.ok) { statusEl.textContent = "Synced."; await loadCards(); } else { const data = await res.json().catch(() => ({})); statusEl.textContent = data.detail || "Sync failed."; }
}

async function importExcel() {
  const fileInput = document.getElementById("excelFile");
  const file = fileInput.files[0];
  if (!file) return;
  const sheet = document.getElementById("sheetName").value || "MASTER LIST";
  const formData = new FormData();
  formData.append("file", file);
  formData.append("sheet_name", sheet);
  const res = await fetch("/cards/import/excel", { method: "POST", body: formData });
  const status = document.getElementById("importStatus");
  if (res.ok) { const data = await res.json(); status.textContent = `Imported ${data.total} (new ${data.inserted}, updated ${data.updated})`; await fetchSets(); } else status.textContent = "Import failed.";
}

async function backfillScores() {
  const res = await fetch("/cards/backfill-scores", { method: "POST" });
  const status = document.getElementById("importStatus");
  if (res.ok) { const data = await res.json(); status.textContent = `Backfilled scores for ${data.updated} cards.`; await loadCards(true); } else status.textContent = "Backfill failed.";
}

function wireEvents() {
  document.getElementById("applyFilters").addEventListener("click", () => loadCards(true));
  document.getElementById("resetFilters").addEventListener("click", () => {
    document.getElementById("searchTerm").value = "";
    document.getElementById("filterPriceMin").value = "";
    document.getElementById("filterPriceMax").value = "";
    document.getElementById("filterRarityMin").value = "";
    document.getElementById("filterValueMin").value = "";
    document.getElementById("filterVariantType").value = "";
    document.getElementById("filterHasImage").value = "";
    document.getElementById("filterSortBy").value = "golden_ratio_score";
    document.getElementById("filterSortOrder").value = "desc";
    state.offset = 0;
    loadCards(true);
  });
  document.getElementById("presetHighValue").addEventListener("click", () => {
    applyPreset({ sortBy: "price", sortOrder: "desc" });
  });
  document.getElementById("presetExpensive").addEventListener("click", () => {
    applyPreset({ priceMin: 20 });
  });
  document.getElementById("preset100").addEventListener("click", () => {
    applyPreset({ priceMin: 100 });
  });
  document.getElementById("preset500").addEventListener("click", () => {
    applyPreset({ priceMin: 500 });
  });
  document.getElementById("preset1000").addEventListener("click", () => {
    applyPreset({ priceMin: 1000 });
  });
  document.getElementById("presetTrending").addEventListener("click", () => {
    applyPreset({ sortBy: "trend", sortOrder: "desc" });
  });
  document.getElementById("createCardBtn").addEventListener("click", createCard);
  document.getElementById("importBtn").addEventListener("click", importExcel);
  document.getElementById("backfillBtn").addEventListener("click", backfillScores);
  document.getElementById("exportExcel").addEventListener("click", exportToExcel);
  document.getElementById("prevPage").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    loadCards();
  });
  document.getElementById("nextPage").addEventListener("click", () => {
    if (state.offset + state.limit < state.total) {
      state.offset += state.limit;
      loadCards();
    }
  });
  document.getElementById("cardsGrid").addEventListener("click", async (event) => {
    const action = event.target.dataset.action;
    const id = event.target.dataset.id;
    if (action === "delete") {
      await deleteCard(id);
    }
    if (action === "sync") {
      const input = event.target.closest(".links").querySelector('input[data-role="market-link"]');
      const url = input?.value?.trim();
      await syncCard(id, url);
    }
  });
  document.getElementById("cardsGrid").addEventListener("click", async (event) => {
    if (event.target.dataset.action === "toggle-leader") {
      const id = event.target.dataset.id;
      const isCurrentlyLeader = event.target.dataset.isLeader === "true";
      await toggleLeader(id, !isCurrentlyLeader);
    }
  });
}











function applyPreset({ priceMin = "", priceMax = "", sortBy = null, sortOrder = null }) {
  const minInput = document.getElementById("filterPriceMin");
  const maxInput = document.getElementById("filterPriceMax");
  const sortByInput = document.getElementById("filterSortBy");
  const sortOrderInput = document.getElementById("filterSortOrder");

  if (minInput) minInput.value = priceMin === null ? "" : String(priceMin);
  if (maxInput) maxInput.value = priceMax === null ? "" : String(priceMax);
  if (sortBy && sortByInput) sortByInput.value = sortBy;
  if (sortOrder && sortOrderInput) sortOrderInput.value = sortOrder;

  state.offset = 0;
  loadCards(true);
}
async function exportToExcel() {
  let url = "/cards/export";
  if (state.currentSet && state.currentSet !== "MASTER LIST") url += `?set_codes=${encodeURIComponent(state.currentSet)}`;
  const filename = state.currentSet && state.currentSet !== "MASTER LIST" ? `one_piece_tcg_${state.currentSet.toLowerCase().replace("-", "")}.xlsx` : "one_piece_tcg_master_list.xlsx";
  try { const response = await fetch(url); const blob = await response.blob(); const blobUrl = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = blobUrl; a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(blobUrl); } catch (err) { console.error("Export failed:", err); }
}

async function toggleLeader(id, makeLeader) {
  const res = await fetch(`/cards/${id}`);
  if (!res.ok) return;
  const card = await res.json();
  let variant = card.variant || "";
  const variantLower = variant.toLowerCase();
  if (makeLeader) { if (!variantLower.includes("leader")) { if (variantLower.includes("alternate art")) variant = variant.replace(/alternate art/i, "Alternate Art (Leader)"); else if (variantLower.includes("alt art")) variant = variant.replace(/alt art/i, "Alt Art (Leader)"); }}
  else variant = variant.replace(/\s*\(leader\)/gi, "").replace(/\s*leader/gi, "").trim();
  const updateRes = await fetch(`/cards/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ variant }) });
  if (updateRes.ok) await loadCards();
}

document.addEventListener("DOMContentLoaded", () => {
  wireEvents();
  resetCreateStatusOnInput();
  fetchSets();
  wireSyncEvents();
  wireNavigationEvents();
  wireLotEvents();
  wireLotSearchEvents();
  wireAiChatEvents();
  restoreLotFromSession();
  wireTopFlipsEvents();
});

// SYNC ALL FUNCTIONALITY
let syncInterval = null;
function wireSyncEvents() { const startBtn = document.getElementById("startSyncBtn"); const stopBtn = document.getElementById("stopSyncBtn"); if (startBtn) startBtn.addEventListener("click", startSync); if (stopBtn) stopBtn.addEventListener("click", stopSync); checkSyncStatus(); }
async function startSync() { const statusEl = document.getElementById("syncStatus"); statusEl.textContent = "Starting sync..."; statusEl.style.background = "#fef3c7"; try { const res = await fetch("/cards/sync-all/start", { method: "POST" }); const data = await res.json(); statusEl.textContent = data.status === "already_running" ? "Sync already running..." : "Sync started!"; if (!syncInterval) syncInterval = setInterval(checkSyncStatus, 3000); } catch (err) { statusEl.textContent = "Error: " + err.message; statusEl.style.background = "#fee2e2"; }}
async function stopSync() { const statusEl = document.getElementById("syncStatus"); try { await fetch("/cards/sync-all/stop", { method: "POST" }); statusEl.textContent = "Stopping sync..."; statusEl.style.background = "#fef3c7"; } catch (err) { statusEl.textContent = "Error: " + err.message; }}
async function checkSyncStatus() { const statusEl = document.getElementById("syncStatus"); try { const res = await fetch("/cards/sync-all/status"); const data = await res.json(); if (data.running) { const pct = data.total > 0 ? Math.round((data.synced / data.total) * 100) : 0; statusEl.innerHTML = `<strong>🔄 Syncing:</strong> ${data.synced}/${data.total} (${pct}%)<br><span style="color:#6b7280;">Current: ${data.current_card || "..."}</span>${data.failed > 0 ? '<br><span style="color:#ef4444;">Failed: ' + data.failed + '</span>' : ""}`; statusEl.style.background = "#dbeafe"; if (!syncInterval) syncInterval = setInterval(checkSyncStatus, 3000); } else { if (data.total > 0) { statusEl.innerHTML = `<strong>✅ Complete:</strong> ${data.synced}/${data.total} synced${data.failed > 0 ? '<span style="color:#ef4444;"> (' + data.failed + ' failed)</span>' : ""}`; statusEl.style.background = "#dcfce7"; } else { statusEl.textContent = 'Click "Start Sync" to begin'; statusEl.style.background = "#f3f4f6"; } if (syncInterval) { clearInterval(syncInterval); syncInterval = null; }}} catch {} }

// NAVIGATION
function wireNavigationEvents() { document.querySelectorAll(".nav-btn").forEach(btn => { btn.addEventListener("click", () => switchPage(btn.dataset.page)); }); }
function switchPage(pageName) { document.querySelectorAll(".nav-btn").forEach(btn => { const isActive = btn.dataset.page === pageName; btn.classList.toggle("active", isActive); btn.style.background = isActive ? "var(--op-gold)" : "rgba(15, 23, 41, 0.8)"; btn.style.color = isActive ? "var(--op-navy)" : "var(--op-cream)"; btn.style.borderColor = isActive ? "var(--op-gold)" : "rgba(245, 197, 66, 0.3)"; }); document.querySelectorAll(".page-content").forEach(p => p.style.display = "none"); const target = document.getElementById(`page-${pageName}`); if (target) target.style.display = "block"; }

// WORKING LOT (SESSION-BASED)
// AI + lot logic moved to ai.js
// TOP FLIP OPPORTUNITIES
// =============================================================================

function wireTopFlipsEvents() {
  const refreshBtn = document.getElementById("refreshFlipsBtn");
  const trendSelect = document.getElementById("trendMethod");
  const charSelect = document.getElementById("flipCharacter");
  const variantSelect = document.getElementById("flipVariant");
  const priceMinInput = document.getElementById("flipPriceMin");
  const priceMaxInput = document.getElementById("flipPriceMax");
  
  if (refreshBtn) refreshBtn.addEventListener("click", loadTopFlips);
  if (trendSelect) trendSelect.addEventListener("change", loadTopFlips);
  if (charSelect) charSelect.addEventListener("change", loadTopFlips);
  if (variantSelect) variantSelect.addEventListener("change", loadTopFlips);
  if (priceMinInput) priceMinInput.addEventListener("change", loadTopFlips);
  if (priceMaxInput) priceMaxInput.addEventListener("change", loadTopFlips);
  
  // Quick preset buttons
  document.querySelectorAll(".flip-preset").forEach(btn => {
    btn.addEventListener("click", () => {
      const char = btn.dataset.char || "";
      const variant = btn.dataset.var || "";
      
      if (charSelect) charSelect.value = char;
      if (variantSelect) variantSelect.value = variant;
      
      document.querySelectorAll(".flip-preset").forEach(b => {
        b.style.background = "rgba(15, 23, 41, 0.8)";
        b.style.borderColor = "rgba(245, 197, 66, 0.3)";
      });
      btn.style.background = "var(--op-gold)";
      btn.style.borderColor = "var(--op-gold)";
      
      loadTopFlips();
    });
  });
  
  loadFlipFilterOptions();
  loadTopFlips();
}

async function loadFlipFilterOptions() {
  const charSelect = document.getElementById("flipCharacter");
  if (!charSelect) return;
  
  try {
    const res = await fetch("/cards/filter-options");
    if (!res.ok) return;
    
    const data = await res.json();
    const characters = data.characters || [];
    
    charSelect.innerHTML = '<option value="">All Characters</option>';
    characters.forEach(c => {
      charSelect.innerHTML += '<option value="' + c.value + '">' + c.label + '</option>';
    });
  } catch (err) {
    console.error("Failed to load filter options:", err);
  }
}

async function loadTopFlips() {
  const grid = document.getElementById("topFlipsGrid");
  const trendMethod = document.getElementById("trendMethod")?.value || "sma";
  const character = document.getElementById("flipCharacter")?.value || "";
  const variantType = document.getElementById("flipVariant")?.value || "";
  const priceMin = document.getElementById("flipPriceMin")?.value || "";
  const priceMax = document.getElementById("flipPriceMax")?.value || "";
  
  grid.innerHTML = '<div class="small">Loading top flip opportunities...</div>';
  
  let url = "/cards/top-flips?limit=10&trend_method=" + trendMethod;
  if (character) url += "&character=" + encodeURIComponent(character);
  if (variantType) url += "&variant_type=" + encodeURIComponent(variantType);
  if (priceMin) url += "&price_min=" + encodeURIComponent(priceMin);
  if (priceMax) url += "&price_max=" + encodeURIComponent(priceMax);
  
  try {
    const res = await fetch(url);
    if (!res.ok) {
      grid.innerHTML = '<div class="small" style="color:#ef4444;">Failed to load flip opportunities.</div>';
      return;
    }
    
    const data = await res.json();
    renderTopFlips(data.cards || [], data.filters || {});
  } catch (err) {
    grid.innerHTML = '<div class="small" style="color:#ef4444;">Error: ' + err.message + '</div>';
  }
}

function renderTopFlips(cards, filters = {}) {
  const grid = document.getElementById("topFlipsGrid");
  
  if (!cards.length) {
    grid.innerHTML = '<div class="small" style="grid-column: 1/-1;">No flip opportunities found. Run sync to populate golden ratio scores.</div>';
    return;
  }
  
  grid.innerHTML = cards.map((card, idx) => {
    const imgSrc = card.image_url || "/static/placeholder-card.svg";
    const goldenScore = card.golden_ratio_score ? card.golden_ratio_score.toFixed(1) : (card.flip_score ? card.flip_score.toFixed(1) : "—");
    const supplyScore = card.supply_score ? card.supply_score.toFixed(0) : "—";
    const demandScore = card.demand_score ? card.demand_score.toFixed(0) : "—";
    const salesWk = card.sales_per_week ? card.sales_per_week.toFixed(1) : "—";
    const listings = card.active_listings ?? "—";
    
    return `
    <div class="card-tile" style="border-left: 4px solid ${idx < 3 ? '#22c55e' : 'rgba(245,197,66,0.3)'};">
      <div class="card-header">
        <div>
          <div style="font-weight:700;">#${idx + 1} ${card.card_name}</div>
          <div class="small">${card.variant || "Base"}</div>
        </div>
        <div class="badge" style="background:rgba(245,197,66,0.2); color:#f5c542;">🏆 ${goldenScore}</div>
      </div>
      <div class="img-box" style="min-height:150px;">
        <img src="${imgSrc}" alt="${card.card_name}" />
      </div>
      <div class="small">💰 Price: <strong>$${card.price?.toFixed(2) || "—"}</strong></div>
      <div class="small" style="color:#f5c542; font-weight:600;">📦 Supply: ${supplyScore} | 📈 Demand: ${demandScore}</div>
      <div class="small">Sales/wk: ${salesWk} | Listings: ${listings}</div>
      <div class="small">Rarity: ${card.rarity_score ?? "—"}</div>
      ${card.market_url ? `<div class="links"><a href="${card.market_url}" target="_blank" rel="noreferrer">📈 View on PriceCharting</a></div>` : ""}
    </div>`;
  }).join("");
}
