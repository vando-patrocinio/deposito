/**
 * SentimentDashboardCard.js — Sentimento das conversas (extraído de stickers)
 *
 * Mostra:
 *  - Score geral (-1 a +1)
 *  - Distribuição por tom (positivo/neutro/negativo)
 *  - Top emoções com contagem
 *  - Timeline com barras empilhadas
 *  - Telefones com múltiplos stickers negativos (alerta de insatisfação)
 */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import { Smile, AlertTriangle, RefreshCw, Loader2, TrendingUp, TrendingDown, Heart } from "lucide-react";

const PERIODS = [
  { label: "7 dias", value: 7 },
  { label: "30 dias", value: 30 },
  { label: "90 dias", value: 90 },
];

const TONE_COLOR = {
  positive: "#16a34a",
  neutral:  "#94a3b8",
  negative: "#dc2626",
};

const TONE_BG = {
  positive: "#dcfce7",
  neutral:  "#f1f5f9",
  negative: "#fee2e2",
};

export default function SentimentDashboardCard() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api._client.get(`/central-ia/dashboard/sentiment?days=${days}`);
      setData(r.data);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  // ScoreVisual: emoji + cor baseado no score
  const scoreEmoji = (s) => {
    if (s >= 0.5) return "";
    if (s >= 0.15) return "";
    if (s >= -0.15) return "";
    if (s >= -0.5) return "";
    return "";
  };
  const scoreLabel = (s) => {
    if (s >= 0.5) return "Excelente";
    if (s >= 0.15) return "Positivo";
    if (s >= -0.15) return "Neutro";
    if (s >= -0.5) return "Negativo";
    return "Crítico";
  };
  const scoreColor = (s) => {
    if (s >= 0.15) return TONE_COLOR.positive;
    if (s >= -0.15) return TONE_COLOR.neutral;
    return TONE_COLOR.negative;
  };

  return (
    <Card title={null} style={{ padding: 0, overflow: "hidden" }}>
      <div style={{
        padding: "14px 18px",
        background: "linear-gradient(135deg, #ec4899 0%, #be185d 100%)",
        color: "#fdf2f8", display: "flex", alignItems: "center",
        justifyContent: "space-between", flexWrap: "wrap", gap: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Heart size={18} color="#fce7f3" fill="#fce7f3" />
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }} data-testid="sentiment-card-title">
            Sentimento dos Clientes
          </h3>
          <span style={{ fontSize: 10, opacity: 0.8, fontStyle: "italic" }}>
            via stickers do WhatsApp
          </span>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {PERIODS.map(p => (
            <button
              key={p.value}
              onClick={() => setDays(p.value)}
              data-testid={`sentiment-period-${p.value}`}
              style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 600,
                background: days === p.value ? "white" : "rgba(255,255,255,0.16)",
                color: days === p.value ? "#be185d" : "white",
                border: "none", borderRadius: 6, cursor: "pointer",
              }}
            >
              {p.label}
            </button>
          ))}
          <button onClick={load} data-testid="sentiment-reload" style={{
            padding: "4px 8px",
            background: "rgba(255,255,255,0.16)",
            color: "white", border: "none", borderRadius: 6, cursor: "pointer",
          }} title="Recarregar">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      <div style={{ padding: 18 }}>
        {loading && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", color: "#64748b" }}>
            <Loader2 size={14} className="animate-spin" /> Carregando…
          </div>
        )}

        {!loading && data && data.total_stickers === 0 && (
          <div style={{
            padding: 16, textAlign: "center", background: "#fdf2f8",
            borderRadius: 10, border: "1px dashed #fbcfe8",
            color: "#9d174d", fontSize: 13,
          }} data-testid="sentiment-empty">
            Nenhum sticker registrado ainda neste período.<br/>
            <span style={{ fontSize: 11, color: "#be185d", opacity: 0.7 }}>
              Quando clientes mandarem figurinhas pela Isabella, a análise emocional aparece aqui.
            </span>
          </div>
        )}

        {!loading && data && data.total_stickers > 0 && (
          <>
            {/* Score em destaque */}
            <div style={{
              display: "flex", gap: 14, alignItems: "center", marginBottom: 14,
              padding: 14, borderRadius: 12,
              background: "linear-gradient(135deg, #fdf2f8, #fce7f3)",
              border: "1px solid #fbcfe8",
            }} data-testid="sentiment-score-block">
              <div style={{ fontSize: 48, lineHeight: 1 }}>
                {scoreEmoji(data.sentiment_score)}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 10, fontWeight: 800, color: "#be185d",
                  textTransform: "uppercase", letterSpacing: ".05em" }}>
                  Score de Sentimento
                </div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                  <span data-testid="sentiment-score-value" style={{
                    fontSize: 32, fontWeight: 800,
                    color: scoreColor(data.sentiment_score),
                    fontVariantNumeric: "tabular-nums",
                  }}>
                    {data.sentiment_score > 0 ? "+" : ""}{data.sentiment_score.toFixed(2)}
                  </span>
                  <span style={{ fontSize: 14, fontWeight: 700,
                    color: scoreColor(data.sentiment_score) }}>
                    {scoreLabel(data.sentiment_score)}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
                  Baseado em <strong>{data.total_stickers}</strong> stickers nos últimos {data.days} dias · escala -1 a +1
                </div>
              </div>
            </div>

            {/* Tom: positivo / neutro / negativo */}
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 14,
            }}>
              {[
                { key: "positive", label: "Positivo", icon: <TrendingUp size={16} /> },
                { key: "neutral",  label: "Neutro",   icon: <Smile size={16} /> },
                { key: "negative", label: "Negativo", icon: <TrendingDown size={16} /> },
              ].map(t => {
                const count = data.by_tone[t.key] || 0;
                const pct = data.total_stickers > 0 ? (count / data.total_stickers * 100).toFixed(0) : 0;
                return (
                  <div key={t.key} style={{
                    padding: 10, background: TONE_BG[t.key], borderRadius: 10,
                    border: `1px solid ${TONE_COLOR[t.key]}55`,
                    display: "flex", alignItems: "center", gap: 8,
                  }} data-testid={`sentiment-tone-${t.key}`}>
                    <div style={{ color: TONE_COLOR[t.key] }}>{t.icon}</div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 10, color: TONE_COLOR[t.key], fontWeight: 700, textTransform: "uppercase" }}>
                        {t.label}
                      </div>
                      <div style={{ fontSize: 18, fontWeight: 800, color: TONE_COLOR[t.key], lineHeight: 1.1 }}>
                        {count}
                        <span style={{ fontSize: 11, marginLeft: 4, opacity: 0.7 }}>· {pct}%</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Emoções */}
            <div style={{ marginBottom: 14 }} data-testid="sentiment-emotions">
              <div style={{ fontSize: 12, fontWeight: 600, color: "#475569", marginBottom: 8 }}>
                Top emoções
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {data.by_emotion.map(e => (
                  <div key={e.emotion} style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    padding: "5px 10px", borderRadius: 999,
                    background: TONE_BG[e.tone],
                    border: `1px solid ${TONE_COLOR[e.tone]}55`,
                    fontSize: 12, fontWeight: 600, color: TONE_COLOR[e.tone],
                  }} data-testid={`sentiment-emo-${e.emotion}`}>
                    <span style={{ fontSize: 14 }}>{e.emoji}</span>
                    {e.label}
                    <span style={{ fontSize: 11, fontWeight: 800, marginLeft: 2 }}>
                      {e.count}
                    </span>
                    <span style={{ fontSize: 10, opacity: 0.7 }}>· {e.pct}%</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Timeline (barras empilhadas) */}
            {data.timeline.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#475569", marginBottom: 8 }}>
                  Evolução
                </div>
                <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 80,
                  padding: "8px 4px", background: "#f8fafc", borderRadius: 8 }}>
                  {data.timeline.map(d => {
                    const total = d.positive + d.neutral + d.negative;
                    return (
                      <div key={d.date}
                          title={`${d.date}: +${d.positive} ◐${d.neutral} -${d.negative}`}
                          style={{
                            flex: 1, display: "flex", flexDirection: "column-reverse",
                            gap: 1, minWidth: 8, minHeight: total > 0 ? 4 : 0,
                          }}>
                        {d.negative > 0 && (
                          <div style={{ background: TONE_COLOR.negative,
                            height: `${(d.negative / Math.max(total, 1)) * 64}px`,
                            borderRadius: "2px 2px 0 0" }} />
                        )}
                        {d.neutral > 0 && (
                          <div style={{ background: TONE_COLOR.neutral,
                            height: `${(d.neutral / Math.max(total, 1)) * 64}px` }} />
                        )}
                        {d.positive > 0 && (
                          <div style={{ background: TONE_COLOR.positive,
                            height: `${(d.positive / Math.max(total, 1)) * 64}px`,
                            borderRadius: total === d.positive ? "2px 2px 0 0" : "0" }} />
                        )}
                      </div>
                    );
                  })}
                </div>
                <div style={{ display: "flex", justifyContent: "space-between",
                  fontSize: 9, color: "#94a3b8", marginTop: 4 }}>
                  <span>{data.timeline[0]?.date}</span>
                  <span>{data.timeline[data.timeline.length - 1]?.date}</span>
                </div>
              </div>
            )}

            {/* Telefones com stickers negativos */}
            {data.top_negative_phones.length > 0 && (
              <div style={{
                padding: 12, background: "#fef2f2", borderRadius: 10,
                border: "1px solid #fecaca",
              }} data-testid="sentiment-hot-phones">
                <div style={{ display: "flex", alignItems: "center", gap: 6,
                  fontSize: 12, fontWeight: 700, color: "#991b1b", marginBottom: 6 }}>
                  <AlertTriangle size={13} /> Atenção: clientes com múltiplos stickers negativos
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {data.top_negative_phones.map(p => (
                    <span key={p.phone} style={{
                      fontSize: 11, padding: "3px 8px", borderRadius: 999,
                      background: "white", color: "#991b1b", fontWeight: 600,
                      fontFamily: "JetBrains Mono, monospace",
                      border: "1px solid #fecaca",
                    }}>
                      {p.phone} · {p.count}x 
                    </span>
                  ))}
                </div>
                <div style={{ fontSize: 11, color: "#7f1d1d", marginTop: 6, lineHeight: 1.4 }}>
                  Esses clientes mostraram insatisfação. Considere uma ligação proativa ou desconto retenção.
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
