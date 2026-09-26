# Artemis Site Check (Chrome extension)

Warns before you open a site that's reported as phishing or likely impersonating a known brand, using
the Artemis server's `/api/check` endpoint. Only the site's domain is sent, and only after the user
turns warnings on in the welcome page.

## Try it locally

1. Start the Artemis server on `http://localhost:8000`.
2. In Chrome, open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and pick
   this `extension` folder.
3. The welcome page opens. Click **Turn on warnings**.

## Before publishing

1. Set `API_BASE` in `config.js` to your Artemis domain (`https://...`).
2. Set `host_permissions` in `manifest.json` to the same origin, e.g. `"https://your-domain/*"`, and
   remove the `localhost` entry.
3. In the Chrome Web Store listing, declare that the extension handles **web browsing activity**
   (the domains of visited sites), link your privacy policy (`https://your-domain/privacy`), and
   explain the `webNavigation` permission: it's how the extension sees which site a tab is opening.

## Files

- `background.js`: checks each top-level navigation and shows `warning.html` for dangerous sites.
- `hosts.js`: decides which addresses are worth checking (skips local addresses, IPs, browser pages).
- `popup.html` / `popup.js`: toolbar button with the current site's verdict and the on/off switch.
- `welcome.html`, `warning.html`: the consent page and the warning page.
- `fonts/`: Space Grotesk and IBM Plex Mono (SIL Open Font License, see the `*-OFL.txt` files).
