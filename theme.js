// Applies the saved theme before the page paints, so there's no flash of the wrong colours.
// Settings live in localStorage (per browser) and, for signed-in users, in the account too (see app.js).
try {
  const theme = JSON.parse(localStorage.getItem("artemis.settings") || "{}").theme;
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
} catch (e) { /* storage unavailable: fall back to the device setting */ }
