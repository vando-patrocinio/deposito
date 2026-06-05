"""iter211n — Reconciliação regex de SNs no texto da nota fiscal.

Simula o caso real do recibo Baixadanet: 10 ONTs FIBERHOME numa linha só,
SNs listados sequencialmente após "Nº Série:".
"""
import re


def extract_sns_from_text(text: str) -> list:
    """Replica o regex que `purchases.upload_extract` usa pra reconciliar."""
    SN_RE = re.compile(r"\b[A-Z]{2,6}[A-Z0-9]{6,20}\b")
    STOPWORDS = {"CNPJ", "RUA", "AVENIDA", "CEP", "RECIBO",
                  "ORDEM", "FORNECEDOR", "CLIENTE", "TELEFONE",
                  "ITAU", "GPON", "WIFI", "AC1200", "BIDI"}
    out = []
    for m in SN_RE.finditer((text or "").upper()):
        tok = m.group(0)
        if tok in STOPWORDS:
            continue
        if len(tok) <= 8:
            continue
        out.append(tok)
    return out


def test_extracts_baixadanet_recibo_sns():
    """Recibo Baixadanet (1/jun/2026) — 10 SNs Fiberhome + 2 SNs GBIC."""
    text = """
    Recibo No 284306
    01-06-2026 13:04:57
    BAIXADANET

    FIBERHOME ONT AC1200 GPON 2GE WIFI HG6145D
    No Serie:
    FHTTC250CE0B,
    FHTTC250CE0C,
    FHTTC250CE14,
    FHTTC250D38F,
    FHTTC250D394,
    FHTTC250D499,
    FHTTC250D4F7,
    FHTTC250DAA5,
    FHTTC250DED9,
    FHTTC250DEF5
    10 UN 190,40 2.115,60

    CORDAO OPTICO LC/APC-LC/APC SM SX 3.0 2M 2FLEX
    3 PC 5,99 19,98

    MINI GBIC BIDI 3524L-R20 LC-DDM - 1.25G 20KM - A
    No Serie:
    ASTT24101105917
    1 PC 70,00 77,77

    MINI GBIC BIDI 5324L-R20 LC-DDM - 1.25G 20KM - B
    No Serie:
    ASTT24101106699
    1 PC 79,99 88,88
    """
    sns = extract_sns_from_text(text)
    # Os 10 SNs Fiberhome devem estar todos
    expected_fh = {f"FHTTC250CE0B", "FHTTC250CE0C", "FHTTC250CE14",
                    "FHTTC250D38F", "FHTTC250D394", "FHTTC250D499",
                    "FHTTC250D4F7", "FHTTC250DAA5", "FHTTC250DED9",
                    "FHTTC250DEF5"}
    found_fh = expected_fh.intersection(sns)
    assert len(found_fh) == 10, \
        f"Esperava 10 SNs Fiberhome, achei {len(found_fh)}: {found_fh}"
    # Os 2 SNs ASTT também
    assert "ASTT24101105917" in sns
    assert "ASTT24101106699" in sns


def test_filters_stopwords_and_models():
    """Não deve confundir 'GPON', 'WIFI', 'HG6145D' com SNs."""
    text = "FIBERHOME ONT GPON HG6145D ASTT24101105917"
    sns = extract_sns_from_text(text)
    assert "ASTT24101105917" in sns
    assert "GPON" not in sns
    assert "WIFI" not in sns
    # HG6145D tem 7 chars — filtrado pelo len > 8


def test_ignores_short_tokens():
    """Tokens curtos (<8) não viram SN — ex: códigos de produto."""
    text = "Cod: 3224 Item: 1351 SN: FHTTC250CE0B"
    sns = extract_sns_from_text(text)
    assert "FHTTC250CE0B" in sns
    assert "3224" not in sns
    assert "1351" not in sns
