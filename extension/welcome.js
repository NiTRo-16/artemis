import { API_BASE } from "./config.js";

document.getElementById("server").textContent = new URL(API_BASE).host;
document.getElementById("privacy-link").href = `${API_BASE}/privacy`;

document.getElementById("enable").addEventListener("click", async () => {
  await chrome.storage.local.set({ enabled: true });
  document.querySelector(".actions").hidden = true;
  document.getElementById("done").hidden = false;
});

document.getElementById("later").addEventListener("click", async () => {
  await chrome.storage.local.set({ enabled: false });
  const tab = await chrome.tabs.getCurrent();
  if (tab) chrome.tabs.remove(tab.id);
});
