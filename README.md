# Slovnik-bot

Telegram and Discord bots for the [Interslavic dictionary](https://interslavic.app). Look up a word in any Slavic language and get the Interslavic translation, how well it is understood across the Slavic languages, its declension or conjugation, and the dictionary's explanation, laid out like the website.

Both bots give the same answers. Telegram shows them as rich messages with real tables. Discord shows them as embeds, because Discord messages have no tables.

## Features

- **Words laid out like the site.** In Telegram a word is a table of translations. In Discord the translations are fields side by side, and declension and conjugation tables are monospace blocks; a table too wide for Discord is shown in parts, each with its row labels.
- **Intelligibility under every word.** The community votes, overall and by native language, with the dictionary's ✅ ⚠️ 🚫 marks and the source, [Slovosbor.online](https://slovosbor.online/).
- **Declension and conjugation.** Use a command keyword or the button under the word.
- **Explanation.** A button shows the dictionary's definitions in the language you asked in and in English, then in all languages.
- **Links to interslavic.app** at the bottom of every message (after a 🏴 emoji) and on every word. Words that exist only in the unofficial lists keep their Google Sheet link, since the site has no page for them.
- **The Slavformer.** The word game of [interslavic.app](https://interslavic.app/game), played in the chat: say how well you understand each word, earn grivnas, turn the old car into a robot and dress it up. Every answer is your intelligibility vote in the dictionary on the site, and the game is your game there (see [The Slavformer](#the-slavformer)).
- **The site's menu** (Telegram). The Menu button of a private chat opens the dictionary, Tandem, the Slavformer and the whole of interslavic.app inside Telegram (see [The Menu button](#the-menu-button)).
- **Announcements from interslavic.app** (Telegram). News of the site, new language partners, voice rooms that open, new events, new articles of Kolozor and of the Interslavic Wikipedia — in the chats that asked for them, with the picture when there is one (see [Announcements](#announcements)).
- **Who is looking for a language partner:** `/tandem`.
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
| `/tandem` (`/тандем`) | Who is looking for a language partner on interslavic.app: names, the languages they help with and the ones they learn. |
| `/obvestky` (`/обвесткы`, `/notify`) | Telegram: which announcements from interslavic.app this chat gets. |
| `/igra` (`/игра`, `/slavformer`) | The Slavformer: the next word to answer. |
| `/robot`, `/magazin`, `/lideri`, `/vyjdi` | Your Slavformer as a picture, its shop, the leaders, and signing the bot out of your account. |
| `/obnovi slovnik\|words\|suggestions\|fraznik\|wiki list\|cognates` | Reload data (`slovnik` = `words`, the official dictionary); without an argument, reload everything. |

Language commands: `/isv` (or `/ms`, `/мс`), `/en`, `/ru` (`/ру`), `/be` (`/бе`), `/uk` (`/ua`, `/ук`), `/pl`, `/cs` (`/cz`), `/sk`, `/bg` (`/бг`), `/mk` (`/мк`), `/sr` (`/ср`), `/hr`, `/sl`. The word can be written in Latin or Cyrillic. Searching a Slavic language gives the Interslavic word; `/isv` and `/ms` search Interslavic itself. `/de`, `/nl` and `/eo` answer that the bot does not have those languages yet: they are in another sheet of the dictionary, which the bot does not download.

`/help` (`/pomoč`, `/помоч`, `/start`) lists all of this in the chat; the text is `help` in `pouky.yaml`.

Most commands also have Cyrillic names: `/помоч`, `/поука1`, `/фразник`, `/обнови`. Lesson commands, in short: `/pouka1`, `/pouka2` links and tools; `/pouka3` passive learning; `/pouka4` how to learn; `/pouka5`, `/pouka6` the dictionary; `/pouka7` the phrasebook; `/pouka8` about the bot; `/pouka9` keyboards.

Buttons under every word of the official dictionary: **Pokazati sklonjenje / spreženje** (declension / conjugation) and **Pokazati objasnjenje** (explanation). In Cyrillic commands the buttons are in Cyrillic.

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
| `SLOVNIK_BOT_SECRET` | The Slavformer, the announcements and `/tandem`: the secret shared with the site's API (the same value on Vercel). |
| `ANNOUNCE=0` | Telegram: no announcements from interslavic.app (the bot does not ask the site for them). |
| `ANNOUNCE_EVERY` | Telegram: how often the site is asked for something new, in seconds. Default 60. |
| `MENU_BUTTON=0` | Telegram: the bot leaves its Menu button alone (see [The Menu button](#the-menu-button)). |
| `RICH_MESSAGES=0` | Telegram: never send rich messages, only ordinary ones. |
| `TELEGRAM_API` | Telegram: address of your own Bot API server. |
| `SITE_EMOJI=0` | Telegram: the ordinary 🏴 instead of the custom emoji. |
| `SITE_EMOJI_ID` | Telegram: ID of the custom emoji to use; skips the lookup in the pack. |
| `SITE_EMOJI_SET` | Telegram: custom emoji pack to look in. Default `InterslavicApp`. |
| `DISCORD_SITE_EMOJI` | Discord: the emoji before the link, such as `<:interslavic:1234567890>`. |

## Announcements

The Telegram bot tells a chat what happens on interslavic.app: news of the site, new language partners, voice rooms that open, new events, new articles of Kolozor and of the Interslavic Wikipedia. A news item, a voice room and an article come with their picture when they have one. Under each announcement is a button that opens it.

**Nothing is sent to a chat that did not ask.**

- **A person** writes `/obvestky` to the bot in a private chat and ticks the kinds they want. The first time someone uses the bot in a private chat, the bot offers this once ("Hčete li dostavati tut novosti…"), and never again.
- **A group or a channel:** an admin writes `/obvestky` there and ticks the kinds. In a group with topics the announcements go to the topic the command was written in. Others who press the buttons only get a note. In a channel the bot has to be an admin (otherwise it neither sees the command nor may post).

`/obvestky` again changes the choice; "Izključiti vse" stops everything. A chat that blocked or removed the bot is forgotten.

**How it works.** The bot keeps nothing itself: the chats' choices and what there is to tell are on the site (`POST /api/community/botnews` with `SLOVNIK_BOT_SECRET`, see `api/_lib/botnews.ts` in interslavic-hub). Once a minute the bot asks for what is new, sends it and says how far it got — so nothing is told twice, and what happened while the bot was not running is told when it starts again, unless it is stale by then (a voice room is worth 20 minutes, the rest two or three days). The site finds the new articles of Kolozor and of the Wikipedia by itself, looking there every ten minutes.

**Pictures and buttons.** A picture on the site's own server (a news item, a voice room) Telegram downloads by its address. A picture of another site — an article of Kolozor or of the Wikipedia — the bot downloads itself and hands to Telegram as a file, once; the other chats get it by the id Telegram gave it. (Telegram's own downloader is refused by some sites: kolozor.com answered it with a page instead of the picture, and the announcement came without one. When the bot cannot get the picture either, the console says `picture from kolozor.com: …` and the text goes alone.) An announcement has one button, "Otvoriti", unless the site names its own: an article of Kolozor has two, "Otvoriti na Interslavic.app" and "Otvoriti na Kolozor.com".

`/tandem` asks the same address for the newest 30 people who look for a language partner.

## The Menu button

In a private chat the Telegram bot has a **Menu** button left of the message field. It opens the menu of interslavic.app inside Telegram — the same one @Interslavic_app has:

1. **Slovnik** — the dictionary;
2. **Tandem** — language partners, voice rooms, requests, and this bot's announcements for the chat (the same switches as `/obvestky`);
3. **Slavformer** — the game's page;
4. **Full app** — the whole site.

The pages open signed in as the person's Telegram account. The commands are still listed when one types `/`.

**Setup.** The page learns who pressed the button from what Telegram signs for it, and the site checks that signature with this bot's token. So the site has to know the token: on Vercel (the API's project → Settings → Environment Variables) set `SLOVNIK_BOT_TOKEN` to the same value as `TELEGRAM_TOKEN` in the bot's `.env`, then redeploy. The token is used there for that check only.

When the bot starts it asks the site whether the menu is offered to it (`POST /api/community/botnews`, `menu`) and sets the button; the console says `Menu button: Menu → https://interslavic.app/tg/`, or why it was not set (the token is missing on Vercel, or is another bot's). Until then the button stays as it was. `MENU_BUTTON=0` in `.env` makes the bot leave the button alone; to get the list of commands back on the button, use `/setmenubutton` in @BotFather.

## The Slavformer

`/igra` in Telegram and `.igra` in Discord start the word game of interslavic.app. The bot shows a dictionary word; its meaning in your mother tongue is hidden under a spoiler. You answer with one of five buttons — *Razuměju*, *Razuměju v kontekstu*, *Razuměju iz nerodnogo jezyka*, *Falšivy prijatelj*, *Ne razuměju* — and the next word takes its place. Every answer is your intelligibility vote on the word at interslavic.app, exactly as if you had voted on the site, and earns grivnas: 10 per word, 50 more every tenth. After 10 words the car stands up, after 30 it is a robot, and the shop opens.

**Signing in.** The first `/igra` asks you to sign in:

- **Vojdti s Telegramom / s Discordom** gives the bot the account interslavic.app gives this Telegram or Discord: the one you connected it to on the site, or the one made by signing in with it. If there is none, it is made now — sign in on the site with the same Telegram or Discord and you see the same game.
- **Uže imam račun na interslavic.app** is for an account made otherwise (Google…). The bot sends a link (only to you: in Telegram in your private chat with the bot, in Discord as a message only you see). Open it, sign in on the site and press *Svęzati*. The link works once, for 15 minutes.

The bot then asks your mother tongue once (the votes are counted by it). `/vyjdi` signs the bot out; the account and the game stay on the site.

**Under each word**: *Propustiti* (skip it), *💬 Komentovati* (write a comment on the word — Telegram asks for a reply to its message "Napišite vaš komentar", Discord opens a form; the comment appears under the word on interslavic.app), *✏️ Izměniti prědhodny odgovor* (go back to the word before and answer it otherwise — no grivnas are added or taken), and the robot, the shop and the leaders.

**Leaders.** `/lideri` (or the 🏆 button) shows who has answered the most words — ever, or in the last seven days — and your own place; the same list is on the site at interslavic.app/leaders.

**In groups and servers** each game belongs to its player: someone else's buttons only show a note (anyone may look at the leaders).

**Setup.** Both bots need the same secret as the site's API, in `.env`:

```
SLOVNIK_BOT_SECRET=a-long-random-string
```

and on Vercel (the API's project → Settings → Environment Variables → `SLOVNIK_BOT_SECRET`, the same value, then redeploy). Whoever has the secret can play for anyone, so it goes nowhere else. The pictures of the robot are made with `resvg-py` (in `requirements.txt`); without it the bot links to the site instead.

For the Telegram menu, add the commands in @BotFather (`/setcommands`):

```
help - All commands
tandem - Who is looking for a language partner
obvestky - Announcements from interslavic.app
igra - Slavformer: the word game
robot - My Slavformer
magazin - The Slavformer's shop
lideri - The Slavformer's leaders
vyjdi - Sign the bot out of my interslavic.app account
```

The game's texts come from the site's translations: `python3 tools/slavformer_strings.py <interslavic-hub>/src/translations/data.json > slavformer_strings.json` updates them.

## How it works

| File | Role |
|---|---|
| `answers.py` | What both bots answer: search, forms, explanation, buttons, phrasebook, Wikipedia, lessons. |
| `tg_format.py` | Builds each answer as a document of blocks (headings, paragraphs, tables); renders it for Telegram as a rich message, ordinary HTML or plain text. |
| `dc_format.py` | Renders the same documents for Discord as embeds within Discord's limits. |
| `_telegrambot.py` | The Telegram bot: commands, buttons, rich-message sending and fallbacks. |
| `_disnake.py` | The Discord bot: commands, buttons, replies. |
| `slavformer.py` | The Slavformer: the game's screens and buttons for both bots, through the site's `/community/slavbot`; the robot's picture from `/community/slavformer`. |
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
