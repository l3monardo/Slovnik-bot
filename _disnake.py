"""
The Discord bot: the same answers as the Telegram bot (answers.py), shown as embeds (dc_format.py).

Commands start with "." (".ru бегать", ".ru бегать spr", ".id 474 skl", ".wiki be …", ".fraznik en …"),
"/" works too. The buttons under a word show its declension or conjugation and its explanation.

Needs DISCORD_TOKEN and, in the Discord Developer Portal, the "Message Content" intent of the bot.
"""
import asyncio
import io
import os
import re
import time

import disnake

import answers
import dc_format as dfmt
import isv_tools as isv
import slavformer as sf
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


# ── the Slavformer, the word game of interslavic.app (slavformer.py) ──

def sf_player(user, script: str = 'latn') -> sf.Player:
    return sf.Player('discord', str(user.id), getattr(user, 'display_name', '') or user.name, script)


def sf_rows(buttons):
    """A screen's buttons as Discord components: at most 5 rows of 5 — more rows are put together, the shortest
    neighbours first (the answers, one a row in Telegram, share rows here)."""
    packed = [list(row) for row in (buttons or [])]
    while len(packed) > 5:
        sizes = [(len(packed[i]) + len(packed[i + 1]), i) for i in range(len(packed) - 1)]
        size, i = min(sizes)
        if size > 5:
            break
        packed[i:i + 2] = [packed[i] + packed[i + 1]]
    rows = []
    for row in packed[:5]:
        rows.append(disnake.ui.ActionRow(*[
            disnake.ui.Button(label=label[:80], url=data[4:], style=disnake.ButtonStyle.link) if data.startswith('url:')
            else disnake.ui.Button(label=label[:80], custom_id=data[:100], style=disnake.ButtonStyle.secondary)
            for label, data in row[:5]
        ]))
    return rows


def sf_message(screen) -> dict:
    """What disnake's send / edit takes for a screen."""
    message = {'content': sf.to_markdown(screen)[:2000] or '\u200b', 'components': sf_rows(screen.buttons)}
    if screen.photo:
        message['file'] = disnake.File(io.BytesIO(screen.photo), filename='slavformer.png')
    return message


async def slavformer_command(message, text):
    """.igra (.игра, .slavformer), .robot, .magazin, .lideri, .vyjdi"""
    first = text.split()[0]
    player = sf_player(message.author, fmt.script_of(first))
    screen = await sf.command(player, first[1:].lower())
    if screen.alert and not screen.lines:
        screen = sf.Screen([[screen.alert]])
    await send(message, None, **sf_message(screen))
    for more in screen.extra:
        await message.channel.send(**sf_message(more))


async def slavformer_button(inter: disnake.MessageInteraction, parsed):
    owner, script, what = parsed
    player = sf_player(inter.author, script)
    # (the leaders are anyone's to look at)
    if owner != player.id and what[0] != 'l':
        await inter.response.send_message(sf.not_yours(player).alert, ephemeral=True)
        return
    if what[0] == 'k' and len(what) > 1:
        # "Napišite vaš komentar": a form — the first answer to the press, before anything else
        word = sf.comment_title(player, what[1])
        await inter.response.send_modal(
            title=sf.tr('Napišite vaš komentar', player)[:45],
            custom_id=sf.data(player, 'k', what[1])[:100],
            components=[disnake.ui.TextInput(
                label=(word or sf.tr('Komentar', player))[:45], custom_id='body',
                style=disnake.TextInputStyle.paragraph, max_length=sf.COMMENT_MAX,
                placeholder=sf.tr('Komentar bude viden pod slovom na interslavic.app.', player)[:100])])
        return
    await inter.response.defer()
    screen = await sf.press(player, owner, what)
    if screen.alert and not screen.lines and not screen.photo:
        await inter.followup.send(screen.alert, ephemeral=True)
        return
    if screen.private:
        # a link to one's own account: only for the player's eyes
        await inter.followup.send(ephemeral=True, **sf_message(screen))
    elif screen.edit and not screen.photo and not inter.message.attachments:
        await inter.edit_original_message(**sf_message(screen))
    else:
        await inter.followup.send(**sf_message(screen))
    for more in screen.extra:
        await inter.followup.send(**sf_message(more))


@bot.event
async def on_modal_submit(inter: disnake.ModalInteraction):
    """The form "Napišite vaš komentar": the comment, on the word's page on interslavic.app."""
    parsed = sf.parse(inter.custom_id)
    if parsed is None or parsed[2][:1] != ['k'] or len(parsed[2]) < 2:
        return
    owner, script, what = parsed
    player = sf_player(inter.author, script)
    if owner != player.id:
        await inter.response.send_message(sf.not_yours(player).alert, ephemeral=True)
        return
    await inter.response.defer()
    try:
        screen = await sf.comment(player, what[1], inter.text_values.get('body', ''))
        await inter.followup.send(**sf_message(screen))
    except Exception as e:
        print(f"slavformer comment: {type(e).__name__}: {e}")


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
for _name in sf.all_commands():
    ROUTES[_name] = slavformer_command


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
    game = sf.parse(data)
    if game is not None:
        try:
            await slavformer_button(inter, game)
        except Exception as e:
            print(f"slavformer button: {type(e).__name__}: {e}")
        return
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
    if not sf.BOT_SECRET:
        print("SLOVNIK_BOT_SECRET is not set: .igra (the Slavformer) will not reach interslavic.app")
    print("Bot jest gotovy")


if __name__ == "__main__":
    bot.run(settings['token_discord'])
