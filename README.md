# Slovnik-bot

Telegram and Discord bots for the [Interslavic dictionary](https://interslavic.app). Look up a word in any Slavic language and get the Interslavic translation, how well it is understood across the Slavic languages, its declension or conjugation, and the dictionary's explanation, laid out like the website.

Both bots give the same answers. Telegram shows them as rich messages with real tables. Discord shows them as embeds, because Discord messages have no tables.

## Features

- **Words laid out like the site.** In Telegram a word is a table of translations. In Discord the translations are fields side by side, and declension and conjugation tables are monospace blocks; a table too wide for Discord is shown in parts, each with its row labels.
- **Intelligibility under every word.** The community votes, overall and by native language, with the dictionary's ✅ ⚠️ 🚫 marks and the source, [Slovosbor.online](https://slovosbor.online/).
- **Declension and conjugation.** Use a command keyword or the button under the word.
- **Explanation.** A button shows the dictionary's definitions in the language you asked in and in English, then in all languages.
- **Links to interslavic.app** at the bottom of every message (after a 🏴 emoji) and on every word. Words that exist only in the unofficial lists keep their Google Sheet link, since the site has no page for them.
- **Cyrillic or Latin.** A Cyrillic command or keyword (`/ру`, `спр`, `скл`) gives Cyrillic tables, labels and buttons.

## Commands

Commands start with `/` in Telegram and `.` in Discord (`/` works in Discord too).

| Command | What it does |
|---|---|
| `/en dog`, `/ru бегать`, `/ms krugly stol` | Look up a word or phrase in a language. |
| `/id 474` | Show a word by its dictionary ID. |
| `/ru жираф decl` or `/ру жираф скл` | Declension table. |
| `/ru бегать conj` or `/ру бегать спр` | Conjugation table. |
| `/id 474 skl` | The forms keyword works with `/id` too. |
| `/fraznik en today` | The phrasebook. |
| `/wiki en katana`, `/wiki_summary ru sobaka` | Wikipedia lookups. |
| `/help` (`/start` in Telegram) and the lesson commands (`/pouka1` … `/pouka9`) | Help texts (see `pouky.yaml`). |
| `.pravila` | The Discord server rules (Discord only). |
| `/obnovi words\|suggestions\|fraznik\|wiki list\|cognates` | Reload data; without an argument, reload everything. |

Language codes: `isv`, `en`, `ru`, `be`, `uk`, `pl`, `cs`, `sk`, `bg`, `mk`, `sr`, `hr`, `sl`.

Forms keywords (Latin or Cyrillic, look-alike letters are accepted): `conj`, `spr`, `спр` for conjugation; `decl`, `skl`, `скл` for declension.

In Telegram groups, `/ru@botname слово` works.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Put the tokens in `.env`:

```
TELEGRAM_TOKEN=123456:ABC...
DISCORD_TOKEN=MTE...
```

Start each bot on its own:

```bash
./run.sh           # Telegram
./run_discord.sh   # Discord
```

The first start downloads the dictionary sheets. If your saved `words.parquet` is older than this version, it is downloaded again, because the bots need the `addition` and `intelligibility` columns. If the download fails, the old file is kept.

Python 3.10 or newer is needed (disnake 2.12).

### Discord

1. Create an application at https://discord.com/developers/applications.
2. **Bot** page: copy the token into `DISCORD_TOKEN`, and turn on **Message Content Intent** (the bot reads `.ru слово` from messages).
3. **OAuth2 → URL Generator**: scope `bot`; permissions **View Channels**, **Send Messages**, **Embed Links** and **Read Message History** (the bot replies to the question). Open the URL to add the bot to your server.
4. Optional, the 🏴 before the link: on the application's **Emojis** page, upload the picture under a name containing `interslavic` (for example `InterslavicApp`). The bot finds it at start; without one it uses the ordinary 🏴.

### Telegram

Create the bot with [@BotFather](https://t.me/BotFather). The 🏴 before the link comes from the [InterslavicApp emoji pack](https://t.me/addemoji/InterslavicApp): at start the bot reads the pack (`getStickerSet`) and takes its 🏴. Telegram lets a bot send custom emoji only when the bot's owner has Telegram Premium; if Telegram refuses it, the bot resends the answer with the ordinary 🏴 and keeps using that.

### Settings (`.env`)

| Variable | Meaning |
|---|---|
| `TELEGRAM_TOKEN` | Telegram bot token. |
| `DISCORD_TOKEN` | Discord bot token. |
| `ISV_ORTHOGRAPHY=etymological` | Forms tables in etymological spelling. Default is standard, as on the site. |
| `SITE_API` | Site API address. Default `https://interslavic-api.vercel.app/api`. |
| `SITE_API_TIMEOUT` | Seconds to wait for the site API. Default 6. |
| `RICH_MESSAGES=0` | Telegram: never send rich messages, only ordinary ones. |
| `TELEGRAM_API` | Telegram: address of your own Bot API server. |
| `SITE_EMOJI=0` | Telegram: the ordinary 🏴 instead of the custom emoji. |
| `SITE_EMOJI_ID` | Telegram: ID of the custom emoji to use; skips the lookup in the pack. |
| `SITE_EMOJI_SET` | Telegram: custom emoji pack to look in. Default `InterslavicApp`. |
| `DISCORD_SITE_EMOJI` | Discord: the emoji before the link, such as `<:interslavic:1234567890>`. |

## How it works

| File | Role |
|---|---|
| `answers.py` | What both bots answer: search, forms, explanation, buttons, phrasebook, Wikipedia, lessons. |
| `tg_format.py` | Builds each answer as a document of blocks (headings, paragraphs, tables); renders it for Telegram as a rich message, ordinary HTML or plain text. |
| `dc_format.py` | Renders the same documents for Discord as embeds within Discord's limits. |
| `_telegrambot.py` | The Telegram bot: commands, buttons, rich-message sending and fallbacks. |
| `_disnake.py` | The Discord bot: commands, buttons, replies. |
| `site_api.py` | Client for the site API with caching: `/community/forms`, `/community/intelligibility`, `/community/explain`. Returns nothing on failure, so the word still arrives. |
| `isv_tools.py`, `bots.py` | Search, cards, word links and data loading. |
| `pouky.yaml` | Help and lesson texts. |

Forms tables come from the site's own code through the API, so they always match interslavic.app.

**Buttons.** A button's data says what to show, the sheet, the word's ID, the language and the script (`f:w:474:ru:l` = forms of word 474, asked in Russian, Latin script). Pressing the same button again within 10 minutes only shows a note. Buttons keep working after the bot restarts.

**Telegram fallbacks.** Rich message with all features, then a simpler rich message, then ordinary HTML, then plain text. If Telegram answers 404 to rich messages, the bot stops trying them; if it answers 400 for one kind of message, that kind is dropped to the next level. The terminal logs `Telegram refused a rich message ...` with the reason.

## Tests

```bash
python test_isv.py
```

## License

See [LICENSE](LICENSE).
