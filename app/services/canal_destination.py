"""Detección de buques que declaran como destino el Canal de Panamá o uno de sus puertos (#59).

El destino AIS es texto libre que escribe la tripulación (20 caracteres): un código UN/LOCODE
(`PABLB`), un nombre (`BALBOA`), una ruta (`USHOU>PABLB`) o cualquier otra cosa. Esta función solo
reconoce los buques que **declaran** Panamá; no detecta los que cruzan el Canal hacia otro destino
(un Houston → Shanghái declara `CNSHA`). Ver docs/DATA_SOURCES.md y ADR-0009.

En una ruta (`USHOU>PABLB`, `USNYC-PACTB-CLSAI`) el primer tramo es el **origen**: un buque que
declara `PAMIT>ITVDL` sale de Panamá hacia Italia y no cuenta. Sí cuentan el destino final y los
pasos intermedios.

Se prefiere perder un buque a mostrar uno que no viene: un nombre ambiguo (`MANZANILLO`,
`PANAMA CITY`) o acompañado de otro país (`COLON AR`, `BALBOA CA`) no cuenta.

Lógica pura, sin I/O: se prueba con destinos reales y falsos positivos conocidos.
"""

import re
import unicodedata

# Puertos y fondeaderos del área del Canal en UN/LOCODE (país PA, función 1 = puerto). Verificados
# el 2026-10-22 contra la lista de la UNECE (copia en github.com/datasets/un-locode). `PAPCN`,
# que a veces se ve como "Panama Canal", no existe en la lista oficial.
CANAL_PORT_LOCODES: dict[str, str] = {
    "PABLB": "Balboa",
    "PACTB": "Cristóbal",
    "PAONX": "Colón",
    "PAMIT": "Manzanillo",
    "PAPTY": "Panamá, Ciudad de",
    "PAROD": "Rodman",
    "PAGTN": "Gatún",
    "PAMFS": "Miraflores",
    "PAGBA": "Gamboa",
    "PAPBM": "Bahía Las Minas",
    "PAPAY": "Payardi",
    "PATBG": "Taboguilla",
}
# Panamá o el Canal sin un puerto concreto (`PANAMA`, `PANAMA CANAL`).
COUNTRY_ONLY = "PA"

# El código puede ir con un separador entre país y lugar (`PA BLB`, `PA-BLB`) y no puede formar
# parte de una palabra más larga (`PALEMBANG`, `PAREY`).
_LOCODE = re.compile(
    r"(?<![A-Z0-9])PA[ .\-_/]?("
    + "|".join(code[2:] for code in CANAL_PORT_LOCODES)
    + r")(?![A-Z0-9])"
)
_WORD = re.compile(r"[A-Z0-9]+")
# Separadores de tramos de una ruta. El guion solo separa entre códigos de 5 letras o con
# espacios alrededor, para no partir `PA-BLB`.
_LEG_SEPARATOR = re.compile(r"\s*(?:=>|->|>|\s-\s|(?<=[A-Z]{5})-(?=[A-Z]{5}))\s*")

# Nombres que solo existen en Panamá entre los puertos con tráfico relevante.
_PORT_NAMES = {
    "BALBOA": "PABLB",
    "CRISTOBAL": "PACTB",
    "COLON": "PAONX",
    "RODMAN": "PAROD",
    "PTY": "PAPTY",
}
# Nombres que también son puertos de otros países: solo cuentan junto a `PA` o `PANAMA`.
_SHARED_PORT_NAMES = {"MANZANILLO": "PAMIT"}
_PANAMA_WORDS = {"PA", "PANAMA"}
# Palabras que sitúan el destino fuera de Panamá: Panama City (Florida), Colón (Argentina, Cuba),
# Balboa Island (California)...
_FOREIGN_QUALIFIERS = {
    "FL",
    "FLA",
    "FLORIDA",
    "US",
    "USA",
    "CA",
    "ISLAND",
    "AR",
    "ARGENTINA",
    "CU",
    "CUBA",
    "MX",
    "MEXICO",
}


def match_canal_destination(destination: str | None) -> str | None:
    """UN/LOCODE del puerto del Canal declarado, `"PA"` si solo se declara Panamá, o None."""
    if destination is None or not destination.strip():
        return None
    text = _fold(destination)
    legs = [leg for leg in _LEG_SEPARATOR.split(text) if leg.strip()]
    # El primer tramo de una ruta es el origen: solo cuentan los siguientes.
    for leg in legs[1:] if len(legs) > 1 else legs:
        port = _match_leg(leg)
        if port is not None:
            return port
    return None


def _match_leg(leg: str) -> str | None:
    # 1. Un código explícito es lo más fiable.
    locode = _LOCODE.search(leg)
    if locode:
        return "PA" + locode.group(1)

    words = _WORD.findall(leg)
    if _FOREIGN_QUALIFIERS.intersection(words):
        return None
    # 2. El nombre de un puerto; si además dice Panamá, gana el puerto (`BALBOA PANAMA`).
    for word in words:
        if word in _PORT_NAMES:
            return _PORT_NAMES[word]
        if word in _SHARED_PORT_NAMES and _PANAMA_WORDS.intersection(words):
            return _SHARED_PORT_NAMES[word]
    # 3. Panamá o el Canal sin puerto. `PANAMA CITY` se descarta: suele ser la de Florida.
    if "PANAMA" in words and "CITY" not in words:
        return COUNTRY_ONLY
    if _is_canal_abbreviation(words):
        return COUNTRY_ONLY
    return None


def _fold(value: str) -> str:
    """Mayúsculas y sin tildes (`Cristóbal` → `CRISTOBAL`): AIS no tiene tildes, la entrada sí."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).upper()


def _is_canal_abbreviation(words: list[str]) -> bool:
    """`P.CANAL` o `PCANAL`; `KIEL CANAL` o `USI CANAL` no."""
    if "PCANAL" in words:
        return True
    return any(
        word == "CANAL" and index > 0 and words[index - 1] == "P"
        for index, word in enumerate(words)
    )
