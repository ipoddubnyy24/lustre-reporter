"use strict";
/* Lustre Reporter — vanilla JS SPA. No external dependencies. */

// ---------- tiny DOM helpers ----------
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k === "dataset") Object.assign(n.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return n;
}

async function api(path, params, refresh) {
  const u = new URL(path, location.origin);
  if (params) for (const [k, v] of Object.entries(params)) {
    if (v == null) continue;
    if (Array.isArray(v)) v.forEach((x) => u.searchParams.append(k, x));
    else u.searchParams.set(k, v);
  }
  if (refresh) u.searchParams.set("refresh", "1");
  const r = await fetch(u.toString());
  if (!r.ok) throw new Error("HTTP " + r.status + " for " + path);
  return r.json();
}

const fmtDate = (s, withTime) => {
  if (!s) return "—";
  const str = String(s);
  return withTime ? str.slice(0, 16).replace("T", " ") : str.slice(0, 10);
};
const loading = (txt) => el("div", { class: "loading" }, el("span", { class: "spinner" }), " " + (txt || "Loading…"));

// ---------- state ----------
let CFG = null;
const S = {
  tab: "stability",
  stability: { branch: "es6", days: 30, from: "", to: "", failuresLoaded: false },
  landed: { days: 7 },
  backports: { days: 120, onlyGaps: true },
};

// ---------- source-error banner ----------
function sourceBanner(res, tool) {
  const kind = res.kind || "error";
  const cls = kind === "error" ? "error" : "auth";
  const box = el("div", { class: "banner " + cls });
  if (tool === "maloo" && kind === "auth") {
    box.append(
      el("h3", {}, "Maloo credentials rejected (HTTP 401)"),
      el("div", {}, "The stability report reads nightly CI results from Maloo (testing.whamcloud.com). The current credentials were rejected. To fix:"),
      el("pre", {}, "edit ~/.config/maloo-tool/.env\n  MALOO_USER=<your testing.whamcloud.com login>\n  MALOO_PASS=<your testing.whamcloud.com password>\nthen click ↻ Refresh"),
      el("div", { class: "small muted" }, res.error || ""),
    );
  } else if (kind === "missing") {
    box.append(
      el("h3", {}, "Tool not installed"),
      el("div", {}, res.error || ("The '" + tool + "' CLI was not found on PATH.")),
      el("pre", {}, "cd ~/work/src/llm_jira && ./install.sh"),
    );
  } else {
    box.append(
      el("h3", {}, (tool || "Source") + " error"),
      el("div", { class: "small mono" }, res.error || "unknown error"),
    );
  }
  return box;
}

// ---------- status chips ----------
function statusChip(state) {
  if (state === "ported") return el("span", { class: "chip good" }, "✓ ported");
  if (state === "ticket_only") return el("span", { class: "chip warn", title: "Ticket exists on this branch, but this patch's subject was not found — a companion patch may have been missed." }, "⚠ ticket only");
  return el("span", { class: "chip bad" }, "✗ missing");
}

function changeLink(c) {
  if (!c || !c.url) return null;
  return el("a", { href: c.url, target: "_blank", class: "mono", title: c.subject || "" },
    "#" + c.number + (c.status && c.status !== "MERGED" ? " (" + c.status.toLowerCase() + ")" : ""));
}

function ticketLinks(tickets) {
  const wrap = el("span");
  (tickets || []).forEach((t, i) => {
    if (i) wrap.append(" ");
    wrap.append(el("a", { href: t.url, target: "_blank", class: "ticket-link", title: t.is_cloud ? "DDN cloud Jira" : "Whamcloud Jira" }, t.key));
  });
  if (!(tickets || []).length) wrap.append(el("span", { class: "muted" }, "—"));
  return wrap;
}

// =====================================================================
//  TAB 1 — BUILD STABILITY
// =====================================================================
function stabilityControls() {
  const st = S.stability;
  const branchSel = el("select", { onchange: (e) => { st.branch = e.target.value; st.failuresLoaded = false; renderStability(); } },
    ...CFG.branches.map((b) => el("option", { value: b.key, selected: b.key === st.branch ? "" : null }, b.label + " (" + b.gerrit_branch + ")")));

  const presets = [7, 14, 30, 60, 90];
  const rangeSel = el("select", {
    onchange: (e) => {
      const v = e.target.value;
      if (v === "custom") { st.custom = true; } else { st.custom = false; st.days = +v; st.from = ""; st.to = ""; }
      renderStability();
    },
  },
    ...presets.map((d) => el("option", { value: d, selected: !st.custom && st.days === d ? "" : null }, "last " + d + " days")),
    el("option", { value: "custom", selected: st.custom ? "" : null }, "custom range…"));

  const row = el("div", { class: "controls" },
    el("div", { class: "group" }, el("label", {}, "Branch"), branchSel),
    el("div", { class: "group" }, el("label", {}, "Period"), rangeSel));

  if (st.custom) {
    const from = el("input", { type: "date", value: st.from || "", max: CFG.today, onchange: (e) => { st.from = e.target.value; } });
    const to = el("input", { type: "date", value: st.to || CFG.today, max: CFG.today, onchange: (e) => { st.to = e.target.value; } });
    row.append(
      el("div", { class: "group" }, el("label", {}, "From"), from),
      el("div", { class: "group" }, el("label", {}, "To"), to),
      el("button", { class: "btn accent sm", onclick: () => renderStability() }, "Apply"));
  }
  return row;
}

async function renderStability(refresh) {
  const root = $("#tab-stability");
  const st = S.stability;
  root.replaceChildren(stabilityControls(), loading("Querying Maloo…"));
  let data;
  try {
    const params = { branch: st.branch, days: st.days };
    if (st.custom && st.from) { params.from = st.from; params.to = st.to || CFG.today; }
    data = await api("/api/stability", params, refresh);
  } catch (e) {
    root.replaceChildren(stabilityControls(), el("div", { class: "banner error" }, String(e)));
    return;
  }

  const out = [stabilityControls()];
  if (!data.ok) {
    out.push(sourceBanner(data, "maloo"));
    out.push(el("div", { class: "card muted small" },
      "Trigger job: ", el("code", {}, data.trigger_job || "?"),
      ". Once Maloo authenticates, this tab shows the nightly pass-rate trend, per-day drill-down, and the top failing tests."));
    root.replaceChildren(...out);
    return;
  }

  const sum = data.summary;
  const rateClass = (r) => r == null ? "" : (r >= 90 ? "good" : r >= 70 ? "warn" : "bad");
  const tiles = el("div", { class: "tiles" },
    el("div", { class: "tile " + rateClass(sum.session_pass_rate) }, el("div", { class: "v" }, sum.session_pass_rate == null ? "—" : sum.session_pass_rate + "%"), el("div", { class: "k" }, "clean sessions")),
    el("div", { class: "tile " + rateClass(sum.testset_pass_rate) }, el("div", { class: "v" }, sum.testset_pass_rate == null ? "—" : sum.testset_pass_rate + "%"), el("div", { class: "k" }, "test-set pass rate")),
    el("div", { class: "tile" }, el("div", { class: "v" }, sum.sessions), el("div", { class: "k" }, "sessions")),
    el("div", { class: "tile " + (sum.failed_sessions ? "warn" : "good") }, el("div", { class: "v" }, sum.failed_sessions), el("div", { class: "k" }, "sessions with failures")),
    el("div", { class: "tile " + (sum.testsets_failed ? "bad" : "good") }, el("div", { class: "v" }, sum.testsets_failed), el("div", { class: "k" }, "test-sets failed")));

  const chartCard = el("div", { class: "card" }, el("h2", {}, "Stability trend — " + data.label),
    data.trend.length ? drawTrend(data.trend) : el("div", { class: "muted" }, "No sessions in this period."),
    el("div", { class: "legend" },
      el("span", {}, el("i", { class: "dot-key", style: "background:var(--accent)" }), "clean-session %"),
      el("span", {}, el("i", { class: "dot-key", style: "background:var(--muted);opacity:.4" }), "sessions/day")));

  // top failures (lazy — the query is slow)
  const failCard = el("div", { class: "card" }, el("h2", {}, "Top failing tests"));
  if (!st.failuresLoaded) {
    failCard.append(el("button", { class: "btn", onclick: (e) => { st.failuresLoaded = true; loadTopFailures(failCard); } }, "Load top failures (slow — drills into sessions)"));
  } else {
    loadTopFailures(failCard);
  }

  out.push(tiles, chartCard, failCard, sessionsTable(data.sessions));
  root.replaceChildren(...out);
}

async function loadTopFailures(card) {
  card.replaceChildren(el("h2", {}, "Top failing tests"), loading("Aggregating failures…"));
  const st = S.stability;
  let data;
  try { data = await api("/api/top-failures", { branch: st.branch, days: st.days }); }
  catch (e) { card.replaceChildren(el("h2", {}, "Top failing tests"), el("div", { class: "banner error" }, String(e))); return; }
  if (!data.ok) { card.replaceChildren(el("h2", {}, "Top failing tests"), sourceBanner(data, "maloo")); return; }
  if (!data.failures.length) { card.replaceChildren(el("h2", {}, "Top failing tests"), el("div", { class: "muted" }, "No failures found. 🎉")); return; }
  const rows = data.failures.map((f) => el("tr", {},
    el("td", { class: "num" }, f.rank),
    el("td", {}, el("span", { class: "mono" }, f.suite || "—")),
    el("td", { class: "subject" }, f.test_name),
    el("td", { class: "num" }, f.count),
    el("td", { class: "num" }, f.session_count),
    el("td", { class: "small muted", title: f.error_sample || "" }, (f.error_sample || "").slice(0, 80))));
  card.replaceChildren(el("h2", {}, "Top failing tests (" + data.days + "d)"),
    el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", { class: "num" }, "#"), el("th", {}, "Suite"), el("th", {}, "Test"), el("th", { class: "num" }, "Fails"), el("th", { class: "num" }, "Sessions"), el("th", {}, "Sample error"))),
      el("tbody", {}, ...rows))));
}

function sessionsTable(sessions) {
  const card = el("div", { class: "card" }, el("h2", {}, "Sessions (" + sessions.length + ")"));
  if (!sessions.length) { card.append(el("div", { class: "muted" }, "No sessions.")); return card; }
  const rows = sessions.map((s) => el("tr", {},
    el("td", {}, s.clean ? el("span", { class: "chip good" }, "clean") : el("span", { class: "chip bad" }, "fail")),
    el("td", { class: "nowrap" }, fmtDate(s.date, true)),
    el("td", { class: "mono small" }, s.host || "—"),
    el("td", {}, s.name || s.group || "—"),
    el("td", { class: "num" }, s.passed),
    el("td", { class: "num" }, s.failed),
    el("td", { class: "num" }, s.aborted),
    el("td", {}, s.url ? el("a", { href: s.url, target: "_blank" }, "open") : "—")));
  card.append(el("div", { class: "scroll-x" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", {}, "Result"), el("th", {}, "Submitted"), el("th", {}, "Host"), el("th", {}, "Suite/name"), el("th", { class: "num" }, "Pass"), el("th", { class: "num" }, "Fail"), el("th", { class: "num" }, "Abort"), el("th", {}, "Link"))),
    el("tbody", {}, ...rows))));
  return card;
}

// SVG trend: clean-session % line + faint per-day session bars.
function drawTrend(trend) {
  const W = 760, H = 260, padL = 36, padR = 12, padT = 14, padB = 30;
  const iw = W - padL - padR, ih = H - padT - padB;
  const n = trend.length;
  const maxSessions = Math.max(1, ...trend.map((d) => d.sessions));
  const x = (i) => padL + (n === 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (r) => padT + ih - (Math.max(0, Math.min(100, r)) / 100) * ih;
  const svg = (t, a, ...k) => { const e = document.createElementNS("http://www.w3.org/2000/svg", t); for (const [kk, vv] of Object.entries(a || {})) e.setAttribute(kk, vv); k.forEach((c) => e.append(c)); return e; };

  const g = svg("g");
  // gridlines + y labels
  [0, 25, 50, 75, 100].forEach((v) => {
    g.append(svg("line", { class: "grid", x1: padL, y1: y(v), x2: W - padR, y2: y(v) }));
    g.append(svg("text", { x: padL - 6, y: y(v) + 3, "text-anchor": "end" }, document.createTextNode(v + "%")));
  });
  // session-count bars
  const bw = Math.max(1, iw / Math.max(n, 1) * 0.5);
  trend.forEach((d, i) => {
    const bh = (d.sessions / maxSessions) * ih * 0.5;
    g.append(svg("rect", { class: "bar", x: x(i) - bw / 2, y: padT + ih - bh, width: bw, height: bh }));
  });
  // area + line for clean-session %
  const pts = trend.map((d, i) => [x(i), y(d.session_pass_rate == null ? 0 : d.session_pass_rate)]);
  const linePath = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const areaPath = linePath + " L" + pts[pts.length - 1][0].toFixed(1) + " " + (padT + ih) + " L" + pts[0][0].toFixed(1) + " " + (padT + ih) + " Z";
  g.append(svg("path", { class: "area", d: areaPath }));
  g.append(svg("path", { class: "line", d: linePath }));
  trend.forEach((d, i) => {
    const dot = svg("circle", { class: "dot", cx: x(i), cy: y(d.session_pass_rate), r: 3 });
    dot.append(svg("title", {}, document.createTextNode(
      d.date + ": " + (d.session_pass_rate) + "% clean · " + d.sessions + " sessions · " +
      d.testsets_failed + " test-sets failed" + (d.testset_pass_rate != null ? " · " + d.testset_pass_rate + "% test-sets pass" : ""))));
    g.append(dot);
  });
  // x labels: first, middle, last
  const idxs = n <= 1 ? [0] : [0, Math.floor((n - 1) / 2), n - 1];
  [...new Set(idxs)].forEach((i) => g.append(svg("text", { x: x(i), y: H - 8, "text-anchor": i === 0 ? "start" : (i === n - 1 ? "end" : "middle") }, document.createTextNode(trend[i].date.slice(5)))));

  return svg("svg", { class: "trend", viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "xMidYMid meet" },
    svg("line", { class: "axis", x1: padL, y1: padT, x2: padL, y2: padT + ih }),
    svg("line", { class: "axis", x1: padL, y1: padT + ih, x2: W - padR, y2: padT + ih }),
    g);
}

// =====================================================================
//  TAB 2 — LANDED PATCHES
// =====================================================================
function landedControls() {
  const presets = [7, 14, 30];
  return el("div", { class: "controls" },
    el("div", { class: "group" }, el("label", {}, "Window"),
      el("select", { onchange: (e) => { S.landed.days = +e.target.value; renderLanded(); } },
        ...presets.map((d) => el("option", { value: d, selected: S.landed.days === d ? "" : null }, "last " + d + " days")))),
    el("span", { class: "small muted" }, "Patches merged to each ExaScaler branch in the window."));
}

async function renderLanded(refresh) {
  const root = $("#tab-landed");
  root.replaceChildren(landedControls(), loading("Querying Gerrit…"));
  let data;
  try { data = await api("/api/landed", { days: S.landed.days }, refresh); }
  catch (e) { root.replaceChildren(landedControls(), el("div", { class: "banner error" }, String(e))); return; }

  const out = [landedControls()];
  for (const b of data.branches) {
    const card = el("div", { class: "card" },
      el("h2", {}, b.label + " ",
        el("span", { class: "chip accent" }, b.gerrit_branch),
        " ", el("span", { class: "muted small" }, b.ok ? b.count + " merged in " + data.days + "d" : "")));
    if (!b.ok) { card.append(sourceBanner(b, "gerrit")); out.push(card); continue; }
    if (!b.count) { card.append(el("div", { class: "muted" }, "Nothing merged in this window.")); out.push(card); continue; }
    const rows = b.patches.map((p) => el("tr", {},
      el("td", {}, el("a", { href: p.url, target: "_blank", class: "mono" }, "#" + p.number)),
      el("td", {}, ticketLinks(p.tickets)),
      el("td", { class: "subject" }, stripTicket(p.subject)),
      el("td", { class: "owner nowrap" }, p.owner || "—"),
      el("td", { class: "nowrap" }, fmtDate(p.updated)),
      el("td", { class: "mono small nowrap" }, p.size || "")));
    card.append(el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Patch"), el("th", {}, "Ticket"), el("th", {}, "Subject"), el("th", {}, "Owner"), el("th", {}, "Merged"), el("th", {}, "Size"))),
      el("tbody", {}, ...rows))));
    out.push(card);
  }
  root.replaceChildren(...out);
}

const stripTicket = (s) => (s || "").replace(/^((?:LU|EX|DDN|EHT|GCP|IME)-\d+\s+)+/i, "");

// =====================================================================
//  TAB 3 — BACKPORT CANDIDATES
// =====================================================================
function backportControls() {
  const presets = [30, 60, 90, 120, 180];
  return el("div", { class: "controls" },
    el("div", { class: "group" }, el("label", {}, "Scan master"),
      el("select", { onchange: (e) => { S.backports.days = +e.target.value; renderBackports(); } },
        ...presets.map((d) => el("option", { value: d, selected: S.backports.days === d ? "" : null }, "last " + d + " days")))),
    el("div", { class: "group" }, el("label", {}, "Show"),
      el("div", { class: "pill-toggle" },
        el("button", { class: S.backports.onlyGaps ? "active" : "", onclick: () => { S.backports.onlyGaps = true; renderBackports(); } }, "Gaps only"),
        el("button", { class: !S.backports.onlyGaps ? "active" : "", onclick: () => { S.backports.onlyGaps = false; renderBackports(); } }, "All patches"))),
    el("span", { class: "small muted" }, "Click a row for ticket details & CI. ⚠ ticket-only = a companion patch may have been missed."));
}

async function renderBackports(refresh) {
  const root = $("#tab-backports");
  root.replaceChildren(backportControls(), loading("Diffing master against es6/es7 (several Gerrit queries)…"));
  let data;
  try { data = await api("/api/backports", { days: S.backports.days, only_gaps: S.backports.onlyGaps ? 1 : 0 }, refresh); }
  catch (e) { root.replaceChildren(backportControls(), el("div", { class: "banner error" }, String(e))); return; }

  const out = [backportControls()];

  // summary
  const tiles = el("div", { class: "tiles" });
  data.branches.forEach((b) => {
    const c = data.counts[b.key];
    tiles.append(el("div", { class: "tile" },
      el("div", { class: "v" }, (c.missing + c.ticket_only)),
      el("div", { class: "k" }, b.label + " gaps — " + c.missing + " missing, " + c.ticket_only + " ticket-only")));
  });
  tiles.append(el("div", { class: "tile" }, el("div", { class: "v" }, data.master_changes_scanned), el("div", { class: "k" }, "master patches scanned (" + data.scan_days + "d)")));
  const summaryCard = el("div", { class: "card" }, el("h2", {}, "Backport gap summary"), tiles,
    el("div", { class: "legend" },
      el("span", {}, statusChip("ported")),
      el("span", {}, statusChip("ticket_only"), " companion possibly missed"),
      el("span", {}, statusChip("missing"), " ticket absent from branch")));
  if (data.errors && data.errors.length) summaryCard.append(el("div", { class: "banner error", style: "margin-top:12px" }, el("h3", {}, "Some queries failed"), ...data.errors.slice(0, 4).map((e) => el("div", { class: "small mono" }, e))));
  out.push(summaryCard);

  // table
  const tbody = el("tbody");
  data.candidates.forEach((row) => tbody.append(...backportRow(row, data.branches)));
  const tableCard = el("div", { class: "card" },
    el("h2", {}, "Candidates" + (data.truncated ? " (showing first " + data.candidates.length + ")" : " (" + data.candidate_count + ")")),
    el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "Master patch"), el("th", {}, "Ticket"),
        ...data.branches.map((b) => el("th", {}, b.label)))),
      tbody)));
  out.push(tableCard);
  root.replaceChildren(...out);
}

function backportRow(row, branches) {
  const master = el("td", {},
    el("a", { href: row.url, target: "_blank", class: "mono" }, "#" + row.number),
    " ", el("span", { class: "subject" }, stripTicket(row.subject)),
    el("div", { class: "small muted" }, (row.owner || "") + " · " + (row.master_repo || "") + " · " + fmtDate(row.updated)));
  const cells = branches.map((b) => {
    const st = row.branches[b.key];
    const cell = el("td", {}, statusChip(st.state));
    if (st.state === "ported" && st.change) cell.append(" ", changeLink(st.change));
    if (st.state === "ticket_only" && st.related) cell.append(" ", el("span", { class: "small muted" }, st.related.length + " related"));
    if (st.state !== "ported") {
      cell.append(el("div", {}, el("button", {
        class: "btn sm", style: "margin-top:6px",
        onclick: (e) => { e.stopPropagation(); openPing(b, row); },
      }, "✉ Ping " + b.ping_name)));
    }
    return cell;
  });

  const tr = el("tr", { class: "clickable" }, master, el("td", {}, ticketLinks(row.tickets)), ...cells);
  const detail = el("tr", { class: "detail-row", style: "display:none" },
    el("td", { colspan: 2 + branches.length }, el("div", { class: "detail-grid detail-body" }, el("span", { class: "muted small" }, "click to load…"))));
  let loaded = false;
  tr.addEventListener("click", () => {
    const show = detail.style.display === "none";
    detail.style.display = show ? "" : "none";
    if (show && !loaded) { loaded = true; loadBackportDetail(detail.querySelector(".detail-body"), row, branches); }
  });
  return [tr, detail];
}

async function loadBackportDetail(box, row, branches) {
  box.replaceChildren(loading("Fetching ticket & CI details…"));
  const parts = [];
  // tickets
  for (const t of row.tickets) {
    const card = el("div", { class: "kv" }, el("div", {}, el("strong", {}, el("a", { href: t.url, target: "_blank" }, t.key))), loading("ticket…"));
    parts.push(card);
    api("/api/ticket", { key: t.key }).then((d) => renderTicketCard(card, d)).catch((e) => card.replaceChildren(el("div", {}, el("a", { href: t.url, target: "_blank" }, t.key)), el("div", { class: "small mono" }, String(e))));
  }
  // branch changes + CI
  branches.forEach((b) => {
    const st = row.branches[b.key];
    const changes = st.state === "ported" ? [st.change] : (st.related || []);
    if (!changes.length) return;
    const card = el("div", { class: "kv" }, el("div", { class: "k" }, b.label + " changes"));
    changes.forEach((c) => {
      const line = el("div", { class: "small" }, changeLink(c), " ", el("span", { class: "muted" }, stripTicket(c.subject || "").slice(0, 60)), " ", el("span", { class: "ci" }, ""));
      card.append(line);
      api("/api/change", { url: c.url }).then((d) => {
        if (!d.ok || d.verified == null) return;
        const cls = d.verified > 0 ? "good" : d.verified < 0 ? "bad" : "neutral";
        line.querySelector(".ci").replaceWith(el("span", { class: "chip " + cls }, d.label));
      }).catch(() => {});
    });
    parts.push(card);
  });
  box.replaceChildren(...(parts.length ? parts : [el("span", { class: "muted small" }, "No linked tickets or branch changes.")]));
}

function renderTicketCard(card, d) {
  if (!d.ok) { card.replaceChildren(el("div", {}, el("a", { href: d.url, target: "_blank" }, d.key)), el("div", { class: "small mono muted" }, d.error || "lookup failed")); return; }
  const isCustomer = d.is_cloud;
  const hot = /blocker|critical/i.test(d.priority || "");
  const chips = el("div", {});
  if (d.status) chips.append(el("span", { class: "chip neutral" }, d.status));
  if (d.priority) chips.append(" ", el("span", { class: "chip " + (hot ? "bad" : "neutral") }, d.priority));
  if (isCustomer) chips.append(" ", el("span", { class: "chip accent", title: "Tracked in the DDN cloud Jira (EX/DDN/etc.) — customer-facing tracker" }, "DDN tracker"));
  card.replaceChildren(
    el("div", {}, el("strong", {}, el("a", { href: d.url, target: "_blank" }, d.key)), " ", chips),
    el("div", { class: "small" }, d.summary || ""),
    el("div", { class: "small muted" }, [d.assignee ? "assignee " + d.assignee : null, (d.fix_versions || []).length ? "fixVersions " + d.fix_versions.join(", ") : null].filter(Boolean).join(" · ")));
}

// ---------- Teams ping modal ----------
async function openPing(branchMeta, row) {
  let data;
  try {
    data = await api("/api/ping", { branch: branchMeta.key, subject: row.subject, url: row.url, ticket: row.tickets.map((t) => t.key) });
  } catch (e) { alert("Could not build ping: " + e); return; }
  showPingModal(branchMeta, data);
}

function teamsLink(email, message) {
  return "https://teams.microsoft.com/l/chat/0/0?users=" + encodeURIComponent(email) + "&message=" + encodeURIComponent(message);
}

function showPingModal(branchMeta, data) {
  const ta = el("textarea", {}, data.message);
  const back = el("div", { class: "modal-back", onclick: (e) => { if (e.target === back) back.remove(); } },
    el("div", { class: "modal" },
      el("h2", {}, "Ping about backport to " + branchMeta.gerrit_branch),
      el("div", { class: "who" }, "To " + data.reviewer + " <" + data.email + "> — opens in Microsoft Teams; review & send yourself."),
      ta,
      el("div", { class: "actions" },
        el("button", { class: "btn", onclick: () => back.remove() }, "Cancel"),
        el("button", { class: "btn", onclick: (e) => { navigator.clipboard.writeText(ta.value); e.target.textContent = "Copied ✓"; } }, "Copy"),
        el("button", { class: "btn", onclick: () => { location.href = "mailto:" + data.email + "?subject=" + encodeURIComponent("Backport request: " + stripTicket(ta.value.split("\n")[1] || "")) + "&body=" + encodeURIComponent(ta.value); } }, "Email"),
        el("button", { class: "btn accent", onclick: () => window.open(teamsLink(data.email, ta.value), "_blank") }, "Open in Teams"))));
  $("#modal-root").replaceChildren(back);
}

// ---------- boot ----------
async function boot() {
  try { CFG = await api("/api/config"); }
  catch (e) { document.querySelector("main").append(el("div", { class: "banner error" }, "Could not load config: " + e)); return; }
  $("#today").textContent = CFG.today;
  $$("#tabs button").forEach((b) => b.addEventListener("click", () => {
    S.tab = b.dataset.tab;
    $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
    $$(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + S.tab));
    renderActive(false);
  }));
  $("#refresh").addEventListener("click", () => renderActive(true));
  renderActive(false);
}

function renderActive(refresh) {
  if (S.tab === "stability") return renderStability(refresh);
  if (S.tab === "landed") return renderLanded(refresh);
  if (S.tab === "backports") return renderBackports(refresh);
}

boot();
