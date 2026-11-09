// YigzinBench leaderboard: renders leaderboard.json into a sortable, filterable table.
// All user-supplied text goes in through textContent; links must be http(s).
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));
  const els = {
    head: $("[data-head]"),
    body: $("[data-body]"),
    wrap: $(".table-wrap"),
    view: $("[data-view]"),
    search: $("[data-search]"),
    more: $("[data-more]"),
    empty: $("[data-empty]"),
    error: $("[data-error]"),
  };

  const DEFAULT_REPO = "buda-base/YigzinBench";
  const TOP_N = 10;
  const state = { view: "overall", training: "all", q: "", sort: "mean_cer", dir: 1, all: false };
  let board = null;
  let issueUrl = `https://github.com/${DEFAULT_REPO}/issues/new?template=submission.yml`;

  // ---------- URL state ----------
  function readUrl() {
    const p = new URLSearchParams(location.search);
    state.view = p.get("view") || "overall";
    state.training = ["off-the-shelf", "fine-tuned"].includes(p.get("training")) ? p.get("training") : "all";
    state.q = p.get("q") || "";
    state.sort = p.get("sort") || "mean_cer";
    state.dir = p.get("dir") === "desc" ? -1 : 1;
    state.all = p.get("all") === "1";
  }
  function writeUrl() {
    const p = new URLSearchParams();
    if (state.view !== "overall") p.set("view", state.view);
    if (state.training !== "all") p.set("training", state.training);
    if (state.q) p.set("q", state.q);
    if (state.sort !== "mean_cer") p.set("sort", state.sort);
    if (state.dir === -1) p.set("dir", "desc");
    if (state.all) p.set("all", "1");
    const qs = p.toString();
    history.replaceState(null, "", (qs ? `?${qs}` : location.pathname) + location.hash);
  }

  // ---------- helpers ----------
  const pct = (v) => `${(v * 100).toFixed(1)}%`;
  const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : "");
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "style") node.style.cssText = v;
      else node.setAttribute(k, v);
    }
    for (const c of children) if (c !== null && c !== undefined) node.append(c);
    return node;
  }

  // ---------- columns ----------
  function columns() {
    const base = [
      { key: "rank", label: "Rank", cls: "rank", sortable: false },
      { key: "model", label: "Model", cls: "model", sortable: true },
    ];
    if (state.view === "overall") {
      return base.concat([
        { key: "mean_cer", label: "Error rate", cls: "num cer", sortable: true },
        { key: "median_cer", label: "Median", cls: "num", sortable: true },
        { key: "coverage", label: "Pages", cls: "num", sortable: true },
        { key: "submitted_at", label: "Added", cls: "", sortable: true },
      ]);
    }
    const cat = board.categories[state.view];
    return base.concat(
      [{ key: "mean_cer", label: "Overall", cls: "num", sortable: true }],
      cat.values.map((v) => ({ key: `b:${v.name}`, label: v.name, sub: `${v.n} pages`, cls: "num", sortable: true })),
    );
  }

  function value(entry, key) {
    if (key === "model") return `${entry.model} ${entry.team}`.toLowerCase();
    if (key.startsWith("b:")) {
      const v = (entry.breakdown[state.view] || {})[key.slice(2)];
      return v === undefined ? Infinity : v;
    }
    if (key === "submitted_at") return entry.submitted_at || "";
    return entry[key];
  }

  // ---------- render ----------
  function renderHead(cols) {
    const tr = el("tr");
    for (const c of cols) {
      const active = state.sort === c.key;
      const th = el("th", { scope: "col", class: c.cls, "aria-sort": active ? (state.dir === 1 ? "ascending" : "descending") : null });
      const label = el("span", {}, c.label, c.sub ? el("span", { class: "sub" }, c.sub) : null);
      if (c.sortable) {
        th.append(el("button", { type: "button", class: "sort", "data-sort": c.key },
          label, el("span", { class: "dir", "aria-hidden": "true" }, active ? (state.dir === 1 ? "↑" : "↓") : "")));
      } else {
        th.append(c.key === "rank" ? el("span", { class: "visually-hidden" }, c.label) : label);
      }
      tr.append(th);
    }
    els.head.replaceChildren(tr);
  }

  function modelCell(e) {
    const td = el("td", { class: "model" });
    const url = safeUrl(e.model_url) || safeUrl(e.paper_url) || safeUrl(e.issue_url);
    td.append(url ? el("a", { class: "model__name", href: url, rel: "noopener" }, e.model) : el("span", { class: "model__name" }, e.model));
    if (e.stale) td.append(el("span", { class: "tag", title: "Scored on an older version of the dataset" }, "older version"));
    td.append(el("span", { class: "model__team" }, e.team));
    return td;
  }

  function ghostRow(span) {
    return el("tr", { class: "ghost" },
      el("td", { class: "rank" }, el("span", { class: "rank__n", "aria-hidden": "true" }, "?")),
      el("td", { colspan: String(span - 1) },
        el("span", { class: "ghost__text" }, "Your model here?"),
        el("a", { href: issueUrl }, "Submit it")));
  }

  function renderBody(rows, cols, ranks) {
    const frag = document.createDocumentFragment();
    const worst = Math.max(...board.entries.map((r) => r.mean_cer), 0.0001);
    for (const e of rows) {
      const rank = ranks.get(e.id);
      const tr = el("tr", { class: rank <= 3 ? `top-${rank}` : null });
      for (const c of cols) {
        if (c.key === "rank") tr.append(el("td", { class: "rank" }, el("span", { class: "rank__n" }, String(rank))));
        else if (c.key === "model") tr.append(modelCell(e));
        else if (c.key === "mean_cer" && state.view === "overall") {
          tr.append(el("td", { class: "num cer" },
            el("div", { class: "cer__row" },
              el("span", { class: "cer__bar", "aria-hidden": "true" }, el("span", { style: `--v:${(e.mean_cer / worst).toFixed(4)}` })),
              el("span", { class: "cer__value" }, pct(e.mean_cer)))));
        } else if (c.key === "mean_cer") tr.append(el("td", { class: "num metric" }, pct(e.mean_cer)));
        else if (c.key === "median_cer") tr.append(el("td", { class: "num metric" }, pct(e.median_cer)));
        else if (c.key === "coverage") tr.append(el("td", { class: "num metric" }, `${e.coverage}/${e.n}`));
        else if (c.key === "submitted_at") tr.append(el("td", { class: "metric" }, (e.submitted_at || "").slice(0, 10)));
        else if (c.key.startsWith("b:")) {
          const v = value(e, c.key);
          tr.append(Number.isFinite(v)
            ? el("td", { class: "num heat", style: `--h:${v.toFixed(4)}` }, pct(v))
            : el("td", { class: "num metric", "aria-label": "no data" }));
        }
      }
      frag.append(tr);
    }
    frag.append(ghostRow(cols.length));
    els.body.replaceChildren(frag);
  }

  function render() {
    if (!board) return;
    const q = state.q.trim().toLowerCase();
    const matches = board.entries.filter((e) =>
      (state.training === "all" || e.training === state.training) &&
      (!q || `${e.model} ${e.team}`.toLowerCase().includes(q)));

    // Rank is always by overall error rate within the current filter, whatever the sort.
    const ranks = new Map(matches.slice().sort((a, b) => a.mean_cer - b.mean_cer).map((e, i) => [e.id, i + 1]));

    const cols = columns();
    if (!cols.some((c) => c.key === state.sort && c.sortable)) { state.sort = "mean_cer"; state.dir = 1; }
    let rows = matches.slice().sort((a, b) => {
      const va = value(a, state.sort), vb = value(b, state.sort);
      if (va < vb) return -state.dir;
      if (va > vb) return state.dir;
      return a.mean_cer - b.mean_cer;
    });
    const truncated = !state.all && !q && rows.length > TOP_N;
    if (truncated) rows = rows.slice(0, TOP_N);

    renderHead(cols);
    renderBody(rows, cols, ranks);
    els.wrap.hidden = rows.length === 0;
    els.empty.hidden = rows.length > 0;
    els.more.hidden = !(truncated || (state.all && matches.length > TOP_N && !q));
    els.more.textContent = truncated ? `Show all ${matches.length} models` : `Show top ${TOP_N}`;
    writeUrl();
  }

  // ---------- hero facts ----------
  function renderHero() {
    const best = board.entries[0];
    if (best) {
      $("[data-beat-cer]").textContent = pct(best.mean_cer);
      $("[data-beat-model]").textContent = `${best.model}, ${best.team}`;
      $("[data-to-beat]").hidden = false;
    }
    for (const tag of $$("[data-best]")) {
      const [cat, name] = tag.dataset.best.split(":");
      const scores = board.entries.map((e) => (e.breakdown[cat] || {})[name]).filter(Number.isFinite);
      if (scores.length) tag.append(" ", el("b", {}, `best ${pct(Math.min(...scores))}`));
    }
    $("[data-meta]").textContent = `${board.entries.length} models, character error rate, lower is better`;
  }

  // ---------- controls ----------
  function syncControls() {
    els.view.value = state.view;
    els.search.value = state.q;
    $$("[data-training]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.training === state.training)));
  }

  function bind() {
    $$("[data-training]").forEach((b) => b.addEventListener("click", () => {
      state.training = b.dataset.training; syncControls(); render();
    }));
    $(".seg").addEventListener("keydown", (ev) => {
      if (!["ArrowLeft", "ArrowRight"].includes(ev.key)) return;
      const btns = $$("[data-training]");
      const i = btns.findIndex((b) => b.dataset.training === state.training);
      const next = btns[(i + (ev.key === "ArrowRight" ? 1 : btns.length - 1)) % btns.length];
      next.focus(); next.click();
    });
    els.view.addEventListener("change", () => { state.view = els.view.value; state.sort = "mean_cer"; state.dir = 1; render(); });
    els.search.addEventListener("input", () => { state.q = els.search.value; render(); });
    els.more.addEventListener("click", () => { state.all = !state.all; render(); });
    els.head.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-sort]");
      if (!btn) return;
      const key = btn.dataset.sort;
      state.dir = state.sort === key ? -state.dir : 1;
      state.sort = key;
      render();
      const again = els.head.querySelector(`[data-sort="${CSS.escape(key)}"]`);
      if (again) again.focus();
    });
    $("[data-clear]").addEventListener("click", () => { state.training = "all"; state.q = ""; syncControls(); render(); });
    $("[data-retry]").addEventListener("click", load);
  }

  // ---------- data ----------
  async function fetchJson(urls) {
    for (const url of urls) {
      try {
        const res = await fetch(url, { cache: "no-cache" });
        if (res.ok) return await res.json();
      } catch (_) { /* try the next location */ }
    }
    throw new Error("unavailable");
  }

  async function configureRepo() {
    let repo = DEFAULT_REPO;
    try {
      const cfg = await fetchJson(["config.json"]);
      if (/^[\w.-]+\/[\w.-]+$/.test(cfg.repo || "")) repo = cfg.repo;
    } catch (_) {
      const m = location.hostname.match(/^([\w-]+)\.github\.io$/);
      const seg = location.pathname.split("/").filter(Boolean)[0];
      if (m && seg) repo = `${m[1]}/${seg}`;
    }
    issueUrl = `https://github.com/${repo}/issues/new?template=submission.yml`;
    $$("[data-issue-link]").forEach((a) => { a.href = issueUrl; });
    $$("[data-repo-link]").forEach((a) => { a.href = `https://github.com/${repo}${a.dataset.repoHash || ""}`; });
    $$(".ghost a").forEach((a) => { a.href = issueUrl; });
  }

  async function load() {
    els.error.hidden = true;
    els.wrap.hidden = false;
    try {
      // On Pages the file sits beside the page; in a local checkout it's one level up.
      board = await fetchJson(["leaderboard.json", "../leaderboard/leaderboard.json"]);
    } catch (_) {
      els.wrap.hidden = true;
      els.error.hidden = false;
      return;
    }
    const opts = [el("option", { value: "overall" }, "Overall score")];
    for (const [key, cat] of Object.entries(board.categories)) opts.push(el("option", { value: key }, `By ${cat.label.toLowerCase()}`));
    els.view.replaceChildren(...opts);
    if (!board.categories[state.view]) state.view = "overall";
    syncControls();
    renderHero();
    render();
    // The page grew after the browser jumped to an anchor; jump again.
    const target = location.hash && document.getElementById(location.hash.slice(1));
    if (target) target.scrollIntoView();
  }

  readUrl();
  bind();
  configureRepo();
  load();
})();
