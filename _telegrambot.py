import os
import re
import time
import asyncio
import yaml
import aiohttp
from telebot.async_telebot import AsyncTeleBot
from telebot import asyncio_helper, types
import lang_detect
import wiki
import transliteration as transl
import isv_tools as isv
import bots
import site_api
import tg_format as fmt
from bot_config import *


bot = AsyncTeleBot(settings['token_telegram'])

# The Bot API server: Telegram's own, or a local one (TELEGRAM_API=http://localhost:8081)
TELEGRAM_API = os.getenv('TELEGRAM_API', 'https://api.telegram.org').rstrip('/')
asyncio_helper.API_URL = TELEGRAM_API + '/bot{0}/{1}'
# The spelling of declension and conjugation tables: "standard" (as interslavic.app shows them) or "etymological"
ORTHOGRAPHY = os.getenv('ISV_ORTHOGRAPHY', 'standard')

ERROR_TEXT = "Nažalj, moj programist ne primětil někaku pogrěšku. Mečtam o času, kogda roboti počnut pisati svoj kod sami."


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

@bot.message_handler(commands=['obnovi', 'обнови'])
async def handle_update(message):
    try:
        await reply(message, "Ide obnovjenje")
        text = message.text.lower()
        isv.update_sheets(text)
        await reply(message, "Obnovjenje jest skončeno")
    except Exception as e:
        print(f"obnovi: {e}")
        await reply_error(message)


# "/ru бегать спр", "/ru жираф decl": the word's table of forms instead of its translations.
# Letters that look the same in both alphabets count as the same ("сonj" typed with a Cyrillic с).
LOOKALIKES = str.maketrans("асеорхуіјк", "aceopxyijk")
FORMS_WORDS = {
    word.translate(LOOKALIKES): (kind, fmt.script_of(word)) for word, kind in {
        'conj': 'conjugation', 'spr': 'conjugation', 'спр': 'conjugation',
        'decl': 'declension', 'skl': 'declension', 'скл': 'declension',
    }.items()
}


def split_forms_word(slova: str):
    """("бегать спр") → ("бегать", "conjugation", "cyrl": the keyword's script); (words, None, "latn") without one."""
    parts = slova.rsplit(maxsplit=1)
    if len(parts) == 2:
        found = FORMS_WORDS.get(parts[1].lower().translate(LOOKALIKES))
        if found:
            return parts[0], found[0], found[1]
    return slova, None, 'latn'


async def send_forms(message, card: dict, script: str):
    """The declension or conjugation of a word, as interslavic.app shows it."""
    if not fmt.forms_kind(card["isv"], card.get("partOfSpeech", "")):
        return await send_doc(message, fmt.no_forms_doc(card, script))
    # (the lists of proposed words mark some entries with "#" or "!")
    word = card["isv"].replace("#", "").replace("!", "").strip()
    forms = await site_api.word_forms(word, card.get("addition", ""), card["partOfSpeech"], script, ORTHOGRAPHY)
    if forms is None:
        text = fmt.tr("Ne mogu dostati tabelu iz slovnika. Poprobuj pozdněje.", script)
        return await send_doc(message, fmt.error_doc(text))
    if not forms.get("sections"):
        return await send_doc(message, fmt.no_forms_doc(card, script))
    return await send_doc(message, fmt.forms_doc(card, forms, script))


async def send_explanation(message, card: dict, lang: str, script: str):
    """What the word means (the definitions interslavic.app shows, from slovosbor.online)."""
    data = await site_api.explanation(card["id"], card["isv"])
    if data is None:
        text = fmt.tr("Ne mogu dostati objasnjenje iz slovnika. Poprobuj pozdněje.", script)
        return await send_doc(message, fmt.error_doc(text))
    return await send_doc(message, fmt.explanation_doc(card, data, lang, script))


async def send_word(message, item: dict, script: str):
    """A word: its card with the statistics and the buttons."""
    card = item["card"]
    stats = await site_api.intelligibility(card["id"], card["isv"]) if card["sheet"] == "words" else None
    await send_doc(message, fmt.word_doc(card, script, stats), fmt.word_buttons(card, script))


async def send_item(message, item, script: str):
    """One answer of the search."""
    if not isinstance(item, dict):
        return await reply(message, str(item), is_disable=True)
    kind = item.get("kind")
    if kind == "word":
        return await send_word(message, item, script)
    if kind == "list":
        return await send_doc(message, fmt.list_doc(item, script))
    if kind == "phrase":
        return await send_doc(message, fmt.phrase_doc(item))
    if kind == "wiki":
        doc = fmt.lines_doc(item["text"])
        if doc:
            return await send_doc(message, doc)
    return await reply(message, item.get("text", ""), is_disable=True)


@bot.message_handler(commands=['id', 'isv', 'мс', 'ms', 'ru', 'be', 'uk', 'ua', 'pl', 'cs', 'cz', 'sk', 'bg',
                               'mk', 'sr', 'hr', 'sl', 'ру', 'бе', 'ук', 'бг', 'мк', 'ср', 'en', 'de', 'nl', 'eo'])
async def handle_najdtislovo(message):
    try:
        # "/ru@mashina_slovnik_bot слово" in a group
        text = re.sub(r'^(/[^\s@]+)@\S+', r'\1', message.text.strip())
        if ' ' not in text:
            await reply(message, "Priměr korektnogo prikaza: `/pl kurva`", is_disable=True)
            return
        command = text.split(maxsplit=1)[0]
        lang, slova = bots.command_splitter(text, 1)
        slova, forms_kind, word_script = split_forms_word(slova)
        script = 'cyrl' if 'cyrl' in (fmt.script_of(command), word_script) else 'latn'
        results = await isv.mashina_search(slova, lang, with_meta=True)

        if forms_kind:
            cards = [item["card"] for item in results if isinstance(item, dict) and item.get("kind") == "word"]
            if cards:
                kinds = [fmt.forms_kind(card["isv"], card.get("partOfSpeech", "")) for card in cards]
                # the kind that was asked for; any table when the word has only the other kind
                wanted = [card for card, kind in zip(cards, kinds) if kind == forms_kind] \
                    or [card for card, kind in zip(cards, kinds) if kind] or cards[:1]
                for card in wanted:
                    await send_forms(message, card, script)
                return

        for item in results:
            await send_item(message, item, script)
        if forms_kind and any(isinstance(item, dict) and item.get("kind") == "list" for item in results):
            await reply(message, "Da by uviděti tabelu jednogo slova, napiši jego ID: `/id 474 skl` ili `/id 474 spr`",
                        is_disable=True)
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
        data = (call.data or '').split(':')
        if call.message is None or data[0] not in ('f', 'e') or len(data) != 5:
            await bot.answer_callback_query(call.id)
            return
        script = 'cyrl' if data[4] == 'c' else 'latn'
        if pressed_before(call):
            await bot.answer_callback_query(call.id, text=fmt.tr("Uže pokazano niže ↓", script))
            return
        await bot.answer_callback_query(call.id)

        # f:<sheet>:<id>:<lang>:<l|c> - the forms;  e:w:<id>:<lang>:<l|c> - the explanation
        sheet = fmt.SHEET_NAMES.get(data[1])
        row = isv.find_by_id(data[2], sheet) if sheet else None
        if row is None:
            await send_doc(call.message, fmt.error_doc(fmt.tr("Togo slova uže nema v slovniku.", script)))
            return
        card = isv.card_data(row, sheet, data[3])
        if data[0] == 'f':
            await send_forms(call.message, card, script)
        else:
            await send_explanation(call.message, card, data[3], script)
    except Exception as e:
        print(f"button: {type(e).__name__}: {e}")


# ── Wikipedia, the phrasebook, the lessons ─────────────────────

@bot.message_handler(commands=['wiki', 'wiki1', 'wiki2', 'wiki_summary'])
async def handle_wikipedia(message):
    try:
        text = re.sub(r'^(/[^\s@]+)@\S+', r'\1', message.text.strip())
        if len(text.split(maxsplit=2)) < 3:
            await reply(message, "Priměr korektnogo prikaza: `/wiki be Вайна з эму`", is_disable=True)
            return

        lang, slova = bots.command_splitter(text, 2)

        if lang not in wiki.SUPPORTED_WIKIS:
            await reply(message, "Ne znajemy jezyk")
            return

        if "wiki2" in text or "wiki_summary" in text:
            result = await wiki.wiki_summary(lang, slova)
        else:
            result = await wiki.wiki_titles(lang, slova)

        if result:
            doc = fmt.lines_doc(result)
            if doc:
                await send_doc(message, doc)
            else:
                await reply(message, result)
            return
        noresult = f"V Wikipediji nema teksta o prědmetu `{slova}`, ili on ne imaje prěvody na druge jezyky. Gledati v naših slovnikah: `.{lang} {slova}`"
        await reply(message, noresult)
    except Exception as e:
        print(f"wiki: {type(e).__name__}: {e}")
        await reply_error(message)

with open('pouky.yaml', encoding="UTF-8") as fh:
    pouky_data = yaml.load(fh, Loader=yaml.FullLoader)

def pouka_render(pouky_data, name, command):
    """The text of a lesson - in Latin when the command was typed in Latin - and its picture ('' without one)."""
    name = str(name)
    result = pouky_data[name]["text"]
    if lang_detect.checkalphabet(command) == 'latin':
        result = transl.transliteration2(result, 'kir_to_lat')
    return result, pouky_data[name].get("image", "")

async def send_pouka(message, name, command):
    try:
        text, image = pouka_render(pouky_data, name, command)
        await reply(message, text, image=image)
    except Exception as e:
        print(f"pouka {name}: {type(e).__name__}: {e}")
        await reply_error(message)

@bot.message_handler(commands=['fraznik', 'фразник'])
async def handle_fraznik(message):
    try:
        text = re.sub(r'^(/[^\s@]+)@\S+', r'\1', message.text.strip())
        if len(text.split(maxsplit=2)) < 3:
            await reply(message, "Priměr korektnogo prikaza: `/fraznik en today`", is_disable=True)
            return
        lang, slova = bots.command_splitter(text, 2)

        result = isv.search_in_phrasebook(slova, lang)
        if result.is_empty():
            for text in isv.phrasebook(slova, lang):
                await reply(message, text, is_disable=True)
            return
        for i in range(0, len(result)):
            await send_doc(message, fmt.phrase_doc(isv.phrasebook_card(i, result, with_meta=True)))
    except Exception as e:
        print(f"fraznik: {type(e).__name__}: {e}")
        await reply_error(message)



@bot.message_handler(commands=['start','help', 'pomoč', 'помоч'])
async def handle_help(message):
    await send_pouka(message, "help", "latin")

@bot.message_handler(commands=['pouka1', 'поука1', 'линкы', 'линкы1', 'транслитератор', 'граматика', 'linky', 'linky1', 'transliterator', 'gramatika'])
async def handle_pouka1(message):
    await send_pouka(message, "pouka1", message.text)

@bot.message_handler(commands=['pouka2', 'поука2', 'линкы2', 'linky2'])
async def handle_pouka2(message):
    await send_pouka(message, "pouka2", message.text)

@bot.message_handler(commands=['pouka3', 'поука3', 'пасивно_ученје', 'pasivno_učenje'])
async def handle_pouka3(message):
    await send_pouka(message, "pouka3", message.text)

@bot.message_handler(commands=['pouka4', 'поука4', 'како_учити', 'kako_učiti'])
async def handle_pouka4(message):
    await send_pouka(message, "pouka4", message.text)

@bot.message_handler(commands=['pouka5', 'поука5', 'словник1', 'словник', 'slovnik1', 'slovnik'])
async def handle_pouka5(message):
    await send_pouka(message, "pouka5", message.text)

@bot.message_handler(commands=['pouka6', 'поука6', 'словник2', 'slovnik2'])
async def handle_pouka6(message):
    await send_pouka(message, "pouka6", message.text)

@bot.message_handler(commands=['pouka7', 'поука7', 'о_фразнику', 'o_frazniku'])
async def handle_pouka7(message):
    await send_pouka(message, "pouka7", message.text)

@bot.message_handler(commands=['pouka8', 'поука8', 'о_боту', 'o_botu'])
async def handle_pouka8(message):
    await send_pouka(message, "pouka8", message.text)

@bot.message_handler(commands=['pouka9', 'поука9', 'keyboards', 'клавиатуры', 'klaviatury'])
async def handle_pouka9(message):
    await send_pouka(message, "pouka9", message.text)


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
