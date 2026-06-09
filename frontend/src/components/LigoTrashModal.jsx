/* =============================================================
   LigoTrashModal — Modal de Lixeira compartilhada (iter215bk)
   Usado tanto no "Mapa Interativo" (RedeIaMap) quanto no
   "Documentação / As-Built" (LigoMapsPanel).

   Props:
     - data: { assets, cables }     // resposta de GET /api/ligo-maps/trash
     - onRestore: (kind, id) => Promise<void>
     - onClose: () => void
============================================================= */
import React from "react";
import { Trash2, Undo2 } from "lucide-react";

const TYPE_LABELS = {
  cto: "CTO", ceo: "CEO", pop: "POP",
  splitter: "Splitter", post: "Poste", junction: "Junção",
};

export default function LigoTrashModal({ data, onRestore, onClose }) {
  const items = [
    ...((data?.assets) || []).map((a) => ({ ...a, _kind: "asset" })),
    ...((data?.cables) || []).map((c) => ({ ...c, _kind: "cable" })),
  ];

  return (
    <div
      onClick={onClose}
      data-testid="ligo-trash-overlay"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,.6)",
        zIndex: 2000, display: "flex", alignItems: "center",
        justifyContent: "center", padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        data-testid="ligo-trash-modal"
        style={{
          background: "#fff", borderRadius: 12, padding: 20,
          maxWidth: 720, width: "100%", maxHeight: "85vh",
          overflow: "auto", boxShadow: "0 24px 64px rgba(0,0,0,.4)",
          fontFamily: "Inter, system-ui, sans-serif",
        }}
      >
        <div
          style={{
            display: "flex", justifyContent: "space-between",
            alignItems: "center", marginBottom: 14,
          }}
        >
          <h2
            style={{
              margin: 0, color: "#4b1d7a", fontSize: 18, fontWeight: 700,
              display: "flex", alignItems: "center", gap: 8,
            }}
          >
            <Trash2 size={18} /> Lixeira ({items.length})
          </h2>
          <button
            data-testid="ligo-trash-close"
            onClick={onClose}
            style={{
              background: "transparent", border: "none",
              cursor: "pointer", fontSize: 22, color: "#64748b",
              lineHeight: 1, padding: "0 8px",
            }}
          >×</button>
        </div>
        <div style={{ fontSize: 12, color: "#64748b", marginBottom: 12 }}>
          Aqui ficam os últimos 50 ativos/cabos apagados. Clique
          em <strong>Restaurar</strong> pra trazer de volta.
        </div>
        {items.length === 0 ? (
          <div
            data-testid="ligo-trash-empty"
            style={{ padding: 30, textAlign: "center", color: "#64748b" }}
          >
            Lixeira vazia.
          </div>
        ) : (
          <table
            style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}
          >
            <thead>
              <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                <th style={{ padding: "8px 10px", fontWeight: 700 }}>Tipo</th>
                <th style={{ padding: "8px 10px", fontWeight: 700 }}>Nome</th>
                <th style={{ padding: "8px 10px", fontWeight: 700 }}>Apagado em</th>
                <th style={{ padding: "8px 10px", fontWeight: 700 }}>Por</th>
                <th style={{ padding: "8px 10px" }}></th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr
                  key={`${it._kind}-${it.id}`}
                  data-testid={`ligo-trash-row-${it.id}`}
                  style={{ borderTop: "1px solid #e2e8f0" }}
                >
                  <td
                    style={{
                      padding: "8px 10px", textTransform: "uppercase",
                      fontWeight: 700, color: "#475569", fontSize: 10,
                    }}
                  >
                    {it._kind === "asset"
                      ? (TYPE_LABELS[it.type] || it.type)
                      : `Cabo ${it.fibers || ""}FO`}
                  </td>
                  <td style={{ padding: "8px 10px", fontWeight: 600 }}>
                    {it.label || "—"}
                  </td>
                  <td
                    style={{
                      padding: "8px 10px", color: "#64748b", fontSize: 12,
                    }}
                  >
                    {it.deleted_at
                      ? new Date(it.deleted_at).toLocaleString("pt-BR")
                      : "—"}
                  </td>
                  <td
                    style={{
                      padding: "8px 10px", color: "#64748b", fontSize: 12,
                    }}
                  >
                    {it.deleted_by || "—"}
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right" }}>
                    <button
                      data-testid={`ligo-trash-restore-${it.id}`}
                      onClick={() => onRestore(it._kind, it.id)}
                      style={{
                        padding: "5px 12px", fontSize: 11,
                        background: "#f28c28", color: "#fff",
                        border: "none", borderRadius: 5,
                        fontWeight: 700, cursor: "pointer",
                        display: "inline-flex", alignItems: "center", gap: 4,
                      }}
                    >
                      <Undo2 size={11} /> Restaurar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
