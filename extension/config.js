// Where the Artemis server runs. To test against a local server, change this to
// "http://localhost:8000" and "host_permissions" in manifest.json to "http://localhost:8000/*".
export const API_BASE = "https://artemissecure.co.in";

// Verdicts from /api/check that get a full-page warning, and the one that gets a toolbar badge.
export const BLOCK_LEVELS = ["reported", "likely"];
export const BADGE_LEVEL = "suspicious";
