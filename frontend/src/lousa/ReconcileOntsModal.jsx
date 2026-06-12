/**
 * ReconcileOntsModal — Lousa Admin
 * --------------------------------
 * Botão "Validar ONTs" abre este modal. Cruza estoque (empresa/técnico)
 * com a OLT em tempo real. Para cada ONT cuja serial/MAC aparecer ativa
 * em algum assinante, faz a baixa do técnico/empresa e marca instalada
 * no cliente real (com auditoria em client_equipment_history).
 *
 * Pedido CTO 12/06/2026.
 */
import React from "react";

const overlayStyle = {
  position: "fixed", inset: 0, zIndex: 1000,
  background: "rgba(0,0,0,.55)",
  display: "flex", alignItems: "center", justifyContent: "center",
  padding: 20,
};

const boxStyle = {
  width: "min(720px, 96vw)",
  maxHeight: "90vh", overflowY: "auto",
  background: "var(--bg-surface, #fff)",
  borderRadius: 12,
  boxShadow: "0 24px 60px rgba(0,0,0,.35)",
  padding: 24,
};

const btnPrimary = {
  padding: "10px 18px",
  background: "#0d9488", color: "#fff",
  border: "none", borderRadius: 8,
  fontWeight: 700, cursor: "pointer",
};
const btnGhost = {
  padding: "10px 18px",
  background: "transparent", color: "#475569",
  border: "1px solid #cbd5e1", borderRadius: 8,
  fontWeight: 600, cursor: "pointer",
};

const pill = (bg, color = "#fff") => ({
  display: "inline-block", padding: "2px 8px",
  borderRadius: 999, background: bg, color,
  fontSize: 10, fontWeight: 700,
});

export default function ReconcileOntsModal({ busy, result, error, onClose, onRun }) {
  return (
    <div data-testid="reconcile-onts-modal" style={overlayStyle} onClick={onClose}>
      <div style={boxStyle} onClick={(e) => e.stopPropagation()}>
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "center", marginBottom: 16,
        }}>
          <div>
            <h2 style={{ fontSize: 18, fontWeight: 800, margin: 0 }}>
              Validar ONTs contra a OLT
            </h2>
            <p style={{ fontSize: 12, color: "#64748b", margin: "4px 0 0" }}>
              Cruza estoque (empresa + técnico) com a OLT em tempo real.
            </p>
          </div>
          <button
            onClick={onClose}
            data-testid="reconcile-close-btn"
            style={{
              padding: "6px 12px", fontSize: 12, fontWeight: 700,
              border: "1px solid #cbd5e1", background: "#fff",
              color: "#475569", borderRadius: 6, cursor: "pointer",
            }}
          >Fechar ✕</button>
        </div>

        {!result && !error && !busy && (
          <div data-testid="reconcile-intro">
            <p style={{ fontSize: 13, lineHeight: 1.55, color: "#334155" }}>
              Esta ação vai:
            </p>
            <ol style={{ fontSize: 13, lineHeight: 1.7, color: "#334155",
                          paddingLeft: 20, marginTop: 4 }}>
              <li>Atualizar o cache da SmartOLT via API live.</li>
              <li>Verificar cada ONT em estoque (empresa/técnico) contra
                a OLT por <strong>SN</strong> e <strong>MAC</strong>.</li>
              <li>Se a ONT estiver de fato instalada em um cliente real,
                fazer <strong>baixa automática do técnico/empresa</strong>
                {" "}e <strong>transferir pro cliente</strong> com auditoria.</li>
            </ol>
            <div style={{
              marginTop: 16, padding: 12, background: "#fef3c7",
              border: "1px solid #fde68a", borderRadius: 8,
              fontSize: 12, color: "#92400e",
            }}>
              ⚠ Pode levar até 30s dependendo do volume de ONUs. Não feche
              a janela até concluir.
            </div>
            <div style={{ marginTop: 20, display: "flex", gap: 10,
                            justifyContent: "flex-end" }}>
              <button onClick={onClose} style={btnGhost}
                      data-testid="reconcile-cancel-btn">
                Cancelar
              </button>
              <button onClick={onRun} style={btnPrimary}
                      data-testid="reconcile-run-btn">
                Iniciar validação
              </button>
            </div>
          </div>
        )}

        {busy && (
          <div data-testid="reconcile-busy" style={{
            padding: 30, textAlign: "center", color: "#475569",
          }}>
            <div style={{
              fontSize: 24, marginBottom: 8,
              animation: "spin 1.2s linear infinite",
              display: "inline-block",
            }}>⏳</div>
            <p style={{ fontWeight: 700, margin: 0 }}>
              Sincronizando OLT e validando estoque…
            </p>
            <p style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
              Aguarde, não feche esta janela.
            </p>
          </div>
        )}

        {error && (
          <div data-testid="reconcile-error" style={{
            padding: 16, background: "#fef2f2",
            border: "1px solid #fecaca", borderRadius: 8,
            color: "#991b1b", fontSize: 13,
          }}>
            <strong>Erro na validação:</strong>
            <p style={{ marginTop: 6, fontFamily: "ui-monospace, monospace" }}>
              {String(error)}
            </p>
            <div style={{ marginTop: 14, display: "flex",
                            justifyContent: "flex-end" }}>
              <button onClick={onClose} style={btnGhost}>Fechar</button>
            </div>
          </div>
        )}

        {result && (
          <div data-testid="reconcile-result">
            <div style={{
              display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 16,
            }}>
              <Stat label="Verificadas" value={result.checked}
                    color="#0f172a" />
              <Stat label="Reconciliadas" value={result.reconciled_count}
                    color={result.reconciled_count > 0 ? "#16a34a" : "#94a3b8"} />
              <Stat label="Sem alteração" value={result.no_change_count}
                    color="#64748b" />
              {result.errors_count > 0 && (
                <Stat label="Erros" value={result.errors_count} color="#dc2626" />
              )}
            </div>

            {result.smartolt_sync && (
              <div style={{
                fontSize: 11, color: "#64748b", marginBottom: 12,
              }}>
                {result.smartolt_sync.skipped
                  ? `⚠ SmartOLT sync pulado: ${result.smartolt_sync.reason || "configuração ausente"}`
                  : `✓ OLT sincronizada: ${result.smartolt_sync.total || 0} ONUs `
                    + `(${result.smartolt_sync.inserted || 0} novos, `
                    + `${result.smartolt_sync.updated || 0} atualizados)`}
              </div>
            )}

            {result.reconciled?.length > 0 && (
              <div data-testid="reconcile-list" style={{ marginTop: 12 }}>
                <h3 style={{ fontSize: 13, fontWeight: 800, marginBottom: 8 }}>
                  ONTs transferidas pro cliente:
                </h3>
                <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {result.reconciled.map((r, idx) => (
                    <li key={idx} style={{
                      padding: "10px 12px", marginBottom: 6,
                      background: "#f0fdf4", border: "1px solid #bbf7d0",
                      borderRadius: 8, fontSize: 12,
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between",
                                      gap: 10 }}>
                        <div>
                          <strong style={{ fontFamily: "ui-monospace, monospace" }}>
                            {r.mac || r.sn || "?"}
                          </strong>
                          <span style={pill("#0d9488")}>
                            {r.to?.client_name || r.to?.client_id}
                          </span>
                        </div>
                        <div style={{ fontSize: 11, color: "#475569" }}>
                          {r.olt_status} · {r.olt_name}
                        </div>
                      </div>
                      <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                        Origem: {r.from?.type === "tecnico"
                          ? `técnico ${r.from?.tech_name || r.from?.id}`
                          : "estoque empresa"}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {result.reconciled_count === 0 && result.no_change_count > 0 && (
              <div style={{
                padding: 12, background: "#f1f5f9",
                border: "1px solid #cbd5e1", borderRadius: 8,
                fontSize: 12, color: "#475569",
              }}>
                ✓ Nenhuma divergência encontrada. Todas as ONTs em estoque
                estão corretamente fora de cliente na OLT.
              </div>
            )}

            <div style={{ marginTop: 18, display: "flex",
                            justifyContent: "flex-end" }}>
              <button onClick={onClose} style={btnPrimary}
                      data-testid="reconcile-done-btn">
                Concluir
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div style={{
      padding: "8px 14px", background: "#fff",
      border: "1px solid #e2e8f0", borderRadius: 8, minWidth: 100,
    }}>
      <div style={{ fontSize: 22, fontWeight: 800, color }}>
        {value ?? 0}
      </div>
      <div style={{ fontSize: 10, fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: 0.5, color: "#94a3b8" }}>
        {label}
      </div>
    </div>
  );
}
