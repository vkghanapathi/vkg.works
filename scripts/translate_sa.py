"""
translate_sa.py — Translate all Sanskrit compositions by VKG into Telugu and English.

For each poem or song where language contains 'sa' (Sanskrit), this script:
  1. Extracts the Sanskrit text from the DOCX source file
  2. Calls Vertex AI Gemini for literary translation into English and Telugu
  3. Writes two new fields to the .md sidecar:
       translation_en  — English literary translation
       translation_te  — Telugu literary translation
       translation_status: draft  (changed to 'approved' after VKG review)

Translation style:
  - Literary (not word-for-word) — preserves poetic register and devotional tone
  - English: classical scholarly style matching VKG's academic register
  - Telugu: traditional devotional register (bhakti kavya style)
  - Each śloka translated separately with verse numbers preserved

Uses Vertex AI Gemini via gcloud access token — no separate API key needed.

Usage:
    python scripts/translate_sa.py --section poems --limit 10
    python scripts/translate_sa.py --section songs --limit 20
    python scripts/translate_sa.py --uid VKG-P-001 VKG-P-006
    python scripts/translate_sa.py --all          # all Sanskrit poems + songs
    python scripts/translate_sa.py --dry-run --section poems
    python scripts/translate_sa.py --print --uid VKG-P-001
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import docx
import frontmatter
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from _gemini_rest import GeminiClient

ROOT = Path(__file__).parent.parent
CONTENT_DIR = ROOT / 'content'
REGISTRY_FILE = ROOT / 'state' / 'registry.json'

API_DELAY = 1.5  # seconds between calls

SYSTEM_PROMPT = """You are a distinguished Sanskrit scholar and literary translator
with mastery in classical Sanskrit, Telugu, and English. You assist
Dr. Vamśīkṛṣṇa Ghanapāṭhī, a Ghanapāṭhī of Yajurveda and PhD in Sanskrit.

Your translations must:
- Render the devotional and poetic spirit faithfully, not mechanically
- English: classical scholarly style, dignified and devotional, with accuracy
- Telugu: traditional bhakti-kāvya register, in Telugu script
- Preserve verse structure — translate each śloka separately
- Never omit any verse
- Output must be only the JSON object requested, with no other text"""

TRANSLATE_PROMPT = """Translate the following Sanskrit composition by Dr. Vamśīkṛṣṇa Ghanapāṭhī.

Title: {title}

SANSKRIT TEXT:
{sanskrit_text}

Provide a JSON object with exactly two keys:

{{
  "translation_en": "Complete English literary translation. Translate each verse separately, numbering them 1., 2., etc. Preserve the devotional register. Use flowing literary prose or verse form.",
  "translation_te": "సంపూర్ణ తెలుగు అనువాదం। ప్రతి శ్లోకాన్ని వేర్వేరుగా అనువదించండి, 1., 2., అని సంఖ్యలు వేయండి। భక్తి కావ్య శైలిలో అనువదించండి।"
}}

Return only the JSON object."""


def _has_devanagari_letters(text: str) -> bool:
    """Return True only if text contains actual Devanāgarī letters."""
    return any(('\u0904' <= ch <= '\u0963') or ('\u0966' <= ch <= '\u097f') for ch in text)


def extract_sanskrit_text(docx_path: Path) -> str:
    """
    Extract all Sanskrit (Devanāgarī) paragraphs from a DOCX file.
    Returns a single string with all Sanskrit content, suitable for translation.
    """
    doc = docx.Document(str(docx_path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    sa_lines: list[str] = []
    for para in paragraphs:
        if _has_devanagari_letters(para):
            sa_lines.append(para)

    return '\n'.join(sa_lines)


def build_uid_index() -> dict[str, dict]:
    """Build uid → {section, slug, md_path, docx_path, language} from registry."""
    SECTION_PREFIX = {
        'articles': 'A', 'poems': 'P', 'songs': 'S', 'books': 'B',
        'audio': 'AU', 'video': 'V', 'projects': 'PR', 'coverage': 'C',
    }
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
            docx_path = md_path.with_suffix('.docx')
            if not docx_path.exists():
                docx_path = None

            # Read language from sidecar
            language = ''
            try:
                post = frontmatter.load(str(md_path))
                language = str(post.metadata.get('language', ''))
            except Exception:
                pass

            uid_index[uid] = {
                'section': section, 'slug': slug,
                'md_path': md_path, 'docx_path': docx_path,
                'language': language,
            }

    return uid_index


def print_translation(uid: str, info: dict) -> None:
    """Pretty-print the stored translations for a poem."""
    md_path = info['md_path']
    post = frontmatter.load(str(md_path))
    meta = post.metadata
    title = meta.get('title', uid)

    print(f'\n{"═"*70}')
    print(f'TRANSLATION — {uid} — {title}')
    print(f'Status: {meta.get("translation_status", "not set")}')
    print(f'{"═"*70}')

    en = meta.get('translation_en', '')
    te = meta.get('translation_te', '')

    if en:
        print('\n── English ──')
        for line in en.split('\n'):
            print(f'  {line}')
    else:
        print('  (no English translation)')

    if te:
        print('\n── Telugu ──')
        for line in te.split('\n'):
            print(f'  {line}')
    else:
        print('  (no Telugu translation)')


def translate_item(uid: str, info: dict, client: GeminiClient,
                   dry_run: bool, force: bool = False) -> bool:
    """
    Translate one poem/song. Returns True if successful.
    Skips items that already have translation_en unless force=True.
    """
    md_path = info['md_path']
    docx_path = info['docx_path']

    post = frontmatter.load(str(md_path))
    meta = dict(post.metadata)
    title = meta.get('title', uid)
    language = info['language']

    print(f'\n[{uid}] {title}  (lang={language})')

    # Skip if already translated (unless force)
    if not force and meta.get('translation_en'):
        print(f'  SKIP — already translated (use --force to redo)')
        return True

    if docx_path is None or not docx_path.exists():
        print(f'  SKIP — no DOCX found')
        return False

    # Extract Sanskrit text
    sa_text = extract_sanskrit_text(docx_path)
    if not sa_text:
        print(f'  SKIP — no Sanskrit text found in DOCX')
        return False

    char_count = len(sa_text)
    print(f'  {char_count} chars of Sanskrit text extracted')

    if dry_run:
        print(f'  [DRY] Would translate: {sa_text[:100].replace(chr(10)," ")}…')
        return True

    # Truncate very long texts (> 6000 chars) — focus on main content
    if char_count > 6000:
        sa_text = sa_text[:6000]
        print(f'  NOTE — truncated to 6000 chars for translation')

    prompt = TRANSLATE_PROMPT.format(title=title, sanskrit_text=sa_text)
    print(f'  Translating…', end=' ', flush=True)

    result = client.generate_json(SYSTEM_PROMPT, prompt, max_tokens=8000)
    if result is None:
        print('FAILED')
        return False

    translation_en = str(result.get('translation_en', '')).strip()
    translation_te = str(result.get('translation_te', '')).strip()

    if not translation_en and not translation_te:
        print('FAILED — empty result')
        return False

    print('OK')

    # Write to sidecar
    if translation_en:
        meta['translation_en'] = translation_en
    if translation_te:
        meta['translation_te'] = translation_te
    meta['translation_status'] = 'draft'

    yaml_block = yaml.dump(meta, allow_unicode=True,
                           default_flow_style=False, sort_keys=False).rstrip()
    content_body = post.content or ''
    md_path.write_text(f'---\n{yaml_block}\n---\n{content_body}', encoding='utf-8')
    print(f'  Saved → {md_path.name}')
    return True


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        description='Translate Sanskrit compositions by VKG into Telugu and English.'
    )
    parser.add_argument('--uid', nargs='+', metavar='UID',
                        help='One or more UIDs, e.g. VKG-P-001')
    parser.add_argument('--section', metavar='SECTION',
                        help='Process all Sanskrit items in a section (poems/songs/etc.)')
    parser.add_argument('--all', action='store_true',
                        help='Process all Sanskrit poems and songs')
    parser.add_argument('--limit', type=int, default=999,
                        help='Max items to process (default: no limit)')
    parser.add_argument('--force', action='store_true',
                        help='Re-translate even if translation_en already present')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be processed without calling the API')
    parser.add_argument('--print', action='store_true',
                        help='Print stored translations for the given UIDs')
    parser.add_argument('--model', default='gemini-2.0-flash-001',
                        help='Gemini model (default: gemini-2.0-flash-001)')
    parser.add_argument('--project', default='pranetaa',
                        help='GCP project for Vertex AI (default: pranetaa)')
    args = parser.parse_args()

    print('Building UID index…')
    uid_index = build_uid_index()

    # Determine target UIDs
    target_uids: list[str] = []

    if args.uid:
        target_uids = [u.upper() for u in args.uid]
    elif args.all:
        # All Sanskrit poems and songs
        target_uids = [
            uid for uid, info in uid_index.items()
            if info['section'] in ('poems', 'songs') and 'sa' in info['language']
        ]
        target_uids.sort()
        print(f'Found {len(target_uids)} Sanskrit poems/songs')
    elif args.section:
        target_uids = [
            uid for uid, info in uid_index.items()
            if info['section'] == args.section and 'sa' in info['language']
        ]
        target_uids.sort()
        print(f'Found {len(target_uids)} Sanskrit items in section "{args.section}"')
    else:
        parser.error('Specify --uid, --section, or --all')

    # Apply limit
    if len(target_uids) > args.limit:
        target_uids = target_uids[:args.limit]
        print(f'Limiting to {args.limit} items')

    if not target_uids:
        print('No items to process.')
        return

    # Print mode
    if args.print:
        for uid in target_uids:
            info = uid_index.get(uid)
            if info is None:
                print(f'  UNKNOWN UID: {uid}')
                continue
            print_translation(uid, info)
        return

    # Translation mode
    client = GeminiClient(project=args.project, model=args.model) if not args.dry_run else None

    succeeded = failed = skipped = 0
    for uid in target_uids:
        info = uid_index.get(uid)
        if info is None:
            print(f'\n  UNKNOWN UID: {uid}')
            skipped += 1
            continue
        ok = translate_item(uid, info, client, args.dry_run, args.force)
        if ok:
            succeeded += 1
        else:
            failed += 1
        if not args.dry_run:
            time.sleep(API_DELAY)

    print(f'\n{"DRY RUN — " if args.dry_run else ""}Done.')
    print(f'  Succeeded : {succeeded}')
    print(f'  Failed    : {failed}')
    print(f'  Skipped   : {skipped}')
    if not args.dry_run and succeeded > 0:
        print(f'\nAll translations saved with translation_status: draft')
        print(f'Review with: python scripts/translate_sa.py --print --uid ' +
              ' '.join(target_uids[:min(3, succeeded)]))


if __name__ == '__main__':
    main()
