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
- CI should **not** rely on live glyphmachina.com; use `--skip-gm` with a saved lines XML for tests.

## Pre-cropped images

The tool works best when the pipeline input is already **cropped to a paragraph or case** with **complete lines**, as the site recommends. Heavy reliance on scripted crop-handle dragging is **not** implemented by default.

## Lineation vs transcription

Use Glyph Machina output for **line boundaries and `lineRange` alignment** only. Do **not** treat **Extract Text**, spell-check, or **Modern English** outputs as protocol-ground truth — see the protocol repo’s external line tools note. You may stop the workflow after **Download Lines File** and never use their extracted Latin for canonical YAML.
