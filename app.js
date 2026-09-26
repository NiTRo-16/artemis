// Artemis page logic: runs scans and renders results. Served as /app.js (no inline scripts, for CSP).
const SVG_NS = "http://www.w3.org/2000/svg";
const SEV_COLOR = { critical: "#e2584f", high: "#e8a33d", medium: "#8fb8e8", low: "#8fa0b8" };
const SEV_RADIUS = { critical: 82, high: 104, medium: 124, low: 142 };
const $ = (id) => document.getElementById(id);

let current = null;   // last successful report, restored if a later scan fails

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

// Renders `code` spans from backticks; everything else stays plain text.
function rich(tag, className, text) {
  const node = el(tag, className);
  text.split("`").forEach((part, i) => node.append(i % 2 ? el("code", "", part) : part));
  return node;
}

function catCard(c) {
  const card = el("div", "cat-card");
  const top = el("div", "top");
  top.append(el("h3", "", c.name), el("span", `grade ${c.status}`, c.grade));
  const track = el("div", "bar-track");
  const fill = el("div", `bar-fill ${c.status}`);
  fill.style.width = `${c.score}%`;
  track.append(fill);
  const issues = c.issues ? `${c.issues} issue${c.issues > 1 ? "s" : ""} found.` : "No issues found.";
  card.append(top, track, el("p", "note", [...c.notes, issues].join(" ")));
  return card;
}

function findingRow(f) {
  const row = el("div", "finding");
  const desc = rich("div", "desc", f.title);
  desc.append(el("span", "path", f.location));
  const btn = el("button", "action", "Details");
  btn.type = "button";
  btn.setAttribute("aria-expanded", "false");
  btn.addEventListener("click", () => {
    const open = row.classList.toggle("open");
    btn.setAttribute("aria-expanded", String(open));
    btn.textContent = open ? "Hide" : "Details";
  });
  row.append(el("span", `sev ${f.severity}`, f.severity), desc, el("div", "category", f.category), btn,
             rich("div", "fix", f.fix));
  return row;
}

function renderImpersonation(imp) {
  const box = $("imp");
  box.className = `imp ${imp.level}`;

  const left = el("div");
  left.append(el("div", "imp-verdict", imp.verdict), el("div", "imp-domain", imp.registrable),
              el("p", "imp-summary", imp.summary));
  const signals = el("ul", "imp-signals");
  imp.signals.forEach((s) => signals.append(el("li", s.tone, s.text)));
  left.append(signals);

  const facts = el("dl", "imp-facts");
  const f = imp.facts;
  const page = f.page;
  const form = !page ? "Page not loaded"
    : page.redirected_to ? `Not checked: leads to ${page.redirected_to}`
    : page.credential_form ? (page.credential_form === "card" ? "Asks for card details" : "Asks for a password")
        + (page.form_built_by_script ? " (added by the page's scripts)" : "")
    : page.rendered ? "No password or card fields" : "No password or card fields in the page's HTML";
  [["Registered", f.registered || "Not published"],
   ["Registrar", f.registrar || "Unknown"],
   ["Earliest certificate", f.first_certificate ? `${f.first_certificate} · ${f.certificate_source}` : "None found"],
   ["Page checked", page ? page.url : "None"],
   ["Login or payment form", form],
   ["Brand named on page", page && page.brands_named.length ? page.brands_named.join(", ") : "None"]]
    .forEach(([label, value]) => {
    const cell = el("div");
    cell.append(el("dt", "", label), el("dd", "", value));
    facts.append(cell);
  });
  const lists = el("div", "imp-lists");
  imp.lists.forEach((entry) => {
    const row = el("div");
    row.append(el("span", "", `${entry.name}: ${entry.detail}`), el("span", `st ${entry.status}`, entry.status));
    lists.append(row);
  });
  facts.append(lists);

  box.replaceChildren(left, facts);
}

// The beam turns once every SWEEP_MS; each blip flashes as the leading edge passes over it.
const SWEEP_MS = 4000;
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const sweep = $("sweep").animate([{ transform: "rotate(0deg)" }, { transform: "rotate(360deg)" }],
                                 { duration: SWEEP_MS, iterations: Infinity });
if (reducedMotion) sweep.pause();

function drawBlips(findings) {
  const group = $("blips");
  group.replaceChildren();
  const phase = (sweep.currentTime % SWEEP_MS) / SWEEP_MS;   // where the beam is now, 0..1 clockwise from top
  findings.slice(0, 10).forEach((f, i) => {
    const turn = (i * 0.381966) % 1;   // golden-ratio spacing keeps blips spread out
    const angle = turn * 2 * Math.PI - Math.PI / 2;
    const r = SEV_RADIUS[f.severity];
    const dot = document.createElementNS(SVG_NS, "circle");
    dot.setAttribute("cx", (170 + r * Math.cos(angle)).toFixed(1));
    dot.setAttribute("cy", (170 + r * Math.sin(angle)).toFixed(1));
    dot.setAttribute("r", f.severity === "low" ? 3 : 4);
    dot.setAttribute("fill", SEV_COLOR[f.severity]);
    dot.setAttribute("class", "blip");
    group.append(dot);
    if (reducedMotion) { dot.style.opacity = 1; return; }
    dot.animate([{ opacity: 1 }, { opacity: 0.25, offset: 0.7 }, { opacity: 0.25 }],
                { duration: SWEEP_MS, iterations: Infinity, delay: (((turn - phase) % 1 + 1) % 1) * SWEEP_MS,
                  fill: "backwards" });
  });
}

const RESULT_SECTIONS = ["impersonation", "categories", "findings", "nav-links"];

function render(report) {
  current = report;
  RESULT_SECTIONS.forEach((id) => { $(id).hidden = false; });
  const level = $("risk-level");
  if (report.risk) {
    const tone = report.risk.label.toLowerCase();
    $("risk-num").textContent = report.risk.score;
    $("risk-num").style.color = { low: "var(--teal)", medium: "var(--amber)", high: "var(--red)" }[tone];
    $("risk-num").hidden = false;
    $("risk-lbl").textContent = "Risk score";
    level.textContent = report.risk.label;
    level.className = `level ${tone}`;
    level.hidden = false;
  } else {
    $("risk-num").hidden = true;
    $("risk-lbl").textContent = "Site offline";
    level.hidden = true;
  }

  $("cat-idx").textContent = report.resolves === false ? `${report.domain} is offline`
    : `${report.domain} · ${(report.duration_ms / 1000).toFixed(1)}s`;
  $("cat-grid").replaceChildren(...report.categories.map(catCard));

  const n = report.findings.length;
  $("find-idx").textContent = n || "";
  $("findings-list").replaceChildren(
    ...(n ? report.findings.map(findingRow) : [el("div", "finding empty", "No issues found.")])
  );
  drawBlips(report.findings);
  renderImpersonation(report.impersonation);
  renderVisit(report);
}

// Before the first successful scan: no score, no results.
function renderEmpty() {
  RESULT_SECTIONS.forEach((id) => { $(id).hidden = true; });
  $("risk-num").hidden = true;
  $("risk-lbl").textContent = "No scan yet";
  $("risk-level").hidden = true;
  $("blips").replaceChildren();
  renderVisit(null);
}

// Points a link at a scanned site, opening it in a new tab unless the user chose "same tab".
function aimLink(link, url) {
  link.href = url;
  link.target = settings.same_tab ? "_self" : "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

// Safe sites get a direct link; anything else gets a warning, and "Continue anyway" asks once more.
function renderVisit(report) {
  const box = $("visit");
  const visit = report && report.visit;
  box.replaceChildren();
  box.hidden = !visit;
  if (!visit) return;
  const url = /^https?:\/\//.test(visit.url || "") ? visit.url : null;

  if (visit.allowed && url) {
    box.className = "visit ok";
    box.append(aimLink(el("a", "visit-btn", `Continue to ${report.domain}`), url));
  } else {
    box.className = "visit risky";
    const why = el("ul", "visit-why");
    visit.criteria.filter((c) => !c.passed).forEach((c) => why.append(el("li", "", c.problem)));
    box.append(el("div", "visit-head", "High risk detected"), why);
    if (url) {
      const btn = el("button", "visit-btn", "Continue anyway");
      btn.type = "button";
      btn.addEventListener("click", () => openRiskDialog(report, url));
      box.append(btn);
    }
  }
}

// Everything that made the site high risk, strongest first, without repeats.
function riskFactors(report) {
  const items = [];
  const add = (text, tone) => {
    const plain = text.replaceAll("`", "");
    if (!items.some((i) => i.text === plain)) items.push({ text: plain, tone });
  };
  // A critical certificate finding already says what the "certificate" criterion would, in more detail.
  const certFinding = report.findings.some((f) => f.severity === "critical" && f.category === "TLS / HTTPS");
  report.visit.criteria
    .filter((c) => !c.passed && !(certFinding && c.text === "Certificate is valid and trusted"))
    .forEach((c) => add(c.problem, "red"));
  report.impersonation.signals.filter((s) => s.tone === "red").forEach((s) => add(s.text, "red"));
  report.findings.filter((f) => f.severity === "critical" || f.severity === "high").forEach((f) => add(f.title, "red"));
  report.impersonation.signals.filter((s) => s.tone === "amber").forEach((s) => add(s.text, "amber"));
  return items;
}

function openRiskDialog(report, url) {
  $("risk-target-url").textContent = url;
  $("risk-list").replaceChildren(...riskFactors(report).map((i) => el("li", i.tone === "amber" ? "amber" : "", i.text)));
  aimLink($("risk-continue"), url);
  $("risk-dialog").showModal();
}

function setBusy(busy) {
  $("scan-btn").disabled = busy;
  $("scan-btn").textContent = busy ? "Scanning…" : "Run scan";
  if (!reducedMotion) sweep.updatePlaybackRate(busy ? 3.5 : 1);
  if (busy) {
    $("risk-num").hidden = true;
    $("risk-lbl").textContent = "Scanning";
    $("risk-level").hidden = true;
    $("blips").replaceChildren();
    renderVisit(null);
  }
}

function showError(message) {
  $("scan-error").textContent = message;
  $("scan-error").hidden = !message;
}

$("scan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const domain = $("domain").value.trim();
  if (!domain) { $("domain").focus(); return; }
  showError("");
  setBusy(true);
  let report = null;
  try {
    const res = await fetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domain }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The scan failed.");
    report = data;
  } catch (err) {
    showError(err instanceof TypeError ? "Couldn't reach the scanner. Is the server running?" : err.message);
  }
  setBusy(false);   // back to normal speed before blips are timed against the beam
  if (report || current) render(report || current);
  else renderEmpty();
});

// ---------- settings ----------

const SETTINGS_KEY = "artemis.settings";
const DEFAULT_SETTINGS = { theme: "system", same_tab: false };
let settings = { ...DEFAULT_SETTINGS };
let account = null;   // { email, settings } when signed in

function loadLocalSettings() {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") };
  } catch (e) {
    return { ...DEFAULT_SETTINGS };
  }
}

function applySettings(next) {
  settings = { theme: ["system", "light", "dark"].includes(next.theme) ? next.theme : "system", same_tab: !!next.same_tab };
  if (settings.theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = settings.theme;
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch (e) { /* storage unavailable */ }
  document.querySelectorAll('input[name="theme"]').forEach((r) => { r.checked = r.value === settings.theme; });
  $("same-tab").checked = settings.same_tab;
  if (current) renderVisit(current);   // re-aim links at the new tab preference
}

async function saveSettings(next) {
  applySettings(next);
  if (account) {
    try { await api("/api/settings", { method: "PUT", body: settings }); } catch (e) { /* kept locally */ }
  }
}

document.querySelectorAll('input[name="theme"]').forEach((radio) =>
  radio.addEventListener("change", () => saveSettings({ ...settings, theme: radio.value })));
$("same-tab").addEventListener("change", () => saveSettings({ ...settings, same_tab: $("same-tab").checked }));

// ---------- dialogs ----------

document.querySelectorAll("dialog").forEach((dialog) => {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog || event.target.closest("[data-close]")) dialog.close();   // backdrop or Close
  });
});
$("risk-continue").addEventListener("click", () => $("risk-dialog").close());
$("settings-btn").addEventListener("click", () => $("settings-dialog").showModal());

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong. Try again.");
  return data;
}

// ---------- accounts ----------

function setAccount(next) {
  account = next;
  const signedIn = !!account;
  $("login-btn").hidden = $("signup-btn").hidden = signedIn;
  $("history-btn").hidden = $("logout-btn").hidden = $("account-email").hidden = !signedIn;
  $("account-email").textContent = signedIn ? account.email : "";
  $("account-section").hidden = !signedIn;
  $("settings-scope").textContent = signedIn ? `Saved to your account (${account.email}) and this browser.`
    : "Saved in this browser. Sign in to keep them on every device.";
}

let authMode = "signup";
let linkToken = "";   // from an emailed /verify or /reset link

const OPTIONAL_NOTE = "An account is optional. It keeps your scan history, saves your settings across devices, and raises your limit from 10 to 30 scans a minute.";
const AUTH_MODES = {
  signup: { title: "Your Artemis account", intro: OPTIONAL_NOTE, submit: "Create account", email: true,
            password: "Password (at least 10 characters)", autocomplete: "new-password" },
  login: { title: "Your Artemis account", intro: OPTIONAL_NOTE, submit: "Log in", email: true,
           password: "Password", autocomplete: "current-password" },
  forgot: { title: "Reset your password", intro: "Enter your account's email and we'll send you a link to choose a new password.",
            submit: "Send reset link", email: true, password: null },
  verify: { title: "Confirm your email", intro: "Enter the password you chose when you signed up to finish creating your account.",
            submit: "Confirm email", email: false, password: "Password", autocomplete: "current-password" },
  reset: { title: "Choose a new password", intro: "Setting a new password signs you out on all your other devices.",
           submit: "Set password", email: false, password: "New password (at least 10 characters)", autocomplete: "new-password" },
};

function openAuth(mode) {
  authMode = mode;
  const m = AUTH_MODES[mode];
  $("auth-title").textContent = m.title;
  $("auth-intro").textContent = m.intro;
  $("auth-tabs").hidden = !(mode === "signup" || mode === "login");
  $("tab-signup").setAttribute("aria-selected", String(mode === "signup"));
  $("tab-login").setAttribute("aria-selected", String(mode === "login"));
  $("email-field").hidden = !m.email;
  $("password-field").hidden = !m.password;
  if (m.password) {
    $("auth-password-label").textContent = m.password;
    $("auth-password").autocomplete = m.autocomplete;
  }
  $("auth-submit").textContent = m.submit;
  $("forgot-btn").hidden = mode !== "login";
  $("auth-consent").hidden = mode !== "signup";
  $("auth-error").hidden = true;
  $("auth-form").hidden = false;
  $("auth-sent").hidden = true;
  if (!$("auth-dialog").open) $("auth-dialog").showModal();
  (m.email ? $("auth-email") : $("auth-password")).focus();
}

function showSent(text) {
  $("auth-form").hidden = true;
  $("auth-tabs").hidden = true;
  $("auth-sent-text").textContent = text;
  $("auth-sent").hidden = false;
}

$("signup-btn").addEventListener("click", () => openAuth("signup"));
$("login-btn").addEventListener("click", () => openAuth("login"));
$("tab-signup").addEventListener("click", () => openAuth("signup"));
$("tab-login").addEventListener("click", () => openAuth("login"));
$("forgot-btn").addEventListener("click", () => openAuth("forgot"));

$("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const m = AUTH_MODES[authMode];
  const email = $("auth-email").value.trim();
  const password = $("auth-password").value;
  if ((m.email && !email) || (m.password && !password)) {
    $("auth-error").textContent = m.email && m.password ? "Enter your email and password."
      : m.email ? "Enter your email." : "Enter your password.";
    $("auth-error").hidden = false;
    return;
  }
  $("auth-submit").disabled = true;
  try {
    if (authMode === "signup") {
      await api("/api/signup", { method: "POST", body: { email, password } });
      showSent(`We sent a link to ${email}. Open it to finish creating your account. It expires in 24 hours; if it doesn't arrive, check your spam folder.`);
    } else if (authMode === "forgot") {
      await api("/api/password/forgot", { method: "POST", body: { email } });
      showSent(`If there's an account for ${email}, we've sent it a link to choose a new password. The link expires in 1 hour.`);
    } else {
      const path = { login: "/api/login", verify: "/api/verify", reset: "/api/password/reset" }[authMode];
      const body = authMode === "login" ? { email, password } : { token: linkToken, password };
      const data = await api(path, { method: "POST", body });
      setAccount(data);
      if (authMode === "verify") await saveSettings(settings);   // a new account keeps choices made before it existed
      else applySettings(data.settings);                         // an existing account's settings win
      linkToken = "";
      $("auth-dialog").close();
    }
    $("auth-form").reset();
  } catch (err) {
    $("auth-error").textContent = err.message;
    $("auth-error").hidden = false;
  } finally {
    $("auth-submit").disabled = false;
  }
});

$("logout-btn").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST" }); } catch (e) { /* signed out locally regardless */ }
  setAccount(null);
});

$("delete-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/account/delete", { method: "POST", body: { password: $("delete-password").value } });
    $("delete-form").reset();
    $("delete-error").hidden = true;
    $("settings-dialog").close();
    setAccount(null);
  } catch (err) {
    $("delete-error").textContent = err.message;
    $("delete-error").hidden = false;
  }
});

// ---------- history ----------

function renderHistory(scans) {
  $("history-empty").hidden = scans.length > 0;
  $("history-actions").hidden = scans.length === 0;
  $("history-list").replaceChildren(...scans.map((scan) => {
    const item = el("li");
    const btn = el("button");
    btn.type = "button";
    const when = new Date(scan.scanned_at * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    btn.append(el("span", "h-target", scan.target),
               el("span", `level ${(scan.risk_label || "").toLowerCase()}`, scan.risk_label || "Offline"),
               el("span", "h-meta", `${scan.verdict} · ${when}`));
    btn.addEventListener("click", () => {
      $("history-dialog").close();
      $("domain").value = scan.target;
      $("scan-form").requestSubmit();
    });
    item.append(btn);
    return item;
  }));
}

$("history-btn").addEventListener("click", async () => {
  $("history-list").replaceChildren();
  $("history-empty").hidden = true;
  $("history-actions").hidden = true;
  $("history-dialog").showModal();
  try {
    renderHistory((await api("/api/history")).scans);
  } catch (err) {
    $("history-dialog").close();
    setAccount(null);   // the session ended; show the signed-out header
  }
});

$("history-clear").addEventListener("click", async () => {
  if (!confirm("Delete your whole scan history?")) return;
  try { await api("/api/history", { method: "DELETE" }); renderHistory([]); } catch (e) { /* leave the list as is */ }
});

// ---------- start ----------

applySettings(loadLocalSettings());
renderEmpty();

// Links from account emails: /verify#<token> and /reset#<token>. The token sits after "#" so it never
// reaches the server's logs; take it, then clean the address bar so it isn't left in history.
if (location.pathname === "/verify" || location.pathname === "/reset") {
  const mode = location.pathname === "/verify" ? "verify" : "reset";
  linkToken = location.hash.slice(1);
  history.replaceState(null, "", "/");
  if (/^[A-Za-z0-9_-]{20,200}$/.test(linkToken)) openAuth(mode);
}

// /?scan=example.com starts a scan straight away (used by the browser extension's "Full report" link).
const requested = new URLSearchParams(location.search).get("scan");
if (requested) {
  $("domain").value = requested.slice(0, 2048);
  $("scan-form").requestSubmit();
}
api("/api/me").then((data) => {
  setAccount(data.account);
  if (data.account) applySettings(data.account.settings);
}).catch(() => setAccount(null));
