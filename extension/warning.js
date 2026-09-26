import { API_BASE } from "./config.js";

const target = new URLSearchParams(location.search).get("url") || "";
let host = "";
try {
  const parsed = new URL(target);
  if (parsed.protocol === "http:" || parsed.protocol === "https:") host = parsed.hostname;
} catch (e) { /* malformed: leave host empty */ }

document.getElementById("host").textContent = host || "Unknown site";
document.getElementById("report").href = `${API_BASE}/?scan=${encodeURIComponent(host)}`;
document.getElementById("continue").hidden = !host;

if (host) {
  chrome.runtime.sendMessage({ type: "verdict", host }).then((result) => {
    if (!result) return;
    document.getElementById("verdict").textContent = result.verdict;
    document.getElementById("reasons").replaceChildren(...result.warnings.map((text, i) => {
      const li = document.createElement("li");
      li.textContent = text;
      return li;
    }));
  });
}

document.getElementById("back").addEventListener("click", async () => {
  if (history.length > 1) {
    history.back();
  } else {
    const tab = await chrome.tabs.getCurrent();
    if (tab) chrome.tabs.remove(tab.id);
  }
});

document.getElementById("continue").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "allow", host });
  location.replace(target);
});
