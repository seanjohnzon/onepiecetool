const state = {
  sets: [],
  currentSet: null,
  offset: 0,
  limit: DEFAULT_LIMIT,
  total: 0,
  search: "",
};

// All standard OP sets from OP-01 to OP-13, plus PRB (Premium Booster)
const ALL_STANDARD_SETS = [
  "MASTER LIST",
  "OP-01", "OP-02", "OP-03", "OP-04", "OP-05", "OP-06", "OP-07",
  "OP-08", "OP-09", "OP-10", "OP-11", "OP-12", "OP-13", "PRB-01", "PRB-02"
];

async function fetchSets() {
  const res = await fetch("/cards/sets");
  if (!res.ok) {
    document.getElementById("cardsMeta").textContent = "Failed to load sets.";
    return;
  }
  const data = await res.json();
  const dbSets = data.sets || [];
  
  // Combine standard sets with any extra sets from DB (like PRB-01_02)
  const extraSets = dbSets.filter(s => !ALL_STANDARD_SETS.includes(s));
  state.sets = [...ALL_STANDARD_SETS, ...extraSets];
  state.setsWithData = new Set(dbSets); // Track which sets have cards
  
  if (!state.currentSet && state.sets.length) {
    state.currentSet = "MASTER LIST"; // Default to MASTER LIST on load
  }
  renderSetsNav();
  await loadCards(true);
}

function renderSetsNav() {
  const container = document.getElementById("setsNav");
  container.innerHTML = "";
  if (!state.sets.length) {
    container.textContent = "No sets loaded yet.";
    return;
  }
  state.sets.forEach((setCode) => {
    const btn = document.createElement("button");
    // MASTER LIST always has data (shows all cards)
    const hasData = setCode === "MASTER LIST" || (state.setsWithData && state.setsWithData.has(setCode));
    btn.className = `set-pill ${state.currentSet === setCode ? "active" : ""} ${!hasData ? "empty" : ""}`;
    btn.textContent = setCode;
    btn.onclick = () => {
      state.currentSet = setCode;
      state.offset = 0;
      loadCards(true);
      renderSetsNav();
    };
    container.appendChild(btn);
  });
}

async function loadCards(resetOffset = false) {
  if (resetOffset) state.offset = 0;
  const params = new URLSearchParams();
  params.set("limit", state.limit);
  params.set("offset", state.offset);
  // Don't filter by set if viewing MASTER LIST (shows all cards)
  if (state.currentSet && state.currentSet !== "MASTER LIST") {
    params.append("set_codes", state.currentSet);
  }
  const searchVal = document.getElementById("searchTerm").value.trim();
  if (searchVal) params.set("search", searchVal);

  const res = await fetch(`/cards?${params.toString()}`);
  if (!res.ok) {
    document.getElementById("cardsMeta").textContent = "Failed to load cards.";
    return;
  }
  const data = await res.json();
  state.total = data.total;
  renderCards(data.items || []);
  const start = state.total === 0 ? 0 : state.offset + 1;
  const end = Math.min(state.offset + state.limit, state.total);
  document.getElementById("cardsMeta").textContent =
    state.total === 0
      ? "No cards found."
      : `${state.currentSet || "All"} — Showing ${start}-${end} of ${state.total}`;
}

function renderCards(items) {
  const grid = document.getElementById("cardsGrid");
  if (!items.length) {
    grid.innerHTML = `<div class="small" style="grid-column: 1/-1;">No cards in this view.</div>`;
    return;
  }
  grid.innerHTML = items
    .map((item) => {
      const imgSrc = item.image_path || item.image_url || "/static/placeholder-card.svg";
      const valueScoreText =
        typeof item.value_score === "number" ? item.value_score.toFixed(2) : "—";
      const linkHtml = item.market_url
        ? `<a href="${item.market_url}" target="_blank" rel="noreferrer">Listing/Ref</a>`
        : "Links: (add later)";
      // Show Leader toggle button for Alt Art variants
      const variantLower = (item.variant || "").toLowerCase();
      const isAltArt = variantLower.includes("alt art") || variantLower.includes("alternate art");
      const isLeader = variantLower.includes("leader");
      const leaderBtnHtml = isAltArt
        ? `<button class="leader-toggle ${isLeader ? "active" : ""}" data-action="toggle-leader" data-id="${item.id}" data-is-leader="${isLeader}">${isLeader ? "★ Leader" : "Regular"}</button>`
        : "";
      return `
      <div class="card-tile" data-id="${item.id}">
        <div class="card-header">
          <div>
            <div style="font-weight:700;">${item.card_name}</div>
            <div class="small">${item.card_number} · ${item.set_code}</div>
          </div>
          <div class="badge">${item.variant || "Base"}</div>
        </div>
        <div class="img-box">
          <img src="${imgSrc}" alt="Card image placeholder" />
        </div>
        <div class="small">Avg Price: <strong>$${item.price ?? "—"}</strong></div>
        <div class="small">Rarity Score: ${item.rarity_score ?? "—"}</div>
        <div class="small">Value Score: ${valueScoreText}</div>
        <div class="small">Language: ${item.language || "English"}</div>
        <div class="small">Priority: ${item.auto_priority_rank ?? "—"}</div>
        ${leaderBtnHtml}
        <div class="links" style="display:flex; flex-direction:column; gap:6px;">
          <div>${linkHtml}</div>
          <div class="flex" style="gap:6px;">
            <input type="text" data-role="market-link" data-id="${item.id}" value="${item.market_url || ""}" placeholder="Market link" style="flex:1; padding:6px; font-size:12px;">
            <button data-action="sync" data-id="${item.id}">Sync</button>
          </div>
        </div>
        <div class="flex" style="justify-content:flex-end;">
          <button class="secondary" data-action="delete" data-id="${item.id}">Delete</button>
        </div>
      </div>`;
    })
    .join("");
}

async function createCard() {
  const statusEl = document.getElementById("createStatus");
  const payload = {
    set_code: document.getElementById("createSetCode").value.trim(),
    card_name: document.getElementById("createCardName").value.trim(),
    card_number: document.getElementById("createCardNumber").value.trim(),
    variant: document.getElementById("createVariant").value.trim() || null,
    price: document.getElementById("createPrice").value
      ? parseFloat(document.getElementById("createPrice").value)
      : null,
    rarity_score: document.getElementById("createRarity").value
      ? parseFloat(document.getElementById("createRarity").value)
      : null,
    market_url: document.getElementById("createMarketUrl").value.trim() || null,
    priority_manual: document.getElementById("createPriority").value
      ? Number(document.getElementById("createPriority").value)
      : null,
  };
  if (!payload.market_url && (!payload.set_code || !payload.card_name || !payload.card_number)) {
    statusEl.textContent = "Set code, name, and number are required unless a link is provided.";
    return;
  }
  const res = await fetch("/cards", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.ok) {
    statusEl.textContent = "Created.";
    const created = await res.json();
    // Add new set to navigation if not already there
    if (created.set_code && !state.sets.includes(created.set_code)) {
      state.sets.push(created.set_code);
      state.setsWithData = state.setsWithData || new Set();
      state.setsWithData.add(created.set_code);
      renderSetsNav();
    }
    // Mark set as having data
    if (created.set_code && state.setsWithData) {
      state.setsWithData.add(created.set_code);
    }
    const shouldSync = document.getElementById("createSyncLink").checked;
    if (payload.market_url && shouldSync) {
      await syncCard(created.id, payload.market_url);
    } else {
      await loadCards(true);
    }
  } else {
    const data = await res.json();
    statusEl.textContent = data.detail || "Failed to create.";
  }
}

function resetCreateStatusOnInput() {
  const clearStatus = () => {
    const el = document.getElementById("createStatus");
    if (el) el.textContent = "";
  };
  [
    "createSetCode",
    "createCardName",
    "createCardNumber",
    "createVariant",
    "createPrice",
    "createRarity",
    "createPriority",
    "createMarketUrl",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", clearStatus);
  });
}

async function deleteCard(id) {
  const res = await fetch(`/cards/${id}`, { method: "DELETE" });
  if (res.ok) {
    await loadCards();
  }
}

async function syncCard(id, url) {
  const params = new URLSearchParams();
  if (url) params.set("market_url", url);
  const res = await fetch(`/cards/${id}/market-sync${params.toString() ? `?${params.toString()}` : ""}`, {
    method: "POST",
  });
  const statusEl = document.getElementById("cardsMeta");
  if (res.ok) {
    statusEl.textContent = "Synced.";
    await loadCards();
  } else {
    const data = await res.json().catch(() => ({}));
    statusEl.textContent = data.detail || "Sync failed.";
  }
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
  if (res.ok) {
    const data = await res.json();
    status.textContent = `Imported ${data.total} (new ${data.inserted}, updated ${data.updated})`;
    await fetchSets();
  } else {
    status.textContent = "Import failed.";
  }
}

async function backfillScores() {
  const res = await fetch("/cards/backfill-scores", { method: "POST" });
  const status = document.getElementById("importStatus");
  if (res.ok) {
    const data = await res.json();
    status.textContent = `Backfilled scores for ${data.updated} cards.`;
    await loadCards(true);
  } else {
    status.textContent = "Backfill failed.";
  }
}

function wireEvents() {
  document.getElementById("applyFilters").addEventListener("click", () => loadCards(true));
  document.getElementById("resetFilters").addEventListener("click", () => {
    document.getElementById("searchTerm").value = "";
    state.offset = 0;
    loadCards(true);
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
  // Handle Leader button toggle
  document.getElementById("cardsGrid").addEventListener("click", async (event) => {
    if (event.target.dataset.action === "toggle-leader") {
      const id = event.target.dataset.id;
      const isCurrentlyLeader = event.target.dataset.isLeader === "true";
      await toggleLeader(id, !isCurrentlyLeader);
    }
  });
}

async function exportToExcel() {
  // Build URL with current set filter (or all if viewing MASTER LIST)
  let url = "/cards/export";
  if (state.currentSet && state.currentSet !== "MASTER LIST") {
    url += `?set_codes=${encodeURIComponent(state.currentSet)}`;
  }
  
  // Determine filename
  const filename = state.currentSet && state.currentSet !== "MASTER LIST"
    ? `one_piece_tcg_${state.currentSet.toLowerCase().replace("-", "")}.xlsx`
    : "one_piece_tcg_master_list.xlsx";
  
  try {
    const response = await fetch(url);
    const blob = await response.blob();
    
    // Create object URL and download
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);
  } catch (err) {
    console.error("Export failed:", err);
  }
}

async function toggleLeader(id, makeLeader) {
  // First get the current card data
  const res = await fetch(`/cards/${id}`);
  if (!res.ok) return;
  const card = await res.json();
  
  let variant = card.variant || "";
  const variantLower = variant.toLowerCase();
  
  if (makeLeader) {
    // Add Leader if not already present
    if (!variantLower.includes("leader")) {
      // Insert "Leader" after "Alt Art" or "Alternate Art"
      if (variantLower.includes("alternate art")) {
        variant = variant.replace(/alternate art/i, "Alternate Art (Leader)");
      } else if (variantLower.includes("alt art")) {
        variant = variant.replace(/alt art/i, "Alt Art (Leader)");
      }
    }
  } else {
    // Remove Leader
    variant = variant.replace(/\s*\(leader\)/gi, "").replace(/\s*leader/gi, "").trim();
  }
  
  // Update the card
  const updateRes = await fetch(`/cards/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ variant }),
  });
  
  if (updateRes.ok) {
    await loadCards();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  wireEvents();
  resetCreateStatusOnInput();
  fetchSets();
});

