"""
Announcements from interslavic.app in the Telegram bot, and /tandem.

What is announced: news of the site, new language partners, voice rooms that open, new events, new articles of
Kolozor and of the Interslavic Wikipedia. Nothing is sent to a chat that did not ask:

  * a person switches the kinds on in a private chat with the bot — /obvestky; the bot offers it once
  * in a group or a channel an admin switches them on with the same command (in a group with topics the
    announcements go to the topic the command was written in)

The bot keeps nothing itself. The chats' switches and what there is to tell live on the site
(api/_lib/botnews.ts in interslavic-hub: POST /community/botnews with the bots' secret). Every minute the bot
asks for what is new, sends it to the chats that want its kind — with its picture when there is one — and says
how far it got, so nothing is told twice and what happened while the bot was down is still told (unless it is
stale by then: a voice room is worth 20 minutes).

/tandem shows who is looking for a language partner on the site.

The Menu button (left of the message field in a private chat) opens the site's menu inside Telegram: the
dictionary, Tandem, the Slavformer, the whole site. The bot sets it when it starts — if the site offers it.

Everything here is platform-neutral: _telegrambot.py shows the screens and sends the messages.
Needs SLOVNIK_BOT_SECRET in .env (the same as on Vercel), like the Slavformer.
"""
import asyncio
import os
from urllib.parse import urlsplit

import aiohttp

import site_api
import tg_format as fmt

BOT_SECRET = os.getenv("SLOVNIK_BOT_SECRET", "")
# how often the site is asked for news (seconds); ANNOUNCE=0 turns the announcements off
POLL_SECONDS = max(15.0, float(os.getenv("ANNOUNCE_EVERY", "60")))
ENABLED = os.getenv("ANNOUNCE", "1") != "0"
COMMANDS = ["obvestky", "обвесткы", "обвєсткы", "notify", "notifications"]
TANDEM_COMMANDS = ["tandem", "тандем"]
SITE_URL = "https://interslavic.app"

KINDS = ["news", "tandem", "rooms", "events", "kolozor", "wiki"]
KIND_NAMES = {
    "news": "Novosti sajta",
    "tandem": "Novi jezyčni partneri",
    "rooms": "Otvorjene govorne komnaty",
    "events": "Nove sobytja v kalendaru",
    "kolozor": "Nove članky v Kolozoru",
    "wiki": "Nove članky v Vikipediji",
}
# "§" stands for the site's name (a text is put into the reader's script, the name is not)
TITLE = "🔔 Obvěstky od §"
WHERE = {
    "private": "Izberite, o čem vam bot bude pisati:",
    "group": "Izberite, o čem bot bude pisati v tutoj grupě:",
    "channel": "Izberite, o čem bot bude pisati v tutom kanalu:",
}
TOPIC_NOTE = "Obvěstky budut prihoditi v tutu temu."
ALL_ON = "Vključiti vse"
ALL_OFF = "Izključiti vse"
OFFER = ("🔔 Hčete li dostavati tut novosti od §? Novosti sajta, novi jezyčni partneri, "
         "govorne komnaty, sobytja, nove članky Kolozora i Vikipedije — izberite, čto vam jest interesno.")
OFFER_YES = "🔔 Izbrati obvěstky"
OFFER_NO = "Ne, hvala"
OFFER_DECLINED = "Dobro. Jestli izměnite mněnje: /obvestky"
ADMINS_ONLY = "Jedino administrator može izměniti obvěstky."
NOT_REACHED = "Tutčas ne mogu dojdti do §. Poprobujte pozdněje."
OPEN = "Otvoriti"
TANDEM_TITLE = "🤝 **Iščut jezyčnogo partnera**"
TANDEM_HELPS = "pomagaje s"
TANDEM_WANTS = "uči se"
TANDEM_NONE = "Tutčas nikto ne išče jezyčnogo partnera."
TANDEM_MORE = "Vse objavjenja i svoje možete napisati tut"
TANDEM_SHOWN = ("pokazano", "iz")

_session = None


async def _get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),
                                         headers={"User-Agent": site_api.USER_AGENT})
    return _session


async def close():
    if _session is not None and not _session.closed:
        await _session.close()


async def ask(action: str, **fields):
    """(status, data) from the site; (0, {}) when it cannot be reached."""
    body = {"platform": "telegram", "action": action, **fields}
    try:
        session = await _get_session()
        async with session.post(f"{site_api.API_BASE}/community/botnews", json=body,
                                headers={"x-bot-key": BOT_SECRET}) as response:
            data = await response.json(content_type=None)
            return response.status, data if isinstance(data, dict) else {}
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        print(f"botnews {action}: {type(e).__name__} {e}")
        return 0, {}


# ── pictures ─────────────────────────────────────────────────

PICTURE_MAX = 8 * 1024 * 1024
PICTURE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


def ours(url: str) -> bool:
    """A picture on the site's own API (news, voice rooms): Telegram downloads those by their address."""
    return urlsplit(url).netloc == urlsplit(site_api.API_BASE).netloc


async def picture(url: str):
    """A picture from another site (an article of Kolozor, of the Wikipedia), downloaded here: (bytes, a file
    name) — or None when it is not a picture Telegram takes, is too big or does not come (why is printed).
    Telegram can fetch a picture by its address itself, but some sites refuse its downloader: kolozor.com
    answered it with a page instead of the picture, and the announcement went out without one. A file handed
    over cannot be refused."""
    host = urlsplit(url).netloc
    try:
        session = await _get_session()
        async with session.get(url, headers={"Accept": "image/jpeg,image/png,image/webp,image/*;q=0.8"}) as response:
            kind = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if response.status != 200 or kind not in PICTURE_TYPES:
                print(f"picture from {host}: not a picture ({response.status} {kind or 'no type'})")
                return None
            data = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                data += chunk
                if len(data) > PICTURE_MAX:
                    print(f"picture from {host}: too big")
                    return None
            return (bytes(data), f"picture.{PICTURE_TYPES[kind]}") if data else None
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        print(f"picture from {host}: {type(e).__name__} {e}")
        return None


def buttons(item: dict) -> list:
    """An announcement's buttons, one under the other: [(text, address)]. The site names them when one "Open"
    is not enough (an article of Kolozor: on interslavic.app, on kolozor.com); else one button opens `url`."""
    named = [(str(button["text"]), str(button["url"])) for button in item.get("buttons") or []
             if isinstance(button, dict) and button.get("text") and str(button.get("url") or "").startswith("https://")]
    return named or [(OPEN, item["url"])]


def say(text: str, script: str = "latn") -> str:
    """One of the texts above in the reader's script, with the site's name in its place."""
    return fmt.tr(text, script).replace("§", "interslavic.app")


# ── the switches ───────────────────────────────────────────────

def chat_kind(chat_type: str) -> str:
    """private · group (also a supergroup) · channel"""
    return chat_type if chat_type in ("private", "channel") else "group"


def chat_fields(chat_id, chat_type: str, title: str = "", thread=None) -> dict:
    fields = {"id": str(chat_id), "type": chat_type, "title": title or ""}
    if thread:
        fields["thread"] = int(thread)
    return fields


def button_data(action: str, arg: str = "", script: str = "latn") -> str:
    return ":".join(["an", action, arg, "c" if script == "cyrl" else "l"])


def parse_button(data: str):
    """("an:t:news:l") → ("t", "news", "latn"); None when it is not one of these buttons."""
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[0] != "an":
        return None
    return parts[1], parts[2], "cyrl" if parts[3] == "c" else "latn"


def settings_screen(prefs: dict, chat_type: str, script: str = "latn", in_topic: bool = False):
    """(HTML text, rows of (label, callback data)) — the chat's switches."""
    lines = [f"<b>{say(TITLE, script)}</b>", say(WHERE[chat_kind(chat_type)], script)]
    if in_topic:
        lines.append(fmt.tr(TOPIC_NOTE, script))
    rows = [[(f"{'✅' if prefs.get(kind) else '⬜'} {fmt.tr(KIND_NAMES[kind], script)}", button_data("t", kind, script))]
            for kind in KINDS]
    everything = all(prefs.get(kind) for kind in KINDS)
    rows.append([(fmt.tr(ALL_OFF if everything else ALL_ON, script),
                  button_data("all", "0" if everything else "1", script))])
    return "\n".join(lines), rows


def offer_screen(script: str = "latn"):
    return say(OFFER, script), [[(fmt.tr(OFFER_YES, script), button_data("open", "", script)),
                                    (fmt.tr(OFFER_NO, script), button_data("no", "", script))]]


async def chat_prefs(chat: dict, offer: bool = False):
    """The chat's switches, or None when the site cannot be reached. With `offer`: also whether the bot may
    ask this private chat, now and never again, if it wants the announcements."""
    status, data = await ask("chat", chat=chat, offer=offer)
    if status != 200:
        return None, False
    return data.get("prefs") or {}, bool(data.get("offer"))


async def press(chat: dict, action: str, arg: str):
    """A switch was pressed: the chat's switches after it, or None when the site cannot be reached."""
    if action == "t" and arg in KINDS:
        prefs, _ = await chat_prefs(chat)
        if prefs is None:
            return None
        change = {arg: not prefs.get(arg)}
    elif action == "all":
        change = {kind: arg == "1" for kind in KINDS}
    else:
        change = {}
    status, data = await ask("set", chat=chat, prefs=change)
    return (data.get("prefs") or {}) if status == 200 else None


_asked = set()  # private chats the site was asked about since the bot started (so it is asked once each)


async def may_offer(chat_id, chat_type: str, title: str = "") -> bool:
    """True once in a private chat's life: the moment to ask whether the person wants the announcements."""
    if not ENABLED or not BOT_SECRET or chat_type != "private" or chat_id in _asked:
        return False
    if len(_asked) > 200_000:
        _asked.clear()
    _asked.add(chat_id)
    _, offer = await chat_prefs(chat_fields(chat_id, chat_type, title), offer=True)
    return offer


# ── telling ────────────────────────────────────────────────────

async def tick(send) -> int:
    """Asks the site what is new and tells the chats that want it. `send(chat, item)` sends one announcement
    to one chat ({"id", "kinds", "thread"}; {"id", "kind", "text", "url", "image", "buttons"}) and answers "ok", "gone"
    (the bot was blocked or removed: the chat is forgotten) or "failed". Returns how many were sent."""
    status, data = await ask("feed")
    if status != 200:
        return 0
    chats = [chat for chat in data.get("chats") or [] if chat.get("id")]
    sent = 0
    for item in data.get("items") or []:
        for chat in list(chats):
            if item.get("kind") not in (chat.get("kinds") or []):
                continue
            result = await send(chat, item)
            if result == "ok":
                sent += 1
            elif result == "gone":
                chats.remove(chat)
                await ask("gone", chat={"id": chat["id"]})
            # (Telegram lets a bot write to some 30 chats a second)
            await asyncio.sleep(0.05)
        # told (or not wanted by anybody): never again, also after a restart
        await ask("ack", id=item.get("id"))
    return sent


async def run(send):
    """For as long as the bot lives: every minute, what is new."""
    if not ENABLED:
        return
    if not BOT_SECRET:
        print("SLOVNIK_BOT_SECRET is not set: no announcements from interslavic.app")
        return
    while True:
        try:
            await tick(send)
        except Exception as e:  # the next minute tries again
            print(f"announcements: {type(e).__name__}: {e}")
        await asyncio.sleep(POLL_SECONDS)


# ── the Menu button ────────────────────────────────────────────

# MENU_BUTTON=0: the bot leaves its Menu button alone
MENU_ENABLED = os.getenv("MENU_BUTTON", "1") != "0"
MENU_WHY_NOT = {
    "NO_TOKEN": "the site does not know this bot yet: set SLOVNIK_BOT_TOKEN (this bot's token) on Vercel and redeploy",
    "OTHER_BOT": "SLOVNIK_BOT_TOKEN on Vercel is another bot's token",
}


async def menu(bot_id) -> dict:
    """What the bot's Menu button should be: {"text", "url"} — the site's menu inside Telegram — or {} when it
    is not to be set (the reason is printed). The page tells who pressed the button from what Telegram signs for
    it, and the site checks that signature with this bot's token; so the site offers the menu only once it has
    the token (Vercel: SLOVNIK_BOT_TOKEN), and only to the bot whose token that is (`bot_id`: getMe's id)."""
    if not MENU_ENABLED:
        return {}
    if not BOT_SECRET:
        print("Menu button: not set — SLOVNIK_BOT_SECRET is missing")
        return {}
    status, data = await ask("menu", bot=bot_id)
    found = data.get("menu") if status == 200 else None
    if isinstance(found, dict) and str(found.get("url") or "").startswith("https://") and found.get("text"):
        return {"text": str(found["text"]), "url": str(found["url"])}
    if status == 200:
        why = MENU_WHY_NOT.get(data.get("reason"), "the site does not offer it")
    elif status == 0:
        why = "the site was not reached"
    else:
        why = f"the site's API does not know it yet (deploy the API; it answered {status})"
    print(f"Menu button: not set — {why}")
    return {}


# ── /tandem ────────────────────────────────────────────────────

def _plain(text: str) -> str:
    """A person's name inside the bot's Markdown: nothing in it may start a style."""
    return "".join(ch for ch in str(text) if ch not in "*_`[]()<>~|\\").strip() or "?"


async def tandem(script: str = "latn") -> str:
    """Who looks for a language partner on interslavic.app, as the bot's Markdown."""
    status, data = await ask("tandem")
    if status != 200:
        return say(NOT_REACHED, script)
    link = f"{fmt.tr(TANDEM_MORE, script)}: {data.get('url') or SITE_URL + '/tandem'}"
    cards = data.get("cards") or []
    if not cards:
        return f"{fmt.tr(TANDEM_NONE, script)}\n{link}"
    total = int(data.get("total") or len(cards))
    lines = [f"{fmt.tr(TANDEM_TITLE, script)} ({total})", ""]
    for card in cards:
        helps = ", ".join(fmt.tr(name, script) for name in card.get("helps") or []) or "—"
        wants = ", ".join(fmt.tr(name, script) for name in card.get("wants") or []) or "—"
        lines.append(f"• **{_plain(card.get('name'))}** — {fmt.tr(TANDEM_HELPS, script)}: {helps}; "
                     f"{fmt.tr(TANDEM_WANTS, script)}: {wants}")
    if total > len(cards):
        shown, of = (fmt.tr(word, script) for word in TANDEM_SHOWN)
        lines.append(f"… {shown} {len(cards)} {of} {total}")
    lines += ["", link]
    return "\n".join(lines)
