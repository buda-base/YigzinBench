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
    empty: $("[data-empty]"),
    error: $("[data-error]"),
  };

  const DEFAULT_REPO = "buda-base/YigzinBench";
  const state = { view: "overall", training: "all", q: "", sort: "mean_cer", dir: 1 };
  let board = null;

  // ---------- URL state ----------
  function readUrl() {
    const p = new URLSearchParams(location.search);
    state.view = p.get("view") || "overall";
    state.training = ["off-the-shelf", "fine-tuned"].includes(p.get("training")) ? p.get("training") : "all";
    state.q = p.get("q") || "";
    state.sort = p.get("sort") || "mean_cer";
    state.dir = p.get("dir") === "desc" ? -1 : 1;
  }
  function writeUrl() {
    const p = new URLSearchParams();
    if (state.view !== "overall") p.set("view", state.view);
    if (state.training !== "all") p.set("training", state.training);
    if (state.q) p.set("q", state.q);
    if (state.sort !== "mean_cer") p.set("sort", state.sort);
    if (state.dir === -1) p.set("dir", "desc");
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
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
  function link(href, text) {
    const url = safeUrl(href);
    return url ? el("a", { href: url, rel: "noopener" }, text) : null;
  }

  // ---------- columns ----------
  function columns() {
    const base = [
      { key: "rank", label: "#", cls: "rank", sortable: false },
      { key: "model", label: "model", cls: "model", sortable: true },
    ];
    if (state.view === "overall") {
      return base.concat([
        { key: "mean_cer", label: "mean cer", cls: "num cer", sortable: true },
        { key: "median_cer", label: "median", cls: "num", sortable: true },
        { key: "catastrophic_pct", label: "over 50%", cls: "num", sortable: true },
        { key: "coverage", label: "pages", cls: "num", sortable: true },
        { key: "submitted_at", label: "date", cls: "", sortable: true },
        { key: "links", label: "links", cls: "", sortable: false },
      ]);
    }
    const cat = board.categories[state.view];
    return base.concat(
      [{ key: "mean_cer", label: "overall", cls: "num", sortable: true }],
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
      const th = el("th", {
        scope: "col",
        class: c.cls,
        "aria-sort": active ? (state.dir === 1 ? "ascending" : "descending") : null,
      });
      const label = el("span", {}, c.label, c.sub ? el("span", { class: "sub" }, c.sub) : null);
      if (c.sortable) {
        const btn = el("button", { type: "button", class: "sort", "data-sort": c.key },
          label, el("span", { class: "dir", "aria-hidden": "true" }, active ? (state.dir === 1 ? "↑" : "↓") : ""));
        th.append(btn);
      } else {
        th.append(label);
      }
      tr.append(th);
    }
    els.head.replaceChildren(tr);
  }

  function modelCell(e) {
    const td = el("td", { class: "model" });
    td.append(el("span", { class: "model__name" }, e.model));
    if (e.stale) td.append(el("span", { class: "tag tag--stale", title: "Scored on an older dataset or scorer version" }, "older version"));
    td.append(el("span", { class: "model__team" }, e.source === "bdrc-reference" ? `${e.team}, BDRC reference run` : e.team));
    return td;
  }

  function linksCell(e) {
    const td = el("td", { class: "links" });
    const items = [
      link(e.model_url, "model"),
      link(e.paper_url, "paper"),
      link(e.issue_url, "issue"),
      link(e.predictions_url, "outputs"),
    ].filter(Boolean);
    if (items.length) td.append(...items);
    else td.append(el("span", { class: "none" }, "none"));
    return td;
  }

  function renderBody(rows, cols) {
    const frag = document.createDocumentFragment();
    const worst = Math.max(...rows.map((r) => r.mean_cer), 0.0001);
    rows.forEach((e, i) => {
      const tr = el("tr");
      for (const c of cols) {
        if (c.key === "rank") tr.append(el("td", { class: "rank" }, String(i + 1)));
        else if (c.key === "model") tr.append(modelCell(e));
        else if (c.key === "mean_cer" && state.view === "overall") {
          tr.append(el("td", { class: "num cer" },
            el("div", { class: "cer__row" },
              el("span", { class: "cer__bar", "aria-hidden": "true" }, el("span", { style: `--v:${(e.mean_cer / worst).toFixed(4)}` })),
              el("span", { class: "cer__value" }, pct(e.mean_cer)))));
        } else if (c.key === "mean_cer") tr.append(el("td", { class: "num metric" }, pct(e.mean_cer)));
        else if (c.key === "median_cer") tr.append(el("td", { class: "num metric" }, pct(e.median_cer)));
        else if (c.key === "catastrophic_pct") tr.append(el("td", { class: "num metric" }, `${e.catastrophic_pct.toFixed(1)}%`));
        else if (c.key === "coverage") tr.append(el("td", { class: "num metric" }, `${e.coverage}/${e.n}`));
        else if (c.key === "submitted_at") tr.append(el("td", { class: "metric" }, (e.submitted_at || "").slice(0, 10)));
        else if (c.key === "links") tr.append(linksCell(e));
        else if (c.key.startsWith("b:")) {
          const v = value(e, c.key);
          tr.append(Number.isFinite(v)
            ? el("td", { class: "num heat", style: `--h:${v.toFixed(4)}` }, pct(v))
            : el("td", { class: "num metric", "aria-label": "no data" }));
        }
      }
      frag.append(tr);
    });
    els.body.replaceChildren(frag);
  }

  function render() {
    if (!board) return;
    const q = state.q.trim().toLowerCase();
    let rows = board.entries.filter((e) =>
      (state.training === "all" || e.training === state.training) &&
      (!q || `${e.model} ${e.team}`.toLowerCase().includes(q)));

    const cols = columns();
    if (!cols.some((c) => c.key === state.sort && c.sortable)) { state.sort = "mean_cer"; state.dir = 1; }
    rows = rows.slice().sort((a, b) => {
      const va = value(a, state.sort), vb = value(b, state.sort);
      if (va < vb) return -state.dir;
      if (va > vb) return state.dir;
      return a.mean_cer - b.mean_cer;
    });

    renderHead(cols);
    renderBody(rows, cols);
    els.wrap.dataset.state = rows.length ? "full" : "empty";
    els.empty.hidden = rows.length > 0;
    writeUrl();
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
    els.view.addEventListener("change", () => {
      state.view = els.view.value; state.sort = "mean_cer"; state.dir = 1; render();
    });
    els.search.addEventListener("input", () => { state.q = els.search.value; render(); });
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
    $("[data-clear]").addEventListener("click", () => {
      state.training = "all"; state.q = ""; syncControls(); render();
    });
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
    $$("[data-issue-link]").forEach((a) => { a.href = `https://github.com/${repo}/issues/new?template=submission.yml`; });
    $$("[data-repo-link]").forEach((a) => { a.href = `https://github.com/${repo}`; });
  }

  async function load() {
    els.error.hidden = true;
    els.wrap.hidden = false;
    els.wrap.dataset.state = "loading";
    try {
      // On Pages the file sits beside the page; in a local checkout it's one level up.
      board = await fetchJson(["leaderboard.json", "../leaderboard/leaderboard.json"]);
    } catch (_) {
      els.wrap.hidden = true;
      els.error.hidden = false;
      return;
    }
    const opts = [el("option", { value: "overall" }, "overall")];
    for (const [key, cat] of Object.entries(board.categories)) opts.push(el("option", { value: key }, cat.label.toLowerCase()));
    els.view.replaceChildren(...opts);
    if (!board.categories[state.view]) state.view = "overall";

    $("[data-readout=models]").textContent = String(board.entries.length);
    $("[data-readout=revision]").textContent = board.dataset_revision.slice(0, 7);
    $("[data-readout=scorer]").textContent = `v${board.scorer_version}`;
    syncControls();
    render();
    // The table grew after the browser jumped to #submit or #scoring; jump again.
    const target = location.hash && document.getElementById(location.hash.slice(1));
    if (target && target.id !== "leaderboard") target.scrollIntoView();
  }

  readUrl();
  bind();
  configureRepo();
  load();
})();
