# Artemis Site Check (Chrome extension)

Warns before you open a site that's reported as phishing or likely impersonating a known brand, using
the Artemis server's `/api/check` endpoint. Only the site's domain is sent, and only after the user
turns warnings on in the welcome page.

## Try it

The extension talks to the live server at `https://artemissecure.co.in`.

1. In Chrome, open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and pick
   this `extension` folder.
2. The welcome page opens. Click **Turn on warnings**.

To test against a server on your own computer instead, set `API_BASE` in `config.js` to
`http://localhost:8000` and `host_permissions` in `manifest.json` to `"http://localhost:8000/*"`.

## Publishing to the Chrome Web Store

In the listing, declare that the extension handles **web browsing activity** (the domains of visited
sites), link the privacy policy (`https://artemissecure.co.in/privacy`), and explain the
`webNavigation` permission: it's how the extension sees which site a tab is opening.

## Files

- `background.js`: checks each top-level navigation and shows `warning.html` for dangerous sites.
- `hosts.js`: decides which addresses are worth checking (skips local addresses, IPs, browser pages).
- `popup.html` / `popup.js`: toolbar button with the current site's verdict and the on/off switch.
- `welcome.html`, `warning.html`: the consent page and the warning page.
- `fonts/`: Space Grotesk and IBM Plex Mono (SIL Open Font License, see the `*-OFL.txt` files).
