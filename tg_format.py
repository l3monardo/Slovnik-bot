"""
What the Telegram bot sends: every answer is a small document made of blocks
(a heading, paragraphs, tables, a footer with the link to interslavic.app).

A document is rendered in two ways:
  * render_rich()    - the HTML of a "rich message" (Bot API 10.1+, method
                       sendRichMessage), where a table is a real table;
  * render_classic() - ordinary HTML messages (sendMessage, parse_mode=HTML)
                       for when a rich message cannot be sent: a table becomes
                       lines of text or a monospace block.

Texts inside blocks are HTML with nothing but <b>, <i>, <code> and <a href>:
both kinds of message understand those.
"""
import re
import unicodedata
import urllib.parse

import bots
import transliteration as transl

SITE_URL = bots.SITE_URL
SITE_NAME = "interslavic.app"
# The emoji before the link: a custom emoji of the pack t.me/addemoji/InterslavicApp when the bot found its
# id at start (_telegrambot.load_site_emoji), else this ordinary one
SITE_EMOJI = "🏴"
SITE_EMOJI_ID = None
CLASSIC_MAX = 3900  # a message holds 4096 characters


# ── small things ───────────────────────────────────────────────

def esc(text) -> str:
    """Text for an HTML message."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def attr(text) -> str:
    return esc(text).replace('"', "&quot;")


def link(url: str, inner_html: str) -> str:
    return f'<a href="{attr(url)}">{inner_html}</a>'


def script_of(command: str) -> str:
    """'cyrl' when the command was typed in Cyrillic (/ру, /мс …), else 'latn'."""
    return "cyrl" if re.search(r"[Ѐ-ӿ]", command or "") else "latn"


def tr(text: str, script: str) -> str:
    """One of the bot's own Interslavic texts in the reader's script. They are written here in Latin, with
    the etymological letters where the two scripts need them ("spręžeńje" → spreženje, спреженје)."""
    return transl.transliteration(text, "isv_to_cyrillic" if script == "cyrl" else "isv_to_standard")


# ── blocks ─────────────────────────────────────────────────────

def H(inline: str):
    return ("h", inline)


def P(inline: str):
    return ("p", inline)


def T(rows, plain: str = "pre", grid: bool = False):
    """A table. rows: lists of cells (th / td). plain: how it looks without tables -
    'kv' lines "<b>first</b> second", or 'pre', a monospace block. grid: short names and values that may
    stand side by side (Discord shows them as fields in a row)."""
    return ("table", rows, plain, grid)


def D(summary: str, blocks):
    """A part folded under a title."""
    return ("details", summary, blocks)


def site_emoji_html() -> str:
    if SITE_EMOJI_ID:
        return f'<tg-emoji emoji-id="{SITE_EMOJI_ID}">{SITE_EMOJI}</tg-emoji>'
    return SITE_EMOJI


def site_link_html() -> str:
    """The emoji and the link to interslavic.app."""
    return f"{site_emoji_html()} {link(SITE_URL, SITE_NAME)}"


def footer():
    """The link to interslavic.app. Made when the message is rendered, so that a retry after Telegram
    refused the custom emoji goes out without it."""
    return ("footer",)


def th(inline: str, colspan: int = 1, rowspan: int = 1) -> dict:
    return {"html": inline, "head": True, "colspan": colspan, "rowspan": rowspan}


def td(inline: str, colspan: int = 1, rowspan: int = 1) -> dict:
    return {"html": inline, "head": False, "colspan": colspan, "rowspan": rowspan}


# ── rich messages ──────────────────────────────────────────────

def _rich_table(rows, level: int) -> str:
    out = ["<table bordered striped compact>" if level >= 2 else "<table bordered striped>"]
    for row in rows:
        cells = []
        for c in row:
            tag = "th" if c["head"] else "td"
            span = (f' colspan="{c["colspan"]}"' if c["colspan"] > 1 else "") + \
                   (f' rowspan="{c["rowspan"]}"' if c["rowspan"] > 1 else "")
            cells.append(f"<{tag}{span}>{c['html']}</{tag}>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return "".join(out)


def render_rich(blocks, level: int = 2) -> str:
    """The document as the HTML of a rich message. level 2 uses everything the Bot API describes;
    level 1 keeps to headings, paragraphs and plain tables (no <details>, <footer>, compact)."""
    out = []
    for block in blocks:
        kind = block[0]
        if kind == "h":
            out.append(f"<h4>{block[1]}</h4>")
        elif kind == "p":
            out.append(f"<p>{block[1]}</p>")
        elif kind == "table":
            out.append(_rich_table(block[1], level))
        elif kind == "details":
            inner = render_rich(block[2], level)
            if level >= 2:
                out.append(f"<details><summary>{block[1]}</summary>{inner}</details>")
            else:
                out.append(f"<p><b>{block[1]}</b></p>{inner}")
        elif kind == "footer":
            out.append(f"<footer>{site_link_html()}</footer>" if level >= 2 else f"<p>{site_link_html()}</p>")
    return "".join(out)


# ── ordinary messages ──────────────────────────────────────────

_TAG = re.compile(r"<[^>]+>")


def plain_text(inline: str) -> str:
    """Inline HTML as bare text."""
    text = _TAG.sub("", inline)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")


def _width(text: str) -> int:
    return sum(0 if unicodedata.combining(ch) else 1 for ch in text)


def _grid(rows):
    """Cells laid out with their spans: a list of rows of texts, '' where a span continues."""
    grid = []
    for r, row in enumerate(rows):
        while len(grid) <= r:
            grid.append([])
        col = 0
        for c in row:
            while col < len(grid[r]) and grid[r][col] is not None:
                col += 1
            for dr in range(c["rowspan"]):
                while len(grid) <= r + dr:
                    grid.append([])
                line = grid[r + dr]
                while len(line) < col + c["colspan"]:
                    line.append(None)
                for dc in range(c["colspan"]):
                    line[col + dc] = ""
            grid[r][col] = plain_text(c["html"])
            col += c["colspan"]
    width = max((len(line) for line in grid), default=0)
    return [[(cell or "") for cell in line] + [""] * (width - len(line)) for line in grid]


def _chunks(lines, limit: int = 3000):
    """Lines in groups that each fit a message."""
    groups, current, size = [], [], 0
    for line in lines:
        if current and size + len(line) + 1 > limit:
            groups.append(current)
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        groups.append(current)
    return groups


def _pre_table(rows) -> list:
    grid = _grid(rows)
    if not grid:
        return []
    widths = [max(_width(line[i]) for line in grid) for i in range(len(grid[0]))]
    lines = []
    for line in grid:
        parts = [text + " " * (widths[i] - _width(text)) for i, text in enumerate(line)]
        lines.append(esc("  ".join(parts).rstrip()))
    return ["<pre>" + "\n".join(group) + "</pre>" for group in _chunks(lines)]


def _kv_table(rows) -> list:
    lines = []
    for row in rows:
        if not row:
            continue
        first, rest = row[0], row[1:]
        value = " · ".join(c["html"] for c in rest if c["html"])
        lines.append(f"<b>{first['html']}</b> {value}".rstrip() if first["html"] else value)
    return ["\n".join(group) for group in _chunks(lines)]


def _classic_parts(blocks):
    parts = []
    for block in blocks:
        kind = block[0]
        if kind == "h":
            parts.append(f"<b>{block[1]}</b>")
        elif kind == "p":
            parts.append(block[1])
        elif kind == "table":
            parts.extend(_kv_table(block[1]) if block[2] == "kv" else _pre_table(block[1]))
        elif kind == "details":
            parts.append(f"<b>{block[1]}</b>")
            parts.extend(_classic_parts(block[2]))
        elif kind == "footer":
            parts.append(site_link_html())
    return [part for part in parts if part]


def render_classic(blocks) -> list:
    """The document as ordinary HTML messages (usually one), split between blocks when it is long."""
    messages, current = [], ""
    for part in _classic_parts(blocks):
        if current and len(current) + len(part) + 2 > CLASSIC_MAX:
            messages.append(current)
            current = ""
        current = f"{current}\n\n{part}" if current else part
    if current:
        messages.append(current)
    return messages


def render_plain(blocks) -> str:
    """Last resort: the document as bare text."""
    return plain_text("\n\n".join(_classic_parts(blocks)))[:4000]


# ── the dictionary's cells ─────────────────────────────────────

def get_part_of_speech(details: str):
    """The part of speech of a "partOfSpeech" cell ("m.anim.", "v.tr. ipf.", "adj." …), as the site reads it."""
    arr = (details or "").replace("./", "/").replace(" ", "").split(".")
    for mark, name in (("particle", "particle"), ("prefix", "prefix"), ("suffix", "suffix"),
                       ("phrase", "phrase"), ("adj", "adjective")):
        if mark in arr:
            return name
    if any(mark in arr for mark in ("f", "n", "m", "m/f")):
        return "noun"
    for mark, name in (("adv", "adverb"), ("conj", "conjunction"), ("prep", "preposition"),
                       ("pron", "pronoun"), ("num", "numeral"), ("intj", "interjection"), ("v", "verb")):
        if mark in arr:
            return name
    return None


def forms_kind(isv: str, details: str):
    """'conjugation' or 'declension' when the dictionary shows a table of forms for the word, else None
    (the site's wordHasForms)."""
    pos = get_part_of_speech(details)
    if pos == "verb":
        return "conjugation"
    if pos == "adjective":
        return "declension"
    if pos in ("noun", "numeral", "pronoun"):
        if " " in isv and re.search(r"[^,] [^\[]", isv):
            return None
        return "declension"
    return None


INTELLIGIBILITY_MARKS = {"-": "🚫", "~": "⚠️", "+": "✅"}


def intelligibility_marks(cell: str) -> dict:
    """"bg+ cs~ ru-" → {'bg': '✅', 'cs': '⚠️', 'ru': '🚫'}"""
    marks = {}
    for tag in (cell or "").split(" "):
        m = re.match(r"^!?(\w+)(.?)", tag)
        if m and m.group(2) in INTELLIGIBILITY_MARKS:
            marks[m.group(1)] = INTELLIGIBILITY_MARKS[m.group(2)]
    return marks


def _split_words(words: str):
    sep = "; " if ";" in words else ", "
    return [part.strip() for part in words.split(sep) if part.strip()], sep


def _wiktionary_title(word: str) -> str:
    word = word.replace("!", "").replace("#", "")
    word = re.sub(r" \(.*\)", "", word)
    word = re.sub(r" \[.*\]", "", word)
    return word.strip()


def wiktionary_url(lang: str, word: str) -> str:
    title = _wiktionary_title(word)
    if not title:
        return ""
    if lang == "isv":
        title = transl.transliteration(title, "isv_to_standard")
        return f"https://incubator.wikimedia.org/wiki/Wt/isv/{urllib.parse.quote(title)}"
    return f"https://{lang}.wiktionary.org/wiki/{urllib.parse.quote(title)}"


def words_html(words: str, lang: str) -> str:
    """A cell of translations: every word a link to Wiktionary, a machine translation ("!word") marked 🤖."""
    parts, sep = _split_words(words or "")
    out = []
    for part in parts:
        display = esc(bots.formatizer(part, "telegram").strip())
        url = wiktionary_url(lang, part)
        out.append(link(url, display) if url else display)
    return sep.join(out)


# ── the bot's texts (Interslavic, standard spelling) ───────────

VOTES = [
    ("understand", "Razuměju"),
    ("context", "Razuměju v kontekstu"),
    ("nonNative", "Razuměju iz nerodnogo jezyka"),
    ("rare", "Rědko slovo"),
    ("unsure", "Ne znaju"),
    ("falseFriend", "Falšivy prijatelj"),
    ("notUnderstand", "Ne razuměju"),
]
DEFINITION_LANGS = ["en", "ru", "uk", "be", "pl", "cs", "sk", "sl", "hr", "sr", "mk", "bg"]
SENSES_MAX = 5
SYNONYMS_MAX = 12
STAT_LANGS_MAX = 12
SLOVOSBOR_URL = "https://slovosbor.online/"

BUTTON_TEXT = {
    "declension": "Pokazati sklonjenje",
    "conjugation": "Pokazati spręžeńje",
    "explanation": "Pokazati objasnjenje",
}


def _share(part: int, total: int) -> int:
    return round(part / total * 100) if total else 0


def combined_stats(stats: dict) -> dict:
    """The votes on interslavic.app and on slovosbor.online together, as the site shows them."""
    counts, by_lang = {}, {}
    external = stats.get("external") or {}

    def add(target, source):
        for vote, n in (source or {}).items():
            target[vote] = target.get(vote, 0) + (n or 0)

    add(counts, stats.get("counts"))
    add(counts, external.get("counts"))
    for groups in (stats.get("byLang"), external.get("byLang")):
        for lang, group in (groups or {}).items():
            target = by_lang.setdefault(lang, {"total": 0, "counts": {}})
            target["total"] += group.get("total", 0) or 0
            add(target["counts"], group.get("counts"))
    return {"total": (stats.get("total") or 0) + (external.get("total") or 0), "counts": counts, "byLang": by_lang}


def stats_blocks(stats, script: str, word_url: str = "") -> list:
    """The paragraphs under a word: how well people understand it. stats: the site's answer or None."""
    if not stats:
        return []
    everything = combined_stats(stats)
    title = f"📊 <b>{esc(tr('Statistika razumlivosti', script))}</b>"
    # where the votes come from
    source = P(f"{esc(tr('Izvor', script))}: {link(SLOVOSBOR_URL, 'Slovosbor.online')}")
    if not everything["total"]:
        empty = esc(tr("ješče nikto ne glasoval za to slovo", script))
        return [P(f"{title}: {empty}"), source]
    shares = " · ".join(
        f"{esc(tr(label, script))} {_share(everything['counts'].get(vote, 0), everything['total'])}%"
        for vote, label in VOTES if everything["counts"].get(vote)
    )
    blocks = [P(f"{title} ({esc(tr('glasy', script))}: {everything['total']}): {shares}")]
    langs = sorted(
        ((lang, group) for lang, group in everything["byLang"].items() if group.get("total", 0) > 0),
        key=lambda item: -item[1]["total"],
    )[:STAT_LANGS_MAX]
    if langs:
        per_lang = " · ".join(
            f"<b>{esc(lang)}</b> {_share(group['counts'].get('understand', 0), group['total'])}% ({group['total']})"
            for lang, group in langs
        )
        head = esc(tr("Po rodnomu jezyku", script)) + " — " + esc(tr("Razuměju", script).lower())
        blocks.append(P(f"<i>{head}:</i> {per_lang}"))
    blocks.append(source)
    return blocks


# ── documents ──────────────────────────────────────────────────

def headword_html(card: dict) -> str:
    word = words_html(card["isv"], "isv") or esc(card["isv"])
    details = " ".join(part for part in (card.get("addition"), card.get("partOfSpeech")) if part)
    return f"{word} <i>{esc(details)}</i>" if details else word


def word_doc(card: dict, script: str, stats=None) -> list:
    """A word of the dictionary: its translations as a table, the statistics, the link to interslavic.app."""
    marks = intelligibility_marks(card.get("intelligibility", ""))
    rows = []
    for lang, words in card["translations"]:
        if not words or words == "!":
            continue
        label = esc(lang) + (f" {marks[lang]}" if lang in marks else "")
        rows.append([th(label), td(words_html(words, lang))])
    blocks = [H(headword_html(card))]
    if rows:
        blocks.append(T(rows, plain="kv", grid=True))
    official = card["sheet"] == "words"
    if official:
        blocks.extend(stats_blocks(stats, script, card["link"]))
        blocks.append(P(f"{link(card['link'], esc(tr('Otvoriti v slovniku', script)) + ' ↗')}"
                        f" · <code>/id {esc(card['id'])}</code>"))
    else:
        # a word of the other lists: the site does not have it, the title leads to its row in the sheet
        blocks.append(P(f"⚠️ {link(card['link'], esc(card['title']))} · <code>/id {esc(card['id'])}</code>"))
    blocks.append(footer())
    return blocks


def word_buttons(card: dict, script: str) -> list:
    """The buttons under a word: rows of (text, callback data)."""
    rows = []
    sheet_code = SHEET_CODES.get(card["sheet"])
    kind = forms_kind(card["isv"], card.get("partOfSpeech", ""))
    alphabet = "c" if script == "cyrl" else "l"
    lang = card.get("lang") or "en"
    # callback data (at most 64 bytes): what:sheet:id:language:alphabet
    if kind and sheet_code and card["id"]:
        rows.append([(tr(BUTTON_TEXT[kind], script), f"f:{sheet_code}:{card['id']}:{lang}:{alphabet}")])
    if card["sheet"] == "words" and card["id"].isdigit():
        rows.append([(tr(BUTTON_TEXT["explanation"], script), f"e:w:{card['id']}:{lang}:{alphabet}")])
    return [row for row in rows if len(row[0][1].encode()) <= 64]


SHEET_CODES = {"words": "w", "suggestions": "s", "Wiki list": "l", "Cognates": "c"}
SHEET_NAMES = {code: name for name, code in SHEET_CODES.items()}


def list_doc(item: dict, script: str) -> list:
    """Several words were found: a table of them with the command that shows each."""
    lang = item.get("lang") or ""
    head = [th("isv")] + ([th(esc(lang))] if lang else []) + [th("/id")]
    rows = [head]
    for row in item["rows"]:
        cells = [td(esc(row["isv"]))]
        if lang:
            cells.append(td(esc(row["translation"].lstrip("!"))))
        cells.append(td(f"<code>/id {esc(row['id'])}</code>"))
        rows.append(cells)
    blocks = [P(f"<b>{_md_inline(item['title'])}</b>"), T(rows, plain="kv", grid=True)]
    if item.get("more"):
        blocks.append(P("<i>I tako dalje…</i>"))
    blocks.append(footer())
    return blocks


def phrase_doc(item: dict) -> list:
    rows = [[th(esc(name)), td(esc(value))] for name, value in item["fields"]]
    return [H(f"Rezultat iz {link(_FRAZNIK_URL, 'fraznika')}"), T(rows, plain="kv"), footer()]


_FRAZNIK_URL = "https://gorlatoff.github.io/fraznik.html"


def lines_doc(text: str):
    """A text whose every line is "`code` words" (Wikipedia titles, summaries) as a table; None when it is not."""
    rows = []
    for line in text.split("\n"):
        m = re.match(r"^`([^`]+)`:? (.*)$", line.strip())
        if not m:
            return None
        rows.append([th(esc(m.group(1))), td(esc(m.group(2)))])
    return [T(rows, plain="kv", grid=True), footer()] if rows else None


def _md_inline(text: str) -> str:
    """The little Markdown of the bot's own lines (`code`) as HTML."""
    return re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1).replace('.id', '/id', 1)}</code>", esc(text))


def forms_doc(card: dict, forms: dict, script: str) -> list:
    """The declension or conjugation tables the site gave for the word (GET /api/community/forms)."""
    title = f"{headword_html(card)} — {esc(forms.get('name') or '')}"
    blocks = [H(title)]
    sections = forms.get("sections") or []
    for section in sections:
        if section.get("title"):
            blocks.append(P(f"<b>{esc(section['title'])}</b>"))
        for table in section.get("tables") or []:
            rows = [[
                (th if c.get("head") else td)(esc(c.get("text", "")), c.get("colspan") or 1, c.get("rowspan") or 1)
                for c in row
            ] for row in table]
            # the list of infinitive, participles …: two columns, read as lines without tables
            two = all(len(row) == 2 and row[0]["colspan"] == 1 for row in rows)
            blocks.append(T(rows, plain="kv" if two else "pre", grid=two))
    if card["sheet"] == "words":
        blocks.append(P(link(card["link"], esc(tr("Otvoriti v slovniku", script)) + " ↗")))
    blocks.append(footer())
    return blocks


def no_forms_doc(card: dict, script: str) -> list:
    text = tr("Za to slovo nema tabely sklonjenja ili spręžeńja.", script)
    return [H(headword_html(card)), P(esc(text)), footer()]


def explanation_doc(card: dict, data: dict, lang: str, script: str) -> list:
    """What the word means: the definitions slovosbor.online keeps for it, as interslavic.app shows them."""
    main = lang if lang in DEFINITION_LANGS else "en"
    title = f"{headword_html(card)} — {esc(tr('Objasnjenje', script))}"
    blocks = [H(title)]
    # spelling variants of a word often carry the same definition: once is enough
    senses, seen = [], set()
    for sense in data.get("senses") or []:
        defs = sense.get("defs") or {}
        key = defs.get(main) or defs.get("en") or next(iter(defs.values()), "")
        if key and key not in seen:
            seen.add(key)
            senses.append(defs)
    if not senses:
        blocks.append(P(esc(tr("Za to slovo ješče nema objasnjenja.", script))))
        blocks.append(P(link(card["link"], esc(tr("Otvoriti v slovniku", script)) + " ↗")))
        blocks.append(footer())
        return blocks

    shown = senses[:SENSES_MAX]
    numbered = len(shown) > 1
    rows = []
    for i, defs in enumerate(shown):
        first = main if defs.get(main) else ("en" if defs.get("en") else next(iter(defs)))
        langs = [first] + (["en"] if first != "en" and defs.get("en") else [])
        for j, code in enumerate(langs):
            row = []
            if numbered and j == 0:
                row.append(th(str(i + 1), rowspan=len(langs)))
            row.extend([th(esc(code)), td(esc(defs[code]))])
            rows.append(row)
    blocks.append(T(rows, plain="kv"))
    if len(senses) > len(shown):
        blocks.append(P(f"+{len(senses) - len(shown)}"))

    everything = []
    for i, defs in enumerate(shown):
        if numbered:
            everything.append(P(f"<b>{i + 1}.</b>"))
        everything.append(T([[th(esc(code)), td(esc(defs[code]))] for code in DEFINITION_LANGS if defs.get(code)],
                            plain="kv"))
    blocks.append(D(esc(tr("Na vsih jezykah", script)), everything))

    synonyms = [s for s in (data.get("synonyms") or []) if s][:SYNONYMS_MAX]
    if synonyms:
        blocks.append(P(f"<i>{esc(tr('Sinonimy', script))}:</i> {esc(', '.join(synonyms))}"))
    source = data.get("source") or "https://slovosbor.online"
    blocks.append(P(f"{esc(tr('Izvor', script))}: {link(source, 'Slovosbor.online')}"
                    f" · {link(card['link'], esc(tr('Otvoriti v slovniku', script)) + ' ↗')}"))
    blocks.append(footer())
    return blocks


def error_doc(text: str) -> list:
    return [P(esc(text)), footer()]


# ── texts the bot already had (Markdown written for Discord) ───

def footer_markdown_v2() -> str:
    emoji = f"![{SITE_EMOJI}](tg://emoji?id={SITE_EMOJI_ID})" if SITE_EMOJI_ID else SITE_EMOJI
    return f"\n\n{emoji} [interslavic\\.app]({SITE_URL})"


def footer_plain() -> str:
    return f"\n\n{SITE_EMOJI} {SITE_NAME}"


def rich_markdown(text: str, image: str = "") -> str:
    """One of the bot's Markdown texts (lessons, notes) as the Markdown of a rich message: commands with a
    slash, bullets as a list, every other line a paragraph of its own, the footer with the link."""
    text = text.replace("`.", "`/").replace("@Mašina", "@mashina_slovnik_bot")
    text = re.sub(r"\]\(<([^>]+)>\)", r"](\1)", text)
    paragraphs = []
    for chunk in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip() for line in chunk.split("\n") if line.strip()]
        if lines and all(line.startswith("•") for line in lines):
            paragraphs.append("\n".join("- " + line.lstrip("• ").strip() for line in lines))
        else:
            paragraphs.extend(lines)
    if image:
        paragraphs.insert(0, f"![]({image})")
    paragraphs.append(f'<footer>{site_link_html()}</footer>')
    return "\n\n".join(paragraphs)
