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

const PAYMENT_KIND = { upi: "UPI payment", provider: "Payment page", page: "Payment form on this page" };

function renderPayment(report) {
  const pay = report.payment;
  const box = $("pay");
  box.className = `imp ${pay.level}`;
  const left = el("div");
  left.append(el("div", "imp-verdict", pay.verdict), el("div", "imp-kind", PAYMENT_KIND[pay.kind] || "Payment"),
              el("p", "imp-summary", pay.summary));
  const signals = el("ul", "imp-signals");
  pay.signals.forEach((s) => signals.append(el("li", s.tone, s.text)));
  left.append(signals);
  if (pay.level !== "clear") left.append(reportButton(report, report.kind === "upi" ? "Report this UPI ID" : "Report this site"));
  const facts = el("dl", "imp-facts");
  pay.facts.forEach(([label, value]) => {
    const cell = el("div");
    cell.append(el("dt", "", label), el("dd", "", value));
    facts.append(cell);
  });
  box.replaceChildren(left, facts);
}

const SITE_SECTIONS = ["impersonation", "categories", "findings", "nav-impersonation", "nav-categories", "nav-findings"];

function render(report) {
  current = report;
  const upi = report.kind === "upi";   // a UPI link: only the payment check applies
  SITE_SECTIONS.forEach((id) => { $(id).hidden = upi; });
  $("payment").hidden = $("nav-payment").hidden = !report.payment;
  $("nav-links").hidden = false;
  const level = $("risk-level");
  const tone = report.risk && report.risk.label.toLowerCase();
  if (report.risk && report.risk.score != null) {
    $("risk-num").textContent = report.risk.score;
    $("risk-num").style.color = { low: "var(--teal)", medium: "var(--amber)", high: "var(--red)" }[tone];
    $("risk-num").hidden = false;
    $("risk-lbl").textContent = "Risk score";
  } else {
    $("risk-num").hidden = true;
    $("risk-lbl").textContent = upi ? "Payment risk" : "Site offline";
  }
  if (report.risk) {
    level.textContent = report.risk.label;
    level.className = `level ${tone}`;
  }
  level.hidden = !report.risk;

  if (report.payment) renderPayment(report);
  if (upi) {
    $("blips").replaceChildren();
  } else {
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
  }
  renderVisit(report);
}

// Before the first successful scan: no score, no results.
function renderEmpty() {
  [...SITE_SECTIONS, "payment", "nav-links"].forEach((id) => { $(id).hidden = true; });
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
    if (reportable(report)) box.append(reportButton(report, "Report this site"));
  }
}

// Sites showing signs of phishing, malware or a payment scam can be reported.
function reportable(report) {
  return ["suspicious", "likely", "reported"].includes(report.impersonation && report.impersonation.level)
    || (report.payment && report.payment.level !== "clear");
}

function reportButton(report, label) {
  const btn = el("button", "btn outline report-btn", label);
  btn.type = "button";
  btn.addEventListener("click", () => openReport(report));
  return btn;
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
  const payment = report.payment ? report.payment.signals : [];
  payment.filter((s) => s.tone === "red").forEach((s) => add(s.text, "red"));
  report.impersonation.signals.filter((s) => s.tone === "red").forEach((s) => add(s.text, "red"));
  report.findings.filter((f) => f.severity === "critical" || f.severity === "high").forEach((f) => add(f.title, "red"));
  payment.filter((s) => s.tone === "amber").forEach((s) => add(s.text, "amber"));
  report.impersonation.signals.filter((s) => s.tone === "amber").forEach((s) => add(s.text, "amber"));
  return items;
}

// ---------- reporting a site ----------

let reporting = null;   // { target, upi } being reported

function googleReportLink() {
  const category = (document.querySelector('input[name="report-category"]:checked') || {}).value;
  const kind = category === "malware" ? "report_badware" : "report_phish";
  $("report-google-link").href = `https://safebrowsing.google.com/safebrowsing/${kind}/?url=${encodeURIComponent(reporting.target)}`;
}

function openReport(report) {
  const upi = report.kind === "upi";
  reporting = { target: upi ? report.domain : (report.visit && report.visit.url) || report.domain, upi };
  $("report-title").textContent = upi ? "Report this UPI ID" : "Report this site";
  $("report-target").textContent = reporting.target;
  $("report-form").reset();
  const preset = upi || (report.payment && report.payment.level !== "clear") ? "payment" : "phishing";
  document.querySelector(`input[name="report-category"][value="${preset}"]`).checked = true;
  $("report-error").hidden = true;
  $("report-form").hidden = false;
  $("report-sent").hidden = true;
  $("report-google").hidden = upi;          // Safe Browsing takes web addresses, not UPI IDs
  $("report-upi-app").hidden = !upi;
  if (!upi) googleReportLink();
  $("report-dialog").showModal();
}

document.querySelectorAll('input[name="report-category"]').forEach((radio) =>
  radio.addEventListener("change", () => { if (reporting && !reporting.upi) googleReportLink(); }));

$("report-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const category = document.querySelector('input[name="report-category"]:checked').value;
  $("report-submit").disabled = true;
  try {
    await api("/api/report", { method: "POST", body: { target: reporting.target, category, details: $("report-details").value } });
    $("report-form").hidden = true;
    $("report-sent").hidden = false;
  } catch (err) {
    $("report-error").textContent = err.message;
    $("report-error").hidden = false;
  } finally {
    $("report-submit").disabled = false;
  }
});

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

// ---------- recent searches (kept in this browser only) ----------

const RECENT_KEY = "artemis.recent";
const RECENT_MAX = 5;
let recentActive = -1;   // highlighted suggestion, for the arrow keys

function loadRecent() {
  try {
    const list = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(list) ? list.filter((t) => typeof t === "string").slice(0, RECENT_MAX) : [];
  } catch (e) {
    return [];
  }
}

function saveRecent(list) {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch (e) { /* storage unavailable */ }
}

function rememberSearch(target) {
  saveRecent([target, ...loadRecent().filter((t) => t.toLowerCase() !== target.toLowerCase())].slice(0, RECENT_MAX));
}

function hideRecent() {
  $("recent").hidden = true;
  $("domain").setAttribute("aria-expanded", "false");
  $("domain").removeAttribute("aria-activedescendant");
  recentActive = -1;
}

// Shows recent searches that match what's typed (all of them when the box is empty).
function showRecent() {
  const typed = $("domain").value.trim().toLowerCase();
  const items = loadRecent().filter((t) => !typed || (t.toLowerCase().includes(typed) && t.toLowerCase() !== typed));
  if (!items.length || $("scan-btn").disabled) { hideRecent(); return; }
  recentActive = -1;
  $("domain").removeAttribute("aria-activedescendant");
  $("recent-list").replaceChildren(...items.map((target, i) => {
    const item = el("li", "", target);
    item.id = `recent-${i}`;
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", "false");
    item.addEventListener("mousedown", (e) => e.preventDefault());   // keep focus in the search box
    item.addEventListener("click", () => pickRecent(target));
    return item;
  }));
  $("recent").hidden = false;
  $("domain").setAttribute("aria-expanded", "true");
}

function pickRecent(target) {
  $("domain").value = target;
  hideRecent();
  $("scan-form").requestSubmit();
}

function moveRecent(step) {
  const items = [...$("recent-list").children];
  if (!items.length) return;
  recentActive = recentActive < 0 ? (step > 0 ? 0 : items.length - 1) : (recentActive + step + items.length) % items.length;
  items.forEach((item, i) => item.setAttribute("aria-selected", String(i === recentActive)));
  $("domain").setAttribute("aria-activedescendant", items[recentActive].id);
}

$("domain").addEventListener("focus", showRecent);
$("domain").addEventListener("click", () => { if ($("recent").hidden) showRecent(); });
$("domain").addEventListener("input", showRecent);
$("domain").addEventListener("blur", hideRecent);
$("domain").addEventListener("keydown", (event) => {
  const open = !$("recent").hidden;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    if (!open) showRecent();
    moveRecent(event.key === "ArrowDown" ? 1 : -1);
  } else if (event.key === "Enter" && open && recentActive >= 0) {
    event.preventDefault();
    pickRecent($("recent-list").children[recentActive].textContent);
  } else if (event.key === "Escape" && open) {
    hideRecent();
  }
});
$("recent-clear").addEventListener("mousedown", (e) => e.preventDefault());
$("recent-clear").addEventListener("click", () => { saveRecent([]); hideRecent(); });

$("scan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  hideRecent();
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
    rememberSearch(domain);
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
  // Accounts made with Google may have no password; they confirm deletion by typing their email.
  const password = !signedIn || account.has_password !== false;
  $("delete-label").textContent = password ? "Confirm with your password" : "Type your email address to confirm";
  $("delete-password").type = password ? "password" : "email";
  $("delete-password").autocomplete = password ? "current-password" : "off";
  $("settings-scope").textContent = signedIn ? `Saved to your account (${account.email}) and this browser.`
    : "Saved in this browser. Sign in to keep them on every device.";
}

let authMode = "signup";
let linkToken = "";   // from an emailed /verify or /reset link
let googleSignin = false;   // the server has Google sign-in set up

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
  const google = googleSignin && (mode === "signup" || mode === "login");
  $("google-block").hidden = !google;
  // "Continue with Google" can create an account from either tab, so the terms line shows on both.
  $("auth-consent").hidden = !(mode === "signup" || google);
  $("auth-consent-lead").textContent = google ? "By creating an account or continuing with Google" : "By creating an account";
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
// /?signin=ok|new|failed is where Google sign-in returns; the address bar is cleaned afterwards.
const params = new URLSearchParams(location.search);
const requested = params.get("scan");
const signin = params.get("signin");
if (signin) history.replaceState(null, "", "/");
if (requested) {
  $("domain").value = requested.slice(0, 2048);
  $("scan-form").requestSubmit();
}
api("/api/me").then((data) => {
  googleSignin = !!data.google_signin;
  setAccount(data.account);
  if (data.account && signin === "new") saveSettings(settings);   // a new account keeps choices made before it
  else if (data.account) applySettings(data.account.settings);
  if (signin === "failed" && !data.account) {
    openAuth("login");
    $("auth-error").textContent = "Google sign-in didn't work. Try again, or log in with your email and password.";
    $("auth-error").hidden = false;
  }
}).catch(() => setAccount(null));
