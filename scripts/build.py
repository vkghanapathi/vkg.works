"""
build.py — Static site builder for vkg.works
Usage: python scripts/build.py --site-url https://vkg.works [--social]
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from converters import (
    ArticleData, CONVERTERS,
    convert_audio, convert_video_md, convert_coverage, convert_markdown,
)
import rss as rss_module

# ─── Paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
CONTENT_DIR = ROOT / 'content'
TEMPLATES_DIR = ROOT / 'templates'
ASSETS_DIR = ROOT / 'assets'
STATE_FILE = ROOT / 'state' / 'posted.json'
REGISTRY_FILE = ROOT / 'state' / 'registry.json'
SITE_DIR = ROOT / 'site'

SECTION_PREFIX = {
    'articles': 'A',  'poems': 'P',  'songs': 'S',  'books': 'B',
    'audio': 'AU',    'video': 'V',  'projects': 'PR', 'coverage': 'C',
}

SECTIONS = ['articles', 'poems', 'songs', 'books', 'audio', 'video',
            'projects', 'live', 'coverage', 'contact']

# Template to use per section
SECTION_TEMPLATES = {
    'articles': 'article.html',
    'poems':    'poem_song.html',
    'songs':    'poem_song.html',
    'books':    'book.html',
    'audio':    'audio.html',
    'video':    'video.html',
    'projects': 'article.html',
    'coverage': 'coverage_gallery.html',
}

SECTION_TITLES = {
    'articles': 'Articles',
    'poems':    'Poems',
    'songs':    'Songs',
    'books':    'Books',
    'audio':    'Audio',
    'video':    'Video',
    'projects': 'Projects',
    'live':     'Live',
    'coverage': 'Coverage',
    'contact':  'Contact',
}

QUEUE_STATUSES = {'planned', 'draft', 'in-progress', 'in progress'}


# ─── Registry ───────────────────────────────────────────────────────────────
def load_registry() -> dict:
    if REGISTRY_FILE.exists():
        return json.loads(REGISTRY_FILE.read_text(encoding='utf-8'))
    return {s: {} for s in SECTION_PREFIX}


def save_registry(registry: dict) -> None:
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )


def assign_refs(sections: dict, registry: dict) -> None:
    """Assign permanent A·0001-style refs to every item. Idempotent."""
    for section, items in sections.items():
        if section not in SECTION_PREFIX:
            continue
        prefix = SECTION_PREFIX[section]
        reg = registry.setdefault(section, {})
        next_num = max(reg.values(), default=0) + 1
        for item in sorted(items, key=lambda x: x.date or '0000-00-00'):
            if item.slug not in reg:
                reg[item.slug] = next_num
                next_num += 1
            item.ref = f"{prefix}·{reg[item.slug]:04d}"


# ─── Jinja2 env ─────────────────────────────────────────────────────────────
def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(['html']),
        keep_trailing_newline=True,
    )
    # urlencode filter for pdf_embed template
    from urllib.parse import quote
    env.filters['urlencode'] = lambda s: quote(str(s), safe='/:')
    return env


# ─── Scanning ───────────────────────────────────────────────────────────────
def scan_section(section: str) -> list[ArticleData]:
    section_dir = CONTENT_DIR / section
    if not section_dir.exists():
        return []

    items: list[ArticleData] = []
    text_exts = set(CONVERTERS.keys())
    audio_exts = {'.mp3', '.m4a', '.ogg', '.wav'}
    processed_slugs: set[str] = set()

    if section == 'audio':
        for f in sorted(section_dir.iterdir()):
            if f.suffix.lower() in audio_exts:
                md_companion = f.with_suffix('.md')
                data = convert_audio(f, section, md_companion if md_companion.exists() else None)
                if data.slug not in processed_slugs:
                    items.append(data)
                    processed_slugs.add(data.slug)
        return _sort_items(items)

    if section == 'video':
        for f in sorted(section_dir.iterdir()):
            if f.suffix.lower() == '.md':
                data = convert_video_md(f, section)
                if data.slug not in processed_slugs:
                    items.append(data)
                    processed_slugs.add(data.slug)
        return _sort_items(items)

    if section == 'coverage':
        for entry in sorted(section_dir.iterdir()):
            if entry.is_dir():
                data = convert_coverage(entry, section)
                if data.slug not in processed_slugs:
                    items.append(data)
                    processed_slugs.add(data.slug)
            elif entry.suffix.lower() == '.md':
                data = convert_coverage(entry, section)
                if data.slug not in processed_slugs:
                    items.append(data)
                    processed_slugs.add(data.slug)
        return _sort_items(items)

    for f in sorted(section_dir.iterdir()):
        if not f.is_file():
            continue
        suffix = f.suffix.lower()
        if suffix not in text_exts:
            continue
        # Skip .md sidecars — their metadata is read by convert_docx instead
        if suffix == '.md' and f.with_suffix('.docx').exists():
            continue
        converter = CONVERTERS[suffix]
        try:
            data = converter(f, section)
        except Exception as e:
            print(f'  WARNING: failed to convert {f}: {e}', file=sys.stderr)
            continue
        if data.slug not in processed_slugs:
            items.append(data)
            processed_slugs.add(data.slug)

    return _sort_items(items)


def _sort_items(items: list[ArticleData]) -> list[ArticleData]:
    return sorted(items, key=lambda x: x.date or '0000-00-00', reverse=True)


def _get_categories(items: list[ArticleData]) -> list[str]:
    """Return ordered unique categories preserving first-seen order."""
    seen: list[str] = []
    for item in items:
        if item.category and item.category not in seen:
            seen.append(item.category)
    return seen


def scan_all_sections() -> dict[str, list[ArticleData]]:
    print('Scanning content...')
    sections: dict[str, list[ArticleData]] = {}
    for s in SECTIONS:
        if s in ('live', 'contact'):
            continue
        items = scan_section(s)
        sections[s] = items
        print(f'  {s}: {len(items)} item(s)')
    return sections


# ─── Rendering ──────────────────────────────────────────────────────────────
def render_site(sections: dict[str, list[ArticleData]], site_url: str, env: Environment) -> None:
    print('Rendering site...')
    SITE_DIR.mkdir(parents=True, exist_ok=True)

    # Copy assets
    site_assets = SITE_DIR / 'assets'
    if site_assets.exists():
        shutil.rmtree(site_assets)
    if ASSETS_DIR.exists():
        shutil.copytree(str(ASSETS_DIR), str(site_assets))
        print('  Copied assets/')

    # Separate queue items (planned/draft) from published items
    queue_items: list[ArticleData] = []
    for section_name in list(sections.keys()):
        regular, queued = [], []
        for item in sections[section_name]:
            if item.status and item.status.lower() in QUEUE_STATUSES:
                queued.append(item)
            else:
                regular.append(item)
        sections[section_name] = regular
        queue_items.extend(queued)

    # Render home page
    all_items = [item for items in sections.values() for item in items]
    featured_items = [i for i in all_items if getattr(i, 'featured', False)]
    latest_items = sorted(
        [i for i in all_items if i.date],
        key=lambda x: x.date, reverse=True
    )[:7]
    home_tmpl = env.get_template('home.html')
    (SITE_DIR / 'index.html').write_text(
        home_tmpl.render(
            sections=sections,
            featured_items=featured_items,
            latest_items=latest_items,
            site_url=site_url,
        ),
        encoding='utf-8'
    )
    print('  Rendered index.html')

    # Render section list pages
    list_tmpl = env.get_template('section_list.html')
    for section_name, items in sections.items():
        sec_dir = SITE_DIR / section_name
        sec_dir.mkdir(parents=True, exist_ok=True)
        categories = _get_categories(items)
        (sec_dir / 'index.html').write_text(
            list_tmpl.render(
                section_name=section_name,
                section_title=SECTION_TITLES.get(section_name, section_name.title()),
                items=items,
                categories=categories,
                active_category=None,
            ),
            encoding='utf-8'
        )
        # Render per-category sub-pages
        if categories:
            section_title = SECTION_TITLES.get(section_name, section_name.title())
            for cat in categories:
                cat_slug = cat.lower().replace(' ', '-')
                filtered = [item for item in items if item.category == cat]
                cat_dir = sec_dir / cat_slug
                cat_dir.mkdir(parents=True, exist_ok=True)
                (cat_dir / 'index.html').write_text(
                    list_tmpl.render(
                        section_name=section_name,
                        section_title=section_title,
                        items=filtered,
                        categories=categories,
                        active_category=cat,
                    ),
                    encoding='utf-8'
                )

    # Render individual item pages
    for section_name, items in sections.items():
        tmpl_name = SECTION_TEMPLATES.get(section_name)
        if not tmpl_name:
            continue
        for item in items:
            item_dir = SITE_DIR / section_name / item.slug
            item_dir.mkdir(parents=True, exist_ok=True)

            item_tmpl = env.get_template('pdf_embed.html' if item.is_pdf else tmpl_name)
            ctx = _build_context(item, site_url)
            html = item_tmpl.render(**ctx)
            (item_dir / 'index.html').write_text(html, encoding='utf-8')

            # Copy associated binary files
            _copy_item_assets(item, item_dir)

    print(f'  Rendered {sum(len(v) for v in sections.values())} item pages')

    # Render live page
    _render_live(env)

    # Render contact page
    contact_tmpl = env.get_template('contact.html')
    contact_dir = SITE_DIR / 'contact'
    contact_dir.mkdir(parents=True, exist_ok=True)
    (contact_dir / 'index.html').write_text(
        contact_tmpl.render(), encoding='utf-8'
    )

    # Render queue page (planned + draft items)
    queue_tmpl = env.get_template('queue.html')
    queue_dir = SITE_DIR / 'queue'
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / 'index.html').write_text(
        queue_tmpl.render(queue_items=queue_items),
        encoding='utf-8'
    )


def _build_context(item: ArticleData, site_url: str) -> dict:
    """Build Jinja2 template context from ArticleData."""
    ctx = {
        'title':        item.title,
        'date':         item.date,
        'date_display': item.date_display,
        'author':       item.author,
        'excerpt':      item.excerpt,
        'body_html':    item.body_html,
        'slug':         item.slug,
        'section_name': item.section,
        'site_url':     site_url,
    }
    if item.is_pdf:
        ctx['pdf_url'] = f'/{item.section}/{item.slug}/{item.pdf_filename}'
        ctx['filename'] = item.pdf_filename
    if item.audio_file:
        ctx['audio_url'] = f'/{item.section}/{item.slug}/{item.audio_file}'
        ctx['audio_filename'] = item.audio_file
        # notation_pdf field repurposed to store MIME type for audio items
        if item.section == 'audio':
            ctx['audio_mime'] = item.notation_pdf or 'audio/mpeg'
    if item.youtube_url:
        ctx['youtube_url'] = item.youtube_url
        ctx['youtube_embed_url'] = item.youtube_url
    if item.notation_pdf and item.section not in ('audio',):
        ctx['notation_pdf_url'] = f'/{item.section}/{item.slug}/{item.notation_pdf}'
    if item.pdf_file:
        ctx['pdf_url'] = f'/{item.section}/{item.slug}/{item.pdf_file}'
    if item.video_file:
        ctx['video_file_url'] = f'/{item.section}/{item.slug}/{item.video_file}'
    if item.coverage_type:
        ctx['coverage_type'] = item.coverage_type
    if item.source_url:
        ctx['source_url'] = item.source_url
    if item.photos:
        ctx['photos'] = item.photos
    if item.ref:
        ctx['ref'] = item.ref
    if item.category:
        ctx['category'] = item.category
    return ctx


def _copy_item_assets(item: ArticleData, item_dir: Path) -> None:
    """Copy binary files (PDF, audio, images) into the built item directory."""
    src_dir = CONTENT_DIR / item.section

    # For coverage folders, source is the folder itself
    if item.section == 'coverage':
        coverage_folder = CONTENT_DIR / 'coverage' / item.slug
        if not coverage_folder.exists():
            # Try with date prefix
            for d in (CONTENT_DIR / 'coverage').iterdir():
                if d.is_dir() and d.name.endswith(f'-{item.slug}'):
                    coverage_folder = d
                    break
        if coverage_folder.exists():
            img_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
            for img in coverage_folder.iterdir():
                if img.suffix.lower() in img_exts:
                    shutil.copy2(str(img), str(item_dir / img.name))
        return

    # Copy PDF
    for attr in ('pdf_filename', 'pdf_file'):
        fname = getattr(item, attr, None)
        if fname:
            src = src_dir / fname
            if src.exists():
                shutil.copy2(str(src), str(item_dir / fname))

    # Copy audio
    if item.audio_file:
        src = src_dir / item.audio_file
        if src.exists():
            shutil.copy2(str(src), str(item_dir / item.audio_file))

    # Copy notation PDF
    if item.notation_pdf and item.section not in ('audio',):
        src = src_dir / item.notation_pdf
        if src.exists():
            shutil.copy2(str(src), str(item_dir / item.notation_pdf))

    # Copy video file
    if item.video_file:
        src = src_dir / item.video_file
        if src.exists():
            shutil.copy2(str(src), str(item_dir / item.video_file))

    # Write extracted images (from DOCX inline images)
    for img_fname, img_bytes in getattr(item, 'extracted_images', []):
        (item_dir / img_fname).write_bytes(img_bytes)


def _render_live(env: Environment) -> None:
    live_dir = CONTENT_DIR / 'live'
    events_file = live_dir / 'events.yaml'
    stream_file = live_dir / 'stream.yaml'

    events = []
    stream_active = False
    stream_url = ''
    stream_title = ''

    if events_file.exists():
        data = yaml.safe_load(events_file.read_text(encoding='utf-8')) or {}
        events = data.get('events', [])
        # Filter out past events
        today = datetime.now(tz=timezone.utc).date().isoformat()
        events = [e for e in events if str(e.get('date', '')) >= today]

    if stream_file.exists():
        data = yaml.safe_load(stream_file.read_text(encoding='utf-8')) or {}
        stream_active = data.get('stream_active', False)
        stream_url = data.get('stream_url', '')
        stream_title = data.get('stream_title', 'Live')

    live_tmpl = env.get_template('live.html')
    live_out = SITE_DIR / 'live'
    live_out.mkdir(parents=True, exist_ok=True)
    (live_out / 'index.html').write_text(
        live_tmpl.render(
            events=events,
            stream_active=stream_active,
            stream_url=stream_url,
            stream_title=stream_title,
        ),
        encoding='utf-8'
    )


# ─── Social media state ──────────────────────────────────────────────────────
def load_posted() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    return {}


def detect_new_items(sections: dict[str, list[ArticleData]]) -> list[tuple[str, ArticleData]]:
    posted = load_posted()
    new_items = []
    for section_name, items in sections.items():
        for item in items:
            key = f'{section_name}:{item.slug}'
            if key not in posted:
                new_items.append((section_name, item))
    return new_items


def save_posted(new_items: list[tuple[str, ArticleData]], platforms: list[str]) -> None:
    posted = load_posted()
    for section_name, item in new_items:
        key = f'{section_name}:{item.slug}'
        posted[key] = {
            'posted_at': datetime.now(tz=timezone.utc).isoformat(),
            'platforms': platforms,
            'title': item.title,
        }
    STATE_FILE.write_text(
        json.dumps(posted, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )


# ─── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description='Build vkg.works static site')
    parser.add_argument('--site-url', default='https://vkg.works')
    parser.add_argument('--social', action='store_true',
                        help='Post new items to social media')
    parser.add_argument('--dry-run', action='store_true',
                        help='Build site but skip FTP and social (test mode)')
    args = parser.parse_args()

    site_url = args.site_url.rstrip('/')
    env = _make_env()

    # 1. Scan all content
    sections = scan_all_sections()

    # 1b. Assign permanent reference numbers
    registry = load_registry()
    assign_refs(sections, registry)

    # 2. Render static site
    render_site(sections, site_url, env)

    # 3. Generate RSS feed
    rss_output = SITE_DIR / 'rss.xml'
    rss_module.generate(sections, site_url, rss_output)
    print(f'  Generated rss.xml ({sum(len(v) for v in sections.values())} items)')

    # 4. Save updated registry
    save_registry(registry)

    # 5. Detect new items for social posting
    new_items = detect_new_items(sections)
    if new_items:
        print(f'  {len(new_items)} new item(s) detected for social media')

    # 6. Social posting (only if --social and not --dry-run)
    if args.social and not args.dry_run and new_items:
        import social as social_module
        posted_platforms = social_module.post_all(new_items, site_url)
        save_posted(new_items, posted_platforms)
        print(f'  Social media: posted to {posted_platforms}')
    elif new_items and not args.social:
        print('  (Use --social flag to post to social media)')

    print(f'\nBuild complete. Output: {SITE_DIR}')


if __name__ == '__main__':
    main()
