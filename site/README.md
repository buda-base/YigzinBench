# site

## Overview

The static leaderboard page (vanilla HTML, CSS and JavaScript, no build step).
`index.html` loads `style.css` and `app.js`; `app.js` is one IIFE that fetches
`leaderboard.json`, renders it as a sortable, filterable table whose state is
kept in the URL, and fills in the hero facts and the repository and issue
links. The deploy workflow copies this folder and
`leaderboard/leaderboard.json` into `_site/` for GitHub Pages. The data comes
from [`../tools/`](../tools/README.md) (`build_leaderboard.py`).

## Interface

### Files

- `index.html`: page markup and the `data-*` hooks below. Element ids: `title`,
  `leaderboard`, `board-title`, `join`, `join-title`.
- `app.js`: all behavior.
- `style.css`: imports `tokens.css` (design tokens) and `base.css`. The theme is
  light only (`color-scheme: light`); there is no dark-mode rule.
- `img/`: `page-0008.jpg`, `page-0012.jpg`, `page-0116.jpg`.

### `app.js` symbols

- Constants: `DEFAULT_REPO = "buda-base/YigzinBench"`, `TOP_N = 10`.
- `state = { view: 'overall', training: 'all', q: '', sort: 'mean_cer', dir: 1, all: false }`;
  `board` holds the loaded JSON; `issueUrl` is the new-issue URL with
  `template=submission.yml`.
- `readUrl` / `writeUrl`: sync `state` with the query params `view`,
  `training`, `q`, `sort`, `dir`, `all`.
- Helpers: `$`, `$$`, `el`, `pct` (1-decimal percentage), `safeUrl`
  (http(s) only), `fetchJson` (tries URLs in order).
- Rendering: `columns`, `value`, `renderHead`, `modelCell`, `ghostRow`,
  `renderBody`, `render`, `renderHero`, `syncControls`.
- Setup: `bind`, `configureRepo`, `load`.

### DOM hooks

- Table and controls: `[data-head]`, `[data-body]`, `.table-wrap`,
  `[data-view]`, `[data-search]`, `[data-more]`, `[data-empty]`,
  `[data-error]`, `[data-clear]`, `[data-retry]`, `.seg` with
  `[data-training]` buttons, `[data-sort]` header buttons.
- Hero: `[data-beat-cer]`, `[data-beat-model]`, `[data-to-beat]`,
  `[data-meta]`, and `[data-best="category:name"]` tags (the page uses
  `technology:manuscripts`, `script:Transitional`, `technology:blockprints`).
- Links: `[data-issue-link]`, `[data-repo-link]` (optional
  `data-repo-hash`), `.ghost a`.

### Data read

- `config.json` (optional): `repo`. Not in this folder; `deploy-pages.yml`
  writes it into `_site/` from `$GITHUB_REPOSITORY`.
- `leaderboard.json` (falls back to `../leaderboard/leaderboard.json`):
  `categories[key].label`, `categories[key].values[].{name, n}`, and
  `entries[]` fields `id`, `model`, `team`, `mean_cer`, `median_cer`,
  `coverage`, `n`, `submitted_at`, `training`, `stale`, `model_url`,
  `paper_url`, `issue_url`, `breakdown[category][name]`.

## Invariants

- `entries[0]` is taken as the best model without sorting, so
  `leaderboard.json` must already be ordered by ascending `mean_cer`.
- Each entry has a unique `id`; `mean_cer`, `median_cer` and `breakdown`
  values are fractions from 0 to 1.
- Rank is always by ascending `mean_cer` within the current training and search
  filter, whatever column is sorted.
- Rows sort by `state.sort` and `state.dir` (1 ascending, -1 descending), ties
  broken by ascending `mean_cer`. A sort key that is not a column in the current
  view resets to `mean_cer` ascending, and so does changing the view.
- Sorting by model compares lowercased `` `${model} ${team}` ``; a missing
  breakdown value sorts as `Infinity`.
- The `training` URL param accepts only `off-the-shelf` or `fine-tuned`;
  anything else means `all`. Search is a case-insensitive substring match on
  model and team.
- Only the top `TOP_N` rows show unless "show all" is on or a search is active.
  A "Your model here?" ghost row is always last.
- The model link is the first valid http(s) URL among `model_url`,
  `paper_url`, `issue_url`. Entries with `stale` get an "older version" tag.
  Entries with `coverage < n` get a `partial (coverage/n)` tag next to it.
- A `view` param that is not a key of `board.categories` falls back to
  `overall`.
- `config.json` `repo` must match `^[\w.-]+/[\w.-]+$`. Without it, a
  `*.github.io` host uses `owner/first-path-segment`, otherwise `DEFAULT_REPO`.
- Data text is inserted only through `textContent` or `append`, never as HTML.

## Side Effects

- Fetches `config.json` and `leaderboard.json` (then
  `../leaderboard/leaderboard.json`) with `cache: 'no-cache'`.
- `index.html` loads Google Fonts (Geist, Geist Mono, Noto Serif Tibetan).
- `writeUrl` calls `history.replaceState` on every render, keeping the hash.
  After load, the element named by `location.hash` is scrolled into view.
- Replaces the table head and body, the `[data-view]` options and hero text;
  rewrites the `href` of repository and issue links.
- Adds click, keydown (arrow keys on `.seg`), change and input listeners.
- No `localStorage` or `sessionStorage`.

## Verification

- No automated tests cover the site. Preview it locally:

  ```bash
  mkdir -p _site && cp -r site/. _site/ && cp leaderboard/leaderboard.json _site/ && python -m http.server -d _site 8000
  ```
