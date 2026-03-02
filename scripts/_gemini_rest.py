"""
_gemini_rest.py — Thin Vertex AI Gemini REST helper using gcloud ADC token.

Uses `gcloud auth print-access-token` so no API key file is needed.
The access token is refreshed automatically when it expires (~1 hour).

Usage (internal):
    from _gemini_rest import GeminiClient
    client = GeminiClient(project='pranetaa')
    text = client.generate(system_prompt, user_prompt)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from typing import Optional

# Vertex AI Gemini REST endpoint template
_ENDPOINT = (
    'https://us-central1-aiplatform.googleapis.com/v1'
    '/projects/{project}/locations/us-central1'
    '/publishers/google/models/{model}:generateContent'
)

_DEFAULT_MODEL = 'gemini-2.0-flash-001'
_TOKEN_TTL = 3300  # refresh token after 55 minutes (tokens last 60 min)


class GeminiClient:
    """
    Vertex AI Gemini REST client authenticated via gcloud access token.
    No API key file needed — uses whichever account is active in gcloud.
    """

    def __init__(self, project: str = 'pranetaa', model: str = _DEFAULT_MODEL):
        self.project = project
        self.model = model
        self._token: Optional[str] = None
        self._token_fetched_at: float = 0.0

    def _get_token(self) -> str:
        """Return a valid gcloud access token, refreshing if needed."""
        now = time.time()
        if self._token is None or (now - self._token_fetched_at) > _TOKEN_TTL:
            # On Windows, gcloud is gcloud.cmd; use shell=True for portability
            result = subprocess.check_output(
                'gcloud auth print-access-token',
                text=True, stderr=subprocess.DEVNULL, shell=True,
            )
            self._token = result.strip()
            self._token_fetched_at = now
        return self._token

    def generate(self, system_prompt: str, user_prompt: str,
                 max_tokens: int = 2048, temperature: float = 0.2) -> str:
        """
        Call Gemini and return the raw text response.
        Raises RuntimeError on API failure.
        """
        url = _ENDPOINT.format(project=self.project, model=self.model)
        token = self._get_token()

        payload = {
            'system_instruction': {
                'parts': [{'text': system_prompt}],
            },
            'contents': [
                {'role': 'user', 'parts': [{'text': user_prompt}]},
            ],
            'generationConfig': {
                'maxOutputTokens': max_tokens,
                'temperature': temperature,
            },
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            method='POST',
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='replace')
            raise RuntimeError(f'HTTP {e.code}: {error_body}') from e

        # Parse Gemini response structure
        try:
            return body['candidates'][0]['content']['parts'][0]['text']
        except (KeyError, IndexError) as e:
            raise RuntimeError(f'Unexpected response structure: {body}') from e

    def generate_json(self, system_prompt: str, user_prompt: str,
                      max_tokens: int = 2048) -> dict | None:
        """
        Call Gemini and parse the response as JSON.
        Strips markdown code fences if present. Returns None on parse failure.
        """
        try:
            raw = self.generate(system_prompt, user_prompt, max_tokens).strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw.strip())
            return json.loads(raw)
        except RuntimeError as e:
            print(f'    WARN: API error — {e}', file=sys.stderr)
            return None
        except json.JSONDecodeError as e:
            print(f'    WARN: JSON parse error — {e}', file=sys.stderr)
            return None
