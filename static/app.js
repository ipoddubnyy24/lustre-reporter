"use strict";
/* Lustre Reporter — Material UI SPA. Eager-loads every report on open. */

// ---------- DOM helpers ----------
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
function icon(name) {
  const t = document.createElement("template");
  t.innerHTML = (window.ICONS && window.ICONS[name]) || "";
  return t.content.firstChild;
}
const fmtDate = (s, withTime) => {
  if (!s) return "—";
  const str = String(s);
  return withTime ? str.slice(0, 16).replace("T", " ") : str.slice(0, 10);
};
const spinnerBox = (txt) => el("div", { class: "loading" }, el("span", { class: "spinner" }), txt || "Loading…");
const stripTicket = (s) => (s || "").replace(/^((?:LU|EX|DDN|EHT|GCP|IME|RM)-\d+[\s:-]+)+/i, "");

// ---------- progress plumbing ----------
let inflight = 0;
function bump(delta) {
  inflight = Math.max(0, inflight + delta);
  const busy = inflight > 0;
  $("#progress").classList.toggle("hidden", !busy);
  $("#refresh").classList.toggle("spinning", busy);
  $("#fab").classList.toggle("spinning", busy);
}
async function api(path, params, refresh) {
  const u = new URL(path, location.origin);
  if (params) for (const [k, v] of Object.entries(params)) {
    if (v == null) continue;
    if (Array.isArray(v)) v.forEach((x) => u.searchParams.append(k, x));
    else u.searchParams.set(k, v);
  }
  if (refresh) u.searchParams.set("refresh", "1");
  bump(1);
  try {
    const r = await fetch(u.toString());
    if (!r.ok) throw new Error("HTTP " + r.status + " for " + path);
    return await r.json();
  } finally { bump(-1); }
}

// ---------- state ----------
let CFG = null;
const S = {
  product: "lustre",       // "lustre" | "emf" — top-level switch
  tab: "stability",
  selected: [],            // branch keys shown across all reports (top-bar chips)
  stability: { days: 30, custom: false, from: "", to: "" },
  landed: { days: 7, mode: "days", tag: "" },
  backports: { days: 120, onlyGaps: true },
  emf: { stabilityDays: 30, tag: "" },
};
// stability/topfail are keyed by branch (one section per selected branch)
const DATA = { stability: {}, topfail: {}, landed: null, backports: null };
const LOADING = { landed: false, backports: false };
const EMFDATA = { stability: null, landed: null, coming: null };
const EMFLOADING = { stability: false, landed: false, coming: false };
let emfLoaded = false;
let autoTimer = null;

const selectedBranches = () => CFG.branches.filter((b) => S.selected.includes(b.key));
const isSelected = (key) => S.selected.includes(key);

// ---------- snackbar ----------
let snackTimer;
function snack(msg) {
  const s = $("#snackbar");
  s.textContent = msg;
  s.classList.add("show");
  clearTimeout(snackTimer);
  snackTimer = setTimeout(() => s.classList.remove("show"), 2800);
}
function markUpdated() {
  $("#updated").textContent = "Updated " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

// ---------- shared bits ----------
function statusChip(state) {
  if (state === "ported") return el("span", { class: "chip good" }, icon("check"), "Ported");
  if (state === "ticket_only")
    return el("span", { class: "chip warn", title: "Ticket is on this branch, but this patch's subject was not found — a companion patch may have been missed." }, icon("warning"), "Ticket only");
  return el("span", { class: "chip bad" }, icon("error"), "Missing");
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
function sourceBanner(res, tool) {
  const kind = res.kind || "error";
  const box = el("div", { class: "banner " + (kind === "error" ? "error" : "warn") },
    el("span", { class: "i-wrap" }, icon(kind === "error" ? "error" : "warning")));
  const body = el("div");
  if (tool === "maloo" && kind === "auth") {
    body.append(
      el("h3", {}, "Maloo credentials rejected (HTTP 401)"),
      el("div", {}, "The stability report reads nightly CI results from Maloo (testing.whamcloud.com). Add a working login and refresh:"),
      el("pre", {}, "edit ~/.config/maloo-tool/.env\n  MALOO_USER=<your testing.whamcloud.com login>\n  MALOO_PASS=<your testing.whamcloud.com password>"),
      el("div", { class: "small", style: "margin-top:8px;opacity:.85" }, res.error || ""));
  } else if (kind === "missing") {
    body.append(el("h3", {}, "Tool not installed"), el("div", {}, res.error || ""),
      el("pre", {}, "cd ~/work/src/llm_jira && ./install.sh"));
  } else {
    body.append(el("h3", {}, (tool || "Source") + " error"), el("div", { class: "small mono" }, res.error || "unknown error"));
  }
  box.append(body);
  return box;
}

// =====================================================================
//  STABILITY
// =====================================================================
function stabilityControls() {
  const st = S.stability;
  const presets = [7, 14, 30, 60, 90];
  const rangeSel = el("select", {
    onchange: (e) => {
      const v = e.target.value;
      if (v === "custom") st.custom = true;
      else { st.custom = false; st.days = +v; st.from = ""; st.to = ""; loadStability(false); }
      renderStability();
    },
  }, ...presets.map((d) => el("option", { value: d, selected: !st.custom && st.days === d ? "" : null }, "Last " + d + " days")),
    el("option", { value: "custom", selected: st.custom ? "" : null }, "Custom range…"));

  const row = el("div", { class: "controls" },
    el("div", { class: "field" }, el("label", {}, "Period"), rangeSel),
    el("span", { class: "muted small", style: "align-self:flex-end" }, "Pick branches with the es6 / es7 chips in the top bar."));

  if (st.custom) {
    const from = el("input", { type: "date", value: st.from || "", max: CFG.today, onchange: (e) => { st.from = e.target.value; } });
    const to = el("input", { type: "date", value: st.to || CFG.today, max: CFG.today, onchange: (e) => { st.to = e.target.value; } });
    row.append(
      el("div", { class: "field" }, el("label", {}, "From"), from),
      el("div", { class: "field" }, el("label", {}, "To"), to),
      el("button", { class: "btn filled sm", style: "align-self:flex-end", onclick: () => loadStability(false) }, "Apply"));
  }
  return row;
}

async function loadStability(refresh) {
  const st = S.stability;
  const branches = selectedBranches();
  DATA.stability = {}; DATA.topfail = {};
  renderStability();
  await Promise.all(branches.map(async (b) => {
    const params = { branch: b.key, days: st.days };
    if (st.custom && st.from) { params.from = st.from; params.to = st.to || CFG.today; }
    try { DATA.stability[b.key] = await api("/api/stability", params, refresh); }
    catch (e) { DATA.stability[b.key] = { ok: false, kind: "error", error: String(e) }; }
    renderStability();
    // top failures load independently (slower)
    try { DATA.topfail[b.key] = await api("/api/top-failures", { branch: b.key, days: st.days }, refresh); }
    catch (e) { DATA.topfail[b.key] = { ok: false, kind: "error", error: String(e) }; }
    renderStability();
  }));
}

function renderStability() {
  const root = $("#tab-stability");
  const out = [stabilityControls()];
  selectedBranches().forEach((b) => {
    out.push(el("div", { class: "branch-heading" }, b.label, el("span", { class: "chip primary" }, b.gerrit_branch)));
    const data = DATA.stability[b.key];
    if (!data) { out.push(el("div", { class: "card" }, spinnerBox("Querying Maloo for " + b.label + "…"))); return; }
    if (!data.ok) {
      out.push(sourceBanner(data, "maloo"));
      out.push(el("div", { class: "card muted small" }, "Trigger job: ", el("code", {}, data.trigger_job || "?"),
        ". Once Maloo authenticates, this shows the nightly pass-rate trend, per-day drill-down, and the top failing tests."));
      return;
    }
    out.push(statsCard(data), trendCard(data), failuresCard(b), sessionsCard(data.sessions));
  });
  root.replaceChildren(...out);
}
const tile = (cls, v, k) => el("div", { class: "tile " + cls }, el("div", { class: "v" }, v), el("div", { class: "k" }, k));

function statsCard(data) {
  const sum = data.summary;
  const rc = (r) => r == null ? "" : (r >= 90 ? "good" : r >= 70 ? "warn" : "bad");
  return el("div", { class: "card" },
    el("h2", {}, "Stability — " + data.label),
    el("div", { class: "card-sub" }, "Period " + (data.from ? data.from + " → " + (data.to || CFG.today) : "last " + data.days + " days")),
    el("div", { class: "tiles" },
      tile(rc(sum.session_pass_rate), sum.session_pass_rate == null ? "—" : sum.session_pass_rate + "%", "clean sessions"),
      tile(rc(sum.testset_pass_rate), sum.testset_pass_rate == null ? "—" : sum.testset_pass_rate + "%", "test-set pass rate"),
      tile("", sum.sessions, "sessions"),
      tile(sum.failed_sessions ? "warn" : "good", sum.failed_sessions, "sessions with failures"),
      tile(sum.testsets_failed ? "bad" : "good", sum.testsets_failed, "test-sets failed")));
}

function trendCard(data) {
  return el("div", { class: "card" }, el("h2", {}, "Stability trend"),
    data.trend.length ? drawTrend(data.trend) : el("div", { class: "empty" }, "No sessions in this period."),
    el("div", { class: "legend" },
      el("span", {}, el("i", { class: "dot-key", style: "background:var(--md-primary)" }), "clean-session %"),
      el("span", {}, el("i", { class: "dot-key", style: "background:var(--md-on-surface-variant);opacity:.4" }), "sessions/day")));
}

function failuresCard(b) {
  const card = el("div", { class: "card" }, el("h2", { style: "display:inline-flex;align-items:center;gap:8px" }, icon("science"), "Top failing tests"));
  const tf = DATA.topfail[b.key];
  if (!tf) { card.append(spinnerBox("Aggregating failures…")); return card; }
  if (!tf.ok) { card.append(sourceBanner(tf, "maloo")); return card; }
  if (!tf.failures.length) { card.append(el("div", { class: "empty" }, "No failures found. 🎉")); return card; }
  const rows = tf.failures.map((f) => el("tr", {},
    el("td", { class: "num" }, f.rank), el("td", {}, el("span", { class: "mono" }, f.suite || "—")),
    el("td", { class: "subject" }, f.test_name), el("td", { class: "num" }, f.count), el("td", { class: "num" }, f.session_count),
    el("td", { class: "small muted", title: f.error_sample || "" }, (f.error_sample || "").slice(0, 80))));
  card.append(el("div", { class: "scroll-x" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", { class: "num" }, "#"), el("th", {}, "Suite"), el("th", {}, "Test"), el("th", { class: "num" }, "Fails"), el("th", { class: "num" }, "Sessions"), el("th", {}, "Sample error"))),
    el("tbody", {}, ...rows))));
  return card;
}

function sessionsCard(sessions) {
  const card = el("div", { class: "card" }, el("h2", {}, "Sessions (" + sessions.length + ")"));
  if (!sessions.length) { card.append(el("div", { class: "empty" }, "No sessions.")); return card; }
  const rows = sessions.map((s) => el("tr", {},
    el("td", {}, s.clean ? el("span", { class: "chip good" }, icon("check"), "clean") : el("span", { class: "chip bad" }, "fail")),
    el("td", { class: "nowrap" }, fmtDate(s.date, true)), el("td", { class: "mono small" }, s.host || "—"),
    el("td", {}, s.name || s.group || "—"), el("td", { class: "num" }, s.passed), el("td", { class: "num" }, s.failed),
    el("td", { class: "num" }, s.aborted), el("td", {}, s.url ? el("a", { href: s.url, target: "_blank" }, "open") : "—")));
  card.append(el("div", { class: "scroll-x" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", {}, "Result"), el("th", {}, "Submitted"), el("th", {}, "Host"), el("th", {}, "Suite/name"), el("th", { class: "num" }, "Pass"), el("th", { class: "num" }, "Fail"), el("th", { class: "num" }, "Abort"), el("th", {}, "Link"))),
    el("tbody", {}, ...rows))));
  return card;
}

function drawTrend(trend, opts) {
  opts = opts || {};
  const barKey = opts.barKey || "sessions";
  const rateKey = opts.rateKey || "session_pass_rate";
  const tip = opts.tip || ((d) => d.date + ": " + d.session_pass_rate + "% clean · " +
    d.sessions + " sessions · " + d.testsets_failed + " test-sets failed");
  const W = 900, H = 260, padL = 38, padR = 14, padT = 14, padB = 30;
  const iw = W - padL - padR, ih = H - padT - padB, n = trend.length;
  const maxS = Math.max(1, ...trend.map((d) => d[barKey] || 0));
  const rate = (d) => (d[rateKey] == null ? 0 : d[rateKey]);
  const x = (i) => padL + (n === 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (r) => padT + ih - (Math.max(0, Math.min(100, r)) / 100) * ih;
  const S2 = "http://www.w3.org/2000/svg";
  const mk = (t, a, ...k) => { const e = document.createElementNS(S2, t); for (const [kk, vv] of Object.entries(a || {})) e.setAttribute(kk, vv); k.forEach((c) => e.append(c)); return e; };
  const g = mk("g");
  [0, 25, 50, 75, 100].forEach((v) => {
    g.append(mk("line", { class: "grid", x1: padL, y1: y(v), x2: W - padR, y2: y(v) }));
    g.append(mk("text", { x: padL - 6, y: y(v) + 3, "text-anchor": "end" }, document.createTextNode(v + "%")));
  });
  const bw = Math.max(1, iw / Math.max(n, 1) * 0.5);
  trend.forEach((d, i) => { const bh = ((d[barKey] || 0) / maxS) * ih * 0.5; g.append(mk("rect", { class: "bar", x: x(i) - bw / 2, y: padT + ih - bh, width: bw, height: bh, rx: 1.5 })); });
  const pts = trend.map((d, i) => [x(i), y(rate(d))]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  g.append(mk("path", { class: "area", d: line + " L" + pts[n - 1][0].toFixed(1) + " " + (padT + ih) + " L" + pts[0][0].toFixed(1) + " " + (padT + ih) + " Z" }));
  g.append(mk("path", { class: "line", d: line }));
  trend.forEach((d, i) => {
    const dot = mk("circle", { class: "dot", cx: x(i), cy: y(rate(d)), r: 3.5 });
    dot.append(mk("title", {}, document.createTextNode(tip(d))));
    g.append(dot);
  });
  const idxs = n <= 1 ? [0] : [...new Set([0, Math.floor((n - 1) / 2), n - 1])];
  idxs.forEach((i) => g.append(mk("text", { x: x(i), y: H - 8, "text-anchor": i === 0 ? "start" : (i === n - 1 ? "end" : "middle") }, document.createTextNode(trend[i].date.slice(5)))));
  return mk("svg", { class: "trend", viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "xMidYMid meet" },
    mk("line", { class: "axis", x1: padL, y1: padT, x2: padL, y2: padT + ih }),
    mk("line", { class: "axis", x1: padL, y1: padT + ih, x2: W - padR, y2: padT + ih }), g);
}

// =====================================================================
//  LANDED
// =====================================================================
function landedControls() {
  const L = S.landed;
  const sel = el("select", {
    onchange: (e) => {
      const v = e.target.value;
      if (v === "tag") { L.mode = "tag"; }
      else { L.mode = "days"; L.days = +v; L.tag = ""; }
      loadLanded(false);
    },
  },
    ...[7, 14, 30].map((d) => el("option", { value: d, selected: L.mode === "days" && L.days === d ? "" : null }, "Last " + d + " days")),
    el("option", { value: "tag", selected: L.mode === "tag" ? "" : null }, "Since last tag"));
  const row = el("div", { class: "controls" },
    el("div", { class: "field" }, el("label", {}, "Window"), sel));
  if (L.mode === "tag") {
    const input = el("input", {
      type: "text", value: L.tag || "", placeholder: "latest",
      title: "Blank = each branch's latest tag; or type a tag, e.g. 2.16.0-ddn52",
      oninput: (e) => { L.tag = e.target.value; },
      onkeydown: (e) => { if (e.key === "Enter") { L.tag = e.target.value.trim(); loadLanded(false); } },
    });
    row.append(
      el("div", { class: "field" }, el("label", {}, "Tag"), input),
      el("button", { class: "btn filled sm", style: "align-self:flex-end", onclick: () => { L.tag = input.value.trim(); loadLanded(false); } }, "Apply"));
  }
  if (CFG.confluence_enabled) {
    row.append(el("button", {
      class: "btn tonal sm", style: "align-self:flex-end",
      title: "Build the per-build QA changelog and publish it to Confluence now",
      onclick: (e) => publishToConfluence(e.currentTarget),
    }, icon("publish"), "Publish to Confluence"));
  }
  row.append(el("span", { class: "muted small", style: "align-self:flex-end" },
    L.mode !== "tag" ? "Patches merged to each ExaScaler branch."
      : (L.tag ? "Patches merged since tag " + L.tag + "." : "Patches merged since each branch's latest tag (blank = latest).")));
  return row;
}
async function publishToConfluence(btn) {
  const saved = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = "Publishing…";
  try {
    const r = await api("/api/publish", {}, true);
    const results = r.results || [];
    if (results.length && results.some((x) => x.ok)) {
      snack("Confluence: " + results.map((x) => x.branch + " " + (x.ok ? x.action : "failed")).join(" · "));
    } else {
      snack("Publish failed: " + (r.error || results.map((x) => x.error).filter(Boolean)[0] || "unknown"));
    }
  } catch (e) { snack("Publish failed: " + e); }
  finally { btn.disabled = false; btn.innerHTML = saved; }
}
async function loadLanded(refresh) {
  LOADING.landed = true; renderLanded();
  try { DATA.landed = await api("/api/landed", { mode: S.landed.mode, days: S.landed.days, tag: S.landed.tag || undefined }, refresh); }
  catch (e) { DATA.landed = { branches: [], error: String(e) }; }
  LOADING.landed = false; renderLanded();
}
function renderLanded() {
  const root = $("#tab-landed");
  const out = [landedControls()];
  if (LOADING.landed || !DATA.landed) { out.push(el("div", { class: "card" }, spinnerBox("Querying Gerrit…"))); root.replaceChildren(...out); return; }
  const shown = DATA.landed.branches.filter((b) => isSelected(b.key));
  setBadge("landed", shown.reduce((a, b) => a + (b.count || 0), 0));
  const tagMode = DATA.landed.mode === "tag";
  for (const b of shown) {
    const head = el("h2", {}, b.label, "  ", el("span", { class: "chip primary" }, b.gerrit_branch));
    if (tagMode && b.tag) head.append(" ", el("span", { class: "chip tertiary", title: (b.tag_manual ? "specified tag" : "latest tag") + (b.tag_date ? " · " + b.tag_date : "") }, b.tag));
    const meta = !b.ok ? "" : (tagMode ? b.count + " since tag" : b.count + " merged in " + DATA.landed.days + "d");
    head.append("  ", el("span", { class: "muted small" }, meta));
    const card = el("div", { class: "card" }, head);
    if (b.fetch_note) card.append(el("div", { class: "muted small", style: "margin-bottom:8px" }, "⚠ " + b.fetch_note));
    if (!b.ok) { card.append(sourceBanner(b, tagMode ? "git" : "gerrit")); out.push(card); continue; }
    if (!b.count) { card.append(el("div", { class: "empty" }, tagMode ? "Nothing merged since " + (b.tag || "the last tag") + "." : "Nothing merged in this window.")); out.push(card); continue; }
    const rows = b.patches.map((p) => el("tr", {},
      el("td", {}, el("a", { href: p.url, target: "_blank", class: "mono" }, "#" + p.number)),
      el("td", {}, ticketLinks(p.tickets)), el("td", { class: "subject" }, stripTicket(p.subject)),
      el("td", { class: "owner nowrap" }, p.owner || "—"), el("td", { class: "nowrap" }, fmtDate(p.updated)),
      el("td", { class: "mono small nowrap" }, p.size || "")));
    card.append(el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Patch"), el("th", {}, "Ticket"), el("th", {}, "Subject"), el("th", {}, "Owner"), el("th", {}, "Merged"), el("th", {}, "Size"))),
      el("tbody", {}, ...rows))));
    out.push(card);
  }
  root.replaceChildren(...out);
}

// =====================================================================
//  BACKPORTS
// =====================================================================
function backportControls() {
  return el("div", { class: "controls" },
    el("div", { class: "field" }, el("label", {}, "Scan master"),
      el("select", { onchange: (e) => { S.backports.days = +e.target.value; loadBackports(false); } },
        ...[30, 60, 90, 120, 180].map((d) => el("option", { value: d, selected: S.backports.days === d ? "" : null }, "Last " + d + " days")))),
    el("div", { class: "field" }, el("label", {}, "Show"),
      el("div", { class: "pill-toggle" },
        el("button", { class: S.backports.onlyGaps ? "active" : "", onclick: () => { S.backports.onlyGaps = true; loadBackports(false); } }, "Gaps only"),
        el("button", { class: !S.backports.onlyGaps ? "active" : "", onclick: () => { S.backports.onlyGaps = false; loadBackports(false); } }, "All patches"))),
    el("span", { class: "muted small", style: "align-self:flex-end" }, "Click a row for ticket details & CI."));
}
async function loadBackports(refresh) {
  LOADING.backports = true; renderBackports();
  try { DATA.backports = await api("/api/backports", { days: S.backports.days, only_gaps: S.backports.onlyGaps ? 1 : 0 }, refresh); }
  catch (e) { DATA.backports = { error: String(e), candidates: [], branches: [], counts: {} }; }
  LOADING.backports = false; renderBackports();
}
function renderBackports() {
  const root = $("#tab-backports");
  const out = [backportControls()];
  const data = DATA.backports;
  if (LOADING.backports || !data) { out.push(el("div", { class: "card" }, spinnerBox("Diffing master against es6/es7…"))); root.replaceChildren(...out); return; }
  if (data.error) { out.push(el("div", { class: "banner error" }, el("span", { class: "i-wrap" }, icon("error")), el("div", {}, data.error))); root.replaceChildren(...out); return; }

  const shown = data.branches.filter((b) => isSelected(b.key));
  const rows = S.backports.onlyGaps
    ? data.candidates.filter((r) => shown.some((b) => r.branches[b.key] && r.branches[b.key].state !== "ported"))
    : data.candidates;
  setBadge("backports", rows.length);

  const tiles = el("div", { class: "tiles" });
  shown.forEach((b) => {
    const c = data.counts[b.key];
    tiles.append(el("div", { class: "tile " + (c.missing + c.ticket_only ? "warn" : "good") },
      el("div", { class: "v" }, c.missing + c.ticket_only),
      el("div", { class: "k" }, b.label + " gaps — " + c.missing + " missing · " + c.ticket_only + " ticket-only")));
  });
  tiles.append(tile("", data.master_changes_scanned, "master patches scanned (" + data.scan_days + "d)"));
  const summary = el("div", { class: "card" }, el("h2", {}, "Backport gap summary"), tiles,
    el("div", { class: "legend" },
      el("span", {}, statusChip("ported")), el("span", {}, statusChip("ticket_only"), " companion possibly missed"),
      el("span", {}, statusChip("missing"), " ticket absent from branch")));
  if (data.errors && data.errors.length)
    summary.append(el("div", { class: "banner error", style: "margin-top:14px" }, el("span", { class: "i-wrap" }, icon("error")),
      el("div", {}, el("h3", {}, "Some queries failed"), ...data.errors.slice(0, 4).map((e) => el("div", { class: "small mono" }, e)))));
  out.push(summary);

  const tbody = el("tbody");
  rows.forEach((row) => tbody.append(...backportRow(row, shown)));
  out.push(el("div", { class: "card" },
    el("h2", {}, "Candidates (" + rows.length + ")" + (data.truncated ? " · server-capped at " + data.candidates.length + " scanned" : "")),
    el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Master patch"), el("th", {}, "Ticket"), ...shown.map((b) => el("th", {}, b.label)))),
      tbody))));
  root.replaceChildren(...out);
}
function backportRow(row, branches) {
  const master = el("td", {}, el("a", { href: row.url, target: "_blank", class: "mono" }, "#" + row.number),
    " ", el("span", { class: "subject" }, stripTicket(row.subject)),
    el("div", { class: "small muted" }, (row.owner || "") + " · " + (row.master_repo || "") + " · " + fmtDate(row.updated)));
  const cells = branches.map((b) => {
    const st = row.branches[b.key];
    const cell = el("td", {}, statusChip(st.state));
    if (st.state === "ported" && st.change) cell.append(" ", changeLink(st.change));
    if (st.state === "ticket_only" && st.related) cell.append(" ", el("span", { class: "small muted" }, st.related.length + " related"));
    if (st.state !== "ported")
      cell.append(el("div", { style: "margin-top:8px" }, el("button", { class: "btn tonal sm", onclick: (e) => { e.stopPropagation(); openPing(b, row); } }, icon("mail"), "Ping " + b.ping_name)));
    return cell;
  });
  const tr = el("tr", { class: "clickable" }, master, el("td", {}, ticketLinks(row.tickets)), ...cells);
  const detail = el("tr", { class: "detail-row", style: "display:none" },
    el("td", { colspan: 2 + branches.length }, el("div", { class: "detail-grid detail-body" })));
  let loaded = false;
  tr.addEventListener("click", () => {
    const show = detail.style.display === "none";
    detail.style.display = show ? "" : "none";
    if (show && !loaded) { loaded = true; loadBackportDetail(detail.querySelector(".detail-body"), row, branches); }
  });
  return [tr, detail];
}
async function loadBackportDetail(box, row, branches) {
  box.replaceChildren(spinnerBox("Fetching ticket & CI…"));
  const parts = [];
  for (const t of row.tickets) {
    const card = el("div", { class: "kv" }, el("div", {}, el("strong", {}, el("a", { href: t.url, target: "_blank" }, t.key))), spinnerBox("ticket…"));
    parts.push(card);
    api("/api/ticket", { key: t.key }).then((d) => renderTicketCard(card, d)).catch((e) => card.replaceChildren(el("div", {}, el("a", { href: t.url, target: "_blank" }, t.key)), el("div", { class: "small mono" }, String(e))));
  }
  branches.forEach((b) => {
    const st = row.branches[b.key];
    const changes = st.state === "ported" ? [st.change] : (st.related || []);
    if (!changes.length) return;
    const card = el("div", { class: "kv" }, el("div", { class: "k" }, b.label + " changes"));
    changes.forEach((c) => {
      const line = el("div", { class: "small", style: "margin-top:4px" }, changeLink(c), " ", el("span", { class: "muted" }, stripTicket(c.subject || "").slice(0, 56)), " ", el("span", { class: "ci" }));
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
  const hot = /blocker|critical/i.test(d.priority || "");
  const chips = el("div", { style: "margin:4px 0" });
  if (d.status) chips.append(el("span", { class: "chip neutral" }, d.status));
  if (d.priority) chips.append(" ", el("span", { class: "chip " + (hot ? "bad" : "neutral") }, d.priority));
  if (d.is_cloud) chips.append(" ", el("span", { class: "chip primary", title: "Tracked in the DDN cloud Jira — customer-facing tracker" }, "DDN tracker"));
  card.replaceChildren(
    el("div", {}, el("strong", {}, el("a", { href: d.url, target: "_blank" }, d.key))), chips,
    el("div", { class: "small" }, d.summary || ""),
    el("div", { class: "small muted", style: "margin-top:4px" }, [d.assignee ? "assignee " + d.assignee : null, (d.fix_versions || []).length ? "fixVersions " + d.fix_versions.join(", ") : null].filter(Boolean).join(" · ")));
}

// ---------- Teams ping dialog ----------
async function openPing(branchMeta, row) {
  let data;
  try { data = await api("/api/ping", { branch: branchMeta.key, subject: row.subject, url: row.url, ticket: row.tickets.map((t) => t.key) }); }
  catch (e) { snack("Could not build ping: " + e); return; }
  const teamsLink = (email, message) => "https://teams.microsoft.com/l/chat/0/0?users=" + encodeURIComponent(email) + "&message=" + encodeURIComponent(message);
  const ta = el("textarea", {}, data.message);
  const scrim = el("div", { class: "scrim", onclick: (e) => { if (e.target === scrim) scrim.remove(); } },
    el("div", { class: "dialog" },
      el("h2", {}, "Backport ping — " + branchMeta.gerrit_branch),
      el("div", { class: "who" }, "To " + data.reviewer + " <" + data.email + ">. Opens in Microsoft Teams; review & send yourself."),
      ta,
      el("div", { class: "actions" },
        el("button", { class: "btn text", onclick: () => scrim.remove() }, "Cancel"),
        el("button", { class: "btn text", onclick: (e) => { navigator.clipboard.writeText(ta.value); e.currentTarget.textContent = "Copied"; } }, icon("copy"), "Copy"),
        el("button", { class: "btn tonal", onclick: () => { location.href = "mailto:" + data.email + "?subject=" + encodeURIComponent("Backport request") + "&body=" + encodeURIComponent(ta.value); } }, icon("mail"), "Email"),
        el("button", { class: "btn filled", onclick: () => window.open(teamsLink(data.email, ta.value), "_blank") }, icon("open_in_new"), "Open in Teams"))));
  $("#dialog-root").replaceChildren(scrim);
}

// =====================================================================
//  EMF — build stability (GitHub Actions), landed (CalVer), coming (forecast)
// =====================================================================
async function loadEmfStability(refresh) {
  EMFLOADING.stability = true; renderEmfStability();
  try { EMFDATA.stability = await api("/api/emf/stability", { days: S.emf.stabilityDays }, refresh); }
  catch (e) { EMFDATA.stability = { ok: false, kind: "error", error: String(e) }; }
  EMFLOADING.stability = false; renderEmfStability();
}
async function loadEmfLanded(refresh) {
  EMFLOADING.landed = true; renderEmfLanded();
  try { EMFDATA.landed = await api("/api/emf/landed", { tag: S.emf.tag || undefined }, refresh); }
  catch (e) { EMFDATA.landed = { ok: false, error: String(e) }; }
  EMFLOADING.landed = false; renderEmfLanded();
}
async function loadEmfComing(refresh) {
  EMFLOADING.coming = true; renderEmfComing();
  try { EMFDATA.coming = await api("/api/emf/coming", {}, refresh); }
  catch (e) { EMFDATA.coming = { ok: false, error: String(e) }; }
  EMFLOADING.coming = false; renderEmfComing();
}

function renderEmfStability() {
  const root = $("#tab-emf-stability");
  if (!root) return;
  const presets = [7, 14, 30, 60, 90];
  const controls = el("div", { class: "controls" },
    el("div", { class: "field" }, el("label", {}, "Period"),
      el("select", { onchange: (e) => { S.emf.stabilityDays = +e.target.value; loadEmfStability(false); } },
        ...presets.map((d) => el("option", { value: d, selected: S.emf.stabilityDays === d ? "" : null }, "Last " + d + " days")))),
    el("span", { class: "muted small", style: "align-self:flex-end" },
      "CI pass-rate of the EMF nightly workflow" + (CFG.emf && CFG.emf.workflow ? " (" + CFG.emf.workflow + ")" : "") + "."));
  const out = [controls];
  const d = EMFDATA.stability;
  if (EMFLOADING.stability || !d) { out.push(el("div", { class: "card" }, spinnerBox("Querying GitHub Actions…"))); root.replaceChildren(...out); return; }
  if (!d.ok) { out.push(sourceBanner(d, "GitHub")); root.replaceChildren(...out); return; }
  const sum = d.summary, rc = (r) => r == null ? "" : (r >= 90 ? "good" : r >= 70 ? "warn" : "bad");
  out.push(el("div", { class: "card" },
    el("h2", {}, "Build stability — " + (d.repo || "EMF")),
    el("div", { class: "card-sub" }, "Workflow " + (d.workflow || "?") + " · last " + d.days + " days"),
    el("div", { class: "tiles" },
      tile(rc(sum.pass_rate), sum.pass_rate == null ? "—" : sum.pass_rate + "%", "pass rate"),
      tile("", sum.runs, "runs"),
      tile(sum.passed ? "good" : "", sum.passed, "passed"),
      tile(sum.failed ? "bad" : "good", sum.failed, "failed"),
      tile("", sum.other, "cancelled / skipped"))));
  out.push(el("div", { class: "card" }, el("h2", {}, "Stability trend"),
    d.trend.length ? drawTrend(d.trend, {
      barKey: "runs", rateKey: "pass_rate",
      tip: (x) => x.date + ": " + (x.pass_rate == null ? "n/a" : x.pass_rate + "% pass") + " · " + x.runs + " runs · " + x.failed + " failed",
    }) : el("div", { class: "empty" }, "No runs in this period."),
    el("div", { class: "legend" },
      el("span", {}, el("i", { class: "dot-key", style: "background:var(--md-primary)" }), "pass %"),
      el("span", {}, el("i", { class: "dot-key", style: "background:var(--md-on-surface-variant);opacity:.4" }), "runs/day"))));
  const runs = d.runs || [];
  const rcard = el("div", { class: "card" }, el("h2", {}, "Recent runs (" + runs.length + ")"));
  if (!runs.length) { rcard.append(el("div", { class: "empty" }, "No runs.")); }
  else {
    const chip = (c) => el("span", { class: "chip " + (c === "success" ? "good" : c === "failure" ? "bad" : "neutral") }, c || "?");
    const rows = runs.map((r) => el("tr", {},
      el("td", {}, chip(r.conclusion)), el("td", { class: "nowrap" }, fmtDate(r.date, true)),
      el("td", { class: "mono small" }, r.branch || "—"), el("td", { class: "small muted" }, r.event || ""),
      el("td", {}, r.url ? el("a", { href: r.url, target: "_blank" }, "open") : "—")));
    rcard.append(el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Result"), el("th", {}, "When"), el("th", {}, "Branch"), el("th", {}, "Event"), el("th", {}, "Link"))),
      el("tbody", {}, ...rows))));
  }
  out.push(rcard);
  root.replaceChildren(...out);
}

function renderEmfLanded() {
  const root = $("#tab-emf-landed");
  if (!root) return;
  const input = el("input", {
    type: "text", value: S.emf.tag || "", placeholder: "latest CalVer",
    title: "Blank = since the newest CalVer release; or type a release tag, e.g. 6.3.8-2026061600",
    onkeydown: (e) => { if (e.key === "Enter") { S.emf.tag = e.target.value.trim(); loadEmfLanded(false); } },
  });
  const controls = el("div", { class: "controls" },
    el("div", { class: "field" }, el("label", {}, "Since release"), input),
    el("button", { class: "btn filled sm", style: "align-self:flex-end", onclick: () => { S.emf.tag = input.value.trim(); loadEmfLanded(false); } }, "Apply"),
    el("span", { class: "muted small", style: "align-self:flex-end" }, "Merged onto the release branch since the newest CalVer release."));
  const out = [controls];
  const d = EMFDATA.landed;
  if (EMFLOADING.landed || !d) { out.push(el("div", { class: "card" }, spinnerBox("Querying GitHub…"))); root.replaceChildren(...out); return; }
  if (!d.ok) { out.push(sourceBanner(d, "GitHub")); root.replaceChildren(...out); return; }
  setBadge("emf-landed", d.count || 0);
  const head = el("h2", {}, el("span", { class: "mono" }, d.branch || "release"));
  if (d.tag) head.append(" ", el("span", { class: "chip tertiary", title: (d.manual ? "chosen" : "latest") + " release" + (d.tag_date ? " · " + d.tag_date : "") }, d.tag));
  head.append("  ", el("span", { class: "muted small" }, (d.count || 0) + " since release" + (d.ahead != null ? " · " + d.ahead + " commits ahead" : "")));
  const card = el("div", { class: "card" }, head);
  if (!d.count) { card.append(el("div", { class: "empty" }, "Nothing merged since " + (d.tag || "the last release") + ".")); out.push(card); root.replaceChildren(...out); return; }
  if (d.areas && d.areas.length) card.append(el("div", { class: "muted small", style: "margin:2px 0 12px" }, "Areas: " + d.areas.map((a) => a[0] + " ×" + a[1]).join(" · ")));
  const rows = d.patches.map((p) => el("tr", {},
    el("td", {}, p.url ? el("a", { href: p.url, target: "_blank", class: "mono" }, p.number ? "#" + p.number : "commit") : "—"),
    el("td", {}, ticketLinks(p.tickets)), el("td", { class: "subject" }, stripTicket(p.subject)),
    el("td", { class: "owner nowrap" }, p.owner || "—"), el("td", { class: "nowrap" }, fmtDate(p.date))));
  card.append(el("div", { class: "scroll-x" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", {}, "PR"), el("th", {}, "Ticket"), el("th", {}, "Subject"), el("th", {}, "Author"), el("th", {}, "Merged"))),
    el("tbody", {}, ...rows))));
  out.push(card);
  root.replaceChildren(...out);
}

function probBar(p, tier) {
  const pct = p == null ? null : Math.round(p * 100);
  return el("span", { class: "prob-bar" },
    el("span", { class: "track tier-" + (tier || "other") }, el("i", { style: "width:" + (pct == null ? 0 : pct) + "%" })),
    el("span", { class: "pct" }, pct == null ? "—" : pct + "%"));
}
function prLinks(prs) {
  if (!prs || !prs.length) return el("span", { class: "muted" }, "—");
  const wrap = el("span");
  prs.forEach((p, i) => {
    if (i) wrap.append(" ");
    wrap.append(el("a", { href: p.url, target: "_blank", class: "mono", title: p.draft ? "draft PR" : "open PR" }, "#" + p.number + (p.draft ? "*" : "")));
  });
  return wrap;
}
function renderEmfComing() {
  const root = $("#tab-emf-coming");
  if (!root) return;
  const out = [el("div", { class: "controls" },
    el("span", { class: "muted small" }, "Forecast of what lands in each upcoming release — open Jira items weighted by status and days-to-release. Green = likely, red = unlikely.")) ];
  const d = EMFDATA.coming;
  if (EMFLOADING.coming || !d) { out.push(el("div", { class: "card" }, spinnerBox("Fetching Jira items & release dates…"))); root.replaceChildren(...out); return; }
  if (!d.ok) { out.push(sourceBanner(d, "Jira")); root.replaceChildren(...out); return; }
  if (!d.releases.length) { out.push(el("div", { class: "card" }, el("div", { class: "empty" }, "No upcoming releases with a date in the " + (d.project || "EX") + " project."))); root.replaceChildren(...out); return; }
  setBadge("emf-coming", d.releases.reduce((a, r) => a + Math.round(r.expected || 0), 0));
  d.releases.forEach((r) => out.push(comingCard(r)));
  root.replaceChildren(...out);
}
function comingCard(r) {
  const daysChip = () => {
    if (r.days == null) return el("span", { class: "chip neutral" }, "no date");
    if (r.days < 0) return el("span", { class: "chip bad" }, Math.abs(r.days) + "d overdue");
    if (r.days <= 10) return el("span", { class: "chip warn" }, "in " + r.days + "d");
    return el("span", { class: "chip neutral" }, "in " + r.days + "d");
  };
  const pct = r.total ? Math.round((r.expected / r.total) * 100) : 0;
  const card = el("div", { class: "card" },
    el("h2", { style: "display:flex;align-items:center;gap:10px;flex-wrap:wrap" },
      r.name, el("span", { class: "chip tertiary" }, fmtDate(r.release_date)), daysChip()));
  if (!r.items_ok) { card.append(sourceBanner({ kind: "error", error: r.items_error }, "Jira")); return card; }
  card.append(el("div", { class: "card-sub", style: "margin-top:8px" },
    "Expected to land: ", el("strong", {}, "~" + r.expected + " of " + r.total + " open"), " (" + pct + "%)"));
  card.append(el("div", { class: "meter", title: "~" + r.expected + " of " + r.total + " expected to land" }, el("i", { style: "width:" + pct + "%" })));
  const t = r.tiers || {}, tc = (k) => (t[k] && t[k].count) || 0, te = (k) => (t[k] && t[k].expected) || 0;
  const tiles = el("div", { class: "tiles", style: "margin-top:14px" },
    tile("good", tc("review"), "in review (~" + te("review") + " land)"),
    tile("warn", tc("progress"), "in progress (~" + te("progress") + " land)"),
    tile("bad", tc("todo"), "to do (~" + te("todo") + " land)"));
  if (tc("other")) tiles.append(tile("", tc("other"), "other status"));
  card.append(tiles);
  const items = r.items || [];
  if (items.length) {
    const rows = items.map((it) => el("tr", {},
      el("td", {}, probBar(it.probability, it.tier)),
      el("td", {}, el("span", { class: "chip tier-" + it.tier }, it.status || "?")),
      el("td", {}, el("a", { href: it.url, target: "_blank", class: "ticket-link" }, it.key)),
      el("td", { class: "subject" }, it.summary || ""),
      el("td", { class: "owner nowrap" }, it.assignee || "—"),
      el("td", {}, prLinks(it.prs))));
    card.append(el("div", { class: "scroll-x", style: "margin-top:10px" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Chance"), el("th", {}, "Status"), el("th", {}, "Ticket"), el("th", {}, "Summary"), el("th", {}, "Assignee"), el("th", {}, "PRs"))),
      el("tbody", {}, ...rows))));
  }
  return card;
}

// ---------- badges / tabs / boot ----------
function setBadge(name, n) {
  const b = $("#badge-" + name);
  if (!b) return;
  b.textContent = n;
  b.hidden = !n;
}
function renderBranchChips() {
  $("#branch-chips").replaceChildren(...CFG.branches.map((b) => {
    const on = isSelected(b.key);
    return el("span", {
      class: "chip branch-toggle " + (on ? "primary on" : "outline"),
      title: (on ? "Showing " : "Hidden ") + b.label + " (" + b.gerrit_branch + ") — click to toggle",
      role: "button", tabindex: "0",
      onclick: () => toggleBranch(b.key),
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleBranch(b.key); } },
    }, b.key);
  }));
}
function toggleBranch(key) {
  const next = isSelected(key) ? S.selected.filter((k) => k !== key) : [...S.selected, key];
  if (!next.length) return;                       // keep at least one branch selected
  S.selected = CFG.branches.map((b) => b.key).filter((k) => next.includes(k));
  try { localStorage.setItem("lr.selected", JSON.stringify(S.selected)); } catch (e) { /* ignore */ }
  renderBranchChips();
  loadStability(false);   // fetches the selected branches (cached, so quick)
  renderLanded();
  renderBackports();
}
function switchTab(name) {
  S.tab = name;
  const isEmf = name.startsWith("emf-");
  const nav = isEmf ? "#emf-tabs" : "#tabs";
  const panel = isEmf ? "#product-emf" : "#product-lustre";
  $$(nav + " .tab-btn").forEach((x) => x.classList.toggle("active", x.dataset.tab === name));
  $$(panel + " .tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + name));
}
function switchProduct(product) {
  S.product = product;
  $$("#product-switch .seg").forEach((s) => s.classList.toggle("active", s.dataset.product === product));
  $("#product-lustre").classList.toggle("hidden", product !== "lustre");
  $("#product-emf").classList.toggle("hidden", product !== "emf");
  $("#branch-chips").style.display = product === "lustre" ? "" : "none";
  if (product === "emf" && !emfLoaded) { emfLoaded = true; loadAllEmf(false); }
}
async function loadAll(refresh) {
  await Promise.allSettled([loadStability(refresh), loadLanded(refresh), loadBackports(refresh)]);
  markUpdated();
  if (refresh) snack("Data refreshed");
}
async function loadAllEmf(refresh) {
  emfLoaded = true;
  await Promise.allSettled([loadEmfStability(refresh), loadEmfLanded(refresh), loadEmfComing(refresh)]);
  markUpdated();
  if (refresh) snack("EMF data refreshed");
}
const refreshCurrent = () => (S.product === "emf" ? loadAllEmf(true) : loadAll(true));
function setAuto(sec) {
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null; }
  if (sec > 0) autoTimer = setInterval(refreshCurrent, sec * 1000);
}
async function boot() {
  $("#refresh").append(icon("refresh"));
  $(".fab-icon", document).replaceWith(icon("refresh"));
  try { CFG = await api("/api/config"); }
  catch (e) { $("main").append(el("div", { class: "banner error" }, "Could not load config: " + e)); return; }

  const allKeys = CFG.branches.map((b) => b.key);
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem("lr.selected") || "null"); } catch (e) { /* ignore */ }
  S.selected = (Array.isArray(saved) && saved.length && saved.every((k) => allKeys.includes(k)))
    ? allKeys.filter((k) => saved.includes(k)) : allKeys.slice();
  renderBranchChips();
  $$(".tabs .tab-btn").forEach((btn) => btn.addEventListener("click", () => switchTab(btn.dataset.tab)));
  if (CFG.emf_enabled) {
    $$("#product-switch .seg").forEach((b) => b.addEventListener("click", () => switchProduct(b.dataset.product)));
  } else {
    $("#product-switch").style.display = "none";   // EMF off -> Lustre-only, hide switch
  }
  $("#refresh").addEventListener("click", refreshCurrent);
  $("#fab").addEventListener("click", refreshCurrent);
  $("#auto").addEventListener("change", (e) => setAuto(+e.target.value));

  // eager initial spinners so nothing is blank, then load Lustre now; EMF is
  // lazy-loaded on first switch (its GitHub+Jira queries are slower).
  renderStability(); renderLanded(); renderBackports();
  renderEmfStability(); renderEmfLanded(); renderEmfComing();
  await loadAll(false);
}
boot();
