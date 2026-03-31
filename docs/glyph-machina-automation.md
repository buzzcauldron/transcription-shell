# Glyph Machina automation

## No public HTTP API

[Glyph Machina](https://glyphmachina.com/) is delivered as a **web application**. There is **no documented REST API** in public materials for uploading images or retrieving lineation programmatically.

`transcriber-shell` drives the site with **Playwright** (Chromium), mimicking a user: file upload, **Crop Image** (for pre-cropped inputs this usually accepts the full frame), **Identify Lines**, then **Download Lines File**.

## Terms of service and ethics

- Review the site’s **terms of use** before deploying automation.
- Automated access may be **prohibited** or restricted; when in doubt, **contact the Glyph Machina project** for permission or a supported integration.
- This software is provided **as-is**; UI changes can **break** selectors without notice.

## Brittleness

- Selectors target button labels such as **Crop Image**, **Identify Lines**, and **Download Lines File**. Any redesign of the site may require code updates.
- CI should **not** rely on live glyphmachina.com; use `--skip-gm` with a saved lines XML for tests. **`tests/test_lineation_backends.py` mocks `fetch_lines_xml`** — it does not drive Chromium; only manual runs or `scripts/gm_smoke_test.py` hit the real UI.

### When live automation fails (timeouts / hidden download button)

- The site is a **SPA**: `#downloadLinesBtn` may exist in the DOM **before** line detection finishes (still **disabled**), or stay **CSS-hidden** while enabled. The workflow waits for **enabled**, then either **visible** or a short **grace period** for hidden-but-ready, then **`click(force=True)`** to start the download.
- **`TRANSCRIBER_SHELL_GM_POST_IDENTIFY_WAIT_MS`** (default `2000`): extra pause after **Identify Lines** so processing can start before we attach to the download control. Increase for large or slow images (e.g. `8000`).
- **`TRANSCRIBER_SHELL_GM_TIMEOUT_MS`**: overall Playwright timeouts for navigation and the download step.
- **`TRANSCRIBER_SHELL_GM_HEADLESS=false`**: some flows behave better in a visible browser; use a **persistent profile** if the site expects a session.

## Pre-cropped images

The tool works best when the pipeline input is already **cropped to a paragraph or case** with **complete lines**, as the site recommends. Heavy reliance on scripted crop-handle dragging is **not** implemented by default.

## Persistent browser profile (optional)

When **`TRANSCRIBER_SHELL_GM_PERSISTENT_PROFILE`** is true (or the GUI checkbox **Persistent Chromium profile for Glyph Machina**), Playwright uses `launch_persistent_context` with **`TRANSCRIBER_SHELL_GM_USER_DATA_DIR`** (default under `~/.cache/transcriber-shell/glyph-machina-browser`). Cookies and site logins can **persist across runs**, which helps if the site expects a session.

- **Security:** The profile directory holds cookies and local site data — treat it like a browser profile; do not share or commit it.
- **Headless vs visible:** Some flows only work in a visible browser; set **`TRANSCRIBER_SHELL_GM_HEADLESS=false`** to log in interactively once, then reuse the profile.
- **Concurrency:** Do **not** run two pipeline jobs at once against the **same** user-data directory; Chromium profiles are not safe for parallel writers.

## Lineation vs transcription

Use Glyph Machina output for **line boundaries and `lineRange` alignment** only. Do **not** treat **Extract Text**, spell-check, or **Modern English** outputs as protocol-ground truth — see the protocol repo’s external line tools note. You may stop the workflow after **Download Lines File** and never use their extracted Latin for canonical YAML.

---

**Doc workflow inspiration:** [Axel Edin (@axlolo)](https://github.com/axlolo). Adapted for transcriber-shell.

