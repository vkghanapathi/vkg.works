"""
review_export.py — Generate a standalone HTML review document for VKG.

Collects all content with status=draft (MAP analyses + translations)
and renders a printable single-file HTML document for scholarly review.

Usage:
    python scripts/review_export.py
    python scripts/review_export.py --output review-2026-03.html
    python scripts/review_export.py --map-only
    python scripts/review_export.py --translations-only
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

import frontmatter

ROOT = Path(__file__).parent.parent
CONTENT_DIR = ROOT / 'content'
REGISTRY_FILE = ROOT / 'state' / 'registry.json'

SECTION_PREFIX = {
    'articles': 'A', 'poems': 'P', 'songs': 'S', 'books': 'B',
    'audio': 'AU', 'video': 'V', 'projects': 'PR', 'coverage': 'C',
}

MAP_LABELS = [
    ('mula',           'मूलम् — Mūla (Original Verse)'),
    ('padavibhaga',    'पदविभागः — Padavibhāga (Word Splitting)'),
    ('anvaya',         'अन्वयः — Anvaya (Prose Order)'),
    ('pratipadartha',  'प्रतिपदार्थः — Pratipadārtha (Word-by-Word Meaning)'),
    ('rupa_nishpatti', 'रूपनिष्पत्तिः — Rūpa Niṣpatti (Grammatical Forms)'),
    ('sandhi',         'सन्धिः — Sandhi'),
    ('samasa',         'समासः — Samāsa (Compounds)'),
    ('bhavartha_en',   'Bhāvārtha (English Meaning)'),
    ('commentary',     'तात्पर्यम् — Tātparya (Commentary)'),
]

CSS = """
:root {
  --bg: #fdf9f4;
  --card: #fff;
  --border: #e0d8cc;
  --accent: #7b3f00;
  --muted: #888;
  --text: #1a1a1a;
  --heading: #3d1f00;
  --te-bg: #f7f3fb;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Segoe UI', Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 15px;
  line-height: 1.7;
}
.doc-header {
  background: var(--accent);
  color: #fff;
  padding: 2rem 3rem;
  border-bottom: 4px solid #5a2d00;
}
.doc-header h1 { font-size: 1.8rem; font-weight: 700; }
.doc-header p  { font-size: 0.95rem; opacity: 0.85; margin-top: 0.3rem; }
.toc {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 1.5rem 2rem;
  margin: 2rem 3rem;
  max-width: 900px;
}
.toc h2 { font-size: 1rem; color: var(--muted); text-transform: uppercase; letter-spacing:.05em; margin-bottom:.75rem; }
.toc ol { margin-left: 1.25rem; }
.toc li { margin: .25rem 0; }
.toc a { color: var(--accent); text-decoration: none; }
.toc a:hover { text-decoration: underline; }
.section-block { max-width: 960px; margin: 0 auto; padding: 0 3rem 4rem; }
.section-heading {
  font-size: 1.4rem;
  color: var(--heading);
  border-bottom: 2px solid var(--accent);
  padding-bottom: .5rem;
  margin: 3rem 0 1.5rem;
  font-weight: 700;
}
.item-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 2rem;
  overflow: hidden;
}
.item-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: .75rem 1.25rem;
  background: #faf5ee;
  border-bottom: 1px solid var(--border);
}
.item-uid { font-family: monospace; font-size:.8rem; color: var(--muted); }
.item-title { font-size: 1.05rem; font-weight: 600; color: var(--heading); }
.item-body { padding: 1.25rem; }

/* MAP styles */
.verse-block { margin-bottom: 1.5rem; }
.verse-num {
  font-size: .8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--muted);
  margin-bottom: .5rem;
}
.map-table { width: 100%; border-collapse: collapse; font-size: .88rem; }
.map-table th {
  text-align: right;
  padding: .35rem .75rem .35rem 0;
  vertical-align: top;
  color: var(--muted);
  font-weight: 600;
  font-size: .78rem;
  white-space: nowrap;
  border-bottom: 1px solid #f0ece6;
  width: 28%;
}
.map-table td {
  padding: .35rem 0 .35rem .75rem;
  vertical-align: top;
  border-bottom: 1px solid #f0ece6;
  font-size: .9rem;
  line-height: 1.6;
}
.devanagari { font-size: 1.05em; }

/* Translation styles */
.trans-lang {
  font-size: .78rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--accent);
  margin: 1rem 0 .4rem;
  padding-bottom: .25rem;
  border-bottom: 1px solid var(--border);
}
.trans-text { font-size: .9rem; line-height: 1.9; }
.trans-te { background: var(--te-bg); padding: .75rem 1rem; border-radius: 4px; margin-top: .25rem; }

/* Status badge */
.badge {
  font-size: .7rem;
  padding: .2rem .55rem;
  border-radius: 3px;
  font-weight: 600;
  letter-spacing: .03em;
}
.badge-draft { background: #fff3cd; color: #856404; border: 1px solid #ffd166; }

@media print {
  .item-card { break-inside: avoid; }
  .doc-header { background: #3d1f00 !important; -webkit-print-color-adjust: exact; }
}
"""


def _e(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text), quote=False)


def build_uid_index() -> dict[str, dict]:
    date_prefix = re.compile(r'^\d{4}-\d{2}-\d{2}-')
    with open(REGISTRY_FILE, encoding='utf-8') as f:
        registry = json.load(f)

    uid_index: dict[str, dict] = {}
    for section, prefix in SECTION_PREFIX.items():
        items: dict = registry.get(section, {})
        section_dir = CONTENT_DIR / section
        if not section_dir.exists():
            continue
        slug_to_md: dict[str, Path] = {}
        for md in section_dir.glob('*.md'):
            stem = md.stem
            bare = date_prefix.sub('', stem)
            slug_to_md[bare] = md
            slug_to_md[stem] = md
        for slug, num in items.items():
            uid = f'VKG-{prefix}-{num:03d}'
            md_path = slug_to_md.get(slug)
            if md_path is None:
                continue
            try:
                post = frontmatter.load(str(md_path))
            except Exception:
                continue
            meta = post.metadata
            uid_index[uid] = {
                'section': section, 'slug': slug,
                'md_path': md_path, 'meta': meta,
            }
    return uid_index


def render_map_item(uid: str, meta: dict) -> str:
    title = _e(meta.get('title', uid))
    verses = meta.get('map', [])
    parts = [
        f'<div class="item-card" id="{uid}">',
        f'<div class="item-header">',
        f'<div><span class="item-uid">{uid}</span>'
        f'&nbsp;&nbsp;<span class="item-title">{title}</span></div>',
        f'<span class="badge badge-draft">draft</span>',
        f'</div>',
        f'<div class="item-body">',
    ]
    for i, verse in enumerate(verses, 1):
        vnum = verse.get('verse_num', i)
        parts.append(f'<div class="verse-block">')
        parts.append(f'<div class="verse-num">Verse {_e(str(vnum))}</div>')
        parts.append('<table class="map-table">')
        for key, label in MAP_LABELS:
            val = verse.get(key, '')
            if not val:
                continue
            css_class = ' class="devanagari"' if key in ('mula', 'padavibhaga', 'anvaya', 'rupa_nishpatti', 'sandhi', 'samasa') else ''
            parts.append(
                f'<tr><th>{_e(label)}</th>'
                f'<td{css_class}>{_e(str(val))}</td></tr>'
            )
        parts.append('</table></div>')
    parts.extend(['</div>', '</div>'])
    return '\n'.join(parts)


def render_translation_item(uid: str, meta: dict) -> str:
    title = _e(meta.get('title', uid))
    trans_en = str(meta.get('translation_en', '')).strip()
    trans_te = str(meta.get('translation_te', '')).strip()
    section = meta.get('section', '')

    en_html = _e(trans_en).replace('\n', '<br>')
    te_html = _e(trans_te).replace('\n', '<br>')

    parts = [
        f'<div class="item-card" id="{uid}">',
        f'<div class="item-header">',
        f'<div><span class="item-uid">{uid}</span>'
        f'&nbsp;&nbsp;<span class="item-title">{title}</span></div>',
        f'<span class="badge badge-draft">draft</span>',
        f'</div>',
        f'<div class="item-body">',
    ]
    if trans_en:
        parts.append('<div class="trans-lang">English Translation</div>')
        parts.append(f'<div class="trans-text">{en_html}</div>')
    if trans_te:
        parts.append('<div class="trans-lang">Telugu Translation — తెలుగు అనువాదం</div>')
        parts.append(f'<div class="trans-text trans-te">{te_html}</div>')
    parts.extend(['</div>', '</div>'])
    return '\n'.join(parts)


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(description='Export draft content for VKG review.')
    parser.add_argument('--output', default='vkg-review-draft.html',
                        help='Output HTML file (default: vkg-review-draft.html)')
    parser.add_argument('--map-only', action='store_true')
    parser.add_argument('--translations-only', action='store_true')
    args = parser.parse_args()

    print('Building UID index…')
    uid_index = build_uid_index()

    # Collect MAP drafts
    map_items: list[tuple[str, dict]] = []
    if not args.translations_only:
        for uid, info in sorted(uid_index.items()):
            meta = info['meta']
            if meta.get('map') and meta.get('map_status') == 'draft':
                map_items.append((uid, meta))
        print(f'MAP drafts: {len(map_items)}')

    # Collect translation drafts
    trans_items: list[tuple[str, dict]] = []
    if not args.map_only:
        for uid, info in sorted(uid_index.items()):
            meta = info['meta']
            if (meta.get('translation_en') or meta.get('translation_te')) \
                    and meta.get('translation_status') == 'draft':
                trans_items.append((uid, meta))
        print(f'Translation drafts: {len(trans_items)}')

    # Build TOC
    toc_items = []
    if map_items:
        toc_items.append('<li><a href="#section-map">MAP Analysis — Mūla Artha Pratipatti</a>'
                         f' ({len(map_items)} compositions)<ul>')
        for uid, meta in map_items:
            title = html.escape(str(meta.get('title', uid))[:60])
            toc_items.append(f'<li><a href="#{uid}">{uid} — {title}</a></li>')
        toc_items.append('</ul></li>')
    if trans_items:
        toc_items.append('<li><a href="#section-trans">Translations</a>'
                         f' ({len(trans_items)} compositions)<ul>')
        for uid, meta in trans_items:
            title = html.escape(str(meta.get('title', uid))[:60])
            toc_items.append(f'<li><a href="#{uid}-t">{uid} — {title}</a></li>')
        toc_items.append('</ul></li>')

    today = date.today().strftime('%d %B %Y')
    total = len(map_items) + len(trans_items)

    # Build HTML
    sections = []

    if map_items:
        section_html = [
            '<div class="section-block">',
            '<h2 class="section-heading" id="section-map">'
            'MAP Analysis — Mūla Artha Pratipatti (9-segment Sanskrit Verse Analysis)</h2>',
            '<p style="color:var(--muted);font-size:.9rem;margin-bottom:1.5rem">'
            'Each verse is analyzed across 9 scholarly dimensions. '
            'Please review for accuracy and, if approved, note the UID for status change to <strong>approved</strong>.</p>',
        ]
        for uid, meta in map_items:
            # anchor for translation section (different id)
            section_html.append(render_map_item(uid, meta))
        section_html.append('</div>')
        sections.append('\n'.join(section_html))

    if trans_items:
        section_html = [
            '<div class="section-block">',
            '<h2 class="section-heading" id="section-trans">'
            'Translations — Sanskrit to English &amp; Telugu</h2>',
            '<p style="color:var(--muted);font-size:.9rem;margin-bottom:1.5rem">'
            'Literary translations generated by AI (Gemini 2.0 Flash). '
            'Please review for fidelity to the original and devotional register. '
            'Approved items will be published on vkg.works.</p>',
        ]
        for uid, meta in trans_items:
            # Use -t suffix to avoid collision with MAP anchors for same poem
            card = render_translation_item(uid, meta)
            card = card.replace(f'id="{uid}"', f'id="{uid}-t"', 1)
            section_html.append(card)
        section_html.append('</div>')
        sections.append('\n'.join(section_html))

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VKG Review — Draft Content — {today}</title>
<style>{CSS}</style>
</head>
<body>
<div class="doc-header">
  <h1>VKG Review Document</h1>
  <p>Draft content awaiting scholarly approval &bull; Generated {today} &bull; {total} items</p>
</div>
<div class="toc" style="max-width:960px;margin:2rem auto">
  <h2>Contents</h2>
  <ol>{''.join(toc_items)}</ol>
</div>
{''.join(sections)}
</body>
</html>
"""

    out_path = ROOT / args.output
    out_path.write_text(html_doc, encoding='utf-8')
    print(f'\nReview document written → {out_path}')
    print(f'Open in browser: file:///{out_path.as_posix()}')
    print(f'\nTo approve an item after review:')
    print(f'  MAP:         set  map_status: approved  in the sidecar .md')
    print(f'  Translation: set  translation_status: approved  in the sidecar .md')


if __name__ == '__main__':
    main()
