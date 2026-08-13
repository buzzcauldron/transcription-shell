# Computus Web Harvest Coverage Report

Generated: 2026-08-11T00:27:57.483665+00:00

## Summary

- Registry records: **752**
- With confirmed URL: **311**
- Status `downloaded`: **58**
- Access blocked (robots/terms): **5**
- Needs review: **163**
- URL failed: **56**
- Unavailable / not digitized (unknown): **193**
- No candidate URL: **193**
- Cohort crosswalk rows: **35**
- Jobs with images on disk: **240** (67732 image files, ~168.944 GiB)
- Sum of confirmed page estimates: **59004**

### Acquisition status

| Status | Count |
|---|---:|
| confirmed | 276 |
| not_digitized_unknown | 193 |
| needs_review | 163 |
| downloaded | 58 |
| url_failed | 56 |
| access_blocked | 5 |
| local | 1 |

### Material roles

| Role | Count |
|---|---:|
| direct_computus | 747 |
| counterpoint | 5 |

### Confirmed hosts

| Host | Confirmed records |
|---|---:|
| gallica.bnf.fr | 62 |
| digi.vatlib.it | 62 |
| www.e-codices.unifr.ch | 53 |
| iiif.bodleian.ox.ac.uk | 37 |
| www.bl.uk | 35 |
| api.digitale-sammlungen.de | 18 |
| e-codices.unifr.ch | 8 |
| bvmm.irht.cnrs.fr | 6 |
| digital.dombibliothek-koeln.de | 6 |
| dms-data.stanford.edu | 5 |
| www.digitale-sammlungen.de | 3 |
| archive.org | 3 |
| searcharchives.bl.uk | 3 |
| www.e-codices.ch | 2 |
| arca.irht.cnrs.fr | 1 |
| brema.suub.uni-bremen.de | 1 |
| iiif.biblissima.fr | 1 |
| digi.ub.uni-heidelberg.de | 1 |
| cecilia.mediatheques.grand-albigeois.fr | 1 |
| api.irht.cnrs.fr | 1 |
| wellcomecollection.org | 1 |
| archives.bodleian.ox.ac.uk | 1 |

### Downloaded images by host

| Host | Image files | ~GiB |
|---|---:|---:|
| www.e-codices.unifr.ch | 21290 | 71.845 |
| digi.vatlib.it | 17614 | 14.351 |
| unknown | 12599 | 46.055 |
| gallica.bnf.fr | 5400 | 16.026 |
| api.digitale-sammlungen.de | 5012 | 5.853 |
| dms-data.stanford.edu | 2446 | 10.601 |
| digital.dombibliothek-koeln.de | 1806 | 1.827 |
| bvmm.irht.cnrs.fr | 1236 | 1.328 |
| www.digitale-sammlungen.de | 203 | 0.984 |
| archive.org | 124 | 0.070 |
| digi.ub.uni-heidelberg.de | 1 | 0.001 |
| arca.irht.cnrs.fr | 1 | 0.003 |

### Acquire queue progress

- `acquire_queue.jsonl`: 35/311 with ≥5 images (4 partial, 272 empty/missing)
- `needs_review_acquire_queue.jsonl`: 18/172 with ≥5 images (5 partial, 149 empty/missing)

### Discovery adapter hits

| Adapter | Candidate count |
|---|---:|
| `adapter:europeana_search` | 459 |
| `adapter:ecodices_search` | 24 |
| `adapter:gallica_sru` | 7 |
| `adapter:digivatlib_shelfmark` | 5 |
| `adapter:digivatlib_view` | 5 |

### Rights / license statements (top)

| Statement | Count |
|---|---:|
| Images Copyright Biblioteca Apostolica Vaticana | 61 |
| http://creativecommons.org/licenses/by-nc/4.0/ | 41 |
| <span>Photo: © Bodleian Libraries, University of Oxford. Terms of use: <a href="https://creativecomm | 35 |
| https://gallica.bnf.fr/html/und/conditions-dutilisation-des-contenus-de-gallica | 24 |
| https://creativecommons.org/publicdomain/mark/1.0/ | 18 |
| https://creativecommons.org/publicdomain/zero/1.0/deed.en | 10 |
| http://creativecommons.org/licenses/by-nc/3.0/deed.fr | 7 |
| Erzbischöfliche Diözesan- und Dombibliothek | 6 |
| https://creativecommons.org/licenses/by-nc/4.0/ | 5 |
| Staats- und Universitätsbibliothek | 1 |
| http://creativecommons.org/publicdomain/mark/1.0/deed.de | 1 |
| Photo: © Corpus Christi College, Oxford. Terms of use: Non-commercial use is permitted as long as th | 1 |
| <span>Photo: © The President and Fellows of St John's College, Oxford. Terms of use: <a href="https: | 1 |
| Bibliothèque numérique du réseau des Médiathèques du Grand Albigeois | 1 |

### Top failure reasons

| Reason | Count |
|---|---:|
| `http_403` | 478 |
| `http_429` | 34 |
| `http_404` | 13 |
| `ConnectTimeout: timed out` | 10 |
| `ConnectError: [Errno -2] Name or service not known` | 7 |
| `robots_disallow` | 5 |
| `RemoteProtocolError: Server disconnected without sending a response.` | 4 |
| `http_500` | 1 |
| `ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch, certificate is not valid fo` | 1 |

## Interpretation notes

- Confirmed means a candidate URL was successfully probed (HTTP 200) and met the confirmation threshold (existing IIIF / high-confidence catalogue link).
- Access-blocked records retain catalogue URLs but are not queued for image download under robots policy (e.g. Harvard).
- Needs-review records have candidate pages but insufficient confirmation (ambiguous Archive.org hits, soft failures).
- Counterpoints in the 35-target cohort remain labeled `counterpoint` and must not enter the direct-computus denominator.
- Image acquisition is separate from HTR; generate a reviewed downstream queue only after sampling host adapters.

## Companion machine-readable files

- `coverage.json`
- `confirmed.json` / `downloaded.json`
- `access_blocked.json`
- `needs_review.json` / `url_failed.json` / `unavailable.json` / `no_url.json`
- `cohort_crosswalk.json`
- `by_institution.json`
- `repository_samples.json` (from validate_repository_samples.py)
