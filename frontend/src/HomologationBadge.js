/* HomologationBadge.js — Banner global "MODO HOMOLOGAÇÃO"
   Aparece em todas as telas do AI Center. Reseta auto a cada 5min. */
import React, { useEffect, useState } from "react";

const API = process.env.REACT_APP_BACKEND_URL;

const HomologationBadge = () => {
  const [data, setData] = useState(null);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const r = await fetch(
          `${API}/api/ai-center/homologation/status/public`);
        if (r.ok) setData(await r.json());
      } catch (e) { /* silent */ }
    };
    fetchStatus();
    const id = setInterval(fetchStatus, 300000); // 5min
    return () => clearInterval(id);
  }, []);

  if (!data || !data.homolog_mode_active) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-[9999] bg-amber-500
      text-amber-950 border-b-2 border-amber-700 shadow-md"
      data-testid="homolog-badge-global">
      <div className="max-w-7xl mx-auto px-4 py-2 flex items-center
        justify-center gap-3 text-xs font-semibold uppercase
        tracking-wider">
        <span className="inline-block h-2 w-2 rounded-full bg-amber-900
          animate-pulse" />
        <span>MODO HOMOLOGAÇÃO ATIVO</span>
        <span className="text-amber-800 normal-case font-normal
          tracking-normal">
          · Todas as mensagens WhatsApp são redirecionadas para{" "}
          <strong>{data.test_phone}</strong> · prefixo{" "}
          <strong>{data.homolog_prefix}</strong> · clientes mascarados
        </span>
      </div>
    </div>
  );
};

export default HomologationBadge;
