"""
ingest.py — Bulk content ingest for vkg.works

Extracts ZIPs from content/inbox/ into content/{section}/ directories.
ZIP structure (preferred):
    archive.zip/
    ├── articles/2026-03-01-essay.md
    ├── poems/2026-03-05-poem.md
    └── audio/2026-03-10-recording.mp3

Flat ZIPs (all files at root) are also supported — section is guessed from extension.

Usage:
    python scripts/ingest.py                   # processes content/inbox/*.zip
    python scripts/ingest.py /path/to/inbox/   # custom inbox directory
"""
from __future__ import annotations
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTENT_DIR = ROOT / 'content'
INBOX_DIR = CONTENT_DIR / 'inbox'

KNOWN_SECTIONS = {
    'articles', 'poems', 'songs', 'books', 'audio',
    'video', 'projects', 'coverage',
}

# Extension → default section for flat (no-folder) ZIPs
EXT_TO_SECTION: dict[str, str] = {
    '.mp3': 'audio', '.m4a': 'audio', '.ogg': 'audio', '.wav': 'audio',
    '.md':   'articles', '.html': 'articles', '.htm': 'articles',
    '.docx': 'articles', '.pptx': 'articles', '.pdf': 'articles',
    '.txt':  'articles',
}


def ingest_zip(zip_path: Path) -> tuple[int, int]:
    """
    Extract zip_path into content/{section}/ directories.
    Returns (ingested_count, skipped_count).
    """
    ingested = 0
    skipped = 0

    with zipfile.ZipFile(zip_path, 'r') as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue

            parts = Path(member.filename).parts
            filename = parts[-1]

            # Skip hidden / macOS metadata / system files
            if filename.startswith('.') or filename.startswith('__'):
                continue
            if any(p.startswith('__MACOSX') for p in parts):
                continue

            # Determine target section and relative path within it
            if len(parts) >= 2 and parts[0] in KNOWN_SECTIONS:
                # Folder-structured ZIP: first component is the section name
                section = parts[0]
                rel_parts = parts[1:]   # may include sub-folders (e.g. coverage/concert/)
            else:
                # Flat ZIP: guess from extension
                suffix = Path(filename).suffix.lower()
                section = EXT_TO_SECTION.get(suffix, 'articles')
                rel_parts = (filename,)

            target_path = CONTENT_DIR / section / Path(*rel_parts)

            if target_path.exists():
                skipped += 1
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            ingested += 1

    return ingested, skipped


def main(inbox_dir: Path = INBOX_DIR) -> None:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    zips = sorted(inbox_dir.glob('*.zip'))

    if not zips:
        print('No ZIP files found in', inbox_dir)
        return

    total_ingested = 0
    total_skipped = 0

    for zip_path in zips:
        print(f'Processing {zip_path.name}...')
        try:
            ingested, skipped = ingest_zip(zip_path)
            total_ingested += ingested
            total_skipped += skipped
            print(f'  {ingested} file(s) ingested, {skipped} skipped (already exist)')
            zip_path.unlink()
            print(f'  Removed {zip_path.name}')
        except Exception as e:
            print(f'  ERROR processing {zip_path.name}: {e}', file=sys.stderr)

    print(f'\nIngest complete: {total_ingested} file(s) added, {total_skipped} skipped.')


if __name__ == '__main__':
    inbox = Path(sys.argv[1]) if len(sys.argv) > 1 else INBOX_DIR
    main(inbox)
