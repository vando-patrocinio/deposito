"""Iteration 70 — Quebra de bolhas IA no WhatsApp auto-reply

Bug: quando o prompt da IA pedia múltiplas mensagens separadas (parágrafos
com `\\n\\n`), o backend enviava TUDO como UMA bolha só. Cliente via um
muralhão de texto em vez de mensagens curtas.

Fix: helper `_split_ai_reply` em `routes/whatsapp_baileys.py` quebra o
reply em chunks por `\\n\\n` (ou marcador `---`), cap em 6, junta micros
< 12 chars, persiste cada chunk como linha separada em `aihub_wa_messages`
com `chunk_index`/`chunk_total`.
"""
from routes.whatsapp_baileys import _split_ai_reply


def test_paragraphs_separados_viram_chunks_distintos():
    text = ("Olá! Tudo bem?\n\n"
            "Claro, posso te ajudar com isso.\n\n"
            "Qual é o seu CPF para eu localizar seu cadastro?")
    chunks = _split_ai_reply(text)
    assert len(chunks) == 3
    assert chunks[0].startswith("Olá")
    assert "CPF" in chunks[2]


def test_texto_unico_sem_quebra_devolve_um_chunk():
    chunks = _split_ai_reply("Olá, sou a Isabella, atendimento Ligo Fibra.")
    assert len(chunks) == 1


def test_lista_com_bullets_quebras_simples_ficam_juntas():
    text = ("Aqui estão nossos planos:\n"
            "- 400 Mega: R$ 109,90\n"
            "- 600 Mega: R$ 139,90\n\n"
            "Quer que eu envie o link de contratação?")
    chunks = _split_ai_reply(text)
    assert len(chunks) == 2
    assert "400 Mega" in chunks[0] and "600 Mega" in chunks[0]
    assert "link" in chunks[1]


def test_cap_max_chunks_overflow_junta_no_ultimo():
    # 10 parágrafos com tamanho suficiente pra não virar micro-merge
    paragraphs = [f"Parágrafo número {i} com conteúdo longo o suficiente." for i in range(10)]
    chunks = _split_ai_reply("\n\n".join(paragraphs), max_chunks=6)
    assert len(chunks) == 6
    # O último chunk deve ter os 5 parágrafos restantes concatenados
    assert "Parágrafo número 5" in chunks[-1]
    assert "Parágrafo número 9" in chunks[-1]


def test_separador_triplo_dash_explicito():
    text = "Primeira parte\n---\nSegunda parte\n---\nTerceira"
    chunks = _split_ai_reply(text)
    assert len(chunks) >= 2  # 'Segunda' e 'Terceira' podem virar 1 ou 2 chunks
    assert chunks[0] == "Primeira parte"


def test_micro_chunk_merged_com_proximo():
    # "Oi!" tem só 3 chars (< min_chunk_chars=12) → junta com próximo
    text = "Oi!\n\nClaro, posso te ajudar com isso, qual seu CPF?"
    chunks = _split_ai_reply(text)
    assert len(chunks) == 1
    assert "Oi!" in chunks[0] and "CPF" in chunks[0]


def test_vazio_devolve_lista_vazia():
    assert _split_ai_reply("") == []
    assert _split_ai_reply("   \n\n  ") == []


def test_newlines_simples_dentro_de_paragrafo_preservados():
    text = "Linha 1\nLinha 2\n\nOutro parágrafo aqui."
    chunks = _split_ai_reply(text)
    assert len(chunks) == 2
    assert "Linha 1\nLinha 2" == chunks[0]
