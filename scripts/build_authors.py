"""
build_authors.py — Authors & Publications layer for vkg.works
Additive: reuses build.py's scanners so URLs/slugs match exactly, then renders
/authors/, /authors/<slug>/ and /publications/, and writes
state/authors_resolved.json for cross-linking.

Run standalone:  python scripts/build_authors.py
Or import:       build_authors.render(env)   # from build.py after render_site
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from collections import defaultdict

import yaml
try:
    import markdown as _md
    def md(t): return _md.markdown(t or '', extensions=['extra'])
except Exception:
    def md(t):  # minimal fallback: paragraphs only
        return ''.join(f'<p>{p.strip()}</p>' for p in (t or '').split('\n\n') if p.strip())

import build  # reuse dirs, scanners, env

CONTENT_DIR   = build.CONTENT_DIR
SITE_DIR      = build.SITE_DIR
TEMPLATES_DIR = build.TEMPLATES_DIR
STATE_DIR     = (build.REGISTRY_FILE.parent if hasattr(build, 'REGISTRY_FILE') else Path('state'))
AUTHORS_DIR   = CONTENT_DIR / 'authors'
ALIASES_FILE  = STATE_DIR / 'author_aliases.json'
RESOLVED_FILE = STATE_DIR / 'authors_resolved.json'

PROLIFIC_THRESHOLD = 5
# Default publisher per author slug until `publisher:` is backfilled into front matter
PUBLISHER_BY_SLUG = {'vkg': 'VVV — Veda Vijñāna Viṣṭāram',
                     'sgs': 'SGS — Avadhūta Datta Peeṭham'}
SECTION_LABEL = {'books': 'Books', 'articles': 'Articles', 'poems': 'Poems',
                 'songs': 'Songs', 'projects': 'Projects'}


def _slugify(name: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return s or 'unknown'


def _split_front_matter(text: str):
    if text.startswith('---'):
        parts = text.split('---', 2)
        if len(parts) >= 3:
            return yaml.safe_load(parts[1]) or {}, parts[2].strip()
    return {}, text.strip()


def load_authors() -> dict:
    authors = {}
    if AUTHORS_DIR.exists():
        for f in sorted(AUTHORS_DIR.glob('*.md')):
            if f.name.startswith('_'):
                continue
            meta, body = _split_front_matter(f.read_text(encoding='utf-8'))
            slug = meta.get('slug') or f.stem
            authors[slug] = {
                'slug': slug,
                'name': meta.get('name', slug),
                'sort_name': meta.get('sort_name', meta.get('name', slug)),
                'roles': meta.get('roles', []),
                'orcid': meta.get('orcid'),
                'photo': meta.get('photo'),
                'prolific_override': meta.get('prolific'),
                'bio_short': (meta.get('bio_short') or '').strip(),
                'bio_html': md(body),
                'links': meta.get('links', []),
                'needs_bio': False,
            }
    return authors


def load_aliases() -> dict:
    if ALIASES_FILE.exists():
        return json.loads(ALIASES_FILE.read_text(encoding='utf-8'))
    return {}


def collect_works():
    """Return list of work dicts via build.scan_section (published + draft)."""
    works = []
    sections = list(getattr(build, 'SECTION_PREFIX', {}).keys()) or \
               ['articles', 'books', 'poems', 'songs', 'projects']
    for section in sections:
        try:
            items = build.scan_section(section)
        except Exception as e:
            print(f'  build_authors: skip {section}: {e}', file=sys.stderr)
            continue
        for it in items:
            fm = getattr(it, '__dict__', {})
            works.append({
                'title': it.title,
                'slug': it.slug,
                'section': section,
                'url': f'/{section}/{it.slug}/',
                'author_name': it.author or '',
                'year': (it.date or '')[:4] if getattr(it, 'date', None) else '',
                'language': getattr(it, 'language', None),
                'subject': getattr(it, 'subject', None),
                'publisher': fm.get('publisher'),
                'isbn': fm.get('isbn'),
                'uid': getattr(it, 'uid', None),
            })
    return works


def render(env=None):
    authors = load_authors()
    aliases = load_aliases()
    works = collect_works()

    # resolve author name -> slug
    def resolve(name: str) -> str:
        if not name:
            return 'unknown'
        if name in aliases:
            return aliases[name]
        for slug, a in authors.items():
            if a['name'] == name:
                return slug
        return _slugify(name)

    by_author = defaultdict(list)
    for w in works:
        slug = resolve(w['author_name'])
        w['author_slug'] = slug
        by_author[slug].append(w)

    # ensure stub entries for unknown authors
    for slug, ws in by_author.items():
        if slug not in authors:
            authors[slug] = {
                'slug': slug, 'name': ws[0]['author_name'] or slug,
                'sort_name': ws[0]['author_name'] or slug, 'roles': [],
                'orcid': None, 'photo': None, 'prolific_override': None,
                'bio_short': '', 'bio_html': '', 'links': [], 'needs_bio': True,
            }

    # prolific classification
    for slug, a in authors.items():
        count = len(by_author.get(slug, []))
        a['work_count'] = count
        a['prolific'] = a['prolific_override'] if a['prolific_override'] is not None \
            else (count >= PROLIFIC_THRESHOLD)
        a['url'] = f'/authors/{slug}/' if a['prolific'] else f'/authors/#{slug}'

    if env is None:
        env = build._make_env()

    # publisher resolution for a work
    def pub_of(w):
        return w.get('publisher') or PUBLISHER_BY_SLUG.get(w['author_slug'], 'Other')

    # attach author_url to each work for templates
    for w in works:
        a = authors.get(w['author_slug'], {})
        w['author_url'] = a.get('url')

    # ---- /publications/ ----
    groups = defaultdict(list)
    for w in sorted(works, key=lambda x: (x['title'] or '').lower()):
        groups[pub_of(w)].append(w)
    groups = dict(sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])))
    out = SITE_DIR / 'publications'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'index.html').write_text(
        env.get_template('publications.html').render(
            groups=groups, total=len(works)), encoding='utf-8')

    # ---- /authors/ index ----
    prolific = sorted([a for a in authors.values() if a['prolific'] and a['work_count']],
                      key=lambda a: (-a['work_count'], a['sort_name']))
    minor = sorted([a for a in authors.values() if not a['prolific'] and a['work_count']],
                   key=lambda a: a['sort_name'])
    for a in minor:
        a['bio_html'] = a['bio_html'] or md(a['bio_short']) or f"<p>{a['name']}.</p>"
        a['works'] = sorted(by_author.get(a['slug'], []), key=lambda w: w['title'] or '')
    out = SITE_DIR / 'authors'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'index.html').write_text(
        env.get_template('authors.html').render(prolific=prolific, minor=minor),
        encoding='utf-8')

    # ---- /authors/<slug>/ for prolific ----
    for a in prolific:
        ws = sorted(by_author.get(a['slug'], []), key=lambda w: (w['section'], w['title'] or ''))
        grouped = defaultdict(list)
        for w in ws:
            grouped[SECTION_LABEL.get(w['section'], w['section'].title())].append(w)
        adir = out / a['slug']
        adir.mkdir(parents=True, exist_ok=True)
        (adir / 'index.html').write_text(
            env.get_template('author.html').render(
                author=a, works=ws, works_grouped=dict(grouped)), encoding='utf-8')

    # ---- resolution map for cross-linking from other templates ----
    resolved = {}
    for slug, a in authors.items():
        entry = {'slug': slug, 'url': a['url'], 'name': a['name'], 'prolific': a['prolific']}
        resolved[slug] = entry
        resolved[a['name']] = entry
    for name, slug in aliases.items():
        if slug in authors:
            resolved[name] = resolved[slug]
    RESOLVED_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f'  Authors: {len(prolific)} prolific pages, {len(minor)} contributors; '
          f'Publications: {len(works)} works in {len(groups)} groups')


if __name__ == '__main__':
    render()
