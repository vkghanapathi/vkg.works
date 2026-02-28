"""
assign_uids.py — Stamp uid, orcid, and doi placeholder into every .md sidecar.

For each item in registry.json, finds the companion .md sidecar and adds:
    uid   : VKG-A-042          (section prefix + zero-padded registry integer)
    orcid : 0009-0007-3852-0158
    doi   :                    (empty placeholder — filled after Zenodo upload)

Fields are only added if not already present; existing values are never
overwritten. The field order is preserved; new fields are inserted after
the `author` field if present, otherwise appended.

Standards observed:
    - Internal UID : VKG-{PREFIX}-{NNN}  (3 digits, zero-padded)
    - Author ORCID : ISO 16684 / ORCID (https://orcid.org/0009-0007-3852-0158)
    - DOI          : left blank until Zenodo upload assigns one
    - Language     : ISO 639-1 codes added separately via enrich pipeline
    - Subject/Topic: LCSH-aligned, added separately via enrich pipeline

Usage:
    python scripts/assign_uids.py              # live run, all sections
    python scripts/assign_uids.py --dry-run    # preview only, no writes
    python scripts/assign_uids.py --section articles
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import frontmatter
import yaml

ROOT = Path(__file__).parent.parent
CONTENT_DIR = ROOT / 'content'
REGISTRY_FILE = ROOT / 'state' / 'registry.json'

AUTHOR_ORCID = '0009-0007-3852-0158'

SECTION_PREFIX: dict[str, str] = {
    'articles': 'A',
    'poems':    'P',
    'songs':    'S',
    'books':    'B',
    'audio':    'AU',
    'video':    'V',
    'projects': 'PR',
    'coverage': 'C',
}


def make_uid(prefix: str, num: int) -> str:
    return f'VKG-{prefix}-{num:03d}'


def stamp_sidecar(md_path: Path, uid: str, dry_run: bool) -> str:
    """
    Add uid / orcid / doi to sidecar if not already present.
    Returns a status string: 'stamped', 'skipped' (already had uid), 'error'.
    """
    try:
        post = frontmatter.load(str(md_path))
    except Exception as e:
        return f'error: {e}'

    meta = dict(post.metadata)
    changed = False

    if 'uid' not in meta:
        meta['uid'] = uid
        changed = True
    if 'orcid' not in meta:
        meta['orcid'] = AUTHOR_ORCID
        changed = True
    if 'doi' not in meta:
        meta['doi'] = ''          # placeholder — filled after Zenodo upload
        changed = True

    if not changed:
        return 'skipped'

    if dry_run:
        return 'would stamp'

    yaml_block = yaml.dump(
        meta,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip()
    content_body = post.content or ''
    md_path.write_text(f'---\n{yaml_block}\n---\n{content_body}', encoding='utf-8')
    return 'stamped'


def build_slug_map(section_dir: Path) -> dict[str, Path]:
    """
    Build a map from slug -> Path for all .md files in a section directory.
    Handles both bare slugs (slug.md) and date-prefixed files (YYYY-MM-DD-slug.md).
    """
    slug_map: dict[str, Path] = {}
    import re
    date_prefix = re.compile(r'^\d{4}-\d{2}-\d{2}-')
    for md in section_dir.glob('*.md'):
        stem = md.stem
        bare = date_prefix.sub('', stem)   # strip leading date if present
        slug_map[bare] = md
        slug_map[stem] = md                # also index by full stem
    return slug_map


def process_section(section: str, registry: dict, dry_run: bool) -> tuple[int, int, int]:
    """Returns (stamped, skipped, missing)."""
    prefix = SECTION_PREFIX.get(section, section.upper()[:2])
    items: dict = registry.get(section, {})
    section_dir = CONTENT_DIR / section

    stamped = skipped = missing = 0

    slug_map = build_slug_map(section_dir) if section_dir.exists() else {}

    for slug, num in sorted(items.items(), key=lambda x: x[1]):
        uid = make_uid(prefix, num)
        md_path = slug_map.get(slug)

        if md_path is None:
            print(f'  MISSING  {uid}  {slug}.md')
            missing += 1
            continue

        status = stamp_sidecar(md_path, uid, dry_run)
        if status in ('stamped', 'would stamp'):
            stamped += 1
            print(f'  {"DRY" if dry_run else "OK"}  {uid}  {slug}.md')
        else:
            skipped += 1

    return stamped, skipped, missing


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Stamp UIDs into vkg.works sidecar .md files.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview changes without writing')
    parser.add_argument('--section', metavar='SECTION',
                        help='Process one section only (e.g. articles)')
    args = parser.parse_args()

    with open(REGISTRY_FILE, encoding='utf-8') as f:
        registry = json.load(f)

    sections = [args.section] if args.section else list(SECTION_PREFIX.keys())

    total_stamped = total_skipped = total_missing = 0

    for section in sections:
        if section not in registry or not registry[section]:
            continue
        print(f'\n[{section}]')
        s, sk, m = process_section(section, registry, args.dry_run)
        total_stamped += s
        total_skipped += sk
        total_missing += m

    print(f'\n{"DRY RUN — " if args.dry_run else ""}Done.')
    print(f'  Stamped : {total_stamped}')
    print(f'  Skipped : {total_skipped}  (uid already present)')
    print(f'  Missing : {total_missing}  (.md not found)')


if __name__ == '__main__':
    main()
