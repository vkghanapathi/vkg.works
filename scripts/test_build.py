"""
test_build.py — Build validation for vkg.works
Run before deploying: python scripts/test_build.py
Exits with code 0 on pass, 1 on failure.
"""
from __future__ import annotations
import sys
import subprocess
import json
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).parent.parent
SITE_DIR = ROOT / 'site'
SCRIPTS_DIR = ROOT / 'scripts'


def run_build() -> bool:
    """Run the full build in dry-run mode."""
    print('=== Running build (dry-run) ===')
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / 'build.py'),
         '--site-url', 'https://vkg.works', '--dry-run'],
        capture_output=True, text=True, encoding='utf-8',
    )
    print(result.stdout)
    if result.returncode != 0:
        print('BUILD FAILED:', result.stderr, file=sys.stderr)
        return False
    return True


def check_required_files() -> list[str]:
    """Verify that essential output files exist."""
    required = [
        SITE_DIR / 'index.html',
        SITE_DIR / 'rss.xml',
        SITE_DIR / 'assets' / 'css' / 'style.css',
        SITE_DIR / 'live' / 'index.html',
        SITE_DIR / 'contact' / 'index.html',
    ]
    missing = [str(f) for f in required if not f.exists()]
    return missing


def check_index_html() -> list[str]:
    """Validate index.html has basic structure."""
    errors = []
    index = SITE_DIR / 'index.html'
    if not index.exists():
        return ['index.html missing']
    content = index.read_text(encoding='utf-8')
    if '<nav>' not in content:
        errors.append('index.html: missing <nav>')
    if 'vkg.works' not in content:
        errors.append('index.html: site title not found')
    if '/assets/css/style.css' not in content:
        errors.append('index.html: stylesheet not linked')
    if '/rss.xml' not in content:
        errors.append('index.html: RSS link missing')
    if 'VijayaDV' not in content:
        errors.append('index.html: VijayaDV font not referenced')
    return errors


def check_rss() -> list[str]:
    """Validate RSS feed is well-formed XML."""
    errors = []
    rss_path = SITE_DIR / 'rss.xml'
    if not rss_path.exists():
        return ['rss.xml missing']
    try:
        tree = ET.parse(str(rss_path))
        root = tree.getroot()
        if root.tag != 'rss':
            errors.append(f'rss.xml: root tag is {root.tag!r}, expected "rss"')
        channel = root.find('channel')
        if channel is None:
            errors.append('rss.xml: missing <channel> element')
    except ET.ParseError as e:
        errors.append(f'rss.xml: XML parse error — {e}')
    return errors


def check_section_pages() -> list[str]:
    """Verify each section has an index page."""
    sections = ['articles', 'poems', 'songs', 'books', 'audio',
                'video', 'projects', 'coverage']
    missing = []
    for s in sections:
        page = SITE_DIR / s / 'index.html'
        if not page.exists():
            missing.append(f'{s}/index.html missing')
    return missing


def check_unicode_preserved() -> list[str]:
    """Verify that known Unicode/PUA content is not mangled in index.html."""
    errors = []
    index = SITE_DIR / 'index.html'
    if not index.exists():
        return errors
    content = index.read_text(encoding='utf-8')
    # Check for UTF-8 meta charset declaration
    if 'charset="UTF-8"' not in content and "charset='UTF-8'" not in content:
        errors.append('index.html: UTF-8 charset meta tag missing')
    # Check that no replacement characters (U+FFFD) crept in
    if '\ufffd' in content:
        errors.append('index.html: Unicode replacement character U+FFFD found — encoding issue')
    return errors


def check_no_bare_errors() -> list[str]:
    """Check for obvious template rendering errors in all HTML files."""
    errors = []
    for html_file in SITE_DIR.rglob('*.html'):
        content = html_file.read_text(encoding='utf-8')
        # Jinja2 unclosed variable leakage
        if '{{' in content or '}}' in content:
            errors.append(f'{html_file.relative_to(SITE_DIR)}: unrendered Jinja2 variable')
        if '{%' in content or '%}' in content:
            errors.append(f'{html_file.relative_to(SITE_DIR)}: unrendered Jinja2 tag')
    return errors


def main() -> int:
    all_errors: list[str] = []
    all_warnings: list[str] = []

    # Step 1: Build
    if not run_build():
        print('\n[FAIL] Build step failed. Aborting tests.')
        return 1

    print('\n=== Running validation checks ===')

    # Step 2: Required files
    missing = check_required_files()
    if missing:
        all_errors.extend([f'Missing required file: {f}' for f in missing])

    # Step 3: index.html structure
    all_errors.extend(check_index_html())

    # Step 4: RSS feed validity
    all_errors.extend(check_rss())

    # Step 5: Section pages
    all_errors.extend(check_section_pages())

    # Step 6: Unicode preservation
    all_errors.extend(check_unicode_preserved())

    # Step 7: No template leakage
    all_errors.extend(check_no_bare_errors())

    # Results
    print()
    if all_errors:
        print(f'[FAIL] {len(all_errors)} error(s):')
        for e in all_errors:
            print(f'  ERROR: {e}')
        return 1
    else:
        total_pages = sum(1 for _ in SITE_DIR.rglob('*.html'))
        print(f'[PASS] All checks passed. {total_pages} HTML pages generated.')
        return 0


if __name__ == '__main__':
    sys.exit(main())
