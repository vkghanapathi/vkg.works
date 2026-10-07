# Author registry — file format

One Markdown file per author: `content/authors/<slug>.md`.
Front matter fields:

| field | req | meaning |
|-------|-----|---------|
| `slug` | yes | stable id; used in URLs (`/authors/<slug>/`) and in front matter `author_ids` |
| `name` | yes | display name (diacritics ok) |
| `sort_name` | no | for alphabetical ordering |
| `roles` | no | list, e.g. `[author, editor]` |
| `orcid` | no | ORCID id |
| `photo` | no | filename under `content/authors/_media/` |
| `prolific` | no | `true`/`false` override; if omitted, computed (>=5 works) |
| `bio_short` | no | 1–2 paragraphs; shown for minor authors and on cards |
| `links` | no | list of `{label,url}` |

The Markdown **body** is the full biography — rendered only on a prolific author's
dedicated page. Minor authors need only `bio_short`.

Legacy free-text `author:` strings in content are mapped to a slug via
`state/author_aliases.json`. Add new variants there as needed.
