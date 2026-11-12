"""
The Discord bot: the same answers as the Telegram bot (answers.py), shown as embeds (dc_format.py).

Commands start with "." (".ru бегать", ".ru бегать spr", ".id 474 skl", ".wiki be …", ".fraznik en …"),
"/" works too. The buttons under a word show its declension or conjugation and its explanation.

Needs DISCORD_TOKEN and, in the Discord Developer Portal, the "Message Content" intent of the bot.
"""
import asyncio
import os
import re
import time

import disnake

import answers
import dc_format as dfmt
import isv_tools as isv
import tg_format as fmt
from bot_config import *

intents = disnake.Intents.default()
intents.message_content = True  # to read ".ru слово"
bot = disnake.Client(intents=intents, allowed_mentions=disnake.AllowedMentions.none())

PREFIXES = ('.', '/')
PRESSED = {}  # (message, button) → when: the same button is answered once
PRESSED_SECONDS = 600


# ── sending ────────────────────────────────────────────────────

def action_rows(buttons):
    """The buttons under a word as Discord components."""
    return [disnake.ui.ActionRow(*[
        disnake.ui.Button(label=label, custom_id=data, style=disnake.ButtonStyle.secondary)
        for label, data in row
    ]) for row in dfmt.buttons(buttons)] if buttons else []


async def send(target: disnake.Message, followup=None, **kwargs):
    """A reply under `target`; through the interaction when the bot may not reply in that channel."""
    try:
        return await target.reply(mention_author=False, **kwargs)
    except disnake.Forbidden:
        if followup is None:
            raise
        return await followup.send(**kwargs)


async def deliver(target: disnake.Message, answer_list, followup=None):
    """Sends what answers.py gave, one answer after another, as replies to `target`."""
    for answer in answer_list:
        if "doc" in answer:
            print(fmt.render_plain(answer["doc"]))
            messages = dfmt.render(answer["doc"])
            for i, message in enumerate(messages):
                last = i == len(messages) - 1
                await send(target, followup,
                           embeds=[disnake.Embed.from_dict(embed) for embed in message["embeds"]],
                           components=action_rows(answer["buttons"]) if last else [])
        else:
            print(answer["text"])
            contents = dfmt.text_messages(answer["text"])
            for i, content in enumerate(contents):
                if answer.get("image") and i == len(contents) - 1:
                    picture = disnake.Embed(color=dfmt.COLOR).set_image(url=answer["image"])
                    await send(target, followup, content=content, embed=picture)
                else:
                    await send(target, followup, content=content, flags=disnake.MessageFlags(suppress_embeds=True))


async def deliver_error(target: disnake.Message, followup=None):
    try:
        await deliver(target, [answers.Text(answers.ERROR_TEXT)], followup)
    except Exception as e:
        print(f"Could not send the error message: {e}")


# ── commands ───────────────────────────────────────────────────

async def update(message, text):
    await deliver(message, [answers.Text("Ide obnovjenje")])
    # (the download takes a while: not in the loop that keeps the bot connected)
    await asyncio.to_thread(isv.update_sheets, text.lower())
    await deliver(message, [answers.Text("Obnovjenje jest skončeno")])


async def dictionary(message, text):
    await deliver(message, await answers.dictionary(text))


async def wikipedia(message, text):
    await deliver(message, await answers.wikipedia(text))


async def fraznik(message, text):
    await deliver(message, answers.fraznik(text))


def lesson(name):
    async def handle(message, text):
        # the help is always in Latin; a lesson in the script of its command
        await deliver(message, answers.pouka(name, 'latin' if name == 'help' else text.split()[0]))
    return handle


ROUTES = {}
for _name in answers.DICTIONARY_COMMANDS:
    ROUTES[_name] = dictionary
for _name in answers.WIKI_COMMANDS:
    ROUTES[_name] = wikipedia
for _name in answers.FRAZNIK_COMMANDS:
    ROUTES[_name] = fraznik
for _name in answers.UPDATE_COMMANDS + ['update']:
    ROUTES[_name] = update
for _lesson, _names in answers.POUKY_COMMANDS.items():
    for _name in _names:
        ROUTES[_name] = lesson(_lesson)
for _name in ('pravila', 'правила'):
    ROUTES[_name] = lesson('pravila_discord')


def route_of(content: str):
    """(handler, text) for ".ru слово" and the like; None for anything else."""
    text = (content or "").strip().replace(' --public', '')  # (an old option of this bot)
    if len(text) < 2 or text[0] not in PREFIXES or text[1] in PREFIXES:
        return None
    name = re.sub(r'@.*$', '', text[1:].split(maxsplit=1)[0]).lower()
    handler = ROUTES.get(name)
    return (handler, text) if handler else None


@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot:
        return
    found = route_of(message.content)
    if not found:
        return
    handler, text = found
    try:
        async with message.channel.typing():
            await handler(message, text)
    except Exception as e:
        print(f"{text.split()[0]}: {type(e).__name__}: {e}")
        await deliver_error(message)


# ── the buttons under a word ───────────────────────────────────

def pressed_before(message_id: int, data: str) -> bool:
    now = time.monotonic()
    key = (message_id, data)
    if len(PRESSED) > 5000:
        for old in [k for k, at in PRESSED.items() if now - at > PRESSED_SECONDS]:
            PRESSED.pop(old, None)
    if now - PRESSED.get(key, -PRESSED_SECONDS) < PRESSED_SECONDS:
        return True
    PRESSED[key] = now
    return False


@bot.event
async def on_button_click(inter: disnake.MessageInteraction):
    data = inter.data.custom_id
    parsed = answers.parse_button(data)
    if parsed is None:
        return
    script = parsed[4]
    try:
        if pressed_before(inter.message.id, data):
            await inter.response.send_message(fmt.tr("Uže pokazano niže ↓", script), ephemeral=True)
            return
        await inter.response.defer()
        await deliver(inter.message, await answers.button(parsed), inter.followup)
    except Exception as e:
        print(f"button: {type(e).__name__}: {e}")
        await deliver_error(inter.message, inter.followup)


# ── start ──────────────────────────────────────────────────────

async def load_site_emoji():
    """The emoji before the interslavic.app link: DISCORD_SITE_EMOJI ("<:interslavic:123…>"), else the bot's own
    application emoji whose name has "interslavic" in it (Developer Portal → the app → Emojis), else 🏴."""
    chosen = os.getenv('DISCORD_SITE_EMOJI', '').strip()
    if not chosen and hasattr(bot, 'fetch_application_emojis'):
        try:
            emojis = await bot.fetch_application_emojis()
            found = next((e for e in emojis if 'interslavic' in e.name.lower()), None)
            chosen = str(found) if found else ''
        except Exception as e:
            print(f"Application emojis: {type(e).__name__}: {e}")
    if chosen:
        dfmt.SITE_EMOJI = chosen
    print(f"Site emoji: {dfmt.SITE_EMOJI}")


@bot.event
async def on_ready():
    await load_site_emoji()
    print("Bot jest gotovy")


if __name__ == "__main__":
    bot.run(settings['token_discord'])
