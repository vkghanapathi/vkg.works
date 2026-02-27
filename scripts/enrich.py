"""
enrich.py — AI enrichment of vkg.works content using Claude.

For each draft .md sidecar that lacks an `abstract` field, this script:
  1. Reads the title + body text from the companion DOCX (or .md content)
  2. Calls Claude to generate English scholarly metadata
  3. Writes three new fields to the .md sidecar:
       abstract  — 2–3 sentence scholarly summary
       preamble  — 1 paragraph situating the work in its tradition
       keywords  — 5–8 subject terms for search indexing

Original body text, VijayaDV characters, and Sanskrit/Telugu/Kannada text
are NEVER modified. Only the frontmatter is extended.

Rules (from RAG memory):
  - No condensation of original text
  - Full reproduction policy — AI adds context, not substitutes
  - Abstract, preamble, keywords in English
  - Scholarly tone matching VKG's academic register

Usage:
    python scripts/enrich.py --section articles --limit 10
    python scripts/enrich.py --all --limit 50
    python scripts/enrich.py --section poems --dry-run

Requires:
    ANTHROPIC_API_KEY environment variable (set via GitHub Secrets or .env)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import frontmatter
import yaml

ROOT = Path(__file__).parent.parent
CONTENT_DIR = ROOT / 'content'

SECTIONS = ['articles', 'poems', 'songs', 'books', 'projects', 'coverage']

# How much body text to send to Claude (characters). Enough for context,
# not so much we burn tokens on repetitive content.
BODY_EXCERPT_CHARS = 3000

# Delay between API calls (seconds) to respect rate limits
API_DELAY = 0.5

SYSTEM_PROMPT = """\
You are a scholarly research assistant specialising in Vedic literature,
Indian classical texts, Sanskrit, Telugu, and Kannada compositions.
Your role is to make the works of Dr. Vamshi Krishna Ghanapāṭhī
discoverable to English-language readers without altering his original text.

You produce concise, accurate English metadata for each work. You never
translate or paraphrase the body text — you only describe and contextualise it.
"""

USER_PROMPT_TEMPLATE = """\
Work title   : {title}
Section      : {section}
{category_line}
Body excerpt (original language — do not translate):
---
{body_excerpt}
---

Generate English scholarly metadata for this work. Respond with ONLY a
valid JSON object — no explanation, no markdown fences, just raw JSON:

{{
  "abstract": "2–3 sentences describing what this work is and its significance.",
  "preamble": "One paragraph (3–5 sentences) situating this work in its scriptural or ritual tradition, for a reader unfamiliar with the tradition.",
  "keywords": ["term1", "term2", "term3", "term4", "term5"]
}}

Rules:
- abstract: what the work IS and its scholarly importance — do not just restate the title
- preamble: historical/scriptural/ritual context — name the tradition, scripture, deity, or practice involved
- keywords: specific subject terms — scripture names, deity names, ritual names, philosophical concepts (5–8 terms)
- All output in English
- Scholarly register matching an academic journal
"""


def _extract_body_from_docx(docx_path: Path) -> str:
    """Extract plain text from a DOCX file (first BODY_EXCERPT_CHARS chars)."""
    try:
        from docx import Document
        doc = Document(str(docx_path))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        # Skip the first paragraph if it looks like a title (short, no period)
        if paragraphs and len(paragraphs[0]) < 120 and not paragraphs[0].endswith('.'):
            paragraphs = paragraphs[1:]
        text = '\n'.join(paragraphs)
        return text[:BODY_EXCERPT_CHARS]
    except Exception:
        return ''


def _extract_body_from_md(md_path: Path) -> str:
    """Extract plain body text from a standalone .md file."""
    try:
        post = frontmatter.load(str(md_path))
        return post.content[:BODY_EXCERPT_CHARS]
    except Exception:
        return ''


def _get_body_text(md_path: Path) -> str:
    """Get body text: prefer DOCX companion, fall back to .md content."""
    docx = md_path.with_suffix('.docx')
    if docx.exists():
        text = _extract_body_from_docx(docx)
        if text:
            return text
    return _extract_body_from_md(md_path)


def _call_claude(title: str, section: str, category: str | None,
                 body: str, client, model: str) -> dict | None:
    """Call Claude and return parsed JSON dict, or None on failure."""
    category_line = f'Category     : {category}' if category else ''
    prompt = USER_PROMPT_TEMPLATE.format(
        title=title,
        section=section,
        category_line=category_line,
        body_excerpt=body or '(body text not available)',
    )
    try:
        message = client.messages.create(
            model=model,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': prompt}],
        )
        raw = message.content[0].text.strip()
        # Strip markdown fences if model adds them despite instructions
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f'    WARN: JSON parse error — {e}', file=sys.stderr)
        return None
    except Exception as e:
        print(f'    WARN: API error — {e}', file=sys.stderr)
        return None


def _write_enrichment(md_path: Path, enrichment: dict) -> None:
    """Write abstract/preamble/keywords into the .md sidecar frontmatter."""
    post = frontmatter.load(str(md_path))
    meta = dict(post.metadata)

    abstract = str(enrichment.get('abstract', '')).strip()
    preamble = str(enrichment.get('preamble', '')).strip()
    keywords = enrichment.get('keywords', [])
    if isinstance(keywords, list):
        keywords = [str(k).strip() for k in keywords if k]

    if abstract:
        meta['abstract'] = abstract
    if preamble:
        meta['preamble'] = preamble
    if keywords:
        meta['keywords'] = keywords

    yaml_block = yaml.dump(meta, allow_unicode=True,
                           default_flow_style=False, sort_keys=False).rstrip()
    content_body = post.content or ''
    md_path.write_text(f'---\n{yaml_block}\n---\n{content_body}', encoding='utf-8')


def enrich_section(section: str, limit: int, dry_run: bool,
                   client, model: str) -> tuple[int, int, int]:
    """
    Enrich draft items in one section.
    Returns (enriched, skipped, errors).
    """
    section_dir = CONTENT_DIR / section
    if not section_dir.exists():
        return 0, 0, 0

    enriched = skipped = errors = 0

    for md_path in sorted(section_dir.glob('*.md')):
        if enriched >= limit:
            break
        try:
            post = frontmatter.load(str(md_path))
        except Exception:
            skipped += 1
            continue

        meta = post.metadata
        status = str(meta.get('status', '')).lower()
        title = str(meta.get('title', md_path.stem))

        # Only process draft items; skip incomplete (garbled), published, already enriched
        if status in ('', 'published'):
            skipped += 1
            continue
        if status == 'incomplete':
            skipped += 1
            continue
        if meta.get('abstract'):
            skipped += 1
            continue

        category = meta.get('category') or None
        body = _get_body_text(md_path)

        if dry_run:
            print(f'  WOULD ENRICH [{section}]: {md_path.name}  — "{title[:60]}"')
            enriched += 1
            continue

        print(f'  Enriching [{section}] {md_path.name}  — "{title[:60]}"')
        result = _call_claude(title, section, category, body, client, model)

        if result:
            _write_enrichment(md_path, result)
            print(f'    OK: abstract={len(result.get("abstract",""))}chars  '
                  f'keywords={result.get("keywords",[])}')
            enriched += 1
        else:
            errors += 1

        time.sleep(API_DELAY)

    return enriched, skipped, errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description='AI-enrich vkg.works content with abstract/preamble/keywords')
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--section', choices=SECTIONS,
                       help='Enrich one section')
    scope.add_argument('--all', action='store_true',
                       help='Enrich all sections')
    parser.add_argument('--limit', type=int, default=20,
                        help='Max items to enrich per section (default 20)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be enriched without calling API')
    parser.add_argument('--model', default='claude-haiku-4-5-20251001',
                        choices=['claude-haiku-4-5-20251001', 'claude-sonnet-4-6'],
                        help='Claude model to use (default: haiku — fast and cost-effective)')
    args = parser.parse_args()

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key and not args.dry_run:
        print('ERROR: ANTHROPIC_API_KEY environment variable not set.', file=sys.stderr)
        print('Set it via: set ANTHROPIC_API_KEY=sk-ant-...  (Windows)', file=sys.stderr)
        sys.exit(1)

    client = None
    if not args.dry_run:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

    sections_to_process = SECTIONS if args.all else [args.section]
    total_enriched = total_skipped = total_errors = 0

    for section in sections_to_process:
        e, s, err = enrich_section(section, args.limit, args.dry_run, client, args.model)
        total_enriched += e
        total_skipped += s
        total_errors += err
        if e > 0 or err > 0:
            print(f'  {section}: {e} enriched, {s} skipped, {err} errors')

    action = 'Would enrich' if args.dry_run else 'Enriched'
    print(f'\n{action} {total_enriched} item(s). '
          f'Skipped {total_skipped}. Errors: {total_errors}.')
    if total_enriched > 0 and not args.dry_run:
        print('Run: git add content/ && git commit -m "chore: AI enrich content" && git push')


if __name__ == '__main__':
    main()
