import { API_BASE } from "./config.js";
import { checkableHost } from "./hosts.js";

const $ = (id) => document.getElementById(id);
$("privacy-link").href = `${API_BASE}/privacy`;

const { enabled } = await chrome.storage.local.get("enabled");
$("enabled").checked = enabled === true;
$("enabled").addEventListener("change", () => chrome.storage.local.set({ enabled: $("enabled").checked }));

// activeTab: clicking the toolbar button lets the popup read the current tab's address.
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
const host = tab && tab.url ? checkableHost(tab.url) : null;

if (!host) {
  $("verdict").textContent = "Nothing to check on this page";
} else {
  $("host").textContent = host;
  $("report").href = `${API_BASE}/?scan=${encodeURIComponent(host)}`;
  $("report").hidden = false;
  const result = await chrome.runtime.sendMessage({ type: "verdict", host });
  if (result) {
    $("verdict").textContent = result.verdict;
    $("verdict").className = `verdict ${result.level}`;
    $("summary").textContent = result.summary;
  } else {
    $("verdict").textContent = "Couldn't reach Artemis";
    $("summary").textContent = "Check your connection, or try again in a minute.";
  }
}
