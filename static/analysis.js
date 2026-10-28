// EMF build analysis page: /static/analysis.html?run=<GitHub run id>.
// Fetches /api/emf/analysis, renders the Markdown it returns and offers the
// same text as a .md download.
"use strict";

const RUN = new URLSearchParams(location.search).get("run") || "";
const doc = document.getElementById("doc");
const actions = document.getElementById("actions");
let blobUrl = null;

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Escaped text with `code`, **bold**, *emphasis* and [text](http…) links.
function inline(s) {
  return esc(s).split(/(`[^`]*`)/).map((part) => (part.length > 1 && part.startsWith("`") && part.endsWith("`"))
    ? "<code>" + part.slice(1, -1) + "</code>"
    : part.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")).join("");
}

// The Markdown subset the analysis uses: headings, lists, code fences, rules, paragraphs.
function render(md) {
  const out = [];
  let inList = false;
  const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };
  const lines = md.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let m;
    if (line.startsWith("```")) {
      closeList();
      const body = [];
      while (++i < lines.length && !lines[i].startsWith("```")) body.push(esc(lines[i]));
      out.push("<pre><code>" + body.join("\n") + "</code></pre>");
    } else if ((m = line.match(/^(#{1,3}) (.*)$/))) {
      closeList();
      out.push("<h" + m[1].length + ">" + inline(m[2]) + "</h" + m[1].length + ">");
    } else if ((m = line.match(/^(\s*)- (.*)$/))) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push("<li" + (m[1].length ? ' class="sub"' : "") + ">" + inline(m[2]) + "</li>");
    } else if (line.trim() === "---") {
      closeList(); out.push("<hr>");
    } else if (!line.trim()) {
      closeList();
    } else {
      closeList(); out.push("<p>" + inline(line) + "</p>");
    }
  }
  closeList();
  return out.join("\n");
}

function button(text, attrs, onClick) {
  const a = document.createElement("a");
  a.className = "btn tonal sm";
  a.textContent = text;
  for (const [k, v] of Object.entries(attrs)) a.setAttribute(k, v);
  if (onClick) a.addEventListener("click", (e) => { e.preventDefault(); onClick(); });
  return a;
}

async function load(refresh) {
  actions.replaceChildren();
  if (!/^\d+$/.test(RUN)) {
    doc.innerHTML = '<div class="banner error">No run id. Open this page from an analyze link on the EMF Build stability tab.</div>';
    return;
  }
  doc.innerHTML = '<div class="loading"><span class="spinner"></span>Analyzing run ' + esc(RUN)
    + "… downloading the failed job logs can take up to a minute.</div>";
  try {
    const r = await fetch("/api/emf/analysis?run=" + encodeURIComponent(RUN) + (refresh ? "&refresh=1" : ""));
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || "HTTP " + r.status);
    document.title = "EMF Build Analysis #" + (d.run_number || RUN);
    doc.innerHTML = render(d.markdown);
    if (blobUrl) URL.revokeObjectURL(blobUrl);
    blobUrl = URL.createObjectURL(new Blob([d.markdown], { type: "text/markdown" }));
    actions.append(
      button("Download .md", { href: blobUrl, download: d.filename }),
      button("Re-run analysis", { href: "#", title: "Fetch the run and its logs again" }, () => load(true)),
      button("Open run on GitHub", { href: d.url, target: "_blank", rel: "noopener" }));
  } catch (e) {
    doc.innerHTML = '<div class="banner error">Could not analyze run ' + esc(RUN) + ": " + esc(e.message) + "</div>";
    actions.append(button("Retry", { href: "#" }, () => load(true)));
  }
}

load(false);
