"""
rss.py — RSS 2.0 feed generator for vkg.works
Uses feedgen for correct XML escaping and encoding.
VijayaDV PUA Unicode is preserved (feedgen is Unicode-native).
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from feedgen.feed import FeedGenerator


FEED_TITLE = "vkg.works — Dr. Vamśīkṛṣṇa Ghanapāṭhī"
FEED_DESCRIPTION = "Scholarly articles, poems, songs, books, and Vedic recitation"
FEED_AUTHOR = "Dr. Vamśīkṛṣṇa Ghanapāṭhī"
FEED_SECTIONS = ('articles', 'poems', 'songs', 'books', 'audio', 'video', 'projects', 'coverage')


def generate(sections: dict, site_url: str, output_path: Path) -> None:
    """
    Generate site/rss.xml from all content sections.
    sections: {section_name: [ArticleData, ...]}
    """
    fg = FeedGenerator()
    fg.id(site_url)
    fg.title(FEED_TITLE)
    fg.link(href=site_url, rel='alternate')
    fg.link(href=f'{site_url}/rss.xml', rel='self')
    fg.language('en')
    fg.description(FEED_DESCRIPTION)
    fg.author({'name': FEED_AUTHOR})

    # Collect all items with a date, sort newest-first
    all_items = []
    for section_name in FEED_SECTIONS:
        for item in sections.get(section_name, []):
            if item.date:
                all_items.append((section_name, item))

    all_items.sort(key=lambda x: x[1].date or '', reverse=True)

    for section_name, item in all_items[:50]:  # RSS cap at 50 items
        url = f'{site_url}/{section_name}/{item.slug}/'
        fe = fg.add_entry()
        fe.id(url)
        fe.title(f'[{section_name.upper()}] {item.title}')
        fe.link(href=url)
        fe.summary(item.excerpt or item.title)
        fe.author({'name': item.author or FEED_AUTHOR})
        try:
            pub_dt = datetime.fromisoformat(item.date).replace(tzinfo=timezone.utc)
        except Exception:
            pub_dt = datetime.now(tz=timezone.utc)
        fe.published(pub_dt)
        fe.updated(pub_dt)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fg.rss_file(str(output_path), pretty=True)
