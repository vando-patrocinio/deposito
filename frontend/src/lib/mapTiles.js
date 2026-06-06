/* mapTiles.js — Config única para todos os mapas Leaflet do app Ligo.
 *
 * Por que CARTO Voyager?
 *   ✓ Renderização limpa (estilo Apple/Mapbox), cores naturais
 *   ✓ Nomes em PT-BR (usa `name:pt` do OSM com fallback pro local)
 *   ✓ Suporta retina (@2x via `{r}.png`) — nítido em telas HiDPI
 *   ✓ Gratuito até ~75k tiles/dia/IP (mais que suficiente)
 *
 * Por que mesma URL pra todos?
 *   • Browser faz cache compartilhado entre os mapas (LiveMap + Geofence +
 *     CTO Picker + Frota etc) — economia massiva de banda
 *   • Identidade visual consistente em todos os mapas Ligo
 */

// Light: padrão, ótimo pra trabalhar de dia / no laptop.
export const TILE_VOYAGER =
  "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png";

// Dark: pra dashboard escuro (FleetTracking modo dark).
export const TILE_DARK =
  "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";

// Light minimalista — usado em pickers/popups onde só queremos um BG sutil.
export const TILE_POSITRON =
  "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";

export const TILE_ATTRIBUTION =
  'Mapa &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  + ' contribuidores &copy; <a href="https://carto.com/attributions">CARTO</a>';

export const TILE_MAX_ZOOM = 19;
