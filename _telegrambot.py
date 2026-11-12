import os
import re
import time
import asyncio
import aiohttp
from telebot.async_telebot import AsyncTeleBot
from telebot import asyncio_helper, types
import isv_tools as isv
import tg_format as fmt
import answers
from bot_config import *


bot = AsyncTeleBot(settings['token_telegram'])

# The Bot API server: Telegram's own, or a local one (TELEGRAM_API=http://localhost:8081)
TELEGRAM_API = os.getenv('TELEGRAM_API', 'https://api.telegram.org').rstrip('/')
asyncio_helper.API_URL = TELEGRAM_API + '/bot{0}/{1}'
ERROR_TEXT = answers.ERROR_TEXT


# ── sending ────────────────────────────────────────────────────
#
# Tables need a "rich message" (Bot API 10.1, June 2026: sendRichMessage). The bot
# tries that first and, when Telegram refuses it, sends the same answer as an
# ordinary message, so nobody is left without an answer:
#   rich, everything  →  rich, only headings / paragraphs / tables  →  ordinary HTML  →  bare text

class Rich:
    # RICH_MESSAGES=0 turns rich messages off
    level = 0 if os.getenv('RICH_MESSAGES', '1') == '0' else 2
    markdown = level > 0
    worked = set()
    session = None


async def call_rich(payload: dict):
    """sendRichMessage. Returns (sent, error code, description)."""
    if Rich.session is None or Rich.session.closed:
        Rich.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    url = f"{TELEGRAM_API}/bot{settings['token_telegram']}/sendRichMessage"
    try:
        async with Rich.session.post(url, json=payload) as response:
            data = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        return False, 0, f"{type(e).__name__}: {e}"
    if isinstance(data, dict) and data.get('ok'):
        return True, 200, ''
    data = data if isinstance(data, dict) else {}
    return False, data.get('error_code') or response.status, str(data.get('description') or '')


def where(message) -> dict:
    """The parameters that put an answer under `message`, in its topic."""
    params = {
        'chat_id': message.chat.id,
        'reply_parameters': {'message_id': message.message_id, 'allow_sending_without_reply': True},
    }
    if getattr(message, 'is_topic_message', None) and getattr(message, 'message_thread_id', None):
        params['message_thread_id'] = message.message_thread_id
    return params


def refused(kind: str, code: int, description: str):
    print(f"Telegram refused a rich message ({kind}): {code} {description}")


async def send_rich(message, rich_message: dict, mark, buttons=None):
    """One attempt at a rich message. `mark`: what to remember as working / not working."""
    payload = where(message)
    payload['rich_message'] = rich_message
    if buttons:
        payload['reply_markup'] = {'inline_keyboard': [
            [{'text': text, 'callback_data': data} for text, data in row] for row in buttons
        ]}
    sent, code, description = await call_rich(payload)
    if sent:
        Rich.worked.add(mark)
        return True
    refused(mark, code, description)
    if drop_site_emoji(description):
        return False
    if code == 404:
        # this Bot API server does not know rich messages at all
        Rich.level, Rich.markdown = 0, False
    elif code == 400 and mark not in Rich.worked:
        # never accepted: not this one answer's fault - stop trying this kind
        if mark == 'markdown':
            Rich.markdown = False
        else:
            Rich.level = min(Rich.level, mark - 1)
    return False


def keyboard(buttons):
    if not buttons:
        return None
    markup = types.InlineKeyboardMarkup()
    for row in buttons:
        markup.row(*[types.InlineKeyboardButton(text, callback_data=data) for text, data in row])
    return markup


async def send_doc(message, blocks, buttons=None):
    """An answer made of blocks (tg_format): as a rich message with real tables, else as ordinary messages."""
    print(fmt.render_plain(blocks))
    for level in (2, 1):
        for _ in range(2):  # (once more when Telegram refused only the custom emoji)
            had_emoji = fmt.SITE_EMOJI_ID
            if level <= Rich.level and await send_rich(message, {'html': fmt.render_rich(blocks, level)}, level, buttons):
                return True
            if not had_emoji or fmt.SITE_EMOJI_ID:
                break
    thread = getattr(message, 'message_thread_id', None) if getattr(message, 'is_topic_message', None) else None
    try:
        parts = fmt.render_classic(blocks)
        for i, part in enumerate(parts):
            await bot.send_message(
                message.chat.id, part, parse_mode='HTML', disable_web_page_preview=True,
                reply_to_message_id=message.message_id, allow_sending_without_reply=True,
                reply_markup=keyboard(buttons) if i == len(parts) - 1 else None, message_thread_id=thread)
        return True
    except Exception as e:
        print(f"Telegram refused the ordinary message: {e}")
        if drop_site_emoji(str(e)):
            return await send_doc(message, blocks, buttons)
    await bot.send_message(
        message.chat.id, fmt.render_plain(blocks), reply_to_message_id=message.message_id,
        allow_sending_without_reply=True, reply_markup=keyboard(buttons), message_thread_id=thread)
    return True


def markdown_v2(text: str) -> str:
    """The bot's Markdown (written for Discord) as Telegram's MarkdownV2."""
    text = text.replace("`.", "`/")
    text = text.replace("(", r"\(")
    text = text.replace(")", r"\)")

    #De-escape markdown links
    pattern = r'(?<=\])\\(\()(.+?)\\(\))'
    text = re.sub(pattern, lambda match: f'{match.group(1)}{match.group(2)}{match.group(3)}', text)

    text = text.replace(r'\*\*', '__TEMP__')
    text = text.replace(r'\*', r'\\_')
    text = text.replace(r'__TEMP__', '*')

    text = re.sub(r'^(#+)\s*(.+)', r'*\2*', text, flags=re.MULTILINE) # headers to bold

    text = text.replace("_", r"\_")
    text = text.replace("/", r"\/")
    text = text.replace(".", r"\.")
    text = text.replace("#", r"\#")
    text = text.replace("!", r"\!")
    text = text.replace("-", r"\-")
    text = text.replace("=", r"\=")

    text = text.replace("@Mašina", r"@mashina\_slovnik\_bot")
    return text


async def reply(message, text, is_disable=False, image=''):
    """One of the bot's Markdown texts (a note, a lesson) with the link to interslavic.app under it."""
    print(text)
    text = text.replace("<", "").replace(">", "")
    picture = image
    for _ in range(3):
        had_emoji = fmt.SITE_EMOJI_ID
        if not Rich.markdown:
            break
        if await send_rich(message, {'markdown': fmt.rich_markdown(text, picture)}, 'markdown'):
            return True
        if had_emoji and not fmt.SITE_EMOJI_ID:
            continue  # refused only the custom emoji: the same again without it
        if not picture:
            break
        picture = ''  # a picture Telegram cannot fetch refuses the whole message: once more without it
    try:
        picture = f"[​]({image})\n" if image else ''
        await bot.reply_to(message, picture + markdown_v2(text) + fmt.footer_markdown_v2(),
                           parse_mode="MarkdownV2", disable_web_page_preview=is_disable or not image)
    except Exception as e:
        print(f"Telegram refused the MarkdownV2 message: {e}")
        if drop_site_emoji(str(e)):
            return await reply(message, text, is_disable, image)
        await bot.reply_to(message, text + fmt.footer_plain(), disable_web_page_preview=True)
    return True


async def reply_error(message):
    try:
        await reply(message, ERROR_TEXT)
    except Exception as e:
        print(f"Could not send the error message: {e}")


# ── the dictionary ─────────────────────────────────────────────

@bot.message_handler(commands=answers.UPDATE_COMMANDS)
async def handle_update(message):
    try:
        await reply(message, "Ide obnovjenje")
        text = message.text.lower()
        isv.update_sheets(text)
        await reply(message, "Obnovjenje jest skončeno")
    except Exception as e:
        print(f"obnovi: {e}")
        await reply_error(message)


async def deliver(message, answers):
    """Sends what answers.py gave, one answer after another."""
    for answer in answers:
        if "doc" in answer:
            await send_doc(message, answer["doc"], answer["buttons"])
        else:
            await reply(message, answer["text"], image=answer["image"])


@bot.message_handler(commands=answers.DICTIONARY_COMMANDS)
async def handle_najdtislovo(message):
    try:
        await deliver(message, await answers.dictionary(message.text))
    except Exception as e:
        print(f"najdtislovo: {type(e).__name__}: {e}")
        await reply_error(message)


# ── the buttons under a word ───────────────────────────────────

PRESSED = {}  # (chat, message, button) → when: the same button is answered once
PRESSED_SECONDS = 600


def pressed_before(call) -> bool:
    now = time.monotonic()
    key = (call.message.chat.id, call.message.message_id, call.data)
    if len(PRESSED) > 5000:
        for old in [k for k, at in PRESSED.items() if now - at > PRESSED_SECONDS]:
            PRESSED.pop(old, None)
    if now - PRESSED.get(key, -PRESSED_SECONDS) < PRESSED_SECONDS:
        return True
    PRESSED[key] = now
    return False


@bot.callback_query_handler(func=lambda call: True)
async def handle_button(call):
    try:
        parsed = answers.parse_button(call.data)
        if call.message is None or parsed is None:
            await bot.answer_callback_query(call.id)
            return
        script = parsed[4]
        if pressed_before(call):
            await bot.answer_callback_query(call.id, text=fmt.tr("Uže pokazano niže ↓", script))
            return
        await bot.answer_callback_query(call.id)
        await deliver(call.message, await answers.button(parsed))
    except Exception as e:
        print(f"button: {type(e).__name__}: {e}")


# ── Wikipedia, the phrasebook, the lessons ─────────────────────

@bot.message_handler(commands=answers.WIKI_COMMANDS)
async def handle_wikipedia(message):
    try:
        await deliver(message, await answers.wikipedia(message.text))
    except Exception as e:
        print(f"wiki: {type(e).__name__}: {e}")
        await reply_error(message)


@bot.message_handler(commands=answers.FRAZNIK_COMMANDS)
async def handle_fraznik(message):
    try:
        await deliver(message, answers.fraznik(message.text))
    except Exception as e:
        print(f"fraznik: {type(e).__name__}: {e}")
        await reply_error(message)


def pouka_handler(name):
    async def handle(message):
        try:
            # the help is always in Latin; a lesson in the script of its command
            await deliver(message, answers.pouka(name, 'latin' if name == 'help' else message.text))
        except Exception as e:
            print(f"pouka {name}: {type(e).__name__}: {e}")
            await reply_error(message)
    return handle


for _name, _commands in answers.POUKY_COMMANDS.items():
    bot.register_message_handler(pouka_handler(_name), commands=_commands)


async def want_updates():
    """Tell Telegram which updates the bot reads: messages and, for the buttons under a word, callback
    queries. Asked once, directly: the setting is remembered, and nothing is taken from the queue."""
    if Rich.session is None or Rich.session.closed:
        Rich.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    url = f"{TELEGRAM_API}/bot{settings['token_telegram']}/getUpdates"
    try:
        async with Rich.session.post(url, json={
            'allowed_updates': ['message', 'callback_query'], 'timeout': 0, 'limit': 1,
        }) as response:
            await response.read()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"getUpdates: {type(e).__name__}: {e}")


# The emoji before the interslavic.app link: from the custom emoji pack t.me/addemoji/InterslavicApp.
# Bots may use custom emoji when their owner has Telegram Premium (Bot API 9.4); otherwise, or when the
# pack cannot be read, the link gets the ordinary 🏴. SITE_EMOJI_ID=<id> skips the lookup, SITE_EMOJI=0
# turns the custom emoji off.
SITE_EMOJI_SET = os.getenv('SITE_EMOJI_SET', 'InterslavicApp')


async def load_site_emoji():
    if os.getenv('SITE_EMOJI', '1') == '0':
        return
    if os.getenv('SITE_EMOJI_ID'):
        fmt.SITE_EMOJI_ID = os.getenv('SITE_EMOJI_ID')
        return
    if Rich.session is None or Rich.session.closed:
        Rich.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    url = f"{TELEGRAM_API}/bot{settings['token_telegram']}/getStickerSet"
    try:
        async with Rich.session.post(url, json={'name': SITE_EMOJI_SET}) as response:
            data = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        print(f"getStickerSet: {type(e).__name__}: {e}")
        return
    stickers = (data.get('result') or {}).get('stickers') or [] if isinstance(data, dict) else []
    stickers = [st for st in stickers if st.get('custom_emoji_id')]
    if not stickers:
        print(f"getStickerSet {SITE_EMOJI_SET}: no custom emoji ({data.get('description', '') if isinstance(data, dict) else data})")
        return
    chosen = next((st for st in stickers if st.get('emoji') == fmt.SITE_EMOJI), stickers[0])
    fmt.SITE_EMOJI_ID = chosen['custom_emoji_id']
    print(f"Site emoji: {fmt.SITE_EMOJI_ID} from {SITE_EMOJI_SET}")


def drop_site_emoji(description: str) -> bool:
    """Telegram refused the custom emoji (the bot may not use them): the plain one from now on."""
    if fmt.SITE_EMOJI_ID and 'emoji' in (description or '').lower():
        print("Telegram refused the custom emoji: using the plain one from now on")
        fmt.SITE_EMOJI_ID = None
        return True
    return False


async def main():
    await bot.remove_webhook()
    await want_updates()
    await load_site_emoji()
    await bot.polling(none_stop=True)
#    await bot.infinity_polling()

if __name__ == "__main__":
    print("Bot jest gotovy")
    asyncio.run(main())
