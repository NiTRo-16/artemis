// Checks each site you open against the Artemis server and shows a warning page for dangerous ones.
// Only the site's domain is sent (never the full address or page content), and only after the user
// turns warnings on in the welcome page.
import { API_BASE, BADGE_LEVEL, BLOCK_LEVELS } from "./config.js";
import { checkableHost } from "./hosts.js";

const CACHE_MS = 6 * 60 * 60 * 1000;   // matches the server's cache

async function enabled() {
  return (await chrome.storage.local.get("enabled")).enabled === true;
}

// Verdict for a host: from this browser session's cache, or the server. null if the server can't answer.
export async function verdictFor(host) {
  const key = `verdict:${host}`;
  const cached = (await chrome.storage.session.get(key))[key];
  if (cached && Date.now() - cached.at < CACHE_MS) return cached.result;
  try {
    const res = await fetch(`${API_BASE}/api/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domain: host }),
    });
    if (!res.ok) return null;   // rate limited, rejected or server error: don't get in the way
    const result = await res.json();
    await chrome.storage.session.set({ [key]: { at: Date.now(), result } });
    return result;
  } catch (e) {
    return null;                // offline or server unreachable: browsing continues normally
  }
}

async function allowedThisSession(host) {
  const key = `allow:${host}`;
  return (await chrome.storage.session.get(key))[key] === true;
}

export async function handleNavigation({ tabId, frameId, url }) {
  if (frameId !== 0 || !(await enabled())) return;
  const host = checkableHost(url);
  if (!host) return;
  const result = await verdictFor(host);
  await chrome.action.setBadgeText({ tabId, text: "" });
  if (!result || (await allowedThisSession(host))) return;

  if (BLOCK_LEVELS.includes(result.level)) {
    const warning = chrome.runtime.getURL(`warning.html?url=${encodeURIComponent(url)}`);
    await chrome.tabs.update(tabId, { url: warning });
  } else if (result.level === BADGE_LEVEL) {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#e8a33d" });
    await chrome.action.setBadgeText({ tabId, text: "!" });
    await chrome.action.setTitle({ tabId, title: `Artemis: ${result.verdict}. ${result.summary}` });
  }
}

chrome.webNavigation.onBeforeNavigate.addListener((details) => { handleNavigation(details); });

chrome.runtime.onInstalled.addListener(({ reason }) => {
  if (reason === "install") chrome.tabs.create({ url: chrome.runtime.getURL("welcome.html") });
});

// The warning page asks for a host to be allowed for the rest of this browser session.
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message && message.type === "allow" && typeof message.host === "string") {
    chrome.storage.session.set({ [`allow:${message.host}`]: true }).then(() => reply({ ok: true }));
    return true;   // reply asynchronously
  }
  if (message && message.type === "verdict" && typeof message.host === "string") {
    verdictFor(message.host).then(reply);
    return true;
  }
  return false;
});
