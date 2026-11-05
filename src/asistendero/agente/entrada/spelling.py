"""Cómo escribe el cliente de verdad: «tuvo pbc de media pa l agua», «2 vultos de sement».

El servidor solo acepta los atributos y las variantes que el cliente dijo (``ProductQuery.grounded`` e
``is_distinguished``). Si se compararan letra por letra, una falta de ortografía bastaría para que Grok no pudiera
cotizar lo que entendió bien. ``heard_as`` reescribe cada palabra del cliente que **suena igual** a una palabra que
Grok extrajo («tuvo» → «tubo», «pbc» → «pvc», «sement» → «cemento», «bultico» → «bulto») y expande abreviaturas
de chat («pa» → «para»). Los números nunca se corrigen: una medida o una cantidad tiene que estar escrita tal cual.
"""

import re
import unicodedata


SLANG = {"pa": "para", "pal": "para el", "q": "que", "k": "que", "xq": "porque", "pq": "porque", "porfa": "por favor",
         "xfa": "por favor", "tb": "tambien", "tmb": "tambien", "d": "de", "dl": "del", "kiero": "quiero",
         "nesesito": "necesito"}
DIMINUTIVE = re.compile(r"^(\w{3,}?)(?:c|qu)?(?:it|ic|ill)([oa]s?)$")
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
MIN_LETTERS = 3


def _plain(word: str) -> str:
    normalized = unicodedata.normalize("NFKD", word.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def sound_key(word: str) -> str:
    """Clave fonética del español de Colombia: b/v, s/c/z, ll/y, h muda y letras dobles suenan igual."""
    key = _plain(word).replace("ch", "x").replace("qu", "k").replace("ll", "y").replace("w", "b").replace("v", "b")
    key = re.sub(r"c(?=[ei])", "s", key).replace("c", "k").replace("z", "s").replace("h", "")
    return re.sub(r"(.)\1+", r"\1", key)


def _distance(first: str, second: str) -> int:
    previous = list(range(len(second) + 1))
    for row, left in enumerate(first, 1):
        current = [row]
        for column, right in enumerate(second, 1):
            current.append(min(previous[column] + 1, current[column - 1] + 1, previous[column - 1] + (left != right)))
        previous = current
    return previous[-1]


def _sounds_like(said: str, heard: str) -> bool:
    candidates = {said}
    match = DIMINUTIVE.match(_plain(said))
    if match:
        candidates.add(match.group(1) + match.group(2))  # «bultico» → «bulto», «tornillito» → «tornillo»
    target = sound_key(heard)
    for candidate in candidates:
        key = sound_key(candidate)
        if key == target:
            return True
        # Una letra de más o de menos solo en palabras largas: «pino» y «piso» no se confunden.
        shortest = min(len(key), len(target))
        if (shortest >= 5 and _distance(key, target) <= 1) or (shortest >= 8 and _distance(key, target) <= 2):
            return True
    return False


def heard_as(message: str, extracted: str) -> str:
    """El mensaje con cada palabra que suena como una de ``extracted`` reescrita como esa palabra."""
    vocabulary = {_plain(word) for word in WORD.findall(extracted) if len(word) >= MIN_LETTERS}

    def rewrite(match: re.Match) -> str:
        word = match.group(0)
        plain = _plain(word)
        if plain in SLANG:
            return SLANG[plain]
        if plain in vocabulary or len(plain) < MIN_LETTERS:
            return word
        return next((target for target in sorted(vocabulary) if _sounds_like(plain, target)), word)

    return WORD.sub(rewrite, message)
