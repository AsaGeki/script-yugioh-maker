"""Valores levantados varrendo o dataset completo da API oficial YGOPRODeck
(14.519 cartas, endpoint cardinfo.php sem filtro)."""

from enum import StrEnum


class CardAttribute(StrEnum):
    DARK = "DARK"
    DIVINE = "DIVINE"
    EARTH = "EARTH"
    FIRE = "FIRE"
    LIGHT = "LIGHT"
    WATER = "WATER"
    WIND = "WIND"


# Campo "type" bruto da API: mistura categoria (Monster/Spell/Trap) + subtipo +
# tracos (Toon/Spirit/Union/Gemini/Flip/Tuner) num unico string. "Skill Card"
# (feature do Duel Links) fica de fora: o maker nao suporta esse tipo de carta.
class CardType(StrEnum):
    NORMAL_MONSTER = "Normal Monster"
    EFFECT_MONSTER = "Effect Monster"
    FUSION_MONSTER = "Fusion Monster"
    RITUAL_MONSTER = "Ritual Monster"
    RITUAL_EFFECT_MONSTER = "Ritual Effect Monster"
    SYNCHRO_MONSTER = "Synchro Monster"
    SYNCHRO_TUNER_MONSTER = "Synchro Tuner Monster"
    SYNCHRO_PENDULUM_EFFECT_MONSTER = "Synchro Pendulum Effect Monster"
    XYZ_MONSTER = "XYZ Monster"
    XYZ_PENDULUM_EFFECT_MONSTER = "XYZ Pendulum Effect Monster"
    LINK_MONSTER = "Link Monster"
    PENDULUM_NORMAL_MONSTER = "Pendulum Normal Monster"
    PENDULUM_EFFECT_MONSTER = "Pendulum Effect Monster"
    PENDULUM_EFFECT_FUSION_MONSTER = "Pendulum Effect Fusion Monster"
    PENDULUM_EFFECT_RITUAL_MONSTER = "Pendulum Effect Ritual Monster"
    PENDULUM_FLIP_EFFECT_MONSTER = "Pendulum Flip Effect Monster"
    PENDULUM_TUNER_EFFECT_MONSTER = "Pendulum Tuner Effect Monster"
    FLIP_EFFECT_MONSTER = "Flip Effect Monster"
    FLIP_TUNER_EFFECT_MONSTER = "Flip Tuner Effect Monster"
    GEMINI_MONSTER = "Gemini Monster"
    SPIRIT_MONSTER = "Spirit Monster"
    TOON_MONSTER = "Toon Monster"
    TUNER_MONSTER = "Tuner Monster"
    NORMAL_TUNER_MONSTER = "Normal Tuner Monster"
    UNION_EFFECT_MONSTER = "Union Effect Monster"
    TOKEN = "Token"
    SPELL_CARD = "Spell Card"
    TRAP_CARD = "Trap Card"


# Campo "race" quando o "type" e de monstro. "Illusion" e raca nova (cartas
# recentes) que o site yugiohcardmaker.org ainda pode nao suportar no select.
class MonsterRace(StrEnum):
    AQUA = "Aqua"
    BEAST = "Beast"
    BEAST_WARRIOR = "Beast-Warrior"
    CREATOR_GOD = "Creator God"
    CYBERSE = "Cyberse"
    DINOSAUR = "Dinosaur"
    DIVINE_BEAST = "Divine-Beast"
    DRAGON = "Dragon"
    FAIRY = "Fairy"
    FIEND = "Fiend"
    FISH = "Fish"
    ILLUSION = "Illusion"
    INSECT = "Insect"
    MACHINE = "Machine"
    PLANT = "Plant"
    PSYCHIC = "Psychic"
    PYRO = "Pyro"
    REPTILE = "Reptile"
    ROCK = "Rock"
    SEA_SERPENT = "Sea Serpent"
    SPELLCASTER = "Spellcaster"
    THUNDER = "Thunder"
    WARRIOR = "Warrior"
    WINGED_BEAST = "Winged Beast"
    WYRM = "Wyrm"
    ZOMBIE = "Zombie"


# Campo "race" quando o "type" e "Spell Card" ou "Trap Card" (subtipo da magia/armadilha).
# "Counter" so existe em Trap.
class SpellTrapSubtype(StrEnum):
    NORMAL = "Normal"
    CONTINUOUS = "Continuous"
    EQUIP = "Equip"
    FIELD = "Field"
    QUICK_PLAY = "Quick-Play"
    RITUAL = "Ritual"
    COUNTER = "Counter"


class LinkMarker(StrEnum):
    TOP = "Top"
    BOTTOM = "Bottom"
    LEFT = "Left"
    RIGHT = "Right"
    TOP_LEFT = "Top-Left"
    TOP_RIGHT = "Top-Right"
    BOTTOM_LEFT = "Bottom-Left"
    BOTTOM_RIGHT = "Bottom-Right"
