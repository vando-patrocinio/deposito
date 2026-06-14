"""
Universo Ligo V2 — Módulo de Fundação.

Implementa a infraestrutura técnica do Universo Ligo conforme aprovado na
trilogia FASE A.1 (Manifesto + Economia + Comunidade).

REGRAS INEGOCIÁVEIS (FASE A · CEO):
1. Não quebrar nenhuma funcionalidade existente.
2. Não alterar layouts, fluxos ou telas atuais.
3. Não remover estruturas legadas sem migração.
4. Tudo reversível via feature flag USE_UNIVERSO_LIGO_V2.
5. Toda mudança auditável em `universo_ligo_migration_log`.
6. Zero mocks · zero dados fabricados.

Este módulo NÃO substitui o legado. Ele COEXISTE com `services/universo_ligo.py`
até a Fase B (migração aprovada). Apenas APIs novas devem importar daqui.
"""
__version__ = "2.0.0-phase-a"
