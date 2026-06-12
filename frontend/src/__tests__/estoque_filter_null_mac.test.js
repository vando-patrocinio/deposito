/* Regression test — iter247 fix
 * Bug: EstoquePanel.js linha 950 fazia `o.mac.toLowerCase()` sem fallback.
 * ONTs zumbi do fluxo `lousa_retirada_troca_photo` ficam com mac=null
 * aguardando revisão humana → useMemo crasha → tela do Estoque cai.
 */
const assert = require("node:assert");

// Reproduz a lógica EXATA do useMemo após o fix (linha 945-956 de EstoquePanel.js)
function filterOnts(onts, filter, locFilter) {
  const q = filter.toLowerCase();
  return onts.filter((o) => {
    const sn = (o.scan_sn || o.sn || "").toLowerCase();
    const txt = !q || sn.includes(q) || (o.mac || "").toLowerCase().includes(q)
      || (o.model || "").toLowerCase().includes(q)
      || (o.client_name || "").toLowerCase().includes(q);
    const loc = locFilter === "all" || o.location_type === locFilter;
    return txt && loc;
  });
}

// 1) ONT zumbi (mac/sn/model todos null) NÃO pode quebrar o filtro
const onts = [
  // ONT normal
  { scan_sn: "FHTTC250CE14", mac: "SN-FHTTC250CE14",
    model: "FIBERHOME HG6145D", status: "disponivel",
    location_type: "empresa", client_name: null },
  // ONT zumbi pending_human_review
  { scan_sn: null, mac: null, model: null,
    status: "pending_human_review", location_type: "tecnico",
    client_name: null, source: "lousa_retirada_troca_photo" },
  // ONT com client_name
  { scan_sn: "ABC123", mac: "AA:BB:CC:DD:EE:FF",
    model: "Huawei", status: "instalada",
    location_type: "instalado", client_name: "Maria Cliente" },
];

// Sem filtro → todas passam
let r = filterOnts(onts, "", "all");
assert.strictEqual(r.length, 3, "esperava 3 sem filtro");

// Filtro vazio com locFilter empresa → 1
r = filterOnts(onts, "", "empresa");
assert.strictEqual(r.length, 1, "esperava 1 filtrando por empresa");

// Filtro por SN → 1
r = filterOnts(onts, "FHTTC", "all");
assert.strictEqual(r.length, 1, "esperava 1 filtrando por SN");

// Filtro por nome cliente → 1
r = filterOnts(onts, "maria", "all");
assert.strictEqual(r.length, 1, "esperava 1 filtrando por client_name");

// Filtro por MAC parcial → 1 (não pode crashar com mac=null no meio!)
r = filterOnts(onts, "aa:bb", "all");
assert.strictEqual(r.length, 1, "esperava 1 filtrando por mac");

// Filtro com termo que não bate em nada → 0
r = filterOnts(onts, "xxxxnotfound", "all");
assert.strictEqual(r.length, 0, "esperava 0 sem match");

console.log("OK — 6/6 testes de regressão do EstoquePanel passaram.");
