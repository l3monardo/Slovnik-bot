import os
import io
import re
import time
import asyncio
from collections import OrderedDict
from html import escape
import aiohttp
from telebot.async_telebot import AsyncTeleBot
from telebot import asyncio_helper, types
import isv_tools as isv
import tg_format as fmt
import answers
import slavformer as sf
import announce as an
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
    await an_offer(message)


@bot.message_handler(commands=answers.DICTIONARY_COMMANDS)
async def handle_najdtislovo(message):
    try:
        await deliver(message, await answers.dictionary(message.text))
    except Exception as e:
        print(f"najdtislovo: {type(e).__name__}: {e}")
        await reply_error(message)


# ── the Slavformer, the word game of interslavic.app (slavformer.py) ──

def sf_player(user, script: str = 'latn') -> sf.Player:
    name = ' '.join(filter(None, [user.first_name, user.last_name])) or user.username or ''
    return sf.Player('telegram', str(user.id), name, script)


def sf_markup(buttons):
    if not buttons:
        return None
    markup = types.InlineKeyboardMarkup()
    for row in buttons:
        markup.row(*[
            types.InlineKeyboardButton(label, url=data[4:]) if data.startswith('url:')
            else types.InlineKeyboardButton(label, callback_data=data)
            for label, data in row
        ])
    return markup


def topic_of(message):
    return message.message_thread_id if getattr(message, 'is_topic_message', None) else None


# "Napišite vaš komentar": the prompt's message → whose comment on which word (an answer to it is the comment)
SF_PROMPTS = OrderedDict()
SF_PROMPTS_MAX = 2000


async def sf_show(chat_id, screen, reply_to=None, thread=None, under=None, user=None):
    """A screen of the game: in place of the message `under` (its buttons were pressed) when it may, else new."""
    html = sf.to_html(screen)
    markup = sf_markup(screen.buttons)
    if screen.prompt and user is not None:
        # a comment: the reply to this message (in a group: only the one it names is asked)
        mention = f'<a href="tg://user?id={user.id}">{escape(user.first_name or user.username or "")}</a>, '
        sent = await bot.send_message(
            chat_id, html if chat_id == user.id else mention + html, parse_mode='HTML',
            reply_markup=types.ForceReply(selective=True, input_field_placeholder='Vaš komentar…'),
            reply_to_message_id=reply_to, allow_sending_without_reply=True, message_thread_id=thread)
        SF_PROMPTS[(chat_id, sent.message_id)] = (str(user.id), screen.prompt['word'])
        while len(SF_PROMPTS) > SF_PROMPTS_MAX:
            SF_PROMPTS.popitem(last=False)
        return
    if screen.photo:
        await bot.send_photo(chat_id, screen.photo, caption=html, parse_mode='HTML', reply_markup=markup,
                             reply_to_message_id=reply_to, allow_sending_without_reply=True, message_thread_id=thread)
    elif under is not None and screen.edit and under.content_type == 'text':
        try:
            await bot.edit_message_text(html, under.chat.id, under.message_id, parse_mode='HTML', reply_markup=markup,
                                        disable_web_page_preview=True)
        except Exception as e:
            if 'not modified' not in str(e):
                raise
    else:
        await bot.send_message(chat_id, html, parse_mode='HTML', reply_markup=markup, disable_web_page_preview=True,
                               reply_to_message_id=reply_to, allow_sending_without_reply=True,
                               message_thread_id=thread)
    for more in screen.extra:
        await sf_show(chat_id, more, thread=thread)


SF_ME = {'username': ''}


async def sf_username():
    if not SF_ME['username']:
        try:
            SF_ME['username'] = (await bot.get_me()).username or ''
        except Exception as e:
            print(f"getMe: {e}")
    return SF_ME['username']


@bot.message_handler(func=lambda message: (message.text or '').split()[:2] == ['/start', 'igra'])
@bot.message_handler(commands=sf.all_commands())
async def handle_slavformer(message):
    """/igra (/игра, /slavformer), /robot, /magazin, /lideri, /vyjdi — and the link t.me/<bot>?start=igra."""
    name = 'igra' if (message.text or '').startswith('/start') else sf.command_name(message.text)
    player = sf_player(message.from_user, fmt.script_of((message.text or '').split()[0]))
    try:
        screen = await sf.command(player, name)
        if screen.alert and not screen.lines:
            screen = sf.Screen([[screen.alert]])
        await sf_show(message.chat.id, screen, reply_to=message.message_id, thread=topic_of(message),
                      user=message.from_user)
    except Exception as e:
        print(f"slavformer {name}: {type(e).__name__}: {e}")
        await reply_error(message)


def sf_prompted(message) -> bool:
    replied = message.reply_to_message
    return replied is not None and (message.chat.id, replied.message_id) in SF_PROMPTS


@bot.message_handler(func=sf_prompted, content_types=['text'])
async def handle_slavformer_comment(message):
    """The answer to "Napišite vaš komentar": the comment, on the word's page on interslavic.app."""
    key = (message.chat.id, message.reply_to_message.message_id)
    owner, word = SF_PROMPTS[key]
    if str(message.from_user.id) != owner:
        return
    SF_PROMPTS.pop(key, None)
    script = 'cyrl' if re.search('[а-яёђјљњћџѣѧ]', message.reply_to_message.text or '', re.I) else 'latn'
    player = sf_player(message.from_user, script)
    try:
        screen = await sf.comment(player, word, message.text)
        await sf_show(message.chat.id, screen, reply_to=message.message_id, thread=topic_of(message))
    except Exception as e:
        print(f"slavformer comment: {type(e).__name__}: {e}")
        await reply_error(message)


@bot.callback_query_handler(func=lambda call: (call.data or '').startswith('sf:'))
async def handle_slavformer_button(call):
    parsed = sf.parse(call.data)
    if parsed is None or call.message is None:
        await bot.answer_callback_query(call.id)
        return
    owner, script, what = parsed
    player = sf_player(call.from_user, script)
    try:
        screen = await sf.press(player, owner, what)
        if screen.alert and not screen.lines and not screen.photo:
            await bot.answer_callback_query(call.id, text=screen.alert, show_alert=True)
            return
        chat = call.message.chat
        if screen.private and chat.type != 'private':
            # a link to one's own account: never in a group — in the private chat, if the player opened one
            try:
                await sf_show(call.from_user.id, screen)
                await bot.answer_callback_query(call.id, text=sf.tr("Svęz jest v osobnom čatu s botom.", player))
            except Exception:
                username = await sf_username()
                await bot.answer_callback_query(call.id, show_alert=True, text=sf.tr(
                    f"Najprvo napišite mi v osobnom čatu: t.me/{username}?start=igra", player))
            return
        await bot.answer_callback_query(call.id)
        await sf_show(chat.id, screen, thread=topic_of(call.message), under=call.message, user=call.from_user)
    except Exception as e:
        print(f"slavformer button: {type(e).__name__}: {e}")
        try:
            await bot.answer_callback_query(call.id, text=sf.tr("Ne udalo se — poprobujte znova.", player))
        except Exception:
            pass


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


# ── announcements from interslavic.app, /tandem (announce.py) ──

async def an_is_admin(chat, user, sender_chat=None) -> bool:
    """Whoever may change a chat's announcements: the person in their own chat, an admin of a group or channel."""
    if chat.type == 'private':
        return True
    # written in the chat's own name: an anonymous admin of a group, or a post in a channel
    if sender_chat is not None and sender_chat.id == chat.id:
        return True
    if user is None:
        return False
    try:
        member = await bot.get_chat_member(chat.id, user.id)
        return member.status in ('creator', 'administrator')
    except Exception as e:
        print(f"getChatMember: {type(e).__name__}: {e}")
        return False


def an_chat(message) -> dict:
    chat = message.chat
    return an.chat_fields(chat.id, chat.type, chat.title or chat.first_name or '', topic_of(message))


async def an_offer(message):
    """Once in a private chat's life: "do you want the news of interslavic.app here?" """
    try:
        chat = message.chat
        if await an.may_offer(chat.id, chat.type, chat.first_name or ''):
            command = (message.text or '').split()[0] if (message.text or '').startswith('/') else ''
            text, rows = an.offer_screen(fmt.script_of(command))
            await bot.send_message(chat.id, text, reply_markup=keyboard(rows))
    except Exception as e:
        print(f"offer: {type(e).__name__}: {e}")


@bot.channel_post_handler(commands=an.COMMANDS)
@bot.message_handler(commands=an.COMMANDS)
async def handle_announcements(message):
    """/obvestky: the chat's switches — a person's own, or (for an admin) a group's or a channel's."""
    script = fmt.script_of((message.text or '').split()[0])
    thread = topic_of(message)
    try:
        if not await an_is_admin(message.chat, message.from_user, getattr(message, 'sender_chat', None)):
            await bot.send_message(message.chat.id, fmt.tr(an.ADMINS_ONLY, script), message_thread_id=thread,
                                   reply_to_message_id=message.message_id, allow_sending_without_reply=True)
            return
        an._asked.add(message.chat.id)  # (whoever opened the switches needs no offer)
        prefs, _ = await an.chat_prefs(an_chat(message))
        if prefs is None:
            await bot.send_message(message.chat.id, an.say(an.NOT_REACHED, script), message_thread_id=thread)
            return
        text, rows = an.settings_screen(prefs, message.chat.type, script, bool(thread))
        await bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=keyboard(rows),
                               message_thread_id=thread)
    except Exception as e:
        print(f"obvestky: {type(e).__name__}: {e}")
        await reply_error(message)


@bot.callback_query_handler(func=lambda call: (call.data or '').startswith('an:'))
async def handle_announcements_button(call):
    parsed = an.parse_button(call.data)
    message = call.message
    try:
        if parsed is None or message is None:
            await bot.answer_callback_query(call.id)
            return
        action, arg, script = parsed
        if not await an_is_admin(message.chat, call.from_user):
            await bot.answer_callback_query(call.id, text=fmt.tr(an.ADMINS_ONLY, script), show_alert=True)
            return
        if action == 'no':
            await bot.answer_callback_query(call.id)
            await bot.edit_message_text(fmt.tr(an.OFFER_DECLINED, script), message.chat.id, message.message_id)
            return
        chat = an_chat(message)
        prefs = (await an.chat_prefs(chat))[0] if action == 'open' else await an.press(chat, action, arg)
        if prefs is None:
            await bot.answer_callback_query(call.id, text=an.say(an.NOT_REACHED, script), show_alert=True)
            return
        await bot.answer_callback_query(call.id)
        text, rows = an.settings_screen(prefs, message.chat.type, script, bool(topic_of(message)))
        try:
            await bot.edit_message_text(text, message.chat.id, message.message_id, parse_mode='HTML',
                                        reply_markup=keyboard(rows))
        except asyncio_helper.ApiTelegramException as e:
            if 'not modified' not in str(e):
                raise
    except Exception as e:
        print(f"obvestky button: {type(e).__name__}: {e}")


@bot.message_handler(commands=an.TANDEM_COMMANDS)
async def handle_tandem(message):
    """/tandem: who is looking for a language partner on interslavic.app."""
    try:
        script = fmt.script_of((message.text or '').split()[0])
        await deliver(message, [answers.Text(await an.tandem(script))])
    except Exception as e:
        print(f"tandem: {type(e).__name__}: {e}")
        await reply_error(message)


def an_gone(error) -> bool:
    """The bot cannot write there any more: blocked by the person, removed from the group, the chat is gone."""
    text = str(getattr(error, 'description', '') or error).lower()
    return getattr(error, 'error_code', 0) == 403 or 'chat not found' in text or 'deactivated' in text


# An announcement's picture as it is handed to Telegram, by the item's id: the bytes downloaded here (a picture
# of another site), then the id Telegram gave the file once one chat took it, or just its address.
an_pictures = {}


async def an_picture(item: dict):
    """The item's picture: (bytes, file name) to upload, or a string — an address or Telegram's id of the file."""
    key = item.get('id')
    if key not in an_pictures:
        url = item.get('image')
        found = url
        if url and not an.ours(url):
            found = await an.picture(url) or url
        if len(an_pictures) > 40:
            an_pictures.clear()
        an_pictures[key] = found
    return an_pictures[key]


async def an_send(chat: dict, item: dict) -> str:
    """One announcement to one chat: with its picture when it has one and Telegram takes it. A picture of another
    site is uploaded as a file with the first chat, and the others get it by the id Telegram gave it."""
    markup = types.InlineKeyboardMarkup()
    for text, url in an.buttons(item):
        markup.row(types.InlineKeyboardButton(text, url=url))
    where = dict(reply_markup=markup, message_thread_id=chat.get('thread') or None)
    for attempt in range(2):
        try:
            photo = await an_picture(item) if len(item['text']) <= 1000 else None
            if photo:
                uploaded = isinstance(photo, tuple)
                try:
                    if uploaded:
                        handed = io.BytesIO(photo[0])
                        handed.name = photo[1]
                    else:
                        handed = photo
                    message = await bot.send_photo(chat['id'], handed, caption=item['text'], parse_mode='HTML', **where)
                    if uploaded and getattr(message, 'photo', None):
                        an_pictures[item.get('id')] = message.photo[-1].file_id
                    return 'ok'
                except asyncio_helper.ApiTelegramException as e:
                    if an_gone(e) or e.error_code == 429:
                        raise
                    print(f"announcement {item.get('id')}: without its picture ({e.description})")
                    if uploaded and 'rights' not in str(e.description).lower():
                        # Telegram does not take the file itself: the other chats get the address to try
                        an_pictures[item.get('id')] = item.get('image')
            await bot.send_message(chat['id'], item['text'], parse_mode='HTML', disable_web_page_preview=True, **where)
            return 'ok'
        except asyncio_helper.ApiTelegramException as e:
            if an_gone(e):
                return 'gone'
            wait = ((e.result_json or {}).get('parameters') or {}).get('retry_after')
            if e.error_code == 429 and wait and attempt == 0:
                await asyncio.sleep(min(float(wait), 30) + 0.5)  # Telegram asks for a pause: once more after it
                continue
            print(f"announcement {item.get('id')} to {chat['id']}: {e.description}")
            return 'failed'
        except Exception as e:
            print(f"announcement {item.get('id')} to {chat['id']}: {type(e).__name__}: {e}")
            return 'failed'
    return 'failed'


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
    """Tell Telegram which updates the bot reads: messages, for the buttons under a word callback queries,
    and a channel's posts (its admin writes /obvestky there). Asked once, directly: the setting is remembered,
    and nothing is taken from the queue."""
    if Rich.session is None or Rich.session.closed:
        Rich.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    url = f"{TELEGRAM_API}/bot{settings['token_telegram']}/getUpdates"
    try:
        async with Rich.session.post(url, json={
            'allowed_updates': ['message', 'callback_query', 'channel_post'], 'timeout': 0, 'limit': 1,
        }) as response:
            await response.read()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"getUpdates: {type(e).__name__}: {e}")


async def set_menu_button():
    """The Menu button of the bot's private chats (left of the message field): the menu of interslavic.app inside
    Telegram — the dictionary, Tandem, the Slavformer, the whole site (announce.menu). When the site does not
    offer it, the button stays as it is. The commands are still listed when one types "/"."""
    try:
        me = await bot.get_me()
        menu = await an.menu(me.id)
        if not menu:
            return
        await bot.set_chat_menu_button(menu_button=types.MenuButtonWebApp(
            type='web_app', text=menu['text'], web_app=types.WebAppInfo(url=menu['url'])))
        print(f"Menu button: {menu['text']} → {menu['url']}")
    except Exception as e:  # the bot works without it
        print(f"Menu button: {type(e).__name__}: {e}")


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
    if not sf.BOT_SECRET:
        print("SLOVNIK_BOT_SECRET is not set: /igra (the Slavformer) will not reach interslavic.app")
    await want_updates()
    await load_site_emoji()
    await set_menu_button()
    announcing = asyncio.create_task(an.run(an_send))  # every minute: what is new on interslavic.app
    try:
        await bot.polling(none_stop=True)
    finally:
        announcing.cancel()
#    await bot.infinity_polling()

if __name__ == "__main__":
    print("Bot jest gotovy")
    asyncio.run(main())
