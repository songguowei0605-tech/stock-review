(() => {
  const $ = (id) => document.getElementById(id);
  const elements = {
    tradeDate: $("trade-date"), dataState: $("data-state"), modelCount: $("model-count"),
    stockCount: $("stock-count"), topSector: $("top-sector"), topSectorCount: $("top-sector-count"),
    topConcept: $("top-concept"), topConceptCount: $("top-concept-count"), statusText: $("status-text"),
    latestLink: $("latest-link"), loading: $("loading"), error: $("load-error"),
    stockList: $("stock-list"), resultCount: $("result-count"), search: $("stock-search"),
    stockEmpty: $("stock-empty"), industryList: $("industry-list"), conceptList: $("concept-list"),
    historyList: $("history-list"), generatedAt: $("generated-at"), installHint: $("install-hint"),
    installClose: $("install-close")
  };
  let currentData = null;
  let themeByCode = new Map();
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[ch]);
  const fmt = (value, digits = 2) => {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : "--";
  };
  const dateLabel = (value) => {
    if (!value) return "--";
    const parts = String(value).split("-");
    return parts.length === 3 ? `${parts[1]}月${parts[2]}日` : String(value);
  };
  function setPanel(panelId) {
    document.querySelectorAll('[role="tab"]').forEach((tab) => {
      tab.setAttribute("aria-selected", String(tab.getAttribute("aria-controls") === panelId));
    });
    document.querySelectorAll(".panel").forEach((panel) => { panel.hidden = panel.id !== panelId; });
  }
  function bindTabs() {
    document.querySelectorAll('[role="tab"]').forEach((tab) => {
      tab.addEventListener("click", () => setPanel(tab.getAttribute("aria-controls")));
    });
  }
  function buildThemeMap() {
    themeByCode = new Map();
    (currentData?.theme?.details || []).forEach((item) => themeByCode.set(String(item.code || ""), item));
  }
  function renderSummary() {
    const modelRows = currentData?.model?.results || [];
    const themes = currentData?.theme || {};
    const topSector = (themes.top_sectors || [])[0] || {};
    const topConcept = (themes.top_concepts || [])[0] || {};
    elements.tradeDate.textContent = `${currentData?.as_of || "--"} 收盘复盘`;
    elements.modelCount.textContent = String(currentData?.model?.count ?? modelRows.length);
    elements.stockCount.textContent = String(themes.stock_count ?? "--");
    elements.topSector.textContent = topSector.name || "--";
    elements.topSectorCount.textContent = topSector.name ? `出现 ${topSector.count} 只` : "等待数据";
    elements.topConcept.textContent = topConcept.name || "--";
    elements.topConceptCount.textContent = topConcept.name ? `出现 ${topConcept.count} 只` : "等待数据";
    const isHistory = Boolean(new URLSearchParams(location.search).get("date"));
    elements.statusText.textContent = isHistory ? `正在查看 ${currentData?.as_of || "--"} 的历史数据` : "已载入最新收盘复盘";
    elements.latestLink.hidden = !isHistory;
    elements.generatedAt.textContent = currentData?.generated_at ? `生成于 ${currentData.generated_at.slice(0, 16).replace("T", " ")}` : "";
  }
  function renderStocks() {
    const query = elements.search.value.trim().toLowerCase();
    const rows = currentData?.model?.results || [];
    const filtered = rows.filter((row) => {
      if (!query) return true;
      const detail = themeByCode.get(String(row.code || "")) || {};
      const haystack = [row.code, row.name, row.industry, detail.sectors?.join(" "), detail.concepts?.join(" ")].join(" ").toLowerCase();
      return haystack.includes(query);
    });
    elements.resultCount.textContent = `${filtered.length}/${rows.length}只`;
    elements.stockEmpty.hidden = filtered.length !== 0;
    elements.stockList.innerHTML = filtered.map((row) => {
      const detail = themeByCode.get(String(row.code || "")) || {};
      const tags = [
        ...(detail.sectors || []).slice(0, 2).map((name) => `<span class="tag blue">${esc(name)}</span>`),
        ...(detail.concepts || []).slice(0, 5).map((name) => `<span class="tag">${esc(name)}</span>`)
      ].join("");
      return `<article class="stock-card">
        <div class="stock-top">
          <div><h3 class="stock-name">${esc(row.name)}</h3><div class="stock-code">${esc(row.code)} · ${esc(row.market || "")}</div></div>
          <div class="stock-change">+${fmt(row.pct_chg)}%</div>
        </div>
        <div class="metrics">
          <div class="metric"><span>量比</span><b>${fmt(row.volume_ratio)}</b></div>
          <div class="metric"><span>换手</span><b>${fmt(row.turnover)}%</b></div>
          <div class="metric"><span>总市值</span><b>${fmt(row.total_mv_yi, 1)}亿</b></div>
          <div class="metric"><span>60日强势</span><b>${esc(row.up5_count)}次</b></div>
        </div>
        <div class="meta-line">
          <span class="tag gold">${esc(row.industry || "行业未分类")}</span>
          <span class="tag hot">最近强势 ${esc(row.last_up5_date || "--")}</span>
          ${tags}
        </div>
      </article>`;
    }).join("");
  }
  function renderRanks() {
    const sectors = currentData?.theme?.top_sectors || [];
    const concepts = currentData?.theme?.top_concepts || [];
    const maxSector = Math.max(1, ...sectors.map((item) => Number(item.count) || 0));
    const maxConcept = Math.max(1, ...concepts.map((item) => Number(item.count) || 0));
    elements.industryList.innerHTML = sectors.map((item, index) => `
      <div class="rank-row">
        <span class="rank-no ${index < 3 ? "top" : ""}">${index + 1}</span>
        <div class="rank-main"><span class="rank-name">${esc(item.name)}</span><div class="rank-track"><i style="width:${(Number(item.count) / maxSector) * 100}%"></i></div></div>
        <span class="rank-count">${esc(item.count)}</span>
      </div>`).join("");
    elements.conceptList.innerHTML = concepts.map((item, index) => `
      <div class="rank-row concept">
        <span class="rank-no ${index < 3 ? "top" : ""}">${index + 1}</span>
        <div class="rank-main"><span class="rank-name">${esc(item.name)}</span><div class="rank-track"><i style="width:${(Number(item.count) / maxConcept) * 100}%"></i></div></div>
        <span class="rank-count">${esc(item.count)}</span>
      </div>`).join("");
  }
  async function renderHistory() {
    try {
      const response = await fetch("./data/history/index.json", { cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      const rows = await response.json();
      if (!Array.isArray(rows) || rows.length === 0) {
        elements.historyList.innerHTML = '<div class="empty-state">暂无历史记录</div>';
        return;
      }
      elements.historyList.innerHTML = rows.map((row) => `
        <a class="history-row" href="./?date=${encodeURIComponent(row.date_key)}">
          <div><div class="history-date">${esc(row.as_of)}</div><div class="history-sub">行业第一 ${esc(row.top_sector)} · 概念第一 ${esc(row.top_concept)}</div></div>
          <div class="history-count">${esc(row.model_count)}只</div>
        </a>`).join("");
    } catch (error) {
      elements.historyList.innerHTML = '<div class="empty-state">历史数据尚未生成</div>';
    }
  }
  function renderAll() {
    buildThemeMap();
    renderSummary();
    renderStocks();
    renderRanks();
  }
  async function loadData() {
    const dateKey = new URLSearchParams(location.search).get("date");
    const url = dateKey ? `./data/history/${encodeURIComponent(dateKey)}.json` : "./data/latest.json";
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      currentData = await response.json();
      elements.loading.hidden = true;
      elements.error.hidden = true;
      renderAll();
      renderHistory();
    } catch (error) {
      elements.loading.hidden = true;
      elements.error.hidden = false;
      elements.error.textContent = "数据读取失败，请检查网络后重试。";
      elements.statusText.textContent = "数据加载失败";
    }
  }
  function setupInstallHint() {
    const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
    const standalone = window.navigator.standalone === true || window.matchMedia("(display-mode: standalone)").matches;
    if (isIos && !standalone && localStorage.getItem("install-hint-closed") !== "1") {
      elements.installHint.hidden = false;
    }
    elements.installClose.addEventListener("click", () => {
      localStorage.setItem("install-hint-closed", "1");
      elements.installHint.hidden = true;
    });
  }
  function setupNetworkState() {
    const update = () => { elements.dataState.textContent = navigator.onLine ? "在线" : "离线"; };
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    update();
  }
  function registerServiceWorker() {
    if ("serviceWorker" in navigator && location.protocol === "https:") {
      navigator.serviceWorker.register("./sw.js").catch(() => {});
    }
  }
  bindTabs();
  elements.search.addEventListener("input", renderStocks);
  setupInstallHint();
  setupNetworkState();
  registerServiceWorker();
  loadData();
})();
