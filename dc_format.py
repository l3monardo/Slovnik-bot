"""
The Discord look of the bot's answers: the same documents as in Telegram (tg_format blocks),
sent as embeds, since Discord messages have no tables.

  * a heading                      → the embed's title (a link when the heading has one)
  * a table of names and values    → fields; side by side when the table is a grid (the translations of a word)
  * a table with columns (forms)   → a monospace code block
  * a folded part ("on all languages") → an embed of its own
  * the footer                     → 🏴 [interslavic.app](https://interslavic.app)

render() gives a list of messages, each {"embeds": [embed as Discord's JSON]}, within Discord's limits:
4096 characters of description, 25 fields of at most 1024, 6000 characters and 10 embeds a message.
"""
import html
import re

import tg_format as fmt

COLOR = 0x2F6FDB
# The emoji before the link; the bot puts its own application emoji here ("<:interslavic:123…>") when it has one
SITE_EMOJI = "🏴"

TITLE_MAX = 256
DESCRIPTION_MAX = 4096
FIELDS_MAX = 25
FIELD_NAME_MAX = 256
FIELD_VALUE_MAX = 1024
MESSAGE_MAX = 6000
EMBEDS_MAX = 10
CONTENT_MAX = 2000
INLINE_MAX = 60  # a grid with a value longer than this puts its fields under one another
BLANK = "​"


# ── inline HTML (<b>, <i>, <code>, <a href>) as Discord Markdown ──

_TOKEN = re.compile(r'<a href="([^"]*)">|</a>|<(/?)(b|i|code)>|<[^>]+>|([^<]+)')
_SPECIAL = re.compile(r'([\\*_~`|\[\]])')


def escape(text: str) -> str:
    """Plain text that Discord shows as it is."""
    text = _SPECIAL.sub(r'\\\1', text)
    # "# ", "- ", "1. ", "> " at the start of a line would be a heading, a list or a quote
    return re.sub(r'(?m)^(\s*)([#>-]|\d+\.)(\s)', r'\1\\\2\3', text)


def command(text: str) -> str:
    """The bot's commands with Discord's prefix: "/id 474" → ".id 474"."""
    return re.sub(r'^/(?=\w)', '.', text)


def code_span(text: str) -> str:
    text = command(text)
    fence = "``" if "`" in text else "`"
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}" if text else ""


def _url(url: str) -> str:
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def md(inline: str, angle: bool = False) -> str:
    """Inline HTML of a block as Discord Markdown. angle: links as [text](<url>) (no preview in messages)."""
    out, link_stack, code = [], [], None
    for m in _TOKEN.finditer(inline or ""):
        href, closing, tag, text = m.group(1), m.group(2), m.group(3), m.group(4)
        if href is not None:
            link_stack.append((len(out), html.unescape(href)))
        elif m.group(0) == "</a>":
            if link_stack:
                start, url = link_stack.pop()
                label = "".join(out[start:]) or escape(url)
                del out[start:]
                url = _url(url)
                out.append(f"[{label}](<{url}>)" if angle else f"[{label}]({url})")
        elif tag == "code":
            if closing:
                out.append(code_span(code or ""))
                code = None
            else:
                code = ""
        elif tag in ("b", "i"):
            out.append("**" if tag == "b" else "*")
        elif text is not None:
            if code is not None:
                code += html.unescape(text)
            else:
                out.append(escape(html.unescape(text)))
    return "".join(out).replace("****", "")


def plain(inline: str) -> str:
    return re.sub(r"\s+", " ", fmt.plain_text(inline or "")).strip()


def site_line(angle: bool = False) -> str:
    url = f"<{fmt.SITE_URL}>" if angle else fmt.SITE_URL
    return f"{SITE_EMOJI} [{fmt.SITE_NAME}]({url})"


# ── blocks → parts → embeds ────────────────────────────────────

def _first_link(inline: str):
    m = re.search(r'<a href="([^"]*)">', inline or "")
    return html.unescape(m.group(1)) if m else None


CODE_WIDTH = 56  # characters a code block in an embed shows on a line (desktop)


def _grid(rows):
    """Cells laid out with their spans, like tg_format._grid; a cell that continues a column span to the right
    is ("…", text), so that a part of the table cut there can still say what its columns are."""
    grid = []
    for r, row in enumerate(rows):
        while len(grid) <= r:
            grid.append([])
        col = 0
        for c in row:
            while col < len(grid[r]) and grid[r][col] is not None:
                col += 1
            text = fmt.plain_text(c["html"])
            for dr in range(c["rowspan"]):
                while len(grid) <= r + dr:
                    grid.append([])
                line = grid[r + dr]
                while len(line) < col + c["colspan"]:
                    line.append(None)
                for dc in range(c["colspan"]):
                    line[col + dc] = ("…", text) if dr == 0 and dc > 0 else ""
            grid[r][col] = text
            col += c["colspan"]
    width = max((len(line) for line in grid), default=0)
    return [[(cell if cell is not None else "") for cell in line] + [""] * (width - len(line)) for line in grid]


def _column_groups(grid, widths) -> list:
    """The columns of a table too wide for a code block, in groups that fit, each with the row labels
    (the columns before the first heading of the top row)."""
    labels = 1
    while labels < len(widths) - 1 and grid[0][labels] == "":
        labels += 1
    labels = labels if all(grid[0][i] == "" for i in range(labels)) else 1
    base = sum(widths[:labels]) + 2 * (labels - 1)
    groups, current, size = [], [], base
    for col in range(labels, len(widths)):
        if current and size + 2 + widths[col] > CODE_WIDTH:
            groups.append(current)
            current, size = [], base
        current.append(col)
        size += 2 + widths[col]
    if current:
        groups.append(current)
    return [list(range(labels)) + group for group in groups]


def _code_blocks(rows) -> list:
    """A table as monospace text, in code blocks that each fit a field; a wide table in parts."""
    grid = _grid(rows)
    if not grid:
        return []
    text_of = lambda cell: cell[1] if isinstance(cell, tuple) else cell  # noqa: E731
    widths = [max(fmt._width(text_of(line[i])) for line in grid) for i in range(len(grid[0]))]
    if sum(widths) + 2 * (len(widths) - 1) <= CODE_WIDTH:
        groups = [list(range(len(widths)))]
    else:
        groups = _column_groups(grid, widths)
    blocks = []
    for group in groups:
        # the width of a column of this part: its own cells (a span's text counts where it is shown)
        shown = []
        for line in grid:
            cells = []
            for k, col in enumerate(group):
                cell = line[col]
                if isinstance(cell, tuple):
                    cell = cell[1] if k == 0 or not isinstance(line[group[k - 1]], tuple) and group[k - 1] != col - 1 else ""
                cells.append(cell)
            shown.append(cells)
        part_widths = [max(fmt._width(cells[k]) for cells in shown) for k in range(len(group))]
        lines = []
        for cells in shown:
            padded = [text + " " * (part_widths[k] - fmt._width(text)) for k, text in enumerate(cells)]
            line = "  ".join(padded).rstrip().replace("```", "'''")
            if line:  # (a row whose cells are all in other parts of the table)
                lines.append(line)
        blocks += ["```\n" + "\n".join(chunk) + "\n```" for chunk in fmt._chunks(lines, FIELD_VALUE_MAX - 10)]
    return blocks


def _field_rows(rows):
    """A table of names and values as (name, value) pairs; None when it is not one."""
    rows = [row for row in rows if row]
    if len(rows) > 1 and all(c["head"] for c in rows[0]) and not all(c["head"] for c in rows[1]):
        rows = rows[1:]  # the row of column names (a list of words): the fields say it
    pairs = []
    for row in rows:
        heads = [plain(c["html"]) for c in row if c["head"]]
        values = [md(c["html"]) for c in row if not c["head"]]
        if not heads:
            heads, values = [plain(row[0]["html"])], [md(c["html"]) for c in row[1:]]
        name = " · ".join(h for h in heads if h) or BLANK
        value = " · ".join(v for v in values if v) or BLANK
        if len(name) > FIELD_NAME_MAX or len(value) > FIELD_VALUE_MAX:
            return None
        shown = len(" · ".join(plain(c["html"]) for c in row if not c["head"]))  # (without the links' addresses)
        pairs.append((name, value, shown))
    return pairs


def _lines(rows) -> list:
    """A table that cannot be fields, as lines "**first** rest"."""
    out = []
    for row in rows:
        if row:
            rest = " · ".join(md(c["html"]) for c in row[1:] if c["html"])
            out.append(f"**{md(row[0]['html'])}** {rest}".strip() if row[0]["html"] else rest)
    return ["\n".join(group) for group in fmt._chunks(out, FIELD_VALUE_MAX)]


def parts_of(blocks, titled: bool = False) -> list:
    """The document as a flat list of parts: ("title", text, url), ("text", markdown), ("field", name, value, inline)."""
    parts = []
    for block in blocks:
        kind = block[0]
        if kind == "h":
            if not titled:
                parts.append(("title", plain(block[1]), _first_link(block[1])))
                titled = True
            else:
                parts.append(("text", f"**{md(block[1])}**"))
        elif kind == "p":
            parts.append(("text", md(block[1])))
        elif kind == "table":
            pairs = _field_rows(block[1]) if block[2] == "kv" else None
            if pairs and len(pairs) <= FIELDS_MAX:
                inline = len(block) > 3 and block[3] and all(shown <= INLINE_MAX for _, _, shown in pairs)
                parts.extend(("field", name, value, inline) for name, value, _ in pairs)
            elif block[2] == "kv":
                parts.extend(("text", text) for text in _lines(block[1]))
            else:
                parts.extend(("text", text) for text in _code_blocks(block[1]))
        elif kind == "details":
            parts.append(("title", plain(block[1]), None))
            parts.extend(parts_of(block[2], titled=True))
        elif kind == "footer":
            parts.append(("text", site_line()))
    return parts


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def embed_size(embed: dict) -> int:
    """The characters Discord counts against the 6000 of a message."""
    return len(embed.get("title", "")) + len(embed.get("description", "")) + \
        sum(len(f["name"]) + len(f["value"]) for f in embed.get("fields", [])) + \
        len((embed.get("footer") or {}).get("text", ""))


def embeds_of(parts) -> list:
    embeds = []

    def new():
        embeds.append({"color": COLOR, "description": "", "fields": []})
        return embeds[-1]

    current = new()
    texts = []  # text after fields: gathered into one field

    def flush():
        if not texts:
            return
        value = "\n".join(texts)
        texts.clear()
        if len(value) > FIELD_VALUE_MAX:
            for chunk in _split(value, FIELD_VALUE_MAX):
                add_field(BLANK, chunk, False)
        else:
            add_field(BLANK, value, False)

    def add_field(name, value, inline):
        nonlocal current
        if len(current["fields"]) >= FIELDS_MAX or embed_size(current) + len(name) + len(value) > MESSAGE_MAX:
            current = new()
        current["fields"].append({"name": _cut(name, FIELD_NAME_MAX), "value": _cut(value, FIELD_VALUE_MAX),
                                  "inline": inline})

    for part in parts:
        if part[0] == "title":
            flush()
            if current["description"] or current["fields"] or current.get("title"):
                current = new()
            current["title"] = _cut(part[1], TITLE_MAX)
            if part[2]:
                current["url"] = _url(part[2])
        elif part[0] == "field":
            flush()
            add_field(part[1], part[2], part[3])
        elif current["fields"]:
            if len(part[1]) > FIELD_VALUE_MAX:
                flush()
                current = new()
                current["description"] = _cut(part[1], DESCRIPTION_MAX)
            elif texts and len("\n".join(texts)) + 1 + len(part[1]) > FIELD_VALUE_MAX:
                flush()
                texts.append(part[1])
            else:
                texts.append(part[1])
        else:
            joined = f"{current['description']}\n{part[1]}" if current["description"] else part[1]
            if len(joined) > DESCRIPTION_MAX or embed_size(current) + len(part[1]) + 1 > MESSAGE_MAX:
                current = new()
                joined = _cut(part[1], DESCRIPTION_MAX)
            current["description"] = joined
    flush()
    for embed in embeds:
        if not embed["description"]:
            del embed["description"]
        if not embed["fields"]:
            del embed["fields"]
    return [e for e in embeds if e.get("title") or e.get("description") or e.get("fields")]


def _split(text: str, limit: int) -> list:
    return [_cut("\n".join(group), limit) for group in fmt._chunks(text.split("\n"), limit)]


def render(blocks) -> list:
    """The document as Discord messages: [{"embeds": [...]}, …], each within Discord's limits."""
    messages, current, size = [], [], 0
    for embed in embeds_of(parts_of(blocks)):
        n = embed_size(embed)
        if current and (size + n > MESSAGE_MAX or len(current) >= EMBEDS_MAX):
            messages.append({"embeds": current})
            current, size = [], 0
        current.append(embed)
        size += n
    if current:
        messages.append({"embeds": current})
    return messages


# ── the bot's Markdown texts (notes, lessons) ──────────────────

def text_messages(text: str) -> list:
    """One of the bot's Markdown texts as message contents (at most 2000 characters each), the link under it."""
    text = re.sub(r"`/(?=\w)", "`.", text)
    # links without previews in a message
    text = re.sub(r"\]\((?!<)([^)\s]+)\)", r"](<\1>)", text)
    text = f"{text.strip()}\n\n{site_line(angle=True)}"
    out = []
    for group in fmt._chunks(text.split("\n"), CONTENT_MAX - 20):
        out.append("\n".join(group))
    return [_cut(part, CONTENT_MAX) for part in out]


def buttons(rows) -> list:
    """The buttons under a word for Discord: rows of (label, custom_id); a row holds at most five."""
    return [[(_cut(text, 80), data[:100]) for text, data in row[:5]] for row in rows[:5]]
