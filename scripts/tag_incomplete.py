"""
tag_incomplete.py — Scan content .md sidecars for garbled (legacy-encoded) titles
and mark them as status: incomplete so they appear in Queue with a red badge.

Legacy Telugu/Kannada font files (Nudi, iLeap, Shree-Dev, etc.) used single-byte
encodings mapped to Latin-1 Supplement characters (U+0080–U+00FF).  When imported
as UTF-8, these appear as strings like "NSLRiùzqsµôðj¶" — ASCII letters mixed
with characters such as µ ¶ ô ù ð ñ ò ó ÿ etc.

Detection rule:
  Title contains at least one character in U+0080–U+00FF  AND
  Title also contains at least one plain ASCII letter (A-Z / a-z)
  → almost certainly legacy-encoded, not meaningful Unicode.

Usage:
    python scripts/tag_incomplete.py [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import frontmatter
import yaml

ROOT = Path(__file__).parent.parent
CONTENT_DIRS = [
    ROOT / 'content' / 'articles',
    ROOT / 'content' / 'poems',
    ROOT / 'content' / 'songs',
    ROOT / 'content' / 'books',
    ROOT / 'content' / 'projects',
    ROOT / 'content' / 'coverage',
]

# Match any character in the Latin-1 Supplement block (legacy font artefacts)
_LEGACY_CHAR = re.compile(r'[\u0080-\u00FF]')
_ASCII_LETTER = re.compile(r'[A-Za-z]')
# Match VijayaDV/iLeap PUA characters (E000–F8FF) — unreadable by AI/search
_PUA_CHAR = re.compile(r'[\uE000-\uF8FF]')


def is_garbled(title: str) -> bool:
    """Return True if the title looks like legacy single-byte font encoding."""
    # Latin-1 Supplement artefacts (Nudi/iLeap imported as UTF-8)
    if bool(_LEGACY_CHAR.search(title)) and bool(_ASCII_LETTER.search(title)):
        return True
    # PUA-only titles (VijayaDV encoding — no ASCII letters, just PUA glyphs)
    if _PUA_CHAR.search(title) and not _ASCII_LETTER.search(title):
        return True
    return False


def tag_file(md_path: Path, dry_run: bool) -> bool:
    """
    If the .md sidecar's title is garbled, set status: incomplete.
    Returns True if the file was (or would be) changed.
    """
    try:
        post = frontmatter.load(str(md_path))
    except Exception as e:
        print(f'  SKIP (parse error): {md_path.name} — {e}')
        return False

    title = str(post.metadata.get('title', ''))
    current_status = str(post.metadata.get('status', ''))

    if not is_garbled(title):
        return False
    if current_status == 'incomplete':
        return False  # already tagged

    if dry_run:
        print(f'  WOULD TAG: {md_path.relative_to(ROOT)}  title={ascii(title)}')
        return True

    # Update status to incomplete
    post.metadata['status'] = 'incomplete'
    meta_dict = dict(post.metadata)
    yaml_block = yaml.dump(meta_dict, allow_unicode=True,
                           default_flow_style=False, sort_keys=False).rstrip()
    md_path.write_text(f'---\n{yaml_block}\n---\n{post.content}', encoding='utf-8')
    print(f'  TAGGED: {md_path.relative_to(ROOT)}  title={ascii(title)}')
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description='Tag garbled-title sidecars as incomplete')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would change without writing files')
    args = parser.parse_args()

    tagged = skipped = 0
    for content_dir in CONTENT_DIRS:
        if not content_dir.exists():
            continue
        for md_path in sorted(content_dir.glob('*.md')):
            result = tag_file(md_path, args.dry_run)
            if result:
                tagged += 1
            else:
                skipped += 1

    action = 'Would tag' if args.dry_run else 'Tagged'
    print(f'\n{action} {tagged} file(s) as incomplete. {skipped} unchanged.')


if __name__ == '__main__':
    main()
