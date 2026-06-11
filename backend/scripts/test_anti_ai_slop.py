"""TEST ANTI-AI-SLOP — 13 regras do CTO contra IA-slop.

Para cada regra, valida que `deslop()` reescreve corretamente.
Zero mocks.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.anti_ai_slop import deslop, detect_slop


CASES = [
    # ─── Regra 1: Narração de trabalho ─────────────
    ("Verifiquei seu cadastro. Seu plano é 700 Mega.",
     ["Verifiquei"], "Seu plano é 700 Mega.", "narração"),
    ("Consultei o sistema e identifiquei sua fatura pendente.",
     ["Consultei"], "fatura pendente", "narração"),
    ("Analisei as informações. A queda foi no nó 12.",
     ["Analisei"], "A queda foi no nó 12.", "narração"),

    # ─── Regra 2: Confirmações vazias ─────────────
    ("Entendi. Sua instalação está agendada para amanhã.",
     ["Entendi"], "instalação", "confirmação vazia"),
    ("Compreendo. O pagamento foi identificado.",
     ["Compreendo"], "pagamento", "confirmação vazia"),
    ("Perfeito. A conexão já normalizou.",
     ["Perfeito"], "normalizou", "confirmação vazia"),
    ("Claro. Vou enviar a segunda via.",
     ["Claro"], "segunda via", "confirmação vazia"),

    # ─── Regra 3: Explicação excessiva ─────────────
    ("Sua solicitação foi recebida e será encaminhada para a equipe.",
     ["Sua solicitação"], "Abri o chamado", "explica demais"),

    # ─── Regra 4: Manual de instruções ─────────────
    ("Para prosseguir com sua solicitação, será necessário realizar os seguintes procedimentos. Preciso do CPF.",
     ["Para prosseguir"], "Preciso", "manual"),

    # ─── Regra 6: Repetir pergunta ─────────────
    ("Entendo que você está sem internet. Vamos resolver agora.",
     ["Entendo que você está"], "Vamos resolver", "rephrase"),

    # ─── Regra 7: Corporativas ─────────────
    ("Agradecemos o seu contato. Sua satisfação é muito importante para nós.",
     ["Agradecemos", "satisfação"], "", "corporativa"),

    # ─── Regra 9: Excessivamente educada ─────────────
    ("Peço gentilmente que aguarde mais alguns instantes enquanto realizo a verificação.",
     ["gentilmente"], "Só um instante", "excessivamente educado"),

    # ─── Regra 10: Empatia genérica ─────────────
    ("Entendo sua frustração. Vamos resolver isso.",
     ["frustração"], "Vamos resolver", "empatia genérica"),
    ("Lamento o ocorrido. A equipe está atuando.",
     ["Lamento"], "equipe está atuando", "empatia genérica"),

    # ─── Regra 12: Parecer inteligente ─────────────
    ("Após análise aprofundada do cenário apresentado, encontrei a causa.",
     ["Após análise aprofundada"], "encontrei a causa", "pretensão"),

    # ─── Regra 13: Blacklist ─────────────
    ("Entendo sua solicitação. Como posso ajudar?",
     [], "", "blacklist"),
    ("Estou aqui para ajudar. Em que posso ajudar?",
     ["Estou aqui"], "", "blacklist"),
]


def main():
    fails = 0
    for i, (inp, must_be_gone, must_contain, kind) in enumerate(CASES, 1):
        out = deslop(inp)
        ok_gone = all(g.lower() not in out.lower() for g in must_be_gone)
        ok_contain = (must_contain.lower() in out.lower()) if must_contain else True
        ok = ok_gone and ok_contain
        flag = "✅" if ok else "❌"
        print(f"{flag} [{kind:22}] {inp[:60]!r}")
        print(f"   → {out!r}")
        if not ok:
            print(f"   FAIL: gone={[g for g in must_be_gone if g.lower() in out.lower()]} contain_missing={must_contain if not ok_contain else None}")
            fails += 1
    print(f"\n=== {len(CASES)-fails}/{len(CASES)} ===")
    if fails:
        sys.exit(1)


def test_idempotent():
    print("\n[idempotência] deslop(deslop(x)) == deslop(x)")
    samples = [c[0] for c in CASES[:6]]
    for s in samples:
        o1 = deslop(s)
        o2 = deslop(o1)
        if o1 != o2:
            print(f"  ❌ não-idempotente: {s!r}")
            print(f"     o1: {o1!r}")
            print(f"     o2: {o2!r}")
            sys.exit(1)
    print("  ✅ idempotente em todas as amostras")


def test_no_destroy_clean_text():
    print("\n[preservação] texto limpo não é alterado")
    clean = [
        "Seu plano é 700 Mega.",
        "Existe uma fatura pendente.",
        "A instalação ficou para amanhã entre 13h e 18h.",
        "Você tem razão em cobrar isso. Vamos resolver.",
        "Encontrei a causa. A equipe está atuando.",
    ]
    for c in clean:
        out = deslop(c)
        # Aceitamos pequenas mudanças (whitespace), mas conteúdo igual
        words_in = set(c.lower().split())
        words_out = set(out.lower().split())
        common = words_in & words_out
        if len(common) / max(len(words_in), 1) < 0.8:
            print(f"  ❌ destruiu: {c!r} → {out!r}")
            sys.exit(1)
        print(f"  ✅ {c!r} → {out!r}")


def test_detect_slop():
    print("\n[detect_slop] lista violações sem reescrever")
    bad = "Verifiquei seu cadastro. Entendi sua solicitação. Agradecemos o contato."
    vio = detect_slop(bad)
    assert len(vio) >= 3, f"esperava ≥3 violações, got {vio}"
    print(f"  ✅ detectou {len(vio)} violações: {vio[:3]}")


if __name__ == "__main__":
    main()
    test_idempotent()
    test_no_destroy_clean_text()
    test_detect_slop()
    print("\n=== ALL TESTS PASSED ✅ ===")
