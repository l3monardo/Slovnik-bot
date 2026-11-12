"""
What the bot asks interslavic.app for (its public API, the one the website itself uses):

  * the declension / conjugation tables of a word   GET /community/forms
  * how well people understand a word                GET /community/intelligibility
  * what a word means (slovosbor.online)             GET /community/explain

Every function returns None when the site cannot be reached or answers with
an error: the bot then simply leaves that part out.
"""
import asyncio
import os
import time

import aiohttp

API_BASE = os.getenv("SITE_API", "https://interslavic-api.vercel.app/api").rstrip("/")
USER_AGENT = "Slovnik-bot/2 (Telegram; https://github.com/l3monardo/Slovnik-bot)"
TIMEOUT_SECONDS = float(os.getenv("SITE_API_TIMEOUT", "6"))
CACHE_MAX = 3000

_cache = {}  # address → (expires, data)
_session = None


async def _get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
    return _session


async def close():
    if _session is not None and not _session.closed:
        await _session.close()


async def _get(path: str, params: dict, ttl: int):
    key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    try:
        session = await _get_session()
        async with session.get(f"{API_BASE}/{path}", params=params) as response:
            if response.status != 200:
                print(f"interslavic.app: {path} answered {response.status}")
                return None
            data = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        print(f"interslavic.app: {path} failed: {type(e).__name__} {e}")
        return None
    if not isinstance(data, dict):
        return None
    if len(_cache) >= CACHE_MAX:
        for old in sorted(_cache, key=lambda k: _cache[k][0])[:CACHE_MAX // 4]:
            _cache.pop(old, None)
    _cache[key] = (now + ttl, data)
    return data


async def word_forms(isv: str, addition: str, details: str, script: str = "latn", orth: str = "standard"):
    """The tables of forms of a dictionary entry (its "isv", "addition" and "partOfSpeech" cells)."""
    params = {"w": isv, "d": details, "script": script}
    if addition:
        params["add"] = addition
    if orth == "etymological":
        params["orth"] = orth
    return await _get("community/forms", params, 24 * 3600)


async def intelligibility(word_id: str, isv: str):
    """The votes on how well the word is understood (interslavic.app and slovosbor.online)."""
    if not str(word_id).isdigit():
        return None
    return await _get("community/intelligibility", {"id": word_id, "w": isv}, 600)


async def explanation(word_id: str, isv: str):
    """The word's definitions in 12 languages and its synonyms."""
    if not str(word_id).isdigit():
        return None
    return await _get("community/explain", {"id": word_id, "w": isv}, 3600)
