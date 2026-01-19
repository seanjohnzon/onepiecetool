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
  document.getElementById("saveLotBtn")?.addEventListener("click", showSaveLotModal);
}

function showSaveLotModal() {
  if (workingLot.length === 0) { alert("Add cards to your lot first!"); return; }
  const name = prompt("Enter a name for this lot:", "My Lot " + new Date().toLocaleDateString());
  if (!name) return;
  saveLot(name);
}

async function saveLot(name) {
  const cardIds = workingLot.map(c => c.id);
  const btn = document.getElementById("saveLotBtn");
  if (btn) btn.textContent = "Saving...";
  try {
    const res = await fetch("/cards/saved-lots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, card_ids: cardIds })
    });
    if (res.ok) {
      alert("Lot saved!");
      if (btn) btn.textContent = "💾 Save Lot...";
    } else {
      const err = await res.json();
      alert("Error: " + (err.detail || "Unknown"));
      if (btn) btn.textContent = "💾 Save Lot...";
    }
  } catch (e) {
    alert("Error: " + e.message);
    if (btn) btn.textContent = "💾 Save Lot...";
  }
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
    const res = await fetch(`/cards?search=${encodeURIComponent(q)}&limit=100`);
    const data = await res.json();
    const items = data.items || [];
    const total = data.total || items.length;
    if (!items.length) { results.innerHTML = '<div class="small" style="padding:10px;">No cards found.</div>'; return; }
    const header = `<div style="padding:8px 12px;background:rgba(245,197,66,0.15);border-bottom:1px solid rgba(245,197,66,0.3);font-size:13px;color:var(--op-gold);font-weight:600;">📦 Found ${total} cards for "${q}"</div>`;
    const cardsList = items.map(card => {
      const img = card.image_path || card.image_url || "/static/placeholder-card.svg";
      const inLot = workingLot.find(c => c.id === card.id);
      const cardJson = JSON.stringify(card).replace(/'/g, "&#39;");
      return `<div class="search-result-item"><img src="${img}" onerror="this.src='/static/placeholder-card.svg'"><div class="info"><div class="name">${card.card_name}</div><div class="details">${card.card_number||""} · ${card.variant||"Base"}</div></div><div class="price">$${card.price?.toFixed(2)||"—"}</div><button class="add-btn" data-card='${cardJson}' ${inLot?"disabled style='opacity:.5'":""}>${inLot?"✓":"+ Add"}</button></div>`;
    }).join("");
    results.innerHTML = header + `<div style="max-height:350px;overflow-y:auto;">${cardsList}</div>`;
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
    const lotContext = workingLot.length ? workingLot.map(c => `${c.card_name} [${c.variant||"Base"}] $${c.price?.toFixed(2)||"?"}`).join(", ") : "";
    const fullMessage = lotContext ? `[User has these cards in lot: ${lotContext}]\n\n${query}` : query;
    const res = await fetch("/cards/ai/chat", { 
      method: "POST", 
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: fullMessage, conversation_history: chatHistory })
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || errData.error || "AI request failed");
    }
    const data = await res.json();
    const response = data.response || data.error || "No response from AI.";
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
  if (!cards || cards.length === 0) return "";
  let html = '<div style="margin-top:16px;padding:12px;background:rgba(0,0,0,0.3);border-radius:8px;border:1px solid var(--op-gold);">';
  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">';
  html += '<span style="font-weight:600;color:var(--op-gold);">📦 Add to Lot (' + cards.length + ' cards)</span>';
  html += '<button class="ai-add-all-btn" data-cards=\'' + JSON.stringify(cards).replace(/'/g,"&#39;") + '\' style="padding:6px 12px;background:var(--op-gold);border:none;border-radius:4px;color:var(--op-navy);font-weight:600;cursor:pointer;">+ Add All</button>';
  html += '</div>';
  html += '<div style="display:flex;gap:8px;overflow-x:auto;padding-bottom:8px;">';
  for (const c of cards) {
    const cj = JSON.stringify(c).replace(/'/g,"&#39;");
    html += '<div style="flex-shrink:0;width:120px;background:rgba(15,23,41,0.9);border:1px solid rgba(245,197,66,0.3);border-radius:8px;padding:8px;text-align:center;">';
    html += '<div style="font-size:11px;font-weight:600;color:var(--op-cream);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + c.card_name + '</div>';
    html += '<div style="font-size:10px;color:var(--op-gray);">' + (c.card_number || "") + '</div>';
    html += '<div style="font-size:14px;font-weight:700;color:var(--op-gold);margin:6px 0;">$' + (c.price ? c.price.toFixed(2) : "?") + '</div>';
    html += '<button class="ai-card-btn" data-card=\'' + cj + '\' style="width:100%;padding:5px;background:#22c55e;border:none;border-radius:4px;color:white;font-size:10px;font-weight:600;cursor:pointer;">+ Add</button>';
    html += '</div>';
  }
  html += '</div></div>';
  return html;
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
