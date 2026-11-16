"""
The Slavformer, the word game of interslavic.app, in the bots (/igra in Telegram, .igra in Discord).

A player gets the dictionary's words one by one and says how well they understand each. Every answer is the
player's intelligibility vote on interslavic.app (the same as on the word's page there), earns grivnas and turns an
old car into a robot that the grivnas dress up. The game lives on the site: the bot plays it for the player through
the site's API (api/_lib/slavbot.ts in interslavic-hub), so the score, the grivnas and the robot are the same here,
in the other bot and on the site.

The player signs in first. "Vojdti" gives the bot the account the site gives this Telegram / Discord (made now when
there is none: one then signs in on the site with the same Telegram / Discord); "Uže imam račun" opens the site,
where one gives the bot an account made otherwise (Google…).

Everything here is platform-neutral: a screen is lines of styled parts and rows of buttons; _telegrambot.py and
_disnake.py show them (to_html / to_markdown) and route the buttons ("sf:…") back to `press`.

Needs SLOVNIK_BOT_SECRET in .env (the same as on Vercel). The pictures are made with resvg-py; without it the
figure is a link to the site.
"""
import asyncio
import json
import os
import random
import re
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from html import escape

import aiohttp

import isv_tools as isv
import site_api
import tg_format as fmt
import transliteration as transl

try:
    import resvg_py
except ImportError:  # the figure is then a link to the site
    resvg_py = None

BOT_SECRET = os.getenv("SLOVNIK_BOT_SECRET", "")
SITE_URL = "https://interslavic.app"
GAME_URL = f"{SITE_URL}/game"
COMMANDS = ["igra", "игра", "slavformer", "славформер", "game"]
SHOP_COMMANDS = ["magazin", "магазин"]
FIGURE_COMMANDS = ["robot", "робот"]
LOGOUT_COMMANDS = ["vyjdi", "выјди", "logout"]
LEADER_COMMANDS = ["lideri", "лидери", "leaders"]
LEADERS_SHOWN = 10
COMMENT_MAX = 2000
CANDIDATES = 50
SHOP_PAGE = 8
SHOWN_MAX = 400
PICTURES_MAX = 200

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, "slavformer_strings.json"), encoding="utf-8") as _file:
    STRINGS = json.load(_file)
TEXTS = STRINGS["texts"]
ITEM_NAMES = STRINGS["items"]
LANG_NAMES = STRINGS["langs"]

# the answers, as on the site (api/community/[type].ts: VOTES)
VOTES = ["understand", "context", "nonNative", "falseFriend", "notUnderstand"]
VOTE_KEYS = {"understand": "voteUnderstand", "context": "voteContext", "nonNative": "voteNonNative",
             "falseFriend": "voteFalseFriend", "notUnderstand": "voteNotUnderstand"}
VOTE_MARKS = {"understand": "🟢", "context": "🟩", "nonNative": "🔵", "falseFriend": "🟠", "notUnderstand": "🔴"}
# the mother tongues a profile can name (api/_lib/langs.ts: SLAVIC_LANGS)
NATIVE_LANGS = ["ru", "uk", "be", "rue", "pl", "csb", "szl", "hsb", "dsb", "cs", "sk", "sl", "hr", "bs", "sr", "cnr",
                "mk", "bg"]
# the dictionary's columns: the meaning is shown in the mother tongue when it is one of them, else in English
MEANING_LANGS = ["ru", "uk", "be", "pl", "cs", "sk", "sl", "hr", "sr", "mk", "bg"]
STAGE_KEYS = {"car": "gameStageCar", "morph": "gameStageMorph", "robot": "gameStageRobot"}
STAGE_MARKS = {"car": "🚗", "morph": "🦿", "robot": "🤖"}
# the ranks (api/_lib/game.ts: GAME_RANKS): the texts' key of each one's name
RANK_KEYS = {"megaslav": "gameRankMegaslav", "optimusSlav": "gameRankOptimusSlav", "slavatron": "gameRankSlavatron",
             "slavbot": "gameRankSlavbot", "slavblbi": "gameRankSlavblbi", "slavtor": "gameRankSlavtor"}
RANK_MARK = "🔩"
PERIODS = {"all": "gameLeadersAll", "week": "gameLeadersWeek"}
MEDALS = ["🥇", "🥈", "🥉"]
PLATFORM_NAMES = {"telegram": "Telegram", "discord": "Discord"}
WITH_PLATFORM = {"telegram": "s Telegramom", "discord": "s Discordom"}


# ── what a screen is made of ───────────────────────────────────

def B(text):
    return ("b", str(text))


def I(text):
    return ("i", str(text))


def S(text):
    """Hidden until tapped: Telegram's spoiler, Discord's ||…||."""
    return ("s", str(text))


@dataclass
class Screen:
    lines: list = field(default_factory=list)       # a line: a list of parts, a part: text or (style, text)
    buttons: list = field(default_factory=list)     # rows of (label, data); data "url:…" is a link
    photo: bytes = None                             # the figure as a PNG
    alert: str = ""                                 # a short note on the pressed button instead of a message
    edit: bool = True                               # may replace the message the button was under
    private: bool = False                           # only for the player's eyes (a link to the site)
    extra: list = field(default_factory=list)       # more screens to send after this one (the figure)
    prompt: dict = None                             # asks for a text: {"word": id} — a comment on that word


def to_html(screen: Screen) -> str:
    out = []
    for line in screen.lines:
        parts = []
        for part in line:
            if isinstance(part, tuple):
                style, text = part
                tag = {"b": "b", "i": "i", "s": "tg-spoiler"}[style]
                parts.append(f"<{tag}>{escape(text)}</{tag}>")
            else:
                parts.append(escape(str(part)))
        out.append("".join(parts))
    return "\n".join(out)


_MARKDOWN = re.compile(r"([\\*_~|`>#\[\]()-])")


def _md(text: str) -> str:
    return _MARKDOWN.sub(r"\\\1", text)


def to_markdown(screen: Screen) -> str:
    out = []
    for line in screen.lines:
        parts = []
        for part in line:
            if isinstance(part, tuple):
                style, text = part
                mark = {"b": "**", "i": "*", "s": "||"}[style]
                parts.append(f"{mark}{_md(text)}{mark}" if text.strip() else _md(text))
            else:
                parts.append(_md(str(part)))
        out.append("".join(parts))
    return "\n".join(out)


def to_plain(screen: Screen) -> str:
    return "\n".join("".join(part[1] if isinstance(part, tuple) else str(part) for part in line)
                     for line in screen.lines)


# ── the player and the site ────────────────────────────────────

@dataclass
class Player:
    platform: str      # telegram | discord
    id: str
    name: str
    script: str = "latn"


def tr(text: str, player: Player) -> str:
    return fmt.tr(text, player.script)


def text(key: str, player: Player, **params) -> str:
    value = TEXTS[key]
    for name, param in params.items():
        value = value.replace(f"{{__{name}__}}", str(param)).replace(f"__{name}__", str(param))
    # (on the site {…} keeps a part from being transliterated: a number needs no such care here)
    return tr(value.replace("{", "").replace("}", ""), player)


def vote_label(vote: str, player: Player) -> str:
    return text(VOTE_KEYS[vote], player)


_session = None


async def _get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12),
                                         headers={"User-Agent": site_api.USER_AGENT})
    return _session


async def close():
    if _session is not None and not _session.closed:
        await _session.close()


async def ask(player: Player, action: str, **fields):
    """(status, data) from the site; (0, {}) when it cannot be reached."""
    body = {"platform": player.platform, "user": {"id": player.id, "name": player.name}, "action": action, **fields}
    try:
        session = await _get_session()
        async with session.post(f"{site_api.API_BASE}/community/slavbot", json=body,
                                headers={"x-bot-key": BOT_SECRET}) as response:
            data = await response.json(content_type=None)
            return response.status, data if isinstance(data, dict) else {}
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        print(f"slavbot {action}: {type(e).__name__} {e}")
        return 0, {}


# ── the words ──────────────────────────────────────────────────

_shown = OrderedDict()    # player → the words shown lately (not offered again soon)
_skipped = OrderedDict()  # player → the words passed over


def _remembered(store: OrderedDict, player: Player) -> deque:
    key = (player.platform, player.id)
    if key not in store:
        store[key] = deque(maxlen=SHOWN_MAX)
        if len(store) > 5000:
            store.popitem(last=False)
    store.move_to_end(key)
    return store[key]


def _words():
    sheet = isv.sheets.get("words")
    return None if sheet is None or sheet is False else sheet


def _ids() -> list:
    sheet = _words()
    if sheet is None:
        return []
    cache = getattr(_ids, "cache", None)
    if cache is None or cache[0] is not sheet:
        ids = [str(i) for i in sheet["id"].to_list() if re.fullmatch(r"\d{1,9}", str(i or ""))]
        _ids.cache = (sheet, ids)
    return _ids.cache[1]


def candidates(player: Player) -> list:
    ids = _ids()
    if not ids:
        return []
    shown = set(_remembered(_shown, player))
    skipped = set(_remembered(_skipped, player))
    picked = []
    for _ in range(CANDIDATES * 4):
        word = random.choice(ids)
        if word not in shown and word not in skipped and word not in picked:
            picked.append(word)
        if len(picked) >= CANDIDATES:
            break
    return picked


def word_of(word_id: str):
    """(entry as the dictionary writes it, what a vote is stored under, part of speech, row) or None."""
    row = isv.find_by_id(word_id)
    if row is None:
        return None
    entry = isv.cell(row, "isv").replace("!", "").replace("#", "").strip()
    first = entry.split(",")[0].strip()
    if not first:
        return None
    return entry, first, isv.cell(row, "partOfSpeech"), row


def meaning_lang(native) -> str:
    return native if native in MEANING_LANGS else "en"


def in_script(entry: str, player: Player) -> str:
    return transl.transliteration(entry, "isv_to_cyrillic") if player.script == "cyrl" else entry


# ── the screens ────────────────────────────────────────────────

def data(player: Player, *parts) -> str:
    """A button's data: sf:<player>:<l|c>:<what>[:…] — only that player's presses count."""
    return ":".join(["sf", player.id, "c" if player.script == "cyrl" else "l", *[str(p) for p in parts]])


def failed_screen(player: Player, status: int, answer: dict) -> Screen:
    code = answer.get("code")
    if code == "BLOCKED":
        return Screen([[text("blockedForever", player)]])
    if code == "TOO_FAST":
        return Screen(alert=text("gameTooFast", player))
    if code == "NOT_CONFIGURED" or status in (401, 503) and not code:
        print(f"slavbot: the site refused the bot ({status} {answer}) — is SLOVNIK_BOT_SECRET the same as on Vercel?")
    return Screen([[tr("⚠️ interslavic.app teper ne odgovarja. Poprobujte znova za hvilju.", player)]])


def rank_name(rank, player: Player) -> str:
    """The rank's name ('' — none, or one this bot does not know yet)."""
    return text(RANK_KEYS[rank], player) if rank in RANK_KEYS else ""


def head(player: Player, game: dict) -> list:
    """🤖 Slavformer · 💰 150 · ⭐ 12 · 🔩 Slavtor — and what comes next: a stage, then a rank, then a bonus."""
    rank = rank_name(game.get("rank"), player)
    lines = [["🤖 ", B(text("gameTitle", player)), f" · 💰 {game.get('coins', 0)} · ⭐ {game.get('votes', 0)}"
              + (f" · {RANK_MARK} {rank}" if rank else "")]]
    stages = game.get("rules", {}).get("stages") or []
    votes = game.get("votes", 0)
    nxt = next((stage for stage in stages if stage["votes"] > votes), None)
    ranks = sorted(game.get("rules", {}).get("ranks") or [], key=lambda one: one["votes"])
    higher = next((one for one in ranks if one["votes"] > votes and one["id"] in RANK_KEYS), None)
    if nxt:
        lines.append([I(text("gameGoalStage", player, stage=text(STAGE_KEYS[nxt["id"]], player),
                             n=nxt["votes"] - votes))])
    elif higher:
        lines.append([I(text("gameGoalRank", player, rank=rank_name(higher["id"], player),
                             n=higher["votes"] - votes))])
    elif game.get("rules"):
        every = game["rules"]["bonusEvery"]
        lines.append([I(text("gameGoalBonus", player, bonus=game["rules"]["bonus"], n=every - votes % every))])
    return lines


def nav_rows(player: Player, word_id: str = None, previous: tuple = None) -> list:
    """Under a word: skip it, comment on it, change the answer before; then the robot, the shop, the leaders."""
    rows = []
    if word_id:
        rows.append([("⏭ " + text("gameSkip", player), data(player, "s", word_id)),
                     ("💬 " + text("gameComment", player), data(player, "k", word_id))])
    if previous and word_id:
        before, index = previous
        rows.append([("✏️ " + text("gamePrevious", player), data(player, "c", before, index, word_id))])
    rows.append([("🤖 " + tr("Moj robot", player), data(player, "f")),
                 ("🛒 " + text("gameShop", player), data(player, "m", 0)),
                 ("🏆 " + text("gameLeaders", player), data(player, "l", "all"))])
    return rows


def sign_in_screen(player: Player, note: str = "") -> Screen:
    platform = PLATFORM_NAMES[player.platform]
    lines = []
    if note:
        lines += [[note], [""]]
    lines += [
        ["🤖 ", B(text("gameTitle", player))],
        [text("gameIntro", player)],
        [""],
        [tr(f"Da byste igrali, vojdite. Vaše odgovory budut glasami za slova v slovniku na interslavic.app, a igra "
            f"bude vaša igra tamo: s tym samym računom vhodite na sajt črěz {platform}.", player)],
    ]
    return Screen(lines, [
        [("✅ " + tr(f"Vojdti {WITH_PLATFORM[player.platform]}", player), data(player, "in"))],
        [("🔗 " + tr("Uže imam račun na interslavic.app", player), data(player, "ln"))],
    ])


def native_screen(player: Player, note_lines: list = None) -> Screen:
    lines = list(note_lines or [])
    lines.append([text("voteNeedsProfile", player)])
    names = [(tr(LANG_NAMES[lang], player), data(player, "n", lang)) for lang in NATIVE_LANGS]
    return Screen(lines, [names[i:i + 4] for i in range(0, len(names), 4)])


def word_screen(player: Player, game: dict, native, free: list, header: list = None,
                previous: tuple = None) -> Screen:
    """The next word (the first free one that the dictionary still has), under what happened just now.
    `previous`: (word, answer) — the answer before, which a button changes."""
    lines = list(header or [])
    for word_id in free:
        found = word_of(word_id)
        if not found:
            continue
        entry, _, pos, row = found
        _remembered(_shown, player).append(word_id)
        lines += head(player, game)
        lines.append([""])
        lines.append([B(in_script(entry, player))] + (["  ", I(pos)] if pos else []))
        meaning = isv.cell(row, meaning_lang(native)).replace("!", "").replace("#", "").strip() \
            or isv.cell(row, "en").replace("!", "").strip()
        language = LANG_NAMES.get(meaning_lang(native), "")
        lines.append([f"{text('gameMeaning', player)} ({tr(language, player)}): ", S(meaning or "—")])
        lines.append([""])
        lines.append([text("voteQuestion", player)])
        votes = [(f"{VOTE_MARKS[vote]} {vote_label(vote, player)}", data(player, "v", word_id, i))
                 for i, vote in enumerate(VOTES)]
        return Screen(lines, [[votes[0]], [votes[1]], [votes[2]], votes[3:], *nav_rows(player, word_id, previous)])
    lines += head(player, game)
    lines.append([text("gameAllDone", player)])
    return Screen(lines, nav_rows(player))


async def play(player: Player, header: list = None) -> Screen:
    if not _ids():
        return Screen([[tr("Slovnik se ješče nagrųžaje. Poprobujte za minutu.", player)]])
    for _ in range(3):
        status, answer = await ask(player, "next", candidates=candidates(player))
        if status == 401 and answer.get("code") == "SIGN_IN":
            return sign_in_screen(player)
        if status != 200:
            return failed_screen(player, status, answer)
        game, native = answer["game"], answer.get("native")
        if not native:
            return native_screen(player, header)
        if game.get("collected"):
            header = list(header or []) + [["🌿 ", text("gameCollected", player, n=game["collected"])], [""]]
        if answer.get("free"):
            return word_screen(player, game, native, answer["free"], header)
        _remembered(_shown, player).clear()
    return word_screen(player, game, native, [], header)


def _combined(stats: dict):
    counts = dict(stats.get("counts") or {})
    total = stats.get("total") or 0
    external = stats.get("external") or {}
    for vote, n in (external.get("counts") or {}).items():
        counts[vote] = counts.get(vote, 0) + n
    total += external.get("total") or 0
    return counts, total


async def vote(player: Player, word_id: str, index: int) -> Screen:
    found = word_of(word_id)
    if not found or not 0 <= index < len(VOTES):
        return Screen(alert=tr("Togo slova uže nema v slovniku.", player))
    entry, first, _, _ = found
    chosen = VOTES[index]
    status, answer = await ask(player, "vote", id=word_id, word=first, vote=chosen, candidates=candidates(player))
    if status == 401 and answer.get("code") == "SIGN_IN":
        return sign_in_screen(player)
    if status == 409 and answer.get("code") == "NO_PROFILE":
        return native_screen(player)
    if status != 200:
        return failed_screen(player, status, answer)
    header = _answer_lines(player, first, chosen, answer)
    header.append(["─" * 12])
    if answer.get("free"):
        # the next word: the first of the free ones the site named, else a new round of candidates
        screen = word_screen(player, answer["game"], answer.get("native"), answer["free"], header,
                             previous=(word_id, index))
    else:
        screen = await play(player, header)
    if answer.get("became"):
        cheer = text("gameBecameRobot" if answer["became"] == "robot" else "gameBecameMorph", player)
        screen.extra.append(await figure(player, note=f"🎉 {cheer}", game=answer["game"]))
    elif rank_name(answer.get("ranked"), player):
        cheer = text("gameNewRank", player, rank=rank_name(answer["ranked"], player))
        screen.extra.append(await figure(player, note=f"🎉 {RANK_MARK} {cheer}", game=answer["game"]))
    return screen


def _answer_lines(player: Player, first: str, chosen: str, answer: dict, mark: str = None) -> list:
    """✏️ grad: Razuměju · +10 💰 — and how the others answered."""
    lines = [[f"{mark or VOTE_MARKS[chosen]} ", B(in_script(first, player)), f": {vote_label(chosen, player)}"
              + (f" · +{answer['gained']} 💰" if answer.get("gained") else "")
              + (f" ({text('gameBonus', player)}!)" if answer.get("bonus") else "")]]
    counts, total = _combined(answer.get("stats") or {})
    if total > 1:
        top = max(VOTES, key=lambda v: counts.get(v, 0))
        lines.append([I(f"{text('gameOthers', player)}: {round(counts.get(top, 0) / total * 100)}% "
                        f"{vote_label(top, player)} ({total})")])
    else:
        lines.append([I(text("gameFirst", player))])
    return lines


async def change(player: Player, word_id: str, index: int, back: str) -> Screen:
    """The answer before, to change: the word, its meaning, the five answers (the one given marked)."""
    found = word_of(word_id)
    if not found or not 0 <= index < len(VOTES):
        return Screen(alert=tr("Togo slova uže nema v slovniku.", player))
    entry, _, pos, row = found
    status, answer = await ask(player, "me")
    if status != 200:
        return failed_screen(player, status, answer)
    if not answer.get("account"):
        return sign_in_screen(player)
    native = answer.get("native")
    meaning = isv.cell(row, meaning_lang(native)).replace("!", "").replace("#", "").strip() \
        or isv.cell(row, "en").replace("!", "").strip()
    language = LANG_NAMES.get(meaning_lang(native), "")
    lines = [["✏️ ", B(text("gameChangeAnswer", player))],
             [""],
             [B(in_script(entry, player))] + (["  ", I(pos)] if pos else []),
             [f"{text('gameMeaning', player)} ({tr(language, player)}): {meaning or '—'}"],
             [""],
             [f"{VOTE_MARKS[VOTES[index]]} {vote_label(VOTES[index], player)}"]]
    votes = [(("✓ " if i == index else "") + f"{VOTE_MARKS[v]} {vote_label(v, player)}",
              data(player, "v2", word_id, i, back)) for i, v in enumerate(VOTES)]
    return Screen(lines, [[votes[0]], [votes[1]], [votes[2]], votes[3:],
                          [("↩ " + text("cancel", player), data(player, "y", back)),
                           ("💬 " + text("gameComment", player), data(player, "k", word_id))]])


async def changed(player: Player, word_id: str, index: int, back: str) -> Screen:
    """A changed answer; then the word that was waiting."""
    found = word_of(word_id)
    if not found or not 0 <= index < len(VOTES):
        return Screen(alert=tr("Togo slova uže nema v slovniku.", player))
    _, first, _, _ = found
    chosen = VOTES[index]
    status, answer = await ask(player, "vote", id=word_id, word=first, vote=chosen, candidates=[back])
    if status == 401 and answer.get("code") == "SIGN_IN":
        return sign_in_screen(player)
    if status != 200:
        return failed_screen(player, status, answer)
    header = _answer_lines(player, first, chosen, answer, mark="✏️") + [["─" * 12]]
    if answer.get("free"):
        return word_screen(player, answer["game"], answer.get("native"), answer["free"], header,
                           previous=(word_id, index))
    return await play(player, header)


async def back_to(player: Player, word_id: str) -> Screen:
    """The word that was on the screen before "change the answer before"."""
    status, answer = await ask(player, "next", candidates=[word_id])
    if status != 200 or not answer.get("free") or not answer.get("native"):
        return await play(player)
    return word_screen(player, answer["game"], answer["native"], answer["free"])


async def skip(player: Player, word_id: str) -> Screen:
    _remembered(_skipped, player).append(word_id)
    return await play(player)


async def set_native(player: Player, lang: str) -> Screen:
    if lang not in NATIVE_LANGS:
        return Screen(alert="?")
    status, answer = await ask(player, "native", lang=lang)
    if status == 401:
        return sign_in_screen(player)
    if status != 200:
        return failed_screen(player, status, answer)
    return await play(player)


async def login(player: Player) -> Screen:
    status, answer = await ask(player, "login")
    if status != 200:
        return failed_screen(player, status, answer)
    platform = PLATFORM_NAMES[player.platform]
    name = answer["account"]["name"]
    if answer.get("created"):
        note = [["✨ ", tr(f"Na interslavic.app jest napravjeny vaš račun «{name}». Na sajt vhodite črěz {platform} — "
                         f"to jest toj samy račun.", player)], [""]]
    else:
        note = [["✅ ", tr(f"Igrate s vašim računom «{name}» na interslavic.app.", player)], [""]]
    if not answer.get("native"):
        return native_screen(player, note)
    return await play(player, note)


async def link(player: Player) -> Screen:
    status, answer = await ask(player, "link")
    if status != 200:
        return failed_screen(player, status, answer)
    return Screen([
        ["🔗 ", tr("Otvorite tu svęz, vojdite na interslavic.app v svoj račun i potvrdite. Svęz važi "
                  f"{answer.get('minutes', 15)} minut i jest samo za vas — ne dajte jej nikomu.", player)],
        [tr("Potom vratite se sjuda i igrajte.", player)],
    ], [
        [("🌐 " + tr("Otvoriti interslavic.app", player), "url:" + answer["url"])],
        [("▶️ " + text("gamePlay", player), data(player, "p"))],
    ], edit=False, private=True)


async def logout(player: Player) -> Screen:
    await ask(player, "logout")
    return Screen([[tr("Bot uže ne igraje za vaš račun. Račun na interslavic.app i vaša igra tamo ostavajut.",
                       player)]])


# ── the leaders ────────────────────────────────────────────────

async def leaders(player: Player, period: str = "all") -> Screen:
    """Who answered the most words — ever or in the last seven days (/lideri; also on the site, /leaders)."""
    period = period if period in PERIODS else "all"
    status, answer = await ask(player, "leaders", period=period)
    if status != 200:
        return failed_screen(player, status, answer)
    lines = [["🏆 ", B(text("gameLeaders", player)), f" · {text(PERIODS[period], player)}"], [""]]
    shown = answer.get("leaders", [])[:LEADERS_SHOWN]
    if not shown:
        lines.append([text("gameLeadersEmpty", player)])
    for leader in shown:
        place = MEDALS[leader["place"] - 1] if leader["place"] <= 3 else f"{leader['place']}."
        mine = answer.get("me") and leader["id"] == answer["me"].get("id")
        rank = rank_name(leader.get("rank"), player)
        lines.append([f"{place} {STAGE_MARKS.get(leader['stage'], '')} ",
                      B(leader["name"]) if mine else leader["name"],
                      f" — {leader['votes']} {text('gameLeadersWords', player)}"
                      + (f" · {RANK_MARK} {rank}" if rank else "")])
    me = answer.get("me")
    if me and me["place"] > len(shown):
        lines += [[""], ["👤 ", text("gameLeadersYou", player, place=me["place"], n=me["votes"])]]
    if answer.get("players"):
        lines += [[""], [I(text("gameLeadersPlayers", player, n=answer["players"]))]]
    tabs = [(("• " if value == period else "") + text(key, player), data(player, "l", value))
            for value, key in PERIODS.items()]
    return Screen(lines, [tabs, [("▶️ " + text("gamePlay", player), data(player, "p")),
                                 ("🌐 interslavic.app", "url:" + SITE_URL + "/leaders"
                                  + ("?period=week" if period == "week" else ""))]])


# ── comments on a word ─────────────────────────────────────────

def comment_prompt(player: Player, word_id: str) -> Screen:
    """"Napišite vaš komentar": Telegram asks for a reply to this message, Discord opens a form."""
    found = word_of(word_id)
    if not found:
        return Screen(alert=tr("Togo slova uže nema v slovniku.", player))
    _, first, _, _ = found
    return Screen([["💬 ", B(tr("Napišite vaš komentar", player)), " — ", B(in_script(first, player))],
                   [I(tr("Komentar bude viden pod slovom na interslavic.app.", player))]],
                  prompt={"word": word_id}, edit=False)


def comment_title(player: Player, word_id: str) -> str:
    found = word_of(word_id)
    return in_script(found[1], player) if found else ""


async def comment(player: Player, word_id: str, body: str) -> Screen:
    """Posts the comment as the player, on the word's page on the site."""
    found = word_of(word_id)
    if not found:
        return Screen([[tr("Togo slova uže nema v slovniku.", player)]])
    _, first, _, _ = found
    body = (body or "").strip()
    if not body:
        return Screen([[tr("Komentar jest prazny.", player)]])
    if len(body) > COMMENT_MAX:
        return Screen([[tr(f"Komentar jest predolgy: do {COMMENT_MAX} znakov.", player)]])
    status, answer = await ask(player, "comment", id=word_id, word=first, body=body)
    if status == 401 and answer.get("code") == "SIGN_IN":
        return sign_in_screen(player)
    if status == 403 and answer.get("code") == "BLOCKED":
        return failed_screen(player, status, answer)
    if status == 409:
        return Screen([[tr("Taky komentar uže jest.", player)]])
    if status == 429:
        return Screen([[tr("Mnogo komentarov za kratko vrěme — počekajte nekoliko minut.", player)]])
    if status != 201:
        return failed_screen(player, status, answer)
    _, me = await ask(player, "me")
    lang = meaning_lang(me.get("native"))
    url = f"{SITE_URL}/?text=id{word_id}&lang=isv-{lang}&comment={answer['comment']['id']}"
    return Screen([["✅ ", tr("Vaš komentar jest na interslavic.app pod slovom ", player), B(in_script(first, player)),
                    "."]],
                  [[("🌐 " + tr("Pokazati na sajtu", player), "url:" + url),
                    ("▶️ " + text("gamePlay", player), data(player, "p"))]], edit=False)


# ── the figure ─────────────────────────────────────────────────

_pictures = OrderedDict()  # (stage, worn) → PNG


async def picture(stage: str, worn: list):
    """The figure as a PNG: the site's drawing (GET /community/slavformer), made into pixels here."""
    if resvg_py is None:
        return None
    key = (stage, ",".join(sorted(worn)))
    if key in _pictures:
        _pictures.move_to_end(key)
        return _pictures[key]
    try:
        session = await _get_session()
        async with session.get(f"{site_api.API_BASE}/community/slavformer",
                               params={"stage": stage, "worn": ",".join(worn)}) as response:
            if response.status != 200:
                return None
            svg = await response.text()
        png = await asyncio.to_thread(resvg_py.svg_to_bytes, svg_string=svg)
        png = bytes(png)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError) as e:
        print(f"slavformer picture: {type(e).__name__} {e}")
        return None
    _pictures[key] = png
    if len(_pictures) > PICTURES_MAX:
        _pictures.popitem(last=False)
    return png


def item_name(item: str, player: Player) -> str:
    """"Sinja" alone says little: a paint is shown as 🎨 Sinja."""
    return ("🎨 " if item.startswith("paint-") else "") + tr(ITEM_NAMES.get(item, item), player)


def worn_names(game: dict, player: Player) -> str:
    return ", ".join(item_name(item, player) for item in game.get("worn") or [])


async def figure(player: Player, note: str = "", game: dict = None) -> Screen:
    if game is None:
        status, answer = await ask(player, "me")
        if status != 200:
            return failed_screen(player, status, answer)
        if not answer.get("account"):
            return sign_in_screen(player)
        game = answer["game"]
    lines = [[note]] if note else []
    rank = rank_name(game.get("rank"), player)
    lines += [["🤖 ", B(text("gameTitle", player)), " — ", text(STAGE_KEYS[game["stage"]], player)]
              + ([f" · {RANK_MARK} ", B(rank)] if rank else []),
              [f"⭐ {text('gameAnswers', player)}: {game['votes']} · 💰 {text('gameCoins', player)}: {game['coins']}"
               + (f" · {text('gamePerHour', player, n=game['perHour'])}" if game.get("perHour") else "")]]
    if game.get("worn"):
        lines.append([I(worn_names(game, player))])
    png = await picture(game["stage"], game.get("worn") or [])
    if png is None:
        lines.append([tr("Kako izgledaje: ", player) + GAME_URL])
    return Screen(lines, [
        [("▶️ " + text("gamePlay", player), data(player, "p")), ("🛒 " + text("gameShop", player), data(player, "m", 0))],
        [("🌐 interslavic.app", "url:" + GAME_URL)],
    ], photo=png, edit=False)


# ── the shop ───────────────────────────────────────────────────

async def shop(player: Player, page: int = 0, answer: dict = None, note: str = "") -> Screen:
    if answer is None:
        status, answer = await ask(player, "shop")
        if status == 401 and answer.get("code") == "SIGN_IN":
            return sign_in_screen(player)
        if status != 200:
            return failed_screen(player, status, answer)
    game, items = answer["game"], answer["shop"]
    robot = game["stage"] == "robot"
    pages = max(1, -(-len(items) // SHOP_PAGE))
    page = min(max(page, 0), pages - 1)
    lines = [[note], [""]] if note else []
    lines += [["🛒 ", B(text("gameShop", player)), f" · 💰 {game['coins']} · {page + 1}/{pages}"],
              [I(text("gameShopHint" if robot else "gameShopLocked", player))]]
    if game.get("worn"):
        lines.append([f"👕 {worn_names(game, player)}"])
    buttons = []
    for index in range(page * SHOP_PAGE, min(len(items), (page + 1) * SHOP_PAGE)):
        item = items[index]
        name = item_name(item["id"], player)
        hourly = f" (+{item['perHour']}/h)" if item.get("perHour") else ""
        if item["id"] in (game.get("items") or []):
            on = item["id"] in (game.get("worn") or [])
            label = f"{'✅' if on else '👕'} {name}"
            buttons.append((label, data(player, "w", index, 0 if on else 1, page)))
        elif not robot and item["slot"] != "paint":
            buttons.append((f"🔒 {name} · {item['price']}", data(player, "b", index, page)))
        else:
            buttons.append((f"{'🛒' if game['coins'] >= item['price'] else '🔒'} {name} · {item['price']}{hourly}",
                            data(player, "b", index, page)))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    nav = []
    if page > 0:
        nav.append(("◀️", data(player, "m", page - 1)))
    nav.append(("▶️ " + text("gamePlay", player), data(player, "p")))
    if page < pages - 1:
        nav.append(("➡️", data(player, "m", page + 1)))
    rows.append(nav)
    return Screen(lines, rows)


async def buy(player: Player, index: int, page: int) -> Screen:
    status, answer = await ask(player, "shop")
    if status != 200:
        return failed_screen(player, status, answer)
    items, game = answer["shop"], answer["game"]
    if not 0 <= index < len(items):
        return Screen(alert="?")
    item = items[index]
    if game["stage"] != "robot" and item["slot"] != "paint":
        return Screen(alert=text("gameShopLocked", player))
    if game["coins"] < item["price"]:
        return Screen(alert=text("gameNeedMore", player, n=f"{item['price'] - game['coins']} 💰"))
    status, done = await ask(player, "buy", item=item["id"])
    if status == 409:
        return Screen(alert=text("gameNeedMore", player, n="💰") if done.get("code") == "NO_COINS"
                      else text("gameShopLocked", player))
    if status != 200:
        return failed_screen(player, status, done)
    screen = await shop(player, page, done, note=f"✨ {item_name(item['id'], player)}")
    picture_screen = await figure(player, game=done["game"])
    screen.extra.append(picture_screen)
    return screen


async def wear(player: Player, index: int, on: bool, page: int) -> Screen:
    status, answer = await ask(player, "shop")
    if status != 200:
        return failed_screen(player, status, answer)
    items = answer["shop"]
    if not 0 <= index < len(items):
        return Screen(alert="?")
    status, done = await ask(player, "wear", item=items[index]["id"], on=on)
    if status != 200:
        return failed_screen(player, status, done)
    return await shop(player, page, done)


# ── the buttons ────────────────────────────────────────────────

def parse(raw: str):
    """"sf:123:l:v:474:0" → ("123", "latn", ["v", "474", "0"]); None for anything else."""
    parts = (raw or "").split(":")
    if len(parts) < 4 or parts[0] != "sf" or not parts[1].isdigit():
        return None
    return parts[1], "cyrl" if parts[2] == "c" else "latn", parts[3:]


def not_yours(player: Player) -> Screen:
    return Screen(alert=tr("To jest igra drugogo igrača. Napišite /igra, da byste igrali sami.", player))


_locks = OrderedDict()  # player → one press at a time (a double tap would answer one word twice)


def _lock(player: Player) -> asyncio.Lock:
    key = (player.platform, player.id)
    lock = _locks.get(key)
    if lock is None:
        lock = _locks[key] = asyncio.Lock()
        if len(_locks) > 5000:
            for old in [k for k, held in _locks.items() if not held.locked()][:1000]:
                _locks.pop(old, None)
    return lock


async def press(player: Player, owner: str, what: list) -> Screen:
    """What a button under the game does. `player` pressed it; `owner` is the one whose game the message shows."""
    # the leaders are anyone's to look at
    if what and what[0] == "l":
        return await leaders(player, what[1] if len(what) > 1 else "all")
    if owner != player.id:
        return not_yours(player)
    async with _lock(player):
        return await _press(player, what)


async def _press(player: Player, what: list) -> Screen:
    kind, args = what[0], what[1:]
    try:
        if kind == "p":
            return await play(player)
        if kind == "v":
            return await vote(player, args[0], int(args[1]))
        if kind == "s":
            return await skip(player, args[0])
        if kind == "c":
            return await change(player, args[0], int(args[1]), args[2])
        if kind == "v2":
            return await changed(player, args[0], int(args[1]), args[2])
        if kind == "y":
            return await back_to(player, args[0])
        if kind == "k":
            return comment_prompt(player, args[0])
        if kind == "n":
            return await set_native(player, args[0])
        if kind == "in":
            return await login(player)
        if kind == "ln":
            return await link(player)
        if kind == "f":
            return await figure(player)
        if kind == "m":
            return await shop(player, int(args[0]))
        if kind == "b":
            return await buy(player, int(args[0]), int(args[1]))
        if kind == "w":
            return await wear(player, int(args[0]), args[1] == "1", int(args[2]))
    except (IndexError, ValueError):
        pass
    return Screen(alert="?")


async def command(player: Player, name: str) -> Screen:
    """/igra, /robot, /magazin, /lideri, /vyjdi."""
    async with _lock(player):
        if name in SHOP_COMMANDS:
            return await shop(player, 0)
        if name in FIGURE_COMMANDS:
            return await figure(player)
        if name in LOGOUT_COMMANDS:
            return await logout(player)
        if name in LEADER_COMMANDS:
            return await leaders(player)
        return await play(player)


def command_name(message_text: str) -> str:
    """"/igra@bot …" → "igra"."""
    first = (message_text or "").strip().split(maxsplit=1)[0] if (message_text or "").strip() else ""
    return re.sub(r"@.*$", "", first[1:]).lower()


def all_commands() -> list:
    return COMMANDS + SHOP_COMMANDS + FIGURE_COMMANDS + LOGOUT_COMMANDS + LEADER_COMMANDS
