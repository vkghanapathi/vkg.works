"""
map_analyze.py — Mūla Artha Pratipatti (MAP) analysis for Sanskrit poems and songs.

MAP is a 9-segment scholarly verse analysis system used in VKG's works:
  1. mula          — original verse (Devanāgarī)
  2. padavibhaga   — word-boundary separation (e.g., पोप्लूयन्तां | प्लवन्तां | ...)
  3. anvaya        — prose syntactic reordering (grammatical word order)
  4. pratipadartha — word-by-word meaning (word = gloss pairs)
  5. rupa_nishpatti— grammatical form analysis (vibhakti, vachana, liṅga, dhātu, etc.)
  6. sandhi        — sandhi identification and rules applied
  7. samasa        — compound analysis (samāsa vigraha, type)
  8. bhavartha_en  — English meaning / paraphrase
  9. commentary    — deeper tātparya / significance

For each verse in the poem/song, a MAP block is generated and stored in the
sidecar .md frontmatter under the key `map:` as a list of verse dicts.

A top-level `map_status: draft` is set so VKG can review before publishing.

Uses Vertex AI Gemini via gcloud access token — no separate API key needed.
Ensure `gcloud auth login` has been run for the active account.

Usage:
    python scripts/map_analyze.py --uid VKG-P-001
    python scripts/map_analyze.py --uid VKG-P-001 VKG-P-006 VKG-P-018
    python scripts/map_analyze.py --batch map1     # runs the pre-set MAP1 batch
    python scripts/map_analyze.py --dry-run --uid VKG-P-001
    python scripts/map_analyze.py --print --uid VKG-P-001   # print stored MAP
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

API_DELAY = 1.0  # seconds between API calls (Sanskrit analysis is heavier)

# Pre-defined MAP1 batch — 5 manageable Sanskrit poems for VKG review
MAP1_BATCH = [
    'VKG-P-001',   # प्लवसंवत्सर शुभाशिषः  — 1 verse (starter)
    'VKG-P-002',   # अकाल मोक्षस्तूप पूजा मन्त्रः — ritual mantra
    'VKG-P-006',   # भीमशङ्कर पञ्चकम् — 5 verses, Shaiva stotra
    'VKG-P-018',   # षोडश दीपः — Devi worship, 2 verses
    'VKG-P-025',   # Ganesha 32 names — manageable enumeration
]

SYSTEM_PROMPT = """You are a highly trained Sanskrit scholar and Vedic pandit assisting
Dr. Vamśīkṛṣṇa Ghanapāṭhī, a Ghanapāṭhī of Yajurveda and Sanskrit PhD.
You provide rigorous, traditional Sanskrit grammatical analysis (vyākaraṇa) in the
Pāṇinian tradition, with awareness of Vedic, Epic, and Classical Sanskrit registers.
All Sanskrit must use proper Devanāgarī with correct anusvāra, visarga, and accent marks.
Transliterations must follow IAST conventions.
Be precise, concise, and scholarly. Do not add any text outside the JSON object requested."""

MAP_PROMPT_TEMPLATE = """Perform Mūla Artha Pratipatti (MAP) analysis for the following Sanskrit verse.

Title of the work: {title}
Author: Dr. Vamśīkṛṣṇa Ghanapāṭhī

VERSE TEXT:
{verse_text}

Provide a JSON object with exactly these 9 keys (use empty string "" if a segment is not applicable):

{{
  "mula": "the verse in clean Devanāgarī, normalized",
  "padavibhaga": "each word/pada separated by | e.g. पोप्लूयन्तां | प्लवन्तां | ...",
  "anvaya": "prose word order (kartā first, kriyā last), Devanāgarī",
  "pratipadartha": "word = IAST gloss format, semicolon-separated, e.g. पोप्लूयन्तां = poplūyantāṃ (let them float); ...",
  "rupa_nishpatti": "for key words: form analysis, e.g. पोप्लूयन्तां — √plu, yaṅ-luk (intensive), Ātm., lot, prathama-bahu; ...",
  "sandhi": "list key sandhi junctions with rule, e.g. रोग+दुःख → रोगदुःख (savarṇa-dīrgha); ...",
  "samasa": "list compounds with vigraha and type, e.g. रोगदुःखाम्बुराशिः — roga+duḥkha+amburaśiḥ, karmadhāraya; ...",
  "bhavartha_en": "flowing English meaning/paraphrase of the verse (2-4 sentences)",
  "commentary": "tātparya — deeper spiritual/literary significance (3-5 sentences)"
}}

Return only the JSON object, no other text."""


def _has_devanagari_letters(text: str) -> bool:
    """
    Return True only if text contains actual Devanāgarī letters (vowels/consonants),
    NOT just daṇḍa punctuation (।॥ = U+0964-U+0965) or combining marks.
    This prevents IAST transliterations with daṇḍa from being mistaken for Sanskrit.
    Core Devanāgarī letters: U+0904-U+0963, U+0966-U+097F (digits and extensions).
    """
    return any(('\u0904' <= ch <= '\u0963') or ('\u0966' <= ch <= '\u097f') for ch in text)


def extract_verses_from_docx(docx_path: Path) -> list[str]:
    """
    Extract individual Sanskrit verses (ślokas) from a DOCX file.
    Verses are identified by Devanāgarī text blocks bounded by daṇḍa marks.
    Returns a list of verse strings (each containing one or two pādas).

    Rules:
    - Only paragraphs with actual Devanāgarī letters (not just daṇḍa) are collected.
    - A double daṇḍa (।। or ॥) ends a verse.
    - A minimum of 15 Devanāgarī characters per verse ensures we skip titles/headers.
    - When a new numbered section (like "2", "3") resets, we also start a new verse.
    """
    doc = docx.Document(str(docx_path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    verses: list[str] = []
    current_verse_lines: list[str] = []
    MIN_DEVA_CHARS = 15  # skip one-word titles / section headers

    for para in paragraphs:
        has_deva = _has_devanagari_letters(para)

        if has_deva:
            current_verse_lines.append(para)
            # Double daṇḍa signals verse end
            if '।।' in para or '॥' in para:
                verse_text = '\n'.join(current_verse_lines).strip()
                # Only keep if substantial Devanāgarī content
                deva_count = sum(1 for ch in verse_text
                                 if '\u0904' <= ch <= '\u0963' or '\u0966' <= ch <= '\u097f')
                if deva_count >= MIN_DEVA_CHARS:
                    verses.append(verse_text)
                current_verse_lines = []
        else:
            # Non-Devanāgarī line (IAST, Telugu, Kannada, English, commentary prose)
            # Flush any accumulated verse lines
            if current_verse_lines:
                verse_text = '\n'.join(current_verse_lines).strip()
                deva_count = sum(1 for ch in verse_text
                                 if '\u0904' <= ch <= '\u0963' or '\u0966' <= ch <= '\u097f')
                if deva_count >= MIN_DEVA_CHARS:
                    verses.append(verse_text)
                current_verse_lines = []

    # Flush remaining
    if current_verse_lines:
        verse_text = '\n'.join(current_verse_lines).strip()
        deva_count = sum(1 for ch in verse_text
                         if '\u0904' <= ch <= '\u0963' or '\u0966' <= ch <= '\u097f')
        if deva_count >= MIN_DEVA_CHARS:
            verses.append(verse_text)

    return verses


def call_map_api(title: str, verse_text: str, client: GeminiClient) -> dict | None:
    """Call Gemini for MAP analysis of a single verse. Returns dict or None."""
    prompt = MAP_PROMPT_TEMPLATE.format(title=title, verse_text=verse_text)
    return client.generate_json(SYSTEM_PROMPT, prompt, max_tokens=1400)


def build_uid_index() -> dict[str, dict]:
    """
    Build a map: uid → {section, slug, md_path, docx_path}
    from registry.json.
    """
    SECTION_PREFIX = {
        'articles': 'A', 'poems': 'P', 'songs': 'S', 'books': 'B',
        'audio': 'AU', 'video': 'V', 'projects': 'PR', 'coverage': 'C',
    }

    with open(REGISTRY_FILE, encoding='utf-8') as f:
        registry = json.load(f)

    date_prefix = re.compile(r'^\d{4}-\d{2}-\d{2}-')
    uid_index: dict[str, dict] = {}

    for section, prefix in SECTION_PREFIX.items():
        items: dict = registry.get(section, {})
        section_dir = CONTENT_DIR / section
        if not section_dir.exists():
            continue

        # Build slug → file map (handles date-prefixed filenames)
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

            # Find companion DOCX/PDF
            docx_path = md_path.with_suffix('.docx')
            if not docx_path.exists():
                docx_path = None

            language = ''
            try:
                post = frontmatter.load(str(md_path))
                language = str(post.metadata.get('language', ''))
            except Exception:
                pass

            uid_index[uid] = {
                'section': section,
                'slug': slug,
                'md_path': md_path,
                'docx_path': docx_path,
                'language': language,
            }

    return uid_index


def print_map(uid: str, info: dict) -> None:
    """Pretty-print the stored MAP for a poem."""
    md_path = info['md_path']
    post = frontmatter.load(str(md_path))
    meta = post.metadata
    map_data = meta.get('map', [])
    title = meta.get('title', uid)

    print(f'\n{"═"*70}')
    print(f'MAP — {uid} — {title}')
    print(f'Status: {meta.get("map_status", "not set")}')
    print(f'{"═"*70}')

    if not map_data:
        print('  (no MAP data stored)')
        return

    for i, verse in enumerate(map_data, 1):
        print(f'\n── Verse {i} ──')
        for key in ['mula', 'padavibhaga', 'anvaya', 'pratipadartha',
                    'rupa_nishpatti', 'sandhi', 'samasa', 'bhavartha_en', 'commentary']:
            val = verse.get(key, '')
            if val:
                label = {
                    'mula': 'Mūla', 'padavibhaga': 'Padavibhāga',
                    'anvaya': 'Anvaya', 'pratipadartha': 'Pratipadārtha',
                    'rupa_nishpatti': 'Rūpa Niṣpatti', 'sandhi': 'Sandhi',
                    'samasa': 'Samāsa', 'bhavartha_en': 'Bhāvārtha (EN)',
                    'commentary': 'Commentary',
                }.get(key, key)
                print(f'\n  {label}:')
                # Wrap long lines
                for line in str(val).split('\n'):
                    print(f'    {line}')


def analyze_poem(uid: str, info: dict, client: GeminiClient,
                 dry_run: bool, max_verses: int = 10) -> bool:
    """
    Run MAP analysis for one poem/song. Returns True if successful.
    Stores results in the sidecar .md frontmatter.
    """
    md_path = info['md_path']
    docx_path = info['docx_path']
    section = info['section']

    post = frontmatter.load(str(md_path))
    meta = dict(post.metadata)
    title = meta.get('title', uid)

    print(f'\n[{uid}] {title}')

    if docx_path is None or not docx_path.exists():
        print(f'  SKIP — no DOCX found')
        return False

    # Extract verses
    verses = extract_verses_from_docx(docx_path)
    if not verses:
        print(f'  SKIP — no Devanāgarī verses extracted from DOCX')
        return False

    # Cap at max_verses to control token usage
    if len(verses) > max_verses:
        print(f'  NOTE — {len(verses)} verses found; processing first {max_verses}')
        verses = verses[:max_verses]
    else:
        print(f'  Found {len(verses)} verse(s)')

    if dry_run:
        for i, v in enumerate(verses, 1):
            print(f'  [DRY] Verse {i}: {v[:80].replace(chr(10), " ")}…')
        return True

    # Analyze each verse
    map_entries: list[dict] = []
    for i, verse_text in enumerate(verses, 1):
        print(f'  Analyzing verse {i}/{len(verses)}…', end=' ', flush=True)
        result = call_map_api(title, verse_text, client)
        if result is None:
            print('FAILED')
            map_entries.append({'mula': verse_text, 'error': 'API call failed'})
        else:
            result['verse_num'] = i
            map_entries.append(result)
            print('OK')
        time.sleep(API_DELAY)

    # Write to sidecar
    meta['map'] = map_entries
    meta['map_status'] = 'draft'  # VKG reviews before publishing

    yaml_block = yaml.dump(meta, allow_unicode=True,
                           default_flow_style=False, sort_keys=False).rstrip()
    content_body = post.content or ''
    md_path.write_text(f'---\n{yaml_block}\n---\n{content_body}', encoding='utf-8')
    print(f'  Saved MAP ({len(map_entries)} verse(s)) → {md_path.name}')
    return True


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        description='Generate MAP (Mūla Artha Pratipatti) analysis for VKG poems/songs.'
    )
    parser.add_argument('--uid', nargs='+', metavar='UID',
                        help='One or more UIDs to process, e.g. VKG-P-001 VKG-P-006')
    parser.add_argument('--batch', choices=['map1'],
                        help='Run a pre-defined batch (map1 = 5 starter poems)')
    parser.add_argument('--section', metavar='SECTION',
                        help='Process all Sanskrit poems/songs in a section')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be processed without calling the API')
    parser.add_argument('--print', action='store_true',
                        help='Print stored MAP data for the given UIDs (no API calls)')
    parser.add_argument('--limit', type=int, default=999,
                        help='Max items to process in a batch (default: no limit)')
    parser.add_argument('--force', action='store_true',
                        help='Re-analyze even if map already present')
    parser.add_argument('--max-verses', type=int, default=10,
                        help='Max verses per poem to analyze (default 10)')
    parser.add_argument('--model', default='gemini-2.0-flash-001',
                        help='Gemini model to use (default: gemini-2.0-flash-001)')
    parser.add_argument('--project', default='pranetaa',
                        help='GCP project for Vertex AI (default: pranetaa)')
    args = parser.parse_args()

    # Determine which UIDs to process
    target_uids: list[str] = []
    if args.batch == 'map1':
        target_uids = MAP1_BATCH
    elif args.uid:
        target_uids = [u.upper() for u in args.uid]
    elif not args.section:
        parser.error('Specify --uid, --batch, or --section')

    # Build UID index
    print('Building UID index…')
    uid_index = build_uid_index()

    # Section-based selection — filter by section AND Sanskrit language
    if args.section:
        target_uids = sorted([
            uid for uid, info in uid_index.items()
            if info['section'] == args.section and 'sa' in info.get('language', '')
        ])
        print(f'Found {len(target_uids)} Sanskrit items in section "{args.section}"')

    # Skip already-analyzed unless --force
    if not getattr(args, 'force', False) and not args.print:
        before = len(target_uids)
        def _has_map(uid: str) -> bool:
            info = uid_index.get(uid)
            if info is None:
                return False
            import frontmatter as _fm
            try:
                meta = _fm.load(str(info['md_path'])).metadata
                return bool(meta.get('map'))
            except Exception:
                return False
        target_uids = [u for u in target_uids if not _has_map(u)]
        skipped_existing = before - len(target_uids)
        if skipped_existing:
            print(f'  Skipping {skipped_existing} already-analyzed items (use --force to redo)')

    # Apply limit
    if len(target_uids) > args.limit:
        target_uids = target_uids[:args.limit]
        print(f'Limiting to {args.limit} items')

    if not target_uids:
        print('No UIDs to process.')
        return

    # Print mode — no API calls
    if args.print:
        for uid in target_uids:
            info = uid_index.get(uid)
            if info is None:
                print(f'  UNKNOWN UID: {uid}')
                continue
            print_map(uid, info)
        return

    # Create Gemini client (uses gcloud token — no separate API key needed)
    client = GeminiClient(project=args.project, model=args.model) if not args.dry_run else None

    succeeded = failed = skipped = 0
    for uid in target_uids:
        info = uid_index.get(uid)
        if info is None:
            print(f'\n  UNKNOWN UID: {uid}')
            skipped += 1
            continue
        ok = analyze_poem(uid, info, client,
                          args.dry_run, args.max_verses)
        if not args.dry_run:
            time.sleep(1.5)
        if ok:
            succeeded += 1
        else:
            failed += 1

    print(f'\n{"DRY RUN — " if args.dry_run else ""}Done.')
    print(f'  Succeeded : {succeeded}')
    print(f'  Failed    : {failed}')
    print(f'  Skipped   : {skipped}')
    if not args.dry_run and succeeded > 0:
        print('\nAll MAP entries saved with map_status: draft')
        print('Review with:  python scripts/map_analyze.py --print --uid ' +
              ' '.join(target_uids[:succeeded]))


if __name__ == '__main__':
    main()
