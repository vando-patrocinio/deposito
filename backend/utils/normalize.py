"""Normalização defensiva de campos polimórficos.

Tickets, clientes e contratos sincronizados de sistemas legados (Atlaz, ERP)
podem trazer campos como `address`, `phone`, `relato` ora como string, ora como
objeto estruturado. Para evitar crashes no frontend ("Objects are not valid as
a React child"), normalizamos a resposta server-side antes de devolver pro
cliente.

Uso:
    from utils.normalize import norm_string, normalize_fields, normalize_list

    out = normalize_fields(doc, ["address", "phone", "relato", "name"])
    items = normalize_list(items, ["address", "phone"])
"""
from __future__ import annotations


def norm_string(v) -> str:
    """Converte qualquer valor em string segura.

    Reconhece formatos comuns:
      - endereço estruturado: {rua/logradouro, numero, bairro, cidade, estado,
        cep, complemento, referencia}
      - telefone estruturado: {ddd, numero}
      - texto longo: {texto/text/resumo/summary/description/body}
      - nome estruturado: {full/name/nome/razao_social} ou {first, last}
      - listas: join com ", "
      - None/null: retorna ""
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, dict):
        # Endereço estruturado
        if any(k in v for k in ("rua", "logradouro", "street")):
            parts = [
                v.get("rua") or v.get("logradouro") or v.get("street"),
                f"n° {v.get('numero') or v.get('number')}"
                    if (v.get("numero") or v.get("number")) else None,
                v.get("complemento") or v.get("complement"),
                v.get("bairro") or v.get("neighborhood"),
                v.get("cidade") or v.get("city"),
                v.get("estado") or v.get("uf") or v.get("state"),
                f"CEP {v.get('cep') or v.get('zip')}"
                    if (v.get("cep") or v.get("zip")) else None,
                f"({v.get('referencia') or v.get('reference')})"
                    if (v.get("referencia") or v.get("reference")) else None,
            ]
            return ", ".join([p for p in parts if p])
        # Telefone estruturado
        if "ddd" in v and "numero" in v and not v.get("rua"):
            if v.get("ddd") and v.get("numero"):
                return f"({v['ddd']}) {v['numero']}"
        # Texto longo (relato/descrição)
        for k in ("texto", "text", "resumo", "summary",
                   "description", "body"):
            if k in v and v[k]:
                return str(v[k])
        # Nome
        for k in ("full", "name", "nome", "razao_social",
                   "label", "value", "title", "id"):
            if k in v and v[k]:
                return str(v[k])
        # first + last
        if v.get("first") or v.get("last"):
            return f"{v.get('first', '')} {v.get('last', '')}".strip()
        return str(v)
    if isinstance(v, list):
        return ", ".join([norm_string(x) for x in v if x])
    return str(v)


# Campos sensíveis pré-definidos para conveniência
DEFAULT_FIELDS = [
    "name", "address", "phone", "relato", "neighborhood", "praca",
    "cpf", "cnpj", "document", "cidade", "bairro", "logradouro",
    "estado", "uf", "razao_social", "email",
]


def normalize_fields(obj: dict | None, fields: list[str] | None = None) -> dict:
    """Sanitiza fields-by-name no dict. Retorna shallow copy.

    Se `fields` for None, usa DEFAULT_FIELDS.
    """
    if not obj:
        return obj or {}
    out = dict(obj)
    keys = fields or DEFAULT_FIELDS
    for k in keys:
        if k in out:
            out[k] = norm_string(out[k])
    return out


def normalize_list(items, fields: list[str] | None = None,
                    nested_key: str | None = None) -> list:
    """Aplica normalize_fields em todos os items de uma lista.

    Se `nested_key` for fornecido, normaliza o sub-objeto naquela chave
    (ex: nested_key='client_snapshot' em uma lista de tickets).
    """
    if not items:
        return items or []
    out = []
    for it in items:
        if not isinstance(it, dict):
            out.append(it)
            continue
        new_it = dict(it)
        if nested_key:
            if nested_key in new_it:
                new_it[nested_key] = normalize_fields(new_it[nested_key], fields)
        else:
            new_it = normalize_fields(new_it, fields)
        out.append(new_it)
    return out
