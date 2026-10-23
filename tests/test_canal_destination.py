import pytest

from app.services.canal_destination import CANAL_PORT_LOCODES, match_canal_destination


@pytest.mark.parametrize(
    ("destination", "expected"),
    [
        # Códigos UN/LOCODE, con y sin espacio, y con los separadores que usan las tripulaciones.
        ("PABLB", "PABLB"),
        ("PA BLB", "PABLB"),
        ("PA-BLB", "PABLB"),
        ("PA.CTB", "PACTB"),
        ("PAONX", "PAONX"),
        ("PAMIT", "PAMIT"),
        ("PA PTY", "PAPTY"),
        ("PAROD", "PAROD"),
        ("pablb", "PABLB"),
        # Rutas: el Canal puede ser el destino final o un paso intermedio.
        ("USHOU>PABLB", "PABLB"),
        ("USHOU > PA BLB", "PABLB"),
        ("USNYC-PACTB-CLSAI", "PACTB"),
        ("USNYC - PACTB - CLSAI", "PACTB"),
        ("USHOU=>PABLB", "PABLB"),
        ("USHOU->PANAMA", "PA"),
        # Muestra real de 7 min del 2026-10-22 (5847 buques): los dos que venían al Canal.
        ("PA BLB      ", "PABLB"),
        # Nombres de puerto.
        ("BALBOA", "PABLB"),
        ("BALBOA PANAMA", "PABLB"),
        ("CRISTOBAL", "PACTB"),
        ("CRISTÓBAL", "PACTB"),
        ("COLON", "PAONX"),
        ("COLON PANAMA", "PAONX"),
        ("MANZANILLO PA", "PAMIT"),
        ("RODMAN", "PAROD"),
        # El país o el Canal sin puerto concreto.
        ("PANAMA", "PA"),
        ("PANAMA CANAL", "PA"),
        ("PANAMA CANAL ANCH", "PA"),
        ("P.CANAL", "PA"),
        ("FOR ORDERS PANAMA", "PA"),
        ("PTY", "PAPTY"),
    ],
)
def test_canal_destinations_are_detected(destination: str, expected: str) -> None:
    assert match_canal_destination(destination) == expected


@pytest.mark.parametrize(
    "destination",
    [
        None,
        "",
        "   ",
        # Falsos positivos reales de la muestra del 2026-10-21 (#59).
        "USI CANAL",
        "DREDGING KIEL CANAL",
        "KIEL CANAL",
        # Muestra real del 2026-10-22: rutas que salen de Panamá (el primer tramo es el origen)
        # y otros parecidos.
        "PAMIT>ITVDL",
        "PAPAN->USIAH",
        "PACHG>COCOV",
        "PACTB>CNSHA",
        "PANAMA > USHOU",
        "HARVEY CANAL",
        "PECHE CANAL11",
        "PASCO",
        "PATRA",
        "PARIS",
        "PALMA",
        "PARAY - BERLIN - PAR",
        # Otros "canales" y Panamás.
        "SUEZ CANAL",
        "CORINTH CANAL",
        "PANAMA CITY",
        "PANAMA CITY FL",
        "PANAMA CITY,FL",
        "PANAMA CITY FLORIDA",
        "USPFN",
        "US PFN",
        # Otros Colón y Manzanillo: no basta el nombre si va con otro país.
        "COLON AR",
        "COLON ARGENTINA",
        "MANZANILLO",
        "MXZLO",
        "MANZANILLO MX",
        "MANZANILLO CUBA",
        # Palabras que contienen las letras de un código o nombre.
        "PALEMBANG",
        "PALMA DE MALLORCA",
        "PAPENDRECHT",
        "PAREY-BERLIN-PAREY",
        "COLONIA",
        "COLOMBO",
        "BALBOA ISLAND",
        "PATRICIA BAY",
        # Códigos LOCODE de Panamá que no son puertos del Canal.
        "PABOC",
        "PAAML",
        "PAVAC",
        # Destino de otra parte del mundo.
        "CNSHA",
        "USHOU>CNSHA",
        "ROTTERDAM",
    ],
)
def test_other_destinations_are_not_detected(destination: str | None) -> None:
    assert match_canal_destination(destination) is None


def test_every_detected_locode_is_a_canal_port() -> None:
    assert set(CANAL_PORT_LOCODES) == {
        "PABLB",
        "PACTB",
        "PAONX",
        "PAMIT",
        "PAPTY",
        "PAROD",
        "PAGTN",
        "PAMFS",
        "PAGBA",
        "PAPBM",
        "PAPAY",
        "PATBG",
    }
    for locode in CANAL_PORT_LOCODES:
        assert match_canal_destination(locode) == locode
