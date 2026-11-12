# Slovnik-bot

A Telegram (and Discord) bot for the [Interslavic dictionary](https://interslavic.app). Look up a word in any Slavic language and get the Interslavic translation, how well it is understood across the Slavic languages, its declension or conjugation, and the dictionary's explanation, all as tables like the ones on the website.

## Features

- **Tables, not plain text.** Telegram answers are rich messages (Bot API 10.1+), laid out like the dictionary on interslavic.app. If Telegram refuses one, the bot sends the same answer as an ordinary message.
- **Intelligibility under every word.** The community votes from the site, overall and by native language (✅ ⚠️ 🚫).
- **Declension and conjugation.** Use a command keyword or the button under the word.
- **Explanation.** A button shows the dictionary's definitions in the language you asked in and in English, with the other languages folded underneath.
- **Links to interslavic.app** at the bottom of every message and on every word, replacing the old Google Sheet links. Words that exist only in the unofficial lists keep their sheet link, since the site has no page for them.
- **Cyrillic or Latin.** A Cyrillic command or keyword (`/ру`, `спр`, `скл`) gives Cyrillic tables, labels and buttons.

## Commands

Commands start with `/` in Telegram and `.` in Discord.

| Command | What it does |
|---|---|
| `/en dog`, `/ru бегать`, `/ms krugly stol` | Look up a word or phrase in a language. |
| `/id 474` | Show a word by its dictionary ID. |
| `/ru жираф decl` or `/ру жираф скл` | Declension table. |
| `/ru бегать conj` or `/ру бегать спр` | Conjugation table. |
| `/id 474 skl` | The forms keyword works with `/id` too. |
| `/wiki en katana`, `/wiki_summary ru sobaka` | Wikipedia lookups. |
| `/start`, `/help` and the lesson commands | Help texts (see `pouky.yaml`). |
| `/obnovi words\|suggestions\|fraznik\|wiki list\|cognates` | Reload data; without an argument, reload everything. |

Language codes: `isv`, `en`, `ru`, `be`, `uk`, `pl`, `cs`, `sk`, `bg`, `mk`, `sr`, `hr`, `sl`.

Forms keywords (Latin or Cyrillic, look-alike letters are accepted): `conj`, `spr`, `спр` for conjugation; `decl`, `skl`, `скл` for declension.

In groups, `/ru@botname слово` works.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo 'TELEGRAM_TOKEN=123456:ABC...' > .env
./run.sh
```

The first start downloads the dictionary sheets. If your saved `words.parquet` is older than this version, it is downloaded again, because the bot needs the `addition` and `intelligibility` columns. If the download fails, the old file is kept.

For Discord, create an application at https://discord.com/developers/applications/ and set `DISCORD_TOKEN`.

### Settings (`.env`)

| Variable | Meaning |
|---|---|
| `TELEGRAM_TOKEN` | Bot token (required). |
| `DISCORD_TOKEN` | Discord token (optional). |
| `RICH_MESSAGES=0` | Never send rich messages, only ordinary ones. |
| `ISV_ORTHOGRAPHY=etymological` | Forms tables in etymological spelling. Default is standard, as on the site. |
| `SITE_API` | Site API address. Default `https://interslavic-api.vercel.app/api`. |
| `SITE_API_TIMEOUT` | Seconds to wait for the site API. Default 6. |
| `TELEGRAM_API` | Address of your own Bot API server. |

## How it works

| File | Role |
|---|---|
| `_telegrambot.py` | Telegram handlers, buttons, rich-message sending and fallbacks. |
| `tg_format.py` | Builds each answer once as blocks, then renders it as a rich message, ordinary HTML or plain text. |
| `site_api.py` | Client for the site API with caching: `/community/forms`, `/community/intelligibility`, `/community/explain`. Returns nothing on failure, so the word still arrives. |
| `isv_tools.py` | Search, cards, word links and data loading. |
| `bots.py`, `_disnake.py` | Shared search code and the Discord bot. |
| `pouky.yaml` | Help and lesson texts. |

Forms tables come from the site's own code through the API, so they always match interslavic.app.

**Fallbacks.** Rich message with all features, then a simpler rich message, then ordinary HTML, then plain text. If Telegram answers 404 to rich messages, the bot stops trying them; if it answers 400 for one kind of message, that kind is dropped to the next level. The terminal logs `Telegram refused a rich message ...` with the reason.

## Tests

```bash
python test_isv.py
```

## License

See [LICENSE](LICENSE).
