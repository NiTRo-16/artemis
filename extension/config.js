// Where the Artemis server runs. Change this (and "host_permissions" in manifest.json) to your
// https:// domain before publishing the extension.
export const API_BASE = "http://localhost:8000";

// Verdicts from /api/check that get a full-page warning, and the one that gets a toolbar badge.
export const BLOCK_LEVELS = ["reported", "likely"];
export const BADGE_LEVEL = "suspicious";
