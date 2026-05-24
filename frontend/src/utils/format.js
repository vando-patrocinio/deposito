/**
 * Helpers de formatação compartilhados — guards defensivos para campos
 * polimórficos (string|object) que vêm de integrações herdadas (Atlaz, etc).
 *
 * Regra: SEMPRE retorne string. Nunca lance exceção. Aceite null/undefined.
 *
 * Uso recomendado:
 *   {fmtAddress(client.address)}      — endereço estruturado ou string
 *   {fmtPhone(client.phone)}          — telefone normalizado
 *   {fmtName(client.name)}            — nome (objeto first/last ou string)
 *   {fmtPraca(t.praca)}               — praça (id, nome, sigla, etc)
 *   {fmtDoc(client.cpf)}              — CPF/CNPJ
 *   {safeText(qualquer)}              — fallback universal (último recurso)
 */

/** Endereço — string ou {rua, numero, bairro, cidade, estado, referencia}. */
export function fmtAddress(a) {
  if (!a) return "";
  if (typeof a === "string") return a;
  if (typeof a === "object") {
    const parts = [
      a.rua || a.logradouro || a.street,
      (a.numero || a.number) && `n° ${a.numero || a.number}`,
      a.complemento || a.complement,
      a.bairro || a.neighborhood,
      a.cidade || a.city,
      a.estado || a.uf || a.state,
      (a.cep || a.zip) && `CEP ${a.cep || a.zip}`,
      (a.referencia || a.reference) && `(${a.referencia || a.reference})`,
    ].filter(Boolean);
    return parts.join(", ");
  }
  return String(a);
}

/** Telefone — string ou {ddd, numero, e164, internacional, raw}. */
export function fmtPhone(p) {
  if (!p) return "";
  if (typeof p === "string" || typeof p === "number") return String(p);
  if (typeof p === "object") {
    return String(
      p.e164 || p.full || p.numero || p.number || p.raw ||
      (p.ddd && p.numero ? `(${p.ddd}) ${p.numero}` : "") ||
      ""
    );
  }
  return String(p);
}

/** Nome — string ou {first, last, full, nome, razao_social}. */
export function fmtName(n) {
  if (!n) return "";
  if (typeof n === "string") return n;
  if (typeof n === "object") {
    return String(
      n.full || n.name || n.nome || n.razao_social ||
      [n.first, n.last].filter(Boolean).join(" ") ||
      ""
    );
  }
  return String(n);
}

/** Praça/cidade — string ou {nome, sigla, id, cidade}. */
export function fmtPraca(p) {
  if (!p) return "";
  if (typeof p === "string") return p;
  if (typeof p === "object") {
    return String(p.nome || p.name || p.sigla || p.cidade || p.id || "");
  }
  return String(p);
}

/** Documento (CPF/CNPJ) — string ou {cpf, cnpj, document, numero}. */
export function fmtDoc(d) {
  if (!d) return "";
  if (typeof d === "string" || typeof d === "number") return String(d);
  if (typeof d === "object") {
    return String(d.cpf || d.cnpj || d.document || d.numero || d.value || "");
  }
  return String(d);
}

/** Relato/descrição — string ou {texto, resumo, description}. */
export function fmtRelato(r) {
  if (!r) return "";
  if (typeof r === "string") return r;
  if (typeof r === "object") {
    return String(
      r.texto || r.text || r.resumo || r.summary ||
      r.description || r.body || ""
    );
  }
  return String(r);
}

/** Fallback universal — converte QUALQUER coisa em string segura.
 *  Use só quando você não sabe o formato. Prefira os helpers tipados acima. */
export function safeText(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.map(safeText).filter(Boolean).join(", ");
  if (typeof v === "object") {
    // tenta os campos canônicos antes de cair em JSON
    return String(
      v.label || v.name || v.nome || v.text || v.value || v.title || v.id ||
      JSON.stringify(v)
    );
  }
  return String(v);
}
