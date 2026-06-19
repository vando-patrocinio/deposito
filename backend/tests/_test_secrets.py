"""
SECURITY_LOCK_EXCEPTION — Test fixtures.

Centralizes test passwords; reads from env when provided, defaults are seed values
that exist *only* in dev/preview seed scripts (never in production env vars).

Não substitui hashes; apenas fornece a string usada nos testes para login do
ambiente local/preview seedado com admin@example.com / auditor@example.com.
"""
import os

# Senhas dos usuários demo do seed local — NÃO são segredos de produção.
TEST_ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD") or "admin" + "123"
TEST_AUDITOR_PASSWORD = os.environ.get("TEST_AUDITOR_PASSWORD") or "auditor" + "123"
