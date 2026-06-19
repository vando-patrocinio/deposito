/**
 * QuarantinePromotion — Phase D Add-on · CEO 19/06/2026
 *
 * Tela para gestor revisar as 117 ONUs em quarentena que não foram
 * promovidas automaticamente. Aprovar / Rejeitar / Procurar outro cliente.
 */
import React, { useCallback, useEffect, useState } from "react";
import { client } from "./api";

const fmtPct = (v) =>
  v == null ? "—" : `${(Number(v) * 100).toFixed(0)}%`;

function ConfidencePill({ value }) {
  const v = Number(value || 0);
  const cls = v >= 0.9
    ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
    : v >= 0.75
      ? "bg-amber-500/15 text-amber-300 border-amber-500/30"
      : "bg-rose-500/15 text-rose-300 border-rose-500/30";
  return (
    <span className={`inline-block text-[10px] px-2 py-0.5 rounded-full border font-mono ${cls}`}>
      {fmtPct(v)}
    </span>
  );
}

function SubscriberSearch({ value, onChange, onPick }) {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const doSearch = useCallback(async () => {
    if (!value || value.length < 3) { setResults([]); return; }
    setLoading(true);
    try {
      const r = await client.get(
        `/sprint5/quarantine/search-subscribers?q=${encodeURIComponent(value)}&limit=8`);
      setResults(r.data.items || []);
    } catch (e) {
      setResults([]);
    } finally { setLoading(false); }
  }, [value]);
  useEffect(() => { doSearch(); }, [doSearch]);
  return (
    <div className="mt-2" data-testid="quar-search-block">
      <input
        type="text"
        placeholder="Buscar por nome, PPPoE ou full_name..."
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs"
        data-testid="quar-search-input"
      />
      {loading && (
        <div className="text-[10px] text-slate-500 mt-1">buscando...</div>
      )}
      {!loading && results.length > 0 && (
        <div className="mt-1 max-h-32 overflow-y-auto border border-slate-700 rounded">
          {results.map((s) => (
            <button
              key={s.id}
              onClick={() => onPick(s)}
              className="w-full text-left px-2 py-1 hover:bg-slate-700/50 text-xs"
              data-testid={`quar-search-pick-${s.id}`}
            >
              <div className="font-semibold text-slate-200">{s.name || s.full_name || s.id}</div>
              <div className="text-[10px] text-slate-400 font-mono">
                {s.pppoe_user || "—"} · {s.status}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function CandidateCard({ item, onApprove, onReject, busy }) {
  const ont = item.ont || {};
  const [picked, setPicked] = useState(item.suggestions?.[0] || null);
  const [customQuery, setCustomQuery] = useState("");
  const [reason, setReason] = useState("");
  const [showReject, setShowReject] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  const handleApprove = () => {
    if (!picked) return;
    if (reason.length < 10) return;
    onApprove(ont.id, {
      subscriber_id: picked.subscriber_id,
      confidence: picked.confidence,
      reason,
    });
  };

  const handleReject = () => {
    if (rejectReason.length < 20) return;
    onReject(ont.id, { reason: rejectReason });
  };

  return (
    <div
      className="rounded-lg border border-slate-700 bg-slate-900/60 p-4"
      data-testid={`quar-card-${ont.id}`}
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex-1 min-w-[260px]">
          <div className="text-xs uppercase font-mono text-slate-500">
            {ont.id}
          </div>
          <div className="text-base font-semibold text-slate-100 mt-1 break-all">
            {ont.client_name || "(sem nome)"}
          </div>
          <div className="text-[11px] text-slate-400 mt-1 font-mono">
            SN: {ont.sn} · {ont.model} · {ont.olt_name}/port {ont.port_olt}
            {ont.smartolt_status && ` · ${ont.smartolt_status}`}
          </div>
        </div>
      </div>

      {/* Sugestões */}
      <div className="mt-3">
        <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
          Sugestões automáticas
        </div>
        {(item.suggestions || []).length === 0 && (
          <div className="text-xs text-slate-500 italic">
            Nenhuma sugestão automática. Use a busca abaixo.
          </div>
        )}
        {(item.suggestions || []).map((s) => {
          const isPicked = picked?.subscriber_id === s.subscriber_id;
          return (
            <button
              key={s.subscriber_id}
              onClick={() => setPicked(s)}
              className={`w-full text-left rounded px-2 py-1.5 mb-1 border ${isPicked ? "bg-emerald-500/10 border-emerald-500/40" : "bg-slate-800/40 border-slate-700 hover:bg-slate-800"}`}
              data-testid={`quar-sugg-${ont.id}-${s.subscriber_id}`}
            >
              <div className="flex items-center gap-2 flex-wrap">
                <ConfidencePill value={s.confidence} />
                <span className="text-sm font-semibold text-slate-200">
                  {s.subscriber_name}
                </span>
                <span className="text-[10px] text-slate-500 font-mono">
                  {s.match_path}
                </span>
              </div>
              <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                {s.match_evidence}
              </div>
            </button>
          );
        })}
      </div>

      {/* Busca manual */}
      <SubscriberSearch
        value={customQuery}
        onChange={setCustomQuery}
        onPick={(s) => {
          setPicked({
            subscriber_id: s.id, subscriber_name: s.name || s.full_name,
            confidence: 0.85, match_path: "manual_search",
            match_evidence: `gestor buscou por "${customQuery}"`,
          });
          setCustomQuery("");
        }}
      />

      {/* Picked summary + Approve */}
      {picked && (
        <div className="mt-3 rounded bg-emerald-500/5 border border-emerald-500/30 p-2">
          <div className="text-[10px] uppercase text-emerald-300">
            Vai vincular a:
          </div>
          <div className="text-sm font-semibold text-emerald-100">
            {picked.subscriber_name}
          </div>
          <div className="text-[10px] text-emerald-200/70 font-mono">
            {picked.subscriber_id} · conf {fmtPct(picked.confidence)}
          </div>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Justificativa (≥10 chars) — obrigatório para audit"
            className="w-full mt-2 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs"
            rows={2}
            data-testid={`quar-approve-reason-${ont.id}`}
          />
          <div className="text-[10px] text-slate-500 mt-1">
            {reason.length}/10 chars mínimos
          </div>
        </div>
      )}

      {/* Reject section */}
      {showReject && (
        <div className="mt-3 rounded bg-rose-500/5 border border-rose-500/30 p-2">
          <div className="text-[10px] uppercase text-rose-300">
            Rejeitar (vai para permanent_quarantine)
          </div>
          <textarea
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder="Motivo (≥20 chars) — ex: ONU sem correspondente real"
            className="w-full mt-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs"
            rows={2}
            data-testid={`quar-reject-reason-${ont.id}`}
          />
          <div className="text-[10px] text-slate-500 mt-1">
            {rejectReason.length}/20 chars mínimos
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div className="mt-3 flex gap-2 flex-wrap">
        <button
          onClick={handleApprove}
          disabled={!picked || reason.length < 10 || busy}
          className="px-3 py-1.5 rounded text-xs font-semibold bg-emerald-500/20 text-emerald-200 border border-emerald-500/40 hover:bg-emerald-500/30 disabled:opacity-40 disabled:cursor-not-allowed"
          data-testid={`quar-approve-btn-${ont.id}`}
        >
          ✓ Aprovar
        </button>
        {!showReject ? (
          <button
            onClick={() => setShowReject(true)}
            disabled={busy}
            className="px-3 py-1.5 rounded text-xs font-semibold bg-rose-500/10 text-rose-300 border border-rose-500/30 hover:bg-rose-500/20"
            data-testid={`quar-reject-show-${ont.id}`}
          >
            ✗ Rejeitar
          </button>
        ) : (
          <button
            onClick={handleReject}
            disabled={rejectReason.length < 20 || busy}
            className="px-3 py-1.5 rounded text-xs font-semibold bg-rose-500/20 text-rose-200 border border-rose-500/50 hover:bg-rose-500/30 disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid={`quar-reject-confirm-${ont.id}`}
          >
            ✗ Confirmar rejeição
          </button>
        )}
      </div>
    </div>
  );
}

export default function QuarantinePromotion() {
  const [stats, setStats] = useState(null);
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(0);
  const limit = 20;

  const fetchAll = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const [s, c] = await Promise.all([
        client.get("/sprint5/quarantine/stats"),
        client.get(`/sprint5/quarantine/candidates?limit=${limit}&offset=${page * limit}`),
      ]);
      setStats(s.data);
      setItems(c.data.items || []);
      setTotal(c.data.total || 0);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha");
    } finally { setLoading(false); }
  }, [page]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const onApprove = async (ontId, payload) => {
    setBusy(true);
    try {
      await client.post(`/sprint5/quarantine/${ontId}/approve`, payload);
      await fetchAll();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };
  const onReject = async (ontId, payload) => {
    setBusy(true);
    try {
      await client.post(`/sprint5/quarantine/${ontId}/reject`, payload);
      await fetchAll();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  if (loading && !items.length) {
    return (
      <div className="text-slate-400 p-6 animate-pulse" data-testid="quar-loading">
        Carregando quarentena…
      </div>
    );
  }
  if (err) {
    return (
      <div className="bg-rose-950/30 border border-rose-500/40 text-rose-200 p-6 rounded" data-testid="quar-error">
        Erro: {String(err)}
        <button onClick={fetchAll} className="ml-3 px-2 py-1 bg-rose-500/30 rounded text-xs">Retry</button>
      </div>
    );
  }

  const totalPages = Math.ceil(total / limit);

  return (
    <div className="space-y-4" data-testid="quar-root">
      {/* Header / Stats */}
      <div className="rounded-2xl border border-slate-700 bg-slate-900/60 p-4 flex items-center justify-between gap-4 flex-wrap">
        <div>
          <div className="text-xs uppercase font-mono text-slate-400">
            Mutirão de Quarentena · Phase D Add-on
          </div>
          <div className="text-2xl font-bold text-slate-100 mt-1">
            {stats?.pending_review ?? 0}
            <span className="text-base text-slate-400 font-normal ml-2">
              aguardando revisão
            </span>
          </div>
          <div className="text-[11px] text-slate-500 font-mono mt-1">
            Promovidas manualmente: {stats?.promoted_manually ?? 0} ·
            Rejeitadas permanente: {stats?.permanent_quarantine ?? 0}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchAll} disabled={loading}
            className="px-3 py-1.5 rounded bg-slate-700/60 hover:bg-slate-700 text-xs"
            data-testid="quar-refresh-btn">
            ↻ Recarregar
          </button>
        </div>
      </div>

      {/* Lista */}
      {items.length === 0 ? (
        <div className="text-slate-400 p-6 text-center">
          Nada na quarentena. 🎉
        </div>
      ) : (
        <div className="space-y-3" data-testid="quar-list">
          {items.map((it) => (
            <CandidateCard
              key={it.ont.id}
              item={it}
              onApprove={onApprove}
              onReject={onReject}
              busy={busy}
            />
          ))}
        </div>
      )}

      {/* Paginação */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-slate-400 mt-4">
          <span>Página {page + 1} / {totalPages} · {total} itens</span>
          <div className="flex gap-2">
            <button
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="px-2 py-1 rounded bg-slate-700/60 disabled:opacity-30"
              data-testid="quar-prev-btn"
            >← Anterior</button>
            <button
              disabled={page + 1 >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="px-2 py-1 rounded bg-slate-700/60 disabled:opacity-30"
              data-testid="quar-next-btn"
            >Próximo →</button>
          </div>
        </div>
      )}
    </div>
  );
}
