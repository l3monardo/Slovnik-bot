"""
The Slavformer's texts in Interslavic, taken from the website's translations, so that the bot says what the site
says: python3 tools/slavformer_strings.py <interslavic-hub>/src/translations/data.json > slavformer_strings.json
"""
import json
import sys

KEYS = [
    'gameTitle', 'gameIntro', 'gameHonest', 'voteQuestion', 'gameMeaning', 'gameSkip', 'gameNext', 'gameOthers',
    'gameFirst', 'gameBonus', 'gameAllDone', 'gameTooFast', 'gameBecameMorph', 'gameBecameRobot', 'gameShop',
    'gameShopLocked', 'gameShopHint', 'gameWear', 'gameTakeOff', 'gameNeedMore', 'gameScore', 'gameCoins',
    'gamePerHour', 'gameCollected', 'gameStageCar', 'gameStageMorph', 'gameStageRobot', 'gameGoalStage',
    'gameGoalBonus', 'gamePlay', 'voteNeedsProfile', 'blockedForever',
    'voteUnderstand', 'voteContext', 'voteNonNative', 'voteFalseFriend', 'voteNotUnderstand',
]
ITEMS = ['paint-white', 'paint-beige', 'paint-yellow', 'paint-green', 'paint-blue', 'paint-violet', 'paint-cherry',
         'paint-black', 'tank', 'tracksuit', 'telnyashka', 'shirt', 'leather', 'dublenka', 'goldsuit', 'cap', 'ushanka',
         'wreath', 'barsetka', 'squat', 'chain', 'seeds', 'kolbasa', 'kvass', 'tea', 'accordion', 'boombox', 'pickles',
         'borscht', 'pelmeni', 'grinder', 'samovar', 'scanner', 'cat', 'pigeons', 'bear', 'dog', 'matryoshka', 'aloe',
         'servant', 'carpet', 'courtyard', 'kiosk', 'dacha', 'market', 'livingroom', 'subway']
LANGS = ['ru', 'uk', 'be', 'rue', 'pl', 'csb', 'szl', 'hsb', 'dsb', 'cs', 'sk', 'sl', 'hr', 'bs', 'sr', 'cnr', 'mk',
         'bg', 'en']


def item_key(item: str) -> str:
    kind, _, colour = item.partition('-')
    return f"gamePaint{colour.capitalize()}" if colour else f"gameItem{kind.capitalize()}"


def main():
    data = json.load(open(sys.argv[1], encoding='utf-8'))
    out = {
        'texts': {key: data[key]['isv'] for key in KEYS},
        'items': {item: data[item_key(item)]['isv'] for item in ITEMS},
        'langs': {lang: data[f'{lang}Lang']['isv'] for lang in LANGS},
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
