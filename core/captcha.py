from __future__ import annotations

import hashlib
import hmac
import html
import random
import secrets
import time

from django.conf import settings
from django.http import HttpResponse

CAPTCHA_SESSION_KEY = "_batikcraft_captcha"
CAPTCHA_TTL_SECONDS = 10 * 60
_CAPTCHA_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CAPTCHA_LENGTH = 5


def issue_captcha(request, *, force: bool = False) -> str:
    """Create or reuse one short-lived CAPTCHA nonce in the current session."""

    record = request.session.get(CAPTCHA_SESSION_KEY)
    now = int(time.time())
    if not force and isinstance(record, dict):
        nonce = str(record.get("nonce") or "")
        issued_at = int(record.get("issued_at") or 0)
        if nonce and now - issued_at <= CAPTCHA_TTL_SECONDS:
            return nonce

    nonce = secrets.token_urlsafe(24)
    request.session[CAPTCHA_SESSION_KEY] = {
        "nonce": nonce,
        "issued_at": now,
    }
    request.session.modified = True
    return nonce


def captcha_answer_for_nonce(nonce: str) -> str:
    """Derive the visible code without storing the answer in the session."""

    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        str(nonce).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return "".join(
        _CAPTCHA_ALPHABET[value % len(_CAPTCHA_ALPHABET)]
        for value in digest[:_CAPTCHA_LENGTH]
    )


def verify_captcha(request, value: object) -> bool:
    """Consume and verify one CAPTCHA answer using constant-time comparison."""

    record = request.session.pop(CAPTCHA_SESSION_KEY, None)
    request.session.modified = True
    if not isinstance(record, dict):
        return False

    nonce = str(record.get("nonce") or "")
    issued_at = int(record.get("issued_at") or 0)
    if not nonce or int(time.time()) - issued_at > CAPTCHA_TTL_SECONDS:
        return False

    expected = captcha_answer_for_nonce(nonce)
    submitted = str(value or "").strip().upper()
    return hmac.compare_digest(expected, submitted)


def captcha_image(request) -> HttpResponse:
    """Render the current CAPTCHA as a non-cacheable SVG image."""

    nonce = issue_captcha(request, force=request.GET.get("refresh") == "1")
    answer = captcha_answer_for_nonce(nonce)
    response = HttpResponse(_svg_for(answer, nonce), content_type="image/svg+xml")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _svg_for(answer: str, nonce: str) -> str:
    seed = int.from_bytes(hashlib.sha256(nonce.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    width, height = 250, 76

    lines = []
    for _index in range(11):
        x1 = rng.randint(0, width)
        y1 = rng.randint(0, height)
        x2 = rng.randint(0, width)
        y2 = rng.randint(0, height)
        opacity = rng.uniform(0.10, 0.28)
        lines.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="#705448" stroke-width="{rng.randint(1, 3)}" opacity="{opacity:.2f}"/>'
        )

    dots = []
    for _index in range(35):
        dots.append(
            f'<circle cx="{rng.randint(4, width - 4)}" cy="{rng.randint(4, height - 4)}" '
            f'r="{rng.randint(1, 2)}" fill="#96705c" opacity="{rng.uniform(0.12, 0.35):.2f}"/>'
        )

    glyphs = []
    start_x = 34
    for index, character in enumerate(answer):
        x = start_x + index * 43 + rng.randint(-3, 3)
        y = 51 + rng.randint(-4, 4)
        rotation = rng.randint(-16, 16)
        glyphs.append(
            f'<text x="{x}" y="{y}" transform="rotate({rotation} {x} {y})" '
            'font-family="DejaVu Sans, Arial, sans-serif" font-size="38" '
            'font-weight="700" letter-spacing="1" fill="#3e2b24">'
            f'{html.escape(character)}</text>'
        )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="Kode CAPTCHA" viewBox="0 0 250 76" width="250" height="76">'
        '<rect width="250" height="76" rx="12" fill="#f4eadc"/>'
        '<rect x="1" y="1" width="248" height="74" rx="11" fill="none" '
        'stroke="#cfb7a5" stroke-width="2"/>'
        + "".join(lines)
        + "".join(dots)
        + "".join(glyphs)
        + "</svg>"
    )


__all__ = [
    "CAPTCHA_SESSION_KEY",
    "CAPTCHA_TTL_SECONDS",
    "captcha_answer_for_nonce",
    "captcha_image",
    "issue_captcha",
    "verify_captcha",
]
