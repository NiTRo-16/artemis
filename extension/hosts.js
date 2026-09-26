import { API_BASE } from "./config.js";

const IP_ADDRESS = /^(\d{1,3}(\.\d{1,3}){3}|\[[0-9a-f:]+\])$/i;

// Domains worth checking: public hostnames on http(s), and not the Artemis server itself.
export function checkableHost(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch (e) {
    return null;
  }
  const host = parsed.hostname.toLowerCase();
  if (!["http:", "https:"].includes(parsed.protocol)) return null;
  if (!host.includes(".") || IP_ADDRESS.test(host) || host.endsWith(".localhost") || host.endsWith(".local")) return null;
  if (host === new URL(API_BASE).hostname) return null;
  return host;
}
