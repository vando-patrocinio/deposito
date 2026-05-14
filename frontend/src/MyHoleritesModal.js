import React, { useCallback, useEffect, useState } from "react";
import { Button } from "@/ui";
import { api } from "@/api";

const MONTHS = [
  "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
  "Jul", "Ago", "Set", "Out", "Nov", "Dez",
];

function fmtBRL(v) {
  const n = Number(v || 0);
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export default function MyHoleritesModal({ collaboratorId, onClose }) {
  const [data, setData] = useState({ collaborator: {}, items: [], count: 0 });
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.publicHoleritesList(collaboratorId);
      setData(r);
    } finally { setLoading(false); }
  }, [collaboratorId]);

  useEffect(() => { reload(); }, [reload]);

  const items = (data.items || []).filter((h) => {
    if (!filter) return true;
    const q = filter.toLowerCase();
    return (
      String(h.competence_year).includes(q) ||
      MONTHS[h.competence_month - 1]?.toLowerCase().includes(q) ||
      String(fmtBRL(h.net)).toLowerCase().includes(q)
    );
  });

  function viewPDF(h) {
    const url = api.publicHoleriteFileUrl(collaboratorId, h.id);
    window.open(url, "_blank");
  }

  return (
    <div onClick={onClose} data-testid="my-holerites-modal" style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.7)", zIndex: 100,
      padding: 12, overflowY: "auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        maxWidth: 720, margin: "20px auto",
        background: "white", borderRadius: 16, padding: 18,
        boxShadow: "0 20px 50px rgba(0,0,0,.25)",
      }}>
        {/* Header */}
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "flex-start", marginBottom: 14,
        }}>
          <div>
            <div style={{
              fontSize: 11, fontWeight: 800, color: "#64748b",
              textTransform: "uppercase", letterSpacing: ".5px",
            }}>Meus holerites</div>
            <h2 style={{ margin: 0, fontSize: 19, fontWeight: 900, color: "#0f172a" }}>
              Olá, {data.collaborator?.name?.split(" ")[0] || "colaborador"}
            </h2>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
              {data.count || 0} {(data.count || 0) === 1 ? "holerite disponível" : "holerites disponíveis"}
            </div>
          </div>
          <button onClick={onClose} data-testid="my-holerites-close"
                  style={{
                    width: 34, height: 34, borderRadius: "50%",
                    border: "1px solid #e2e8f0", background: "white",
                    cursor: "pointer", fontSize: 18, color: "#64748b",
                  }}>×</button>
        </div>

        {/* Filtro */}
        <input
          type="text" placeholder="Filtrar por ano, mês ou valor…"
          value={filter} onChange={(e) => setFilter(e.target.value)}
          data-testid="my-holerites-filter"
          style={{
            width: "100%", padding: "9px 12px", borderRadius: 10,
            border: "1px solid #e2e8f0", fontSize: 13, marginBottom: 14,
            outline: "none",
          }}
        />

        {/* List */}
        {loading ? (
          <div style={{ padding: 30, textAlign: "center", color: "#64748b" }}>
            Carregando…
          </div>
        ) : items.length === 0 ? (
          <div style={{
            padding: 36, textAlign: "center", color: "#64748b",
            border: "1px dashed #e2e8f0", borderRadius: 12,
          }}>
            <div style={{ fontSize: 28, marginBottom: 6 }}>🧾</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>
              Nenhum holerite disponível ainda
            </div>
            <div style={{ fontSize: 12, marginTop: 4 }}>
              Quando o RH publicar seu holerite, ele aparecerá aqui.
            </div>
          </div>
        ) : (
          <div data-testid="my-holerites-list" style={{ display: "grid", gap: 8 }}>
            {items.map((h) => (
              <HoleriteCard key={h.id} h={h} onView={() => viewPDF(h)} />
            ))}
          </div>
        )}

        <div style={{
          marginTop: 18, padding: 10, borderRadius: 8,
          background: "#f1f5f9", color: "#475569",
          fontSize: 11, lineHeight: 1.5,
        }}>
          <strong>🔒 LGPD:</strong> Esses documentos são confidenciais e
          servidos apenas para você. Todo acesso é registrado para auditoria.
          Em caso de divergência, fale com seu RH.
        </div>
      </div>
    </div>
  );
}

function HoleriteCard({ h, onView }) {
  const month = MONTHS[h.competence_month - 1] || "?";
  return (
    <div data-testid={`my-holerite-${h.id}`} style={{
      padding: 12, borderRadius: 12,
      border: "1px solid #e2e8f0", background: "white",
      display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 12,
      alignItems: "center",
    }}>
      <div style={{
        width: 50, height: 50, borderRadius: 10,
        background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
        color: "white", display: "grid", placeItems: "center",
      }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".5px",
            textTransform: "uppercase", opacity: .9 }}>{month}</div>
          <div style={{ fontSize: 13, fontWeight: 900, marginTop: 1 }}>
            {h.competence_year}
          </div>
        </div>
      </div>

      <div>
        <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a" }}>
          {fmtBRL(h.net)}
        </div>
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 1 }}>
          Bruto {fmtBRL(h.gross)} · Descontos {fmtBRL(h.deductions_total || 0)}
        </div>
        {h.viewed_at && (
          <div style={{ fontSize: 10, color: "#16a34a", marginTop: 2, fontWeight: 700 }}>
            ✓ Visualizado
          </div>
        )}
      </div>

      <Button onClick={onView} data-testid={`view-holerite-${h.id}`}>
        Baixar PDF
      </Button>
    </div>
  );
}
