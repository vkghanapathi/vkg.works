# Publications & Authors — Site Architecture

Status: design + scaffolding (2026-06-08). Target site: **vkg.works** generator
(`scripts/build.py` + Jinja templates). Additive layer — existing build is unaffected
until the build hook is enabled.

## Goal
1. A **/publications/** page listing all book-works, grouped by publisher (VVV / SGS) and
   filterable by Veda / subject / language; every title links to its work page.
2. **Author pages**: a dedicated **/authors/<slug>/** page for *prolific* authors & editors
   (full biography + complete cross-linked works list); a **1–2 paragraph inline bio** for
   authors with few works (rendered on **/authors/** with an `#<slug>` anchor — no own page).
3. **Cross-linking everywhere**: any author name → the author's page/anchor; any title →
   its work page. Applied on item pages, section lists, the catalogue, publications and
   author pages alike.

## The pivotal change
Today `author:` in front matter is a **free-text string** defaulting to
"Dr. Vamshi Krishna Ghanapāṭhī" (see `converters.py`). We promote authors to a
**first-class entity** with a registry, and resolve every author string to it.

## Data model

### Author registry — `content/authors/<slug>.md`
```yaml
---
slug: vkg                       # stable id, used in URLs and front matter
name: Dr. Vaṁśīkṛṣṇa Ghanapāṭhī # display name (diacritics ok)
sort_name: Ghanapathi Vamsikrsna
roles: [author, editor]
orcid: 0009-0007-3852-0158
photo: vkg.jpg                  # optional, under content/authors/_media/
prolific: true                  # optional override; else computed (see threshold)
bio_short: >                    # 1–2 paragraphs; used for minor authors & cards
  ...
links:
  - {label: ORCID, url: https://orcid.org/0009-0007-3852-0158}
---
<full multi-paragraph biography in Markdown — rendered only on the dedicated page>
```

### Name → slug resolution — `state/author_aliases.json`
Maps every free-text `author:` variant to a slug, so legacy content needs no editing:
```json
{ "Dr. Vamshi Krishna Ghanapāṭhī": "vkg",
  "Dr. Vaṁśīkṛṣṇa Ghanapāṭhī": "vkg",
  "Sri Ganapathi Sachchidananda Swamiji": "sgs" }
```
Unresolved names → auto-slug + a **stub** author entry flagged `needs_bio: true`.

### Multi-author / editor support
Front matter may optionally carry `author_ids: [vkg, sgs]` and/or `editor_ids: [...]`.
If absent, the single `author:` string is resolved via aliases. This covers co-edited
granthas and works where VKG is *editor* and another is *author*.

### Publisher & ISBN on works
Add optional front-matter fields to content (sourced from `ISBN_Catalogue_Master.xlsx`):
`publisher: VVV|SGS`, `isbn:`, `pub_year:`, `language:`. Surfaced on the work page and
the publications listing.

## Prolific rule
`prolific = explicit override, else (work_count >= THRESHOLD)`, `THRESHOLD = 5` (configurable).
- **Prolific** → dedicated `/authors/<slug>/` with photo, full bio, roles, ORCID, and the
  complete works list (grouped by section/publisher), each entry linked.
- **Minor** → no own page; the `bio_short` (1–2 paras) appears under "Contributors" on
  `/authors/` at anchor `#<slug>`; their name links there.

## Pages & URLs
| URL | Template | Content |
|-----|----------|---------|
| `/publications/` | `publications.html` | all works grouped by publisher; filters; title→work, author→author |
| `/authors/` | `authors.html` | prolific authors as cards (→ page) + minor authors inline (`#slug`) |
| `/authors/<slug>/` | `author.html` | full bio + complete cross-linked works list |

## Linking conventions
- Jinja filter **`author_url(name)`** → `/authors/<slug>/` (prolific) or `/authors/#<slug>`
  (minor); **`author_label(name)`** → display name. Backed by `state/authors_resolved.json`
  (emitted by the author builder): `{ "<name or slug>": {slug,url,name,prolific} }`.
- Jinja filter **`work_url(uid|slug)`** → the work's canonical `/<section>/<slug>/`.
- Shared partials `_author_link.html`, `_work_link.html` keep markup consistent.
- Item templates (`book.html`, `article.html`, `poem_song.html`), `section_list.html`,
  `catalogue.html` render the author through `author_url`/`author_label`.

## Build integration
- **`scripts/build_authors.py`** (standalone + importable): loads the registry + aliases,
  scans content front matter → `author → [works]`, applies the threshold, renders
  `/authors/`, each `/authors/<slug>/`, and `/publications/`, and writes
  `state/authors_resolved.json`. Runs after the main render; safe to run alone for testing.
- **`build.py`**: (a) register the `author_url`/`author_label`/`work_url` filters in
  `_make_env()` (reading `authors_resolved.json` if present); (b) call
  `build_authors.render(...)` at the end of `render_site`; (c) add **Publications** and
  **Authors** to the nav in `base.html`.
- `test_build.py` must stay green.

## Rollout order
1. ✅ Registry schema + seed authors (`vkg`, `sgs`) + aliases.
2. ✅ Templates (`author.html`, `authors.html`, `publications.html`, partials).
3. ✅ `build_authors.py` (generates pages + `authors_resolved.json`).
4. ⏳ Wire filters + nav + hook into `build.py`; run `test_build.py`.
5. ⏳ Backfill `bio_short` for minor authors; add `publisher/isbn` to book front matter from the catalogue.
