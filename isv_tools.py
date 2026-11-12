import asyncio
import os
import re
import polars as pl
from rapidfuzz import fuzz, process
import bots
import transliteration as transl
import lang_detect
import lemmatizer
import wiki
import urllib.parse

sheet_links = {
  'words': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRsEDDBEt3VXESqAgoQLUYHvsA5yMyujzGViXiamY7-yYrcORhrkEl5g6JZPorvJrgMk6sjUlFNT4Km/pub?output=csv',
  'Cognates': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRz8l3w4h--36bUS-5plpkkVLnSFmCPIB3WnpDYRer87eirVVMYfI-ZDbp3WczyL2G5bOSXKty2MpOY/pub?gid=86109375&single=true&output=csv',
  'Wiki list': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRz8l3w4h--36bUS-5plpkkVLnSFmCPIB3WnpDYRer87eirVVMYfI-ZDbp3WczyL2G5bOSXKty2MpOY/pub?gid=281935577&single=true&output=csv',
  'suggestions': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vS8scL0kxJY7rgLC-2iaG_XmbOI72sbfmd63YhcvuFgc9KDDFpRyvIWwfcr6yHxE7Uk0coCaePfozL-/pub?gid=1226657383&single=true&output=csv',
  'fraznik': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vTIevV03tPoLIILAx4DqHH6QetiiYb13xMiQ7HMvvleWLjveoJ6uayNIDLd0cKUMj9TtNsl2XDsZR8w/pub?gid=0&single=true&output=csv',
#   'CogNet': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRz8l3w4h--36bUS-5plpkkVLnSFmCPIB3WnpDYRer87eirVVMYfI-ZDbp3WczyL2G5bOSXKty2MpOY/pub?gid=1725053439&single=true&output=csv',
}

fraznik_link = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vTIevV03tPoLIILAx4DqHH6QetiiYb13xMiQ7HMvvleWLjveoJ6uayNIDLd0cKUMj9TtNsl2XDsZR8w/pub?gid=0&single=true&output=csv',
sheets = {key: False for key in sheet_links.keys()}
columns = [ 'id', 'isv', 'addition', 'partOfSpeech', 'en', 'ru', 'be', 'uk', 'pl', 'cs', 'sk', 'bg', 'mk', 'sr', 'hr', 'sl', 'frequency', 'intelligibility']
# columns added later: a file saved before them is downloaded again (see load_sheet)
new_columns = {'words': ['addition', 'intelligibility']}
langs = "isv en ru uk be pl cs sk bg mk sr hr sl".split(' ')

brackets_regex1 = re.compile( r" \(.*\)" )
brackets_regex2 = re.compile( r" \[.*\]" )


def cell_normalization(cell: str, lang: str) -> str:
    cell = cell.replace( '!', '').replace( '#', '')
    cell = re.sub(brackets_regex1, "", cell)
    cell = re.sub(brackets_regex2, "", cell)
    cell = cell.lower()
    cell = cell.strip()
    cell = transl.transliteration(cell, lang)
    return cell


def prepare_slovnik(sheet, sheetname: str):
    if sheetname == 'fraznik':
        sheet = sheet.with_columns([
            (sheet['Vse varianty v MS'].map_elements(lambda x: cell_normalization(x, 'isv'), return_dtype=pl.Utf8)).alias(f'isv')
        ])
        return sheet
    for lang in langs:
        print(lang)
        sheet = sheet.with_columns([
            (sheet[lang].map_elements(lambda x: cell_normalization(x, lang), return_dtype=pl.Utf8)).alias(f'{lang}_normalized')
        ])
    sheet = sheet.with_columns(pl.Series(name="index", values=range(1, len(sheet) + 1))) 
    return sheet


def load_sheet(tabela_name: str, update: bool):
    tabela_name_parquet = tabela_name+".parquet"
    if update or not os.path.isfile(tabela_name_parquet):
        print(f'Sheet {tabela_name} is downloading ...')
        # every column as text (naming the text columns one by one fails when a sheet lacks some of them)
        df = pl.read_csv(sheet_links[tabela_name], separator=",", ignore_errors=True, infer_schema_length=0 ).fill_null(' ')
        if tabela_name != 'fraznik': 
            cols = [i for i in df.columns if (i in columns) ]
            df = df.select(cols)
        for column in new_columns.get(tabela_name, []):
            if column not in df.columns:
                df = df.with_columns(pl.lit(' ').alias(column))
        df = prepare_slovnik(df, tabela_name)      
        df.write_parquet(tabela_name_parquet)
        return df
    print( f"Found {tabela_name_parquet} file, using it")
    df = pl.read_parquet(tabela_name_parquet)
    missing = [c for c in new_columns.get(tabela_name, []) if c not in df.columns]
    if missing:
        # the saved file is from before these columns were used: get the sheet again,
        # and go on with the old file when that is not possible right now
        print(f"{tabela_name_parquet} has no {', '.join(missing)}: downloading the sheet again ...")
        try:
            return load_sheet(tabela_name, True)
        except Exception as e:
            print(f"Could not download {tabela_name}: {e}")
    return df

def load_all_sheets(sheet_names=sheets.keys(), update=False):
    for sheetname in sheet_names:
        sheets[sheetname] = load_sheet(sheetname, update)
    return sheets


sheets = load_all_sheets()
sheets['words']['isv_normalized']



def update_sheets(text: str):
    global sheets
    text = transl.transliteration(text, 'kir_to_lat')
    sheets_to_update = [s for s in sheet_links.keys() if (s.lower() in text)]
    if not sheets_to_update:
        sheets = load_all_sheets(update=True)
        return True
    for sheetname in sheets_to_update:
        print(f"Dostava tabely {sheetname}...")
        sheets[sheetname] = load_sheet(sheetname, True)
    print("Obnovjenje jest skončeno")
    return True


# update_sheets("obnovi Cognates", sheet_links, sheets)



card_languages = "en ru be uk pl cs sk bg mk sr hr sl".split(" ")
word_is_in = {
    'words': 'v slovniku',
    'suggestions': 'v spisu novyh slov',
    'Wiki list': 'v tabelě "Wiki list"',
    'CogNet': 'v tabelě "CogNet"',
    'Cognates': 'v tabelě "Cognates"',
}

def cell(row, column: str) -> str:
    """A cell of a one-row table as text; '' when the sheet has no such column or the cell is empty."""
    if column not in row.columns:
        return ''
    value = row[column][0]
    return value.strip() if isinstance(value, str) else ''

def word_link(row, sheet_name: str, lang: str = 'en') -> str:
    """Where the title of a card leads: the word in the dictionary on interslavic.app; a word of the
    other lists, which the site does not have, to its row in the Google Sheet."""
    if sheet_name == 'words':
        return bots.link_na_slovnik(cell(row, 'id'), lang)
    return bots.link_na_slovo(row['index'][0], sheet_name)

def card_data(row, sheet_name: str, lang: str = 'en') -> dict:
    """The card as data: what the Telegram bot shows as a table."""
    i = row['index'][0]
    return {
        "sheet": sheet_name,
        "id": cell(row, 'id'),
        "isv": cell(row, 'isv'),
        "addition": cell(row, 'addition'),
        "partOfSpeech": cell(row, 'partOfSpeech'),
        "intelligibility": cell(row, 'intelligibility'),
        "translations": [(col, cell(row, col)) for col in card_languages],
        "title": f"{i+2} {word_is_in[sheet_name]}",
        "link": word_link(row, sheet_name, lang),
        "lang": lang,
    }

def translations_card(row, sheet_name: str, with_meta: bool = False, lang: str = 'en'):
    i = row['index'][0]
    languages = card_languages
    title = f"{i+2} {word_is_in[sheet_name]}"
    output = f"## [{title}](<{word_link(row, sheet_name, lang)}>)\n\n"
    output += f"**{ format_words_with_links(row['isv'][0], 'isv') }**\n"
    for col in languages:
        words = row[col][0]
        output += f"**`{col}` **{ format_words_with_links(words, col) }\n"
    output += f"\n`.id {row['id'][0]}`"
    if with_meta:
        return {"kind": "word", "text": output, "en_word": primary_wiktionary_word(row['en'][0]),
                "card": card_data(row, sheet_name, lang)}
    return output


def words_list_card(sheet, contain = False, with_meta: bool = False, lang: str = 'en'):
    title = f"Najdeno {len(sheet)} slov(a), vy možete vyzvati jih prikazom `.id`:"
    if contain:
        title = f"Najdeno {len(sheet)} slov(a):"
    result = f"**{title}**\n\n"
    rows = []
    more = False
    for i in range(0, len(sheet)):
        new_row = f"{sheet['isv'][i]} (`.id {sheet['id'][i]}`)\n"
        if len(result) + len(new_row) < 600:
            result += new_row
            translation = sheet[lang][i] if lang in sheet.columns and lang != 'isv' else ''
            rows.append({"isv": sheet['isv'][i], "id": sheet['id'][i],
                         "translation": translation.strip() if isinstance(translation, str) else ''})
        else:
            result += "\n*I tako dalje....*"
            more = True
            break
    if with_meta:
        return {"kind": "list", "text": result, "title": title, "rows": rows, "more": more,
                "lang": lang if lang in sheet.columns and lang != 'isv' else ''}
    return result



fraznik_url = "https://gorlatoff.github.io/fraznik.html"

def phrasebook_card(i: int, tabela, with_meta: bool = False):
    markdown = f"# Rezultat iz [fraznika]({fraznik_url})\n\n"
    fields = []
    for col in tabela.columns[0:8]:
        cell = tabela[col][i]
        if cell != " ":
            markdown += f"## {col}\n{cell}\n\n"
            fields.append((col, cell))
    if with_meta:
        return {"kind": "phrase", "text": markdown, "fields": fields}
    return markdown

def split_by_coma(text: str) -> list:
    if ";" in text:
        return text.split("; ")
    return text.split(", ")

def wiktionary_title(word: str) -> str:
    """Clean word for Wiktionary URL (remove markers and brackets)"""
    word = word.replace('!', '').replace('#', '')
    word = re.sub(brackets_regex1, "", word)
    word = re.sub(brackets_regex2, "", word)
    return word.strip()

def wiktionary_url(lang: str, word: str) -> str:
    """Generate Wiktionary URL for a word in a specific language"""
    title = wiktionary_title(word)
    if not title:
        return ""
    if lang == 'isv':
        title = transl.transliteration(title, 'isv_to_standard')
        return f"https://incubator.wikimedia.org/wiki/Wt/isv/{urllib.parse.quote(title)}"
    return f"https://{lang}.wiktionary.org/wiki/{urllib.parse.quote(title)}"

def format_words_with_links(words: str, lang: str) -> str:
    """Format words as Wiktionary hyperlinks"""
    if not isinstance(words, str) or words.strip() == "":
        return bots.formatizer(str(words) if not isinstance(words, str) else words)
    parts = split_by_coma(words) if ";" in words or "," in words else [words]
    linked_parts = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        display = bots.formatizer(part).strip()
        url = wiktionary_url(lang, part)
        if url:
            linked_parts.append(f"[{display}](<{url}>)")
        else:
            linked_parts.append(display)
    if not linked_parts:
        return bots.formatizer(words)
    sep = "; " if ";" in words else ", "
    result = sep.join(linked_parts)
    # Don't add a leading space for the primary ISV word formatting
    if lang == 'isv':
        return result
    return " " + result

def primary_wiktionary_word(words: str) -> str | None:
    """Get the first valid word from a translation cell for Wiktionary lookup"""
    if not isinstance(words, str):
        return None
    parts = split_by_coma(words) if ";" in words or "," in words else [words]
    for part in parts:
        title = wiktionary_title(part)
        if title:
            return title
    return None


def split_and_search(s: str, text: str) -> bool:
    s = str(s)
    if ";" in s:
        return s in text.split("; ")
    return s in text.split(", ")


def filter_contain(s: str, lang: str, sheet):
    sheet = sheet.filter( pl.col(lang).str.contains(s) == True )
    return sheet



def search(s: str, lang: str, sheet):
    filter_sheet = pl.col(lang).map_elements(lambda text: split_and_search(s, text), return_dtype=pl.Boolean)
    return sheet.filter(filter_sheet)

def search_by_word(s: str, lang: str, sheet):
    split_column = pl.col(lang).map_elements(lambda text: s in re.split(r'[^\w]', text), return_dtype=pl.Boolean)
    return sheet.filter(split_column)

def search_in_sheet(slova: str, lang: str, sheet):
    sheet = filter_contain( slova, lang, sheet)
    if sheet.is_empty():
        return sheet
    najdene_slova = search( slova, lang, sheet)
    if not najdene_slova.is_empty():
        return najdene_slova
    najdene_slova = search_by_word(slova, lang, sheet)
    return najdene_slova



phrasebook_result = search_in_sheet('biti', "isv", sheets['fraznik'])








def search_in_phrasebook(slova: str, lang: str):
    sheet = sheets['fraznik']
    if lang == "isv_normalized":
        slova = transl.transliteration(slova, 'isv')
        return search_in_sheet(slova, "isv", sheet)
    if lang == "en":
        return search_in_sheet(slova, "Slovo na anglijskom", sheet)
    isv_translations = search_in_sheet(slova, lang, sheets['words'])
    if isv_translations.is_empty():
        return isv_translations
    isv_words = isv_translations['isv_normalized'].to_list()
    isv_words = [split_by_coma(text) for text in isv_words]
    isv_words = [item for sublist in isv_words for item in sublist]
    results = pl.DataFrame()
    for isv_word in isv_words:
        phrasebook_result = search_in_sheet(isv_word, "isv", sheet)
        results = pl.concat([results, phrasebook_result], how="vertical")
    return results.unique(maintain_order=True)

def phrasebook(slova: str, lang: str):
    result = search_in_phrasebook(slova, lang)
    messages = []
    if not result.is_empty():
        for i in range(0, len(result)):
            card = phrasebook_card(i, result)
            messages.append(card)
        return messages
    return ["Ničto ne jest najdeno. Tut možeš uviděti vsi slova, ktore imajemo https://gorlatoff.github.io/fraznik.html"]



def search_fuzzy(s: str, langs_wordlist: list):
    results = process.extract(s, langs_wordlist, scorer=fuzz.ratio, score_cutoff=85, limit=6)
    if not results:
        return False
    results = {i[0] for i in results}
    return list(results)


def sort_by_distance(slova: str, lang: str, sheet):
    sheet = sheet.with_columns( 
        pl.col(lang)
        .map_elements(lambda x: fuzz.ratio(slova, x), return_dtype=pl.Float32)
        .alias("distance"),
    )
    return sheet.sort(["distance"], descending=True)


import asyncio
async def mashina_search(slova: str, lang: str, with_meta: bool = False):
    print(slova, lang)
    messages = []
    def add_message(text: str):
        messages.append({"kind": "note", "text": text} if with_meta else text)
    # the language the card's link and list show next to Interslavic
    card_lang = lang if lang in card_languages else 'en'

    lang_normalized = lang + '_normalized'
    if lang == 'id':
        lang_normalized = 'id'
    if lang == 'en':
        lang_normalized = 'en'
    slova = cell_normalization(slova, lang)
    result = search_in_sheet(slova, lang_normalized, sheets['words'])
    if not result.is_empty():
        fraznik_results = search_in_phrasebook(slova, lang_normalized)
        if not fraznik_results.is_empty():
            for i in range(0, len(fraznik_results)):
                messages.append(phrasebook_card(i, fraznik_results, with_meta=with_meta))
        length = len(result)
        if length <= 3:
            for i in range(0, len(result)):
                messages.append(translations_card(result[i:i+1], 'words', with_meta=with_meta, lang=card_lang))
            return messages
        result = sort_by_distance(slova, lang_normalized, result)
        messages.append(words_list_card(result, with_meta=with_meta, lang=card_lang))
        return messages
    result = search_fuzzy(slova, sheets['words'][lang])
    if result:
        if len(result) > 1:
            alternative_variants = f"*{', '.join(result[:-1])}* ili *{result[-1]}*"
            answer = f"Prividno, slovnik ne imaje slovo *{slova}*. Jeste li vy imali na mysli {alternative_variants}?"
            add_message(answer)
        else:
            answer = f"Prividno, slovnik ne imaje slovo *{slova}*. Jeste li vy imali na mysli `.{lang} {result[0]}`?"
            add_message(answer)
    lemma = lemmatizer.slavic_lemmatizer(slova, lang)
    result = search_in_sheet(lemma, lang_normalized, sheets['words'])
    if not result.is_empty():
        add_message(f"Prividno, slovnik ne imaje slovo *{slova}*. Jeste li vy imali na mysli `.{lang} {lemma}`?")
        return messages
    result = filter_contain(slova, lang_normalized, sheets['words'])
    if not result.is_empty():
        result = sort_by_distance(slova, lang_normalized, result)
        messages.append(words_list_card(result, contain=True, with_meta=with_meta, lang=card_lang))
        return messages
    optional_sheets = list(sheets.keys())[1:]
    optional_sheets.remove('fraznik')
    success = False
    for sheet_name in optional_sheets:
        result = search_in_sheet(slova, lang_normalized, sheets[sheet_name])
        if not result.is_empty():
            success = True
            for i in range(0, len(result)):
                messages.append(translations_card(result[i:i+1], sheet_name, with_meta=with_meta, lang=card_lang))
    if success:
        return messages
    if not lang_detect.language_verify(slova, lang):
        answer = f"Vaše poslanje ne izgledaje kako tekst na {lang} jezyku, jeste li vy uvěrjeni?\n\nMožlive jezyky i jih kody:\n`isv` medžuslovjansky, `en` anglijsky, `ru` russky, `be` bělorussky, `uk` ukrajinsky, `pl` poljsky, `cs` češsky, `sk` slovačsky, `bg` bulgarsky, `mk` makedonsky, `sr` srbsky, `hr` hrvatsky, `sl` slovensky."
        add_message(answer)
        return messages
    if lang in wiki.SUPPORTED_WIKIS:
        try:
            wiki_result = await wiki.wiki_titles(lang, slova)
        except Exception as e:
            # Wikipedia cannot be reached: the answer is still "nothing found"
            print(f"wiki: {type(e).__name__}: {e}")
            wiki_result = False
        if wiki_result:
            messages.append({"kind": "wiki", "text": wiki_result} if with_meta else wiki_result)
            return messages
    answer = f"My gledali jesmo v slovniku, neoficialnyh spisah slov, i daže v Wikipediji, i ne jesmo našli ničto. Poprobuj najdti podobne ili srodne rěči, ili stvori novo slovo sam. V analizovanju pomogut [Glosbe.com](<{bots.glosbe(slova, lang)}>) ili [Nicetranslator](<{bots.nicetranslator(lang)}>)."
    add_message(answer)
    return messages


def find_by_id(word_id: str, sheet_name: str = 'words'):
    """The entry with this id as a one-row table, or None."""
    sheet = sheets.get(sheet_name)
    if sheet is None or sheet is False or 'id' not in sheet.columns:
        return None
    result = sheet.filter(pl.col('id') == str(word_id))
    return None if result.is_empty() else result[0:1]


if __name__ == "__main__":
    search_in_phrasebook('привет', 'ru')
    search_fuzzy('млово', 'ru')
    filter_contain("слово", 'ru', sheets['words'])
    search("слово", 'ru', sheets['words'])
    search_by_word("слово", 'ru', sheets['words'])
    print(search_in_sheet("слово", 'ru', sheets['words']))
    search_in_sheet("слово", 'ru_normalized', sheets['words'])
    filter_contain('кaкой-то', 'ru_normalized', sheets['words'])
    search('983', 'id', sheets['words'])
    tests_dict = {
        "млово": "ru",
        "быть": "ru",
        "делaть": "ru",
        "буду": "ru",
        "делaю": "ru",
        "кaкой-то": "ru",
        "зa": "ru",
        "добрый": "ru",
        "ить": "ru",
        "тест": "ru",
        "снежный": "ru",
        "привет": "ru",
        "барс": "ru",
        "pozdrav": "isv",
        "pozdråv": "isv",
        "rodženja": "isv",
    }
    for word, lang in tests_dict.items():
        mashina_search(word, lang)
        print(mashina_search(word, lang))
    x = input()
