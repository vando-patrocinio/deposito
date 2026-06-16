/**
 * GuardrailIaPanel.jsx — Painel da REGRA GLOBAL — IA TESOUREIRA (CTO 2026-02).
 *
 * Mostra:
 *   - Resumo dos status de autorização IA (quantos fornecedores estão liberados)
 *   - Lista de fornecedores com toggle de autorização (dupla confirmação)
 *   - Tabela de auditoria SHA256 (treasury_guardrail_audit)
 *
 * Regras de UI:
 *   - Antes de autorizar, exige checkbox "Estou autorizando..." + texto canônico.
 *   - PIX precisa estar validado antes de autorizar (botão "Validar PIX").
 *   - Revoke sem confirmação dupla (revogar é sempre seguro).
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  ShieldCheck, ShieldAlert, ShieldOff, FileSearch, Hash,
  Clock, AlertTriangle, KeyRound, Building2, Lock, Unlock, RefreshCw,
} from "lucide-react";
import { treasuryApi, C, DateTimeBR, BRL } from "./api";

const CANON = "Estou autorizando a IA Tesoureira a pagar automaticamente este fornecedor dentro das regras globais.";

export default function GuardrailIaPanel() {
  const [payees, setPayees] = useState([]);
  const [audit, setAudit] = useState({ audit: [], counts: {} });
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [openAuth, setOpenAuth] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const reload = async () => {
    setLoading(true); setErr(null);
    try {
      const [py, au] = await Promise.all([
        treasuryApi.listPayees(),
        treasuryApi.listGuardrailAudit({ limit: 100 }),
      ]);
      setPayees((py.payees || []).filter((p) => p.active !== false));
      setAudit(au);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { reload(); }, [refreshKey]);

  const stats = useMemo(() => ({
    total: payees.length,
    autorizados: payees.filter((p) => p.ia_autorizada).length,
    travados: payees.filter((p) => !p.ia_autorizada).length,
    sem_pix: payees.filter((p) => !p?.validacao_chave_pix?.validated_at).length,
  }), [payees]);

  const c = audit.counts || {};

  return (
    <div data-testid="guardrail-ia-panel" style={{ padding: 20 }}>
      <RegrasOuro />

      <div data-testid="guardrail-stats" style={{
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
        gap: 12, marginBottom: 16,
      }}>
        <StatCard testid="stat-autorizados"
          label="Autorizados p/ IA" value={stats.autorizados}
          sub={`de ${stats.total} fornecedores`}
          icon={ShieldCheck} color={C.green}/>
        <StatCard testid="stat-travados"
          label="Travados (failsafe)" value={stats.travados}
          sub="nenhuma autorização"
          icon={Lock} color={C.amber}/>
        <StatCard testid="stat-blocked"
          label="Bloqueios pela IA" value={c.blocked || 0}
          sub={`de ${c.total || 0} validações`}
          icon={ShieldAlert} color={C.red}/>
        <StatCard testid="stat-overrides"
          label="CEO Overrides" value={c.ceo_override || 0}
          sub="auditoria SHA256"
          icon={KeyRound} color={C.accent}/>
      </div>

      {err && <ErrBox>{err}</ErrBox>}

      <div style={{
        background: C.card, border: `1px solid ${C.border}`,
        borderRadius: 12, padding: 16, marginBottom: 16,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8,
          marginBottom: 12 }}>
          <Building2 size={16} color={C.accent}/>
          <strong style={{ color: C.text, fontSize: 14 }}>
            Autorização por fornecedor
          </strong>
          <button data-testid="btn-reload-guardrail"
            onClick={() => setRefreshKey((k) => k + 1)}
            style={{ ...btnGhost, marginLeft: "auto" }}>
            <RefreshCw size={12}/> Atualizar
          </button>
        </div>
        {loading && <div style={{ color: C.muted }}>Carregando...</div>}
        <div style={{ display: "grid", gap: 6 }}>
          {payees.map((p) => (
            <PayeeRow key={p.payee_id} payee={p}
              onAuthorize={() => setOpenAuth(p)}
              onRevoke={async () => {
                const motivo = window.prompt("Motivo da revogação? (opcional)");
                try {
                  await treasuryApi.revokePayeeIa(p.payee_id, motivo);
                  setRefreshKey((k) => k + 1);
                } catch (e) {
                  alert("Falhou: " + (e?.response?.data?.detail || e.message));
                }
              }}
              onValidatePix={async () => {
                if (!window.confirm(
                  `Confirma que a chave PIX abaixo está correta?\n\n` +
                  `Tipo: ${p.pix_key_type}\nChave: ${p.pix_key}\n\n` +
                  "Em PROD esta validação consulta o DICT Asaas; em homologação confiamos no operador.")) return;
                try {
                  await treasuryApi.validatePayeePix(p.payee_id, {});
                  setRefreshKey((k) => k + 1);
                } catch (e) {
                  alert("Falhou: " + (e?.response?.data?.detail || e.message));
                }
              }}/>
          ))}
          {!loading && payees.length === 0 && (
            <div style={{ color: C.muted, fontSize: 12, padding: 16 }}>
              Nenhum fornecedor cadastrado.
            </div>
          )}
        </div>
      </div>

      <AuditTable rows={audit.audit || []}/>

      {openAuth && <AuthorizeModal payee={openAuth}
        onClose={() => setOpenAuth(null)}
        onSaved={() => { setOpenAuth(null); setRefreshKey((k) => k + 1); }}/>}
    </div>
  );
}


function RegrasOuro() {
  return (
    <div data-testid="regras-ouro" style={{
      background: "#fff7ed", border: "1px solid #fed7aa", color: "#7c2d12",
      borderRadius: 12, padding: 14, marginBottom: 16, fontSize: 12,
      lineHeight: 1.55,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
        marginBottom: 6 }}>
        <ShieldOff size={16}/>
        <strong style={{ fontSize: 13 }}>
          REGRA GLOBAL — IA TESOUREIRA
        </strong>
      </div>
      <div>A IA nasce <strong>travada</strong>. Não tem autonomia. Só pode pagar
      fornecedores aprovados (<code>ia_autorizada=true</code>),
      <strong> 1 pagamento a cada 30 dias</strong>, somente entre
      <strong> 08:00 e 18:00 BRT</strong>, com PIX validado.
      Override CEO pode liberar frequência/janela/valor — <strong>mas nunca</strong>
      pagar fornecedor não autorizado. Na dúvida = bloqueia. Tudo auditado com hash SHA-256.</div>
    </div>
  );
}


function PayeeRow({ payee, onAuthorize, onRevoke, onValidatePix }) {
  const auth = !!payee.ia_autorizada;
  const pixOk = !!payee?.validacao_chave_pix?.validated_at;
  return (
    <div data-testid={`payee-row-${payee.payee_id}`} style={{
      display: "grid",
      gridTemplateColumns: "1fr 90px 110px 130px 200px",
      gap: 10, alignItems: "center", padding: "10px 12px",
      borderRadius: 10, border: `1px solid ${C.border}`,
      background: auth ? "#ecfdf5" : C.cardSoft, fontSize: 12,
    }}>
      <div>
        <div style={{ color: C.text, fontWeight: 700, fontSize: 13 }}>
          {payee.name}
        </div>
        <div style={{ color: C.muted, fontSize: 11 }}>
          {payee.document} · {payee.pix_key_type} {payee.pix_key?.slice(0, 22)}
          {payee.pix_key?.length > 22 ? "…" : ""}
        </div>
      </div>
      <div data-testid={`payee-ia-status-${payee.payee_id}`}>
        {auth
          ? <Badge color={C.green} icon={ShieldCheck}>IA AUTORIZADA</Badge>
          : <Badge color={C.muted} icon={Lock}>TRAVADO</Badge>}
      </div>
      <div data-testid={`payee-pix-status-${payee.payee_id}`}>
        {pixOk
          ? <Badge color={C.blue} icon={ShieldCheck}>PIX validado</Badge>
          : <Badge color={C.amber} icon={AlertTriangle}>PIX a validar</Badge>}
      </div>
      <div style={{ color: C.muted, fontSize: 10, textAlign: "right" }}>
        {auth
          ? <>Liberado em<br/>
              <strong>{DateTimeBR(payee.ia_autorizada_at)}</strong>
            </>
          : payee.ia_autorizada_revoked_at
            ? <>Revogado em<br/>
                <strong>{DateTimeBR(payee.ia_autorizada_revoked_at)}</strong>
              </>
            : "—"}
      </div>
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
        {!pixOk && (
          <button data-testid={`btn-validate-pix-${payee.payee_id}`}
            onClick={onValidatePix} style={btnGhost}>
            <KeyRound size={11}/> Validar PIX
          </button>
        )}
        {auth ? (
          <button data-testid={`btn-revoke-ia-${payee.payee_id}`}
            onClick={onRevoke} style={btnDanger}>
            <ShieldOff size={11}/> Revogar
          </button>
        ) : (
          <button data-testid={`btn-authorize-ia-${payee.payee_id}`}
            onClick={onAuthorize} style={btnPrimary} disabled={!pixOk}>
            <Unlock size={11}/> Autorizar IA
          </button>
        )}
      </div>
    </div>
  );
}


function AuthorizeModal({ payee, onClose, onSaved }) {
  const [cb1, setCb1] = useState(false);
  const [cb2, setCb2] = useState("");
  const [maxAmount, setMaxAmount] = useState(
    payee.max_amount_auto || 500);
  const [motivo, setMotivo] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const canSave = cb1 && cb2.trim() === CANON.trim();

  const submit = async () => {
    if (!canSave) {
      setErr("Marque o checkbox e digite o texto exato de autorização.");
      return;
    }
    setBusy(true); setErr(null);
    try {
      await treasuryApi.authorizePayeeIa(payee.payee_id, {
        confirm_authorization: cb1,
        confirm_text: cb2,
        max_amount_auto: Number(maxAmount) || undefined,
        motivo: motivo || null,
      });
      onSaved();
    } catch (e) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === "string" ? d : (d?.error || e.message));
    } finally { setBusy(false); }
  };

  return (
    <Overlay onClose={onClose} testid="modal-authorize-ia"
      title="Autorizar IA Tesoureira a pagar este fornecedor">
      <div data-testid="authorize-payee-info" style={{
        background: C.cardSoft, border: `1px solid ${C.border}`,
        borderRadius: 10, padding: 12, marginBottom: 14,
      }}>
        <div style={{ fontWeight: 700, color: C.text, fontSize: 14 }}>
          {payee.name}
        </div>
        <div style={{ color: C.muted, fontSize: 11, marginTop: 4 }}>
          {payee.document} · {payee.pix_key_type} {payee.pix_key}
        </div>
        {payee?.validacao_chave_pix?.validated_at && (
          <div style={{ color: C.green, fontSize: 11, marginTop: 4,
            display: "inline-flex", alignItems: "center", gap: 6 }}>
            <ShieldCheck size={12}/> PIX validado em{" "}
            {DateTimeBR(payee.validacao_chave_pix.validated_at)}
          </div>
        )}
      </div>

      <Field label="Valor máximo automático (R$ por pagamento)">
        <input type="number" data-testid="auth-max-amount"
          value={maxAmount} step="0.01"
          onChange={(e) => setMaxAmount(e.target.value)} style={input}/>
      </Field>
      <Field label="Motivo / contexto (opcional, ajuda na auditoria)">
        <input data-testid="auth-motivo" value={motivo}
          onChange={(e) => setMotivo(e.target.value)} style={input}
          placeholder="Contas mensais de energia ratificadas pelo CFO"/>
      </Field>

      <label style={{ display: "flex", gap: 8, marginTop: 14,
        color: C.text, fontSize: 13, alignItems: "flex-start" }}>
        <input type="checkbox" data-testid="auth-checkbox-1"
          checked={cb1} onChange={(e) => setCb1(e.target.checked)}
          style={{ marginTop: 3 }}/>
        <span>Sim, autorizo este fornecedor a receber pagamentos automáticos
        da IA Tesoureira, respeitando todas as regras globais (frequência,
        janela horária, valor máximo, validações).</span>
      </label>

      <div style={{ marginTop: 14 }}>
        <div style={{ color: C.muted, fontSize: 11, marginBottom: 4 }}>
          Digite o texto exato para liberar o botão (anti-impulso):
        </div>
        <div style={{ color: C.text, fontSize: 11, padding: "8px 10px",
          background: "#f1f5f9", border: `1px solid ${C.border}`,
          borderRadius: 6, fontFamily: "monospace", marginBottom: 6 }}>
          {CANON}
        </div>
        <textarea data-testid="auth-confirm-text" value={cb2}
          onChange={(e) => setCb2(e.target.value)}
          rows={3} style={{ ...input, fontFamily: "monospace", fontSize: 12 }}
          placeholder="Cole/digite o texto acima exatamente"/>
      </div>

      {err && <ErrBox>{String(err)}</ErrBox>}

      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button data-testid="btn-confirm-authorize"
          onClick={submit} disabled={!canSave || busy}
          style={{ ...btnPrimary, flex: 1,
            opacity: (canSave && !busy) ? 1 : 0.45 }}>
          {busy ? "Autorizando..." : "Autorizar IA para este fornecedor"}
        </button>
        <button onClick={onClose} style={btnGhost}>Cancelar</button>
      </div>
    </Overlay>
  );
}


function AuditTable({ rows }) {
  const [filter, setFilter] = useState("all");  // all | blocked | allowed | override
  const filtered = rows.filter((r) => {
    if (filter === "blocked") return r.allowed === false;
    if (filter === "allowed") return r.allowed === true;
    if (filter === "override") return r.ceo_override_applied === true;
    return true;
  });
  return (
    <div data-testid="guardrail-audit-table" style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 12, padding: 16,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
        marginBottom: 12 }}>
        <FileSearch size={16} color={C.accent}/>
        <strong style={{ color: C.text, fontSize: 14 }}>
          Auditoria IA Tesoureira (SHA-256)
        </strong>
        <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
          {[
            ["all", "Todos"], ["blocked", "Bloqueados"],
            ["allowed", "Liberados"], ["override", "CEO Override"],
          ].map(([k, lab]) => (
            <button key={k} data-testid={`audit-filter-${k}`}
              onClick={() => setFilter(k)}
              style={{ ...btnGhost,
                background: filter === k ? C.accent : "transparent",
                color: filter === k ? "white" : C.text,
                border: `1px solid ${filter === k ? C.accent : C.border}` }}>
              {lab}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 && (
        <div style={{ color: C.muted, padding: 20, textAlign: "center",
          fontSize: 12 }}>Sem entradas para este filtro.</div>
      )}

      <div style={{ display: "grid", gap: 6 }}>
        {filtered.map((row) => (
          <div key={row.id || row.hash_auditoria}
            data-testid={`audit-row-${row.id}`}
            style={{
              display: "grid",
              gridTemplateColumns: "150px 1fr 100px 80px 160px",
              gap: 10, alignItems: "center", padding: "8px 10px",
              borderRadius: 8, fontSize: 11,
              background: row.allowed ? "#ecfdf5" : "#fef2f2",
              border: `1px solid ${row.allowed ? "#bbf7d0" : "#fecaca"}`,
            }}>
            <div>
              <Clock size={10} style={{ marginRight: 4,
                verticalAlign: "middle" }}/>
              <span style={{ color: C.text }}>
                {DateTimeBR(row.data_hora_brasilia)}
              </span>
              <div style={{ color: C.muted, fontSize: 9 }}>
                {row.actor} · {row.origin}
              </div>
            </div>
            <div>
              <div style={{ color: C.text, fontWeight: 600 }}>
                {row.payee_name || row.payee_id || "—"}
              </div>
              <div style={{ color: C.muted, fontSize: 10 }}>
                {row.allowed
                  ? (row.ceo_override_applied
                      ? `CEO Override por ${row.ceo_override_by}: ${row.ceo_override_motivo || ""}`
                      : "Validações OK")
                  : `BLOQUEADO: ${(row.blocked_reasons || []).join(", ")}`}
              </div>
            </div>
            <div style={{ color: C.text, fontFamily: "monospace",
              fontWeight: 700, fontSize: 12, textAlign: "right" }}>
              {BRL(row.amount_brl || 0)}
            </div>
            <div>
              {row.allowed
                ? <Badge color={C.green} icon={ShieldCheck}>OK</Badge>
                : <Badge color={C.red} icon={ShieldAlert}>BLOCK</Badge>}
            </div>
            <div style={{ color: C.muted, fontSize: 10,
              fontFamily: "monospace", textAlign: "right" }}>
              <Hash size={10} style={{ verticalAlign: "middle" }}/>
              {" "}{(row.hash_auditoria || "").slice(0, 16)}…
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


function StatCard({ label, value, sub, icon: Icon, color, testid }) {
  return (
    <div data-testid={testid} style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 12, padding: 14,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 6 }}>
        <span style={{ color: C.muted, fontSize: 11, textTransform: "uppercase",
          letterSpacing: 0.6, fontWeight: 600 }}>{label}</span>
        <Icon size={14} color={color}/>
      </div>
      <div style={{ color: C.text, fontSize: 24, fontWeight: 800 }}>{value}</div>
      {sub && <div style={{ color: C.muted, fontSize: 11, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}


function Badge({ children, color, icon: Icon }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 700,
      background: `${color}22`, color, border: `1px solid ${color}55`,
    }}>
      {Icon && <Icon size={10}/>} {children}
    </span>
  );
}


function ErrBox({ children }) {
  return (
    <div style={{ background: "#fee2e2", color: "#991b1b", padding: 10,
      borderRadius: 8, marginBottom: 12, fontSize: 12 }}>{children}</div>
  );
}


function Overlay({ children, onClose, title, testid }) {
  return (
    <div data-testid={testid} style={{ position: "fixed", inset: 0,
      background: "rgba(15,23,42,.45)", zIndex: 9000, display: "flex",
      alignItems: "center", justifyContent: "center" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ background: C.card, padding: 20, borderRadius: 14,
        width: 620, maxWidth: "94vw", maxHeight: "94vh", overflowY: "auto",
        border: `1px solid ${C.border}` }}>
        <div style={{ display: "flex", justifyContent: "space-between",
          marginBottom: 14, alignItems: "center" }}>
          <h3 style={{ color: C.text, margin: 0, fontSize: 16 }}>{title}</h3>
          <button onClick={onClose} data-testid={`${testid}-close`}
            style={{ background: "transparent", border: 0, color: C.muted,
              fontSize: 24, cursor: "pointer" }}>×</button>
        </div>
        {children}
      </div>
    </div>);
}


const Field = ({ label, children }) => (
  <div style={{ marginBottom: 8 }}>
    <div style={{ color: C.muted, fontSize: 11, marginBottom: 3 }}>{label}</div>
    {children}
  </div>
);

const input = { padding: "8px 10px", borderRadius: 8,
  border: `1px solid ${C.border}`, background: C.card, color: C.text,
  fontSize: 13, width: "100%", boxSizing: "border-box" };
const btnPrimary = { background: C.accent, color: "white", border: 0,
  borderRadius: 8, padding: "6px 10px", fontWeight: 700, fontSize: 11,
  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 4 };
const btnGhost = { background: "transparent", color: C.text,
  border: `1px solid ${C.border}`, borderRadius: 8, padding: "4px 10px",
  fontSize: 11, cursor: "pointer", display: "inline-flex", alignItems: "center",
  gap: 4 };
const btnDanger = { background: C.red, color: "white", border: 0,
  borderRadius: 8, padding: "6px 10px", fontWeight: 700, fontSize: 11,
  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 4 };
