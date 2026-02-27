"""
social.py — Social media posting for vkg.works
Platforms: Facebook Page, LinkedIn, WhatsApp Business Cloud API
Run after build.py detects new items.
Reads credentials from environment variables (set as GitHub Secrets).
Note: Twitter/X excluded — write access requires paid API tier ($100/mo).
"""
from __future__ import annotations
import os
import sys
from typing import Optional


def _post_facebook(title: str, excerpt: str, url: str, section: str) -> bool:
    page_id = os.environ.get('FB_PAGE_ID', '')
    token = os.environ.get('FB_PAGE_ACCESS_TOKEN', '')
    if not (page_id and token):
        print('  Facebook: skipped (FB_PAGE_ID or FB_PAGE_ACCESS_TOKEN not set)')
        return False
    import requests
    message = f'[{section.upper()}] {title}\n\n{excerpt}\n\n{url}'
    resp = requests.post(
        f'https://graph.facebook.com/v20.0/{page_id}/feed',
        data={'message': message[:2000], 'access_token': token},
        timeout=15,
    )
    if resp.ok:
        print(f'  Facebook: posted ({resp.status_code})')
        return True
    print(f'  Facebook: FAILED ({resp.status_code}) — {resp.text[:200]}', file=sys.stderr)
    return False


def _post_linkedin(title: str, excerpt: str, url: str) -> bool:
    token = os.environ.get('LINKEDIN_ACCESS_TOKEN', '')
    person_urn = os.environ.get('LINKEDIN_PERSON_URN', '')
    if not (token and person_urn):
        print('  LinkedIn: skipped (LINKEDIN_ACCESS_TOKEN or LINKEDIN_PERSON_URN not set)')
        return False
    import requests
    body = {
        'author': person_urn,
        'lifecycleState': 'PUBLISHED',
        'specificContent': {
            'com.linkedin.ugc.ShareContent': {
                'shareCommentary': {'text': f'{title}\n\n{excerpt}'},
                'shareMediaCategory': 'ARTICLE',
                'media': [{
                    'status': 'READY',
                    'originalUrl': url,
                    'title': {'text': title[:200]},
                    'description': {'text': excerpt[:700]},
                }],
            }
        },
        'visibility': {
            'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC'
        },
    }
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'X-Restli-Protocol-Version': '2.0.0',
    }
    resp = requests.post(
        'https://api.linkedin.com/v2/ugcPosts',
        json=body, headers=headers, timeout=15,
    )
    if resp.ok:
        print(f'  LinkedIn: posted ({resp.status_code})')
        return True
    print(f'  LinkedIn: FAILED ({resp.status_code}) — {resp.text[:200]}', file=sys.stderr)
    return False


def _post_whatsapp(title: str, url: str) -> bool:
    phone_number_id = os.environ.get('WHATSAPP_PHONE_NUMBER_ID', '')
    token = os.environ.get('WHATSAPP_ACCESS_TOKEN', '')
    recipient_list = os.environ.get('WHATSAPP_RECIPIENT_LIST', '')
    if not (phone_number_id and token and recipient_list):
        print('  WhatsApp: skipped (credentials or recipient list not set)')
        return False
    import requests
    recipients = [r.strip() for r in recipient_list.split(',') if r.strip()]
    success_count = 0
    for recipient in recipients:
        payload = {
            'messaging_product': 'whatsapp',
            'to': recipient,
            'type': 'template',
            'template': {
                'name': 'new_article_announcement',
                'language': {'code': 'en'},
                'components': [{
                    'type': 'body',
                    'parameters': [
                        {'type': 'text', 'text': title[:512]},
                        {'type': 'text', 'text': url},
                    ],
                }],
            },
        }
        resp = requests.post(
            f'https://graph.facebook.com/v20.0/{phone_number_id}/messages',
            json=payload,
            headers={'Authorization': f'Bearer {token}'},
            timeout=15,
        )
        if resp.ok:
            success_count += 1
        else:
            print(f'  WhatsApp: FAILED for {recipient} — {resp.text[:200]}', file=sys.stderr)
    if success_count:
        print(f'  WhatsApp: sent to {success_count}/{len(recipients)} recipients')
        return True
    return False


def post_all(new_items: list, site_url: str) -> list[str]:
    """
    Post all new items to all configured social media platforms.
    Returns list of platform names that had at least one success.
    """
    posted_platforms: set[str] = set()

    for section_name, item in new_items:
        url = f'{site_url}/{section_name}/{item.slug}/'
        title = item.title
        excerpt = (item.excerpt or '')[:200]
        print(f'\nPosting: [{section_name}] {title}')

        if _post_facebook(title, excerpt, url, section_name):
            posted_platforms.add('facebook')
        if _post_linkedin(title, excerpt, url):
            posted_platforms.add('linkedin')
        if _post_whatsapp(title, url):
            posted_platforms.add('whatsapp')

    return sorted(posted_platforms)


if __name__ == '__main__':
    import argparse, json
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--site-url', default='https://vkg.works')
    args = parser.parse_args()

    # This entrypoint is called directly by publish.yml social step
    # build.py already called post_all and saved state; this is a no-op wrapper
    # for the workflow to confirm completion
    print('social.py: social posting handled by build.py --social flag')
