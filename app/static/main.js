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
      <div class="small">Rarity Score: ${item.rarity_score ?? "—"}</div>
      <div class="small">Value Score: ${valueScoreText}</div>
      <div class="small">Language: ${item.language || "English"}</div>
      <div class="small">Priority: ${item.auto_priority_rank ?? "—"}</div>
      ${leaderBtnHtml}
      <div class="links" style="display:flex;flex-direction:column;gap:6px;"><div>${linkHtml}</div>
        <div class="flex" style="gap:6px;"><input type="text" data-role="market-link" data-id="${item.id}" value="${item.market_url || ""}" placeholder="Market link" style="flex:1;padding:6px;font-size:12px;"><button data-action="sync" data-id="${item.id}">Sync</button></div>
      </div>
      <div class="flex" style="justify-content:flex-end;"><button class="secondary" data-action="delete" data-id="${item.id}">Delete</button></div>
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
  document.getElementById("resetFilters").addEventListener("click", () => { document.getElementById("searchTerm").value = ""; state.offset = 0; loadCards(true); });
  document.getElementById("createCardBtn")?.addEventListener("click", createCard);
  document.getElementById("importBtn")?.addEventListener("click", importExcel);
  document.getElementById("backfillBtn")?.addEventListener("click", backfillScores);
  document.getElementById("exportExcel")?.addEventListener("click", exportToExcel);
  document.getElementById("prevPage").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); loadCards(); });
  document.getElementById("nextPage").addEventListener("click", () => { if (state.offset + state.limit < state.total) { state.offset += state.limit; loadCards(); }});
  document.getElementById("cardsGrid").addEventListener("click", async (event) => {
    const action = event.target.dataset.action;
    const id = event.target.dataset.id;
    if (action === "delete") await deleteCard(id);
    if (action === "sync") { const input = event.target.closest(".links").querySelector('input[data-role="market-link"]'); await syncCard(id, input?.value?.trim()); }
    if (action === "toggle-leader") { const isCurrentlyLeader = event.target.dataset.isLeader === "true"; await toggleLeader(id, !isCurrentlyLeader); }
  });
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
let workingLot = [];
function restoreLotFromSession() { try { const saved = sessionStorage.getItem("workingLot"); if (saved) { workingLot = JSON.parse(saved); renderWorkingLot(); }} catch (e) { console.error("Restore lot error:", e); }}
function saveLotToSession() { try { sessionStorage.setItem("workingLot", JSON.stringify(workingLot)); } catch (e) { console.error("Save lot error:", e); }}
function addCardToLot(card, reason = null) { if (workingLot.find(c => c.id === card.id)) return false; workingLot.push({ ...card, addedAt: Date.now(), reason }); saveLotToSession(); renderWorkingLot(); return true; }
function removeCardFromLot(cardId) { workingLot = workingLot.filter(c => c.id !== cardId); saveLotToSession(); renderWorkingLot(); }
function clearWorkingLot() { workingLot = []; saveLotToSession(); renderWorkingLot(); }

function renderWorkingLot() {
  const grid = document.getElementById("lotCardsGrid");
  const countEl = document.getElementById("lotCount");
  const summaryEl = document.getElementById("lotSummary");
  const copyBtn = document.getElementById("copyLotBtn");
  const saveBtn = document.getElementById("saveLotBtn");
  if (!grid) return;
  if (countEl) countEl.textContent = `(${workingLot.length} cards)`;
  if (workingLot.length === 0) {
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px 20px;color:var(--op-gray);"><div style="font-size:48px;margin-bottom:12px;">📋</div><div style="font-size:16px;margin-bottom:8px;">Your working lot is empty</div><div class="small">Search and add cards above, or ask the AI for recommendations!</div></div>';
    if (summaryEl) summaryEl.style.display = "none";
    if (copyBtn) copyBtn.style.display = "none";
    if (saveBtn) saveBtn.style.display = "none";
    return;
  }
  let totalValue = 0, trendSum = 0, trendCount = 0;
  workingLot.forEach(c => { if (c.price) totalValue += c.price; if (c.trend_score_sma) { trendSum += c.trend_score_sma; trendCount++; }});
  if (summaryEl) { summaryEl.style.display = "block"; document.getElementById("lotTotalValue").textContent = totalValue.toFixed(2); document.getElementById("lotCardCount").textContent = workingLot.length; document.getElementById("lotAvgTrend").textContent = trendCount > 0 ? (trendSum / trendCount).toFixed(1) : "—"; }
  if (copyBtn) copyBtn.style.display = "inline-block";
  if (saveBtn) saveBtn.style.display = "inline-block";
  grid.innerHTML = workingLot.map(card => {
    const imgSrc = card.image_path || card.image_url || "/static/placeholder-card.svg";
    const trendClass = card.trend_score_sma > 0 ? "positive" : card.trend_score_sma < 0 ? "negative" : "";
    const trendText = card.trend_score_sma ? `${card.trend_score_sma > 0 ? "+" : ""}${card.trend_score_sma.toFixed(1)}%` : "—";
    return `<div class="lot-card-tile" data-card-id="${card.id}"><button class="remove-btn" data-action="remove-from-lot" data-id="${card.id}">✕</button><div class="img-box"><img src="${imgSrc}" alt="${card.card_name}" onerror="this.src='/static/placeholder-card.svg'"></div><div class="card-info"><div class="card-name" title="${card.card_name}">${card.card_name}</div><div class="card-details">${card.card_number || ""} · ${card.variant || "Base"}</div><div class="card-price">$${card.price?.toFixed(2) || "—"}</div><div class="card-trend ${trendClass}">📊 ${trendText}</div>${card.reason ? '<div class="card-reason">' + card.reason + '</div>' : ""}</div></div>`;
  }).join("");
}

function wireLotEvents() {
  document.getElementById("clearLotBtn")?.addEventListener("click", () => { if (workingLot.length === 0 || confirm("Clear all cards?")) clearWorkingLot(); });
  document.getElementById("lotCardsGrid")?.addEventListener("click", e => { if (e.target.dataset.action === "remove-from-lot") removeCardFromLot(parseInt(e.target.dataset.id)); });
  document.getElementById("analyzeLotBtn")?.addEventListener("click", analyzeLot);
  document.getElementById("copyLotBtn")?.addEventListener("click", copyLotToClipboard);
}

async function analyzeLot() {
  if (workingLot.length === 0) { alert("Add some cards first!"); return; }
  const desc = workingLot.map(c => `- ${c.card_name} ${c.card_number||""} [${c.variant||"Base"}] - $${c.price?.toFixed(2)||"?"}`).join("\\n");
  const total = workingLot.reduce((s, c) => s + (c.price || 0), 0).toFixed(2);
  await sendAiMessage(`Analyze this lot:\\n\\n${desc}\\n\\nTotal: $${total}\\n\\nAre these good buys? What should I offer?`);
}

function copyLotToClipboard() {
  if (workingLot.length === 0) return;
  const text = workingLot.map(c => `${c.card_name} ${c.card_number||""} [${c.variant||"Base"}] - $${c.price?.toFixed(2)||"?"}`).join("\\n");
  const total = workingLot.reduce((s, c) => s + (c.price || 0), 0);
  navigator.clipboard.writeText(`Working Lot (${workingLot.length} cards)\\n==============================\\n${text}\\n==============================\\nTotal: $${total.toFixed(2)}`);
  const btn = document.getElementById("copyLotBtn");
  if (btn) { const orig = btn.textContent; btn.textContent = "✅ Copied!"; setTimeout(() => btn.textContent = orig, 2000); }
}

// LOT CARD SEARCH
function wireLotSearchEvents() {
  const searchInput = document.getElementById("lotSearchInput");
  const searchBtn = document.getElementById("lotSearchBtn");
  const resultsEl = document.getElementById("lotSearchResults");
  if (!searchInput || !searchBtn || !resultsEl) return;
  searchBtn.addEventListener("click", searchCardsForLot);
  searchInput.addEventListener("keypress", e => { if (e.key === "Enter") searchCardsForLot(); });
  document.addEventListener("click", e => { if (!searchInput.contains(e.target) && !resultsEl.contains(e.target) && !searchBtn.contains(e.target)) resultsEl.style.display = "none"; });
}

async function searchCardsForLot() {
  const input = document.getElementById("lotSearchInput");
  const results = document.getElementById("lotSearchResults");
  const q = input.value.trim();
  if (!q) return;
  results.innerHTML = '<div class="small" style="padding:10px;color:var(--op-gray);">Searching...</div>';
  results.style.display = "block";
  try {
    const res = await fetch(`/cards?search=${encodeURIComponent(q)}&limit=10`);
    const data = await res.json();
    const items = data.items || [];
    if (!items.length) { results.innerHTML = '<div class="small" style="padding:10px;">No cards found.</div>'; return; }
    results.innerHTML = items.map(card => {
      const img = card.image_path || card.image_url || "/static/placeholder-card.svg";
      const inLot = workingLot.find(c => c.id === card.id);
      const cardJson = JSON.stringify(card).replace(/'/g, "&#39;");
      return `<div class="search-result-item"><img src="${img}" onerror="this.src='/static/placeholder-card.svg'"><div class="info"><div class="name">${card.card_name}</div><div class="details">${card.card_number||""} · ${card.variant||"Base"}</div></div><div class="price">$${card.price?.toFixed(2)||"—"}</div><button class="add-btn" data-card='${cardJson}' ${inLot?"disabled style='opacity:.5'":""}>${inLot?"✓":"+ Add"}</button></div>`;
    }).join("");
    results.querySelectorAll(".add-btn").forEach(btn => { btn.addEventListener("click", e => { e.stopPropagation(); if (addCardToLot(JSON.parse(btn.dataset.card))) { btn.textContent = "✓"; btn.disabled = true; btn.style.opacity = ".5"; }}); });
  } catch (err) { results.innerHTML = `<div class="small" style="padding:10px;color:#ef4444;">Error: ${err.message}</div>`; }
}

// AI CHAT
let chatHistory = [];
function wireAiChatEvents() {
  const sendBtn = document.getElementById("aiChatSend");
  const input = document.getElementById("aiChatInput");
  sendBtn?.addEventListener("click", () => { const q = input.value.trim(); if (q) sendAiMessage(q); });
  input?.addEventListener("keypress", e => { if (e.key === "Enter") { const q = input.value.trim(); if (q) sendAiMessage(q); }});
  document.querySelectorAll(".ai-quick-btn").forEach(btn => { btn.addEventListener("click", () => { if (btn.dataset.query) sendAiMessage(btn.dataset.query); }); });
}

async function sendAiMessage(query) {
  const msgs = document.getElementById("aiChatMessages");
  const input = document.getElementById("aiChatInput");
  const loading = document.getElementById("aiChatLoading");
  if (!msgs) return;
  if (input) input.value = "";
  msgs.innerHTML += `<div class="ai-message user" style="background:linear-gradient(135deg,rgba(15,23,41,.8),rgba(26,39,68,.8));border-left:3px solid var(--op-cream);padding:10px 12px;border-radius:0 8px 8px 0;margin-bottom:8px;"><strong style="color:var(--op-cream);">👤 You:</strong> <span style="color:var(--op-gray);">${escapeHtml(query)}</span></div>`;
  msgs.scrollTop = msgs.scrollHeight;
  if (loading) loading.style.display = "block";
  try {
    const form = new FormData();
    form.append("query", query);
    form.append("history", JSON.stringify(chatHistory));
    if (workingLot.length) form.append("lot_context", workingLot.map(c => `${c.card_name} [${c.variant||"Base"}] $${c.price?.toFixed(2)||"?"}`).join(", "));
    const res = await fetch("/cards/ai/chat", { method: "POST", body: form });
    if (!res.ok) throw new Error((await res.json().catch(()=>({}))).detail || "AI request failed");
    const data = await res.json();
    const response = data.response || "No response.";
    chatHistory.push({ role: "user", content: query }, { role: "assistant", content: response });
    if (chatHistory.length > 20) chatHistory = chatHistory.slice(-20);
    msgs.innerHTML += `<div class="ai-message assistant" style="background:linear-gradient(135deg,rgba(212,175,55,.2),rgba(212,175,55,.1));border-left:3px solid var(--op-gold);padding:10px 12px;border-radius:0 8px 8px 0;margin-bottom:8px;"><strong style="color:var(--op-gold);">🤖 Claude:</strong> <span style="color:var(--op-cream);">${formatAiResponse(response)}</span>${data.suggested_cards?.length ? renderSuggestedCards(data.suggested_cards) : ""}</div>`;
    if (data.suggested_cards?.length) wireSuggestedCardButtons();
  } catch (err) {
    msgs.innerHTML += `<div class="ai-message" style="background:rgba(220,38,38,.2);border-left:3px solid #ef4444;padding:10px 12px;border-radius:0 8px 8px 0;margin-bottom:8px;"><strong style="color:#ef4444;">❌ Error:</strong> <span style="color:var(--op-cream);">${escapeHtml(err.message)}</span></div>`;
  } finally { if (loading) loading.style.display = "none"; msgs.scrollTop = msgs.scrollHeight; }
}

function formatAiResponse(t) { return escapeHtml(t).replace(/\*\*(.*?)\*\*/g,"<strong>$1</strong>").replace(/\\n/g,"<br>"); }
function escapeHtml(t) { const d = document.createElement("div"); d.textContent = t; return d.innerHTML; }

function renderSuggestedCards(cards) {
  if (!cards?.length) return "";
  return `<div class="ai-suggested-cards"><span class="small" style="color:var(--op-gold);">Suggested:</span>${cards.map(c => { const cardJson = JSON.stringify(c).replace(/'/g, "&#39;"); return '<button class="ai-card-btn" data-card=\'' + cardJson + '\' style="background:rgba(245,197,66,.2);border:1px solid var(--op-gold);border-radius:4px;padding:4px 8px;font-size:12px;color:var(--op-cream);cursor:pointer;">' + c.card_name + ' ' + (c.card_number||"") + '</button>'; }).join("")}<button class="ai-add-all-btn" data-cards='${JSON.stringify(cards).replace(/'/g, "&#39;")}'>+ Add All</button></div>`;
}

function wireSuggestedCardButtons() {
  document.querySelectorAll(".ai-card-btn:not([data-wired])").forEach(btn => { btn.dataset.wired = "1"; btn.addEventListener("click", async () => { const c = JSON.parse(btn.dataset.card); const card = c.id ? c : await findCardByInfo(c); if (card && addCardToLot(card, "AI suggested")) { btn.textContent = "✓"; btn.style.opacity = ".5"; }}); });
  document.querySelectorAll(".ai-add-all-btn:not([data-wired])").forEach(btn => { btn.dataset.wired = "1"; btn.addEventListener("click", async () => { let n = 0; for (const c of JSON.parse(btn.dataset.cards)) { const card = c.id ? c : await findCardByInfo(c); if (card && addCardToLot(card, "AI suggested")) n++; } btn.textContent = `✓ Added ${n}`; btn.disabled = true; }); });
}

async function findCardByInfo(info) {
  const q = info.card_number || info.card_name;
  if (!q) return null;
  try { const res = await fetch(`/cards?search=${encodeURIComponent(q)}&limit=5`); const data = await res.json(); return data.items?.find(c => c.card_number === info.card_number || c.card_name?.toLowerCase() === info.card_name?.toLowerCase()) || data.items?.[0]; } catch { return null; }
}


// =============================================================================
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
    grid.innerHTML = '<div class="small" style="grid-column: 1/-1;">No flip opportunities found. Make sure flip scores are calculated.</div>';
    return;
  }
  
  grid.innerHTML = cards.map((card, idx) => {
    const imgSrc = card.image_url || "/static/placeholder-card.svg";
    const hasTrend = card.sma_30 || card.ema_30;
    const trendLabel = hasTrend ? "w/ Trend" : "Static";
    
    return `
    <div class="card-tile" style="border-left: 4px solid ${idx < 3 ? '#22c55e' : 'rgba(245,197,66,0.3)'};">
      <div class="card-header">
        <div>
          <div style="font-weight:700;">#${idx + 1} ${card.card_name}</div>
          <div class="small">${card.variant || "Base"}</div>
        </div>
        <div class="badge" style="background:rgba(34,197,94,0.2); color:#22c55e;">Score: ${card.total_score?.toFixed(1) || card.flip_score?.toFixed(1) || "—"}</div>
      </div>
      <div class="img-box" style="min-height:150px;">
        <img src="${imgSrc}" alt="${card.card_name}" />
      </div>
      <div class="small">💰 Price: <strong>$${card.price?.toFixed(2) || "—"}</strong></div>
      <div class="small">📈 Flip Score: ${card.flip_score?.toFixed(1) || "—"} (${trendLabel})</div>
      ${card.sma_30 ? `<div class="small">📊 SMA(30): $${card.sma_30.toFixed(2)} | Trend: ${card.trend_score_sma?.toFixed(1) || "—"}</div>` : ""}
      ${card.ema_30 ? `<div class="small">📊 EMA(30): $${card.ema_30.toFixed(2)} | Trend: ${card.trend_score_ema?.toFixed(1) || "—"}</div>` : ""}
      ${card.market_url ? `<div class="links"><a href="${card.market_url}" target="_blank" rel="noreferrer">📈 View on PriceCharting</a></div>` : ""}
    </div>`;
  }).join("");
}
