"""
What the bots answer: the same in Telegram (_telegrambot.py) and Discord (_disnake.py).

Every function here returns a list of answers, and each bot sends them its own way:
  {"doc": blocks, "buttons": rows}  - a document (tg_format blocks) with the buttons under it;
                                     rows are lists of (text, data)
  {"text": markdown, "image": url}  - one of the bot's own Markdown texts (a note, a lesson)

The bot's texts write commands with "/" (Telegram); the Discord bot shows them with ".".
"""
import os
import re

import yaml

import bots
import isv_tools as isv
import lang_detect
import site_api
import tg_format as fmt
import transliteration as transl
import wiki

# The spelling of declension and conjugation tables: "standard" (as interslavic.app shows them) or "etymological"
ORTHOGRAPHY = os.getenv('ISV_ORTHOGRAPHY', 'standard')

ERROR_TEXT = "Nažalj, moj programist ne primětil někaku pogrěšku. Mečtam o času, kogda roboti počnut pisati svoj kod sami."


def Doc(blocks, buttons=None) -> dict:
    return {"doc": blocks, "buttons": buttons or []}


def Text(text: str, image: str = "") -> dict:
    return {"text": text, "image": image}


def clean_command(text: str) -> str:
    """"/ru@mashina_slovnik_bot слово" (a command addressed to the bot in a group) → "/ru слово"."""
    return re.sub(r'^([/.][^\s@]+)@\S+', r'\1', (text or "").strip())


# ── the dictionary ─────────────────────────────────────────────

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


async def forms(card: dict, script: str) -> list:
    """The declension or conjugation of a word, as interslavic.app shows it."""
    if not fmt.forms_kind(card["isv"], card.get("partOfSpeech", "")):
        return [Doc(fmt.no_forms_doc(card, script))]
    # (the lists of proposed words mark some entries with "#" or "!")
    word = card["isv"].replace("#", "").replace("!", "").strip()
    data = await site_api.word_forms(word, card.get("addition", ""), card["partOfSpeech"], script, ORTHOGRAPHY)
    if data is None:
        return [Doc(fmt.error_doc(fmt.tr("Ne mogu dostati tabelu iz slovnika. Poprobuj pozdněje.", script)))]
    if not data.get("sections"):
        return [Doc(fmt.no_forms_doc(card, script))]
    return [Doc(fmt.forms_doc(card, data, script))]


async def explanation(card: dict, lang: str, script: str) -> list:
    """What the word means (the definitions interslavic.app shows, from slovosbor.online)."""
    data = await site_api.explanation(card["id"], card["isv"])
    if data is None:
        return [Doc(fmt.error_doc(fmt.tr("Ne mogu dostati objasnjenje iz slovnika. Poprobuj pozdněje.", script)))]
    return [Doc(fmt.explanation_doc(card, data, lang, script))]


async def word(item: dict, script: str) -> list:
    """A word: its card with the statistics and the buttons."""
    card = item["card"]
    stats = await site_api.intelligibility(card["id"], card["isv"]) if card["sheet"] == "words" else None
    return [Doc(fmt.word_doc(card, script, stats), fmt.word_buttons(card, script))]


async def search_item(item, script: str) -> list:
    """One answer of the search."""
    if not isinstance(item, dict):
        return [Text(str(item))]
    kind = item.get("kind")
    if kind == "word":
        return await word(item, script)
    if kind == "list":
        return [Doc(fmt.list_doc(item, script))]
    if kind == "phrase":
        return [Doc(fmt.phrase_doc(item))]
    if kind == "wiki":
        doc = fmt.lines_doc(item["text"])
        if doc:
            return [Doc(doc)]
    return [Text(item.get("text", ""))]


async def dictionary(text: str) -> list:
    """"/ru бегать", "/ru бегать спр", "/id 474 skl" …"""
    text = clean_command(text)
    if ' ' not in text:
        return [Text("Priměr korektnogo prikaza: `/pl kurva`")]
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
            answers = []
            for card in wanted:
                answers += await forms(card, script)
            return answers

    answers = []
    for item in results:
        answers += await search_item(item, script)
    if forms_kind and any(isinstance(item, dict) and item.get("kind") == "list" for item in results):
        answers.append(Text("Da by uviděti tabelu jednogo slova, napiši jego ID: `/id 474 skl` ili `/id 474 spr`"))
    return answers


# ── the buttons under a word ───────────────────────────────────

def parse_button(data: str):
    """"f:w:474:ru:l" → ("f", "w", "474", "ru", "latn"); None for anything else.
    f: the forms, e: the explanation; w/s/l/c: the sheet (fmt.SHEET_CODES); l/c: Latin or Cyrillic."""
    parts = (data or '').split(':')
    if len(parts) != 5 or parts[0] not in ('f', 'e'):
        return None
    return parts[0], parts[1], parts[2], parts[3], 'cyrl' if parts[4] == 'c' else 'latn'


async def button(parsed) -> list:
    what, sheet_code, word_id, lang, script = parsed
    sheet = fmt.SHEET_NAMES.get(sheet_code)
    row = isv.find_by_id(word_id, sheet) if sheet else None
    if row is None:
        return [Doc(fmt.error_doc(fmt.tr("Togo slova uže nema v slovniku.", script)))]
    card = isv.card_data(row, sheet, lang)
    if what == 'f':
        return await forms(card, script)
    return await explanation(card, lang, script)


# ── Wikipedia, the phrasebook, the lessons ─────────────────────

async def wikipedia(text: str) -> list:
    """"/wiki be Вайна з эму" (titles in other languages), "/wiki_summary ru собака"."""
    text = clean_command(text)
    if len(text.split(maxsplit=2)) < 3:
        return [Text("Priměr korektnogo prikaza: `/wiki be Вайна з эму`")]
    lang, slova = bots.command_splitter(text, 2)
    if lang not in wiki.SUPPORTED_WIKIS:
        return [Text("Ne znajemy jezyk")]
    command = text.split(maxsplit=1)[0]
    if "wiki2" in command or "wiki_summary" in command:
        result = await wiki.wiki_summary(lang, slova)
    else:
        result = await wiki.wiki_titles(lang, slova)
    if result:
        doc = fmt.lines_doc(result)
        return [Doc(doc)] if doc else [Text(result)]
    return [Text(f"V Wikipediji nema teksta o prědmetu `{slova}`, ili on ne imaje prěvody na druge jezyky. "
                 f"Gledati v naših slovnikah: `/{lang} {slova}`")]


def fraznik(text: str) -> list:
    """"/fraznik en today"."""
    text = clean_command(text)
    if len(text.split(maxsplit=2)) < 3:
        return [Text("Priměr korektnogo prikaza: `/fraznik en today`")]
    lang, slova = bots.command_splitter(text, 2)
    result = isv.search_in_phrasebook(slova, lang)
    if result.is_empty():
        return [Text(text) for text in isv.phrasebook(slova, lang)]
    return [Doc(fmt.phrase_doc(isv.phrasebook_card(i, result, with_meta=True))) for i in range(len(result))]


with open('pouky.yaml', encoding="UTF-8") as fh:
    POUKY = yaml.load(fh, Loader=yaml.FullLoader)


def pouka(name: str, command: str) -> list:
    """A lesson - in Latin when the command was typed in Latin - with its picture."""
    text = POUKY[str(name)]["text"]
    if lang_detect.checkalphabet(command) == 'latin':
        text = transl.transliteration2(text, 'kir_to_lat')
    return [Text(text, POUKY[str(name)].get("image", ""))]


# Lesson commands: the lesson's name → the commands that show it (without "/" or ".")
POUKY_COMMANDS = {
    'help': ['start', 'help', 'pomoč', 'помоч'],
    'pouka1': ['pouka1', 'поука1', 'линкы', 'линкы1', 'транслитератор', 'граматика', 'linky', 'linky1',
               'transliterator', 'gramatika'],
    'pouka2': ['pouka2', 'поука2', 'линкы2', 'linky2'],
    'pouka3': ['pouka3', 'поука3', 'пасивно_ученје', 'pasivno_učenje'],
    'pouka4': ['pouka4', 'поука4', 'како_учити', 'kako_učiti'],
    'pouka5': ['pouka5', 'поука5', 'словник1', 'словник', 'slovnik1', 'slovnik'],
    'pouka6': ['pouka6', 'поука6', 'словник2', 'slovnik2'],
    'pouka7': ['pouka7', 'поука7', 'о_фразнику', 'o_frazniku'],
    'pouka8': ['pouka8', 'поука8', 'о_боту', 'o_botu'],
    'pouka9': ['pouka9', 'поука9', 'keyboards', 'клавиатуры', 'klaviatury'],
}

DICTIONARY_COMMANDS = ['id', 'isv', 'мс', 'ms', 'ru', 'be', 'uk', 'ua', 'pl', 'cs', 'cz', 'sk', 'bg', 'mk',
                       'sr', 'hr', 'sl', 'ру', 'бе', 'ук', 'бг', 'мк', 'ср', 'en', 'de', 'nl', 'eo']
WIKI_COMMANDS = ['wiki', 'wiki1', 'wiki2', 'wiki_summary']
FRAZNIK_COMMANDS = ['fraznik', 'фразник']
UPDATE_COMMANDS = ['obnovi', 'обнови']
