import React, { useEffect, useRef, useState } from "react";
import { Circle, MapContainer, Marker, TileLayer, useMap, useMapEvents, ZoomControl } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "@/api";
import { Button, Field, Icon, inputStyle } from "@/ui";

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

// Brasil inteiro como vista inicial (centro aproximado + zoom 4)
const BRAZIL_CENTER = [-14.235, -51.925];
const BRAZIL_ZOOM = 4;

function Recenter({ position, zoom = 17 }) {
  const map = useMap();
  useEffect(() => {
    if (position) map.setView(position, zoom, { animate: true });
  }, [position, zoom, map]);
  return null;
}

// Captura cliques no mapa para reposicionar o pino
function MapClickHandler({ onClick }) {
  useMapEvents({
    click: (e) => onClick([e.latlng.lat, e.latlng.lng]),
  });
  return null;
}

export default function GeofenceMap({ initial, onSubmit, onCancel, submitLabel = "Salvar cerca" }) {
  const [name, setName] = useState(initial?.name || "");
  const [type, setType] = useState(initial?.type || "Cliente");
  const [addressInput, setAddressInput] = useState(initial?.address || "");
  const [position, setPosition] = useState(
    initial?.lat != null && initial?.lng != null ? [initial.lat, initial.lng] : null
  );
  const [radius, setRadius] = useState(Number(initial?.radius) || 15);
  const [resolvedAddress, setResolvedAddress] = useState(initial?.address || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Autocomplete
  const [suggestions, setSuggestions] = useState([]);
  const [searching, setSearching] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [searchHint, setSearchHint] = useState(""); // "rate" | "empty" | ""
  const debounceRef = useRef(null);

  // GPS
  const [gpsStatus, setGpsStatus] = useState(""); // "" | "loading" | "ok" | "error"
  const [gpsMsg, setGpsMsg] = useState("");

  const markerRef = useRef(null);
  const center = position || BRAZIL_CENTER;
  const initialZoom = position ? 17 : BRAZIL_ZOOM;

  function onMapClick([lat, lng]) {
    setPosition([lat, lng]);
    setResolvedAddress(`Lat ${lat.toFixed(6)}, Lng ${lng.toFixed(6)} (clicado no mapa)`);
    if (!name.trim()) {
      setName(`Local em ${lat.toFixed(4)}, ${lng.toFixed(4)}`);
    }
  }

  // Debounced search-as-you-type
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!addressInput || addressInput.trim().length < 3) {
      setSuggestions([]);
      setShowSuggestions(false);
      setSearchHint("");
      return;
    }
    if (addressInput === resolvedAddress) {
      setSuggestions([]);
      setSearchHint("");
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      setSearchHint("");
      try {
        const res = await api.geocodeSearch(addressInput, 5);
        // Backend pode retornar lista direta OU objeto {_rate_limited, results}
        if (Array.isArray(res)) {
          setSuggestions(res);
          setSearchHint(res.length === 0 ? "empty" : "");
        } else if (res?._rate_limited) {
          setSuggestions([]);
          setSearchHint("rate");
        } else {
          setSuggestions(res?.results || []);
          setSearchHint((res?.results || []).length === 0 ? "empty" : "");
        }
        setShowSuggestions(true);
      } catch (e) {
        setSuggestions([]);
        setSearchHint("empty");
      }
      setSearching(false);
    }, 700);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [addressInput, resolvedAddress]);

  function pickSuggestion(s) {
    setPosition([s.lat, s.lng]);
    setResolvedAddress(s.display_name);
    setAddressInput(s.display_name);
    setSuggestions([]);
    setShowSuggestions(false);
    if (!name.trim()) {
      const auto = (s.display_name || "").split(",").slice(0, 2).join(", ").trim();
      if (auto) setName(auto);
    }
  }

  function useMyLocation() {
    setError("");
    if (!navigator.geolocation) {
      setGpsStatus("error");
      setGpsMsg("Seu navegador não suporta geolocalização.");
      return;
    }
    setGpsStatus("loading");
    setGpsMsg("Solicitando permissão e obtendo posição...");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        const acc = pos.coords.accuracy;
        setPosition([lat, lng]);
        setResolvedAddress(`Lat ${lat.toFixed(6)}, Lng ${lng.toFixed(6)} (GPS, precisão ${Math.round(acc)}m)`);
        setAddressInput(`Lat ${lat.toFixed(6)}, Lng ${lng.toFixed(6)}`);
        setGpsStatus("ok");
        setGpsMsg(`Localização obtida (precisão ${Math.round(acc)}m).`);
        if (!name.trim()) {
          setName(`Minha localização (${lat.toFixed(4)}, ${lng.toFixed(4)})`);
        }
      },
      (err) => {
        setGpsStatus("error");
        const map = {
          1: "Permissão negada. Abra as configurações do navegador, permita localização para este site e tente novamente.",
          2: "Posição indisponível. Tente em local com sinal de GPS/Wi-Fi.",
          3: "Tempo esgotado ao obter posição.",
        };
        setGpsMsg(map[err.code] || err.message || "Erro desconhecido.");
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
    );
  }

  function onMarkerDragEnd() {
    const m = markerRef.current;
    if (!m) return;
    const { lat, lng } = m.getLatLng();
    setPosition([lat, lng]);
    setResolvedAddress(`Lat ${lat.toFixed(6)}, Lng ${lng.toFixed(6)} (ajustado manualmente)`);
  }

  async function save() {
    setError("");
    if (!position) {
      setError("Posicione um pino no mapa antes de salvar.");
      return;
    }
    if (!name.trim()) {
      setError("Preencha o nome da cerca.");
      // tenta focar no input do nome
      try { document.querySelector("[data-testid='map-fence-name']")?.focus(); } catch {}
      return;
    }
    setBusy(true);
    try {
      await onSubmit({
        name: name.trim(),
        type,
        address: resolvedAddress || addressInput,
        lat: position[0],
        lng: position[1],
        radius: Number(radius) || 15,
      });
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  }

  return (
    <div data-testid="geofence-map">
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 8, marginBottom: 8 }}>
        <Field label="Nome">
          <input data-testid="map-fence-name" style={inputStyle} value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex: Cliente A / Loja Centro" />
        </Field>
        <Field label="Tipo">
          <select data-testid="map-fence-type" style={inputStyle} value={type} onChange={(e) => setType(e.target.value)}>
            <option>Cliente</option><option>Loja</option><option>Base</option>
          </select>
        </Field>
      </div>

      <div style={{ position: "relative", marginBottom: 10 }}>
        <Field label="Endereço (digite — busca automática)">
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{ position: "relative", flex: 1 }}>
              <input
                data-testid="map-address-input"
                style={{ ...inputStyle, paddingRight: searching ? 38 : 12 }}
                value={addressInput}
                onChange={(e) => setAddressInput(e.target.value)}
                onFocus={() => suggestions.length && setShowSuggestions(true)}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                placeholder="Comece a digitar — Av. Paulista, 1000, São Paulo..."
                autoComplete="off"
              />
              {searching && (
                <span style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", color: "#94a3b8", fontSize: 11 }}>
                  buscando...
                </span>
              )}
              {showSuggestions && suggestions.length > 0 && (
                <ul
                  data-testid="map-suggestions"
                  style={{
                    position: "absolute",
                    top: "100%",
                    left: 0,
                    right: 0,
                    margin: "4px 0 0",
                    padding: 0,
                    listStyle: "none",
                    background: "white",
                    border: "1px solid #cbd5e1",
                    borderRadius: 12,
                    boxShadow: "0 14px 30px rgba(15,23,42,.12)",
                    maxHeight: 240,
                    overflowY: "auto",
                    zIndex: 1000,
                  }}
                >
                  {suggestions.map((s, i) => (
                    <li
                      key={i}
                      data-testid={`suggestion-${i}`}
                      onMouseDown={(e) => { e.preventDefault(); pickSuggestion(s); }}
                      style={{ padding: "10px 12px", cursor: "pointer", borderBottom: i < suggestions.length - 1 ? "1px solid #f1f5f9" : "none", fontSize: 13 }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "#f8fafc")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "white")}
                    >
                      <div style={{ color: "#0f172a", fontWeight: 600 }}>{s.display_name.split(",").slice(0, 2).join(",")}</div>
                      <div style={{ color: "#64748b", fontSize: 11 }}>{s.display_name}</div>
                    </li>
                  ))}
                </ul>
              )}
              {showSuggestions && !searching && suggestions.length === 0 && searchHint && (
                <div data-testid="search-hint" style={{
                  position: "absolute", top: "100%", left: 0, right: 0, margin: "4px 0 0",
                  background: searchHint === "rate" ? "#fef3c7" : "white",
                  color: searchHint === "rate" ? "#92400e" : "#64748b",
                  border: "1px solid " + (searchHint === "rate" ? "#fde68a" : "#cbd5e1"),
                  borderRadius: 12, padding: "10px 12px", fontSize: 13, zIndex: 1000,
                  boxShadow: "0 14px 30px rgba(15,23,42,.12)",
                }}>
                  {searchHint === "rate" ? (
                    <>⏳ Muitas buscas em sequência. Aguarde 2 segundos e tente novamente.</>
                  ) : (
                    <>Nenhum resultado para <strong>{addressInput}</strong>. Tente adicionar a cidade/estado (ex.: <em>“Rua Augusta 100, São Paulo, SP”</em>).</>
                  )}
                </div>
              )}
            </div>
            <Button variant="secondary" onClick={useMyLocation} data-testid="map-use-gps-btn" title="Usar minha localização">
              <Icon name="map" /> Usar GPS
            </Button>
          </div>
        </Field>

        {gpsStatus === "loading" && (
          <div data-testid="gps-loading" style={{ background: "#e0f2fe", color: "#075985", padding: 8, borderRadius: 10, fontSize: 13, marginTop: 4 }}>
            <Icon name="map" /> {gpsMsg}
          </div>
        )}
        {gpsStatus === "ok" && (
          <div style={{ background: "#dcfce7", color: "#166534", padding: 8, borderRadius: 10, fontSize: 13, marginTop: 4 }}>
            ✅ {gpsMsg}
          </div>
        )}
        {gpsStatus === "error" && (
          <div data-testid="gps-error" style={{ background: "#fee2e2", color: "#991b1b", padding: 8, borderRadius: 10, fontSize: 13, marginTop: 4 }}>
            ❌ {gpsMsg}
          </div>
        )}
      </div>

      {error && <div style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10 }}>{error}</div>}

      <div style={{ position: "relative", borderRadius: 18, overflow: "hidden", border: "1px solid #e2e8f0" }}>
        <MapContainer
          center={center}
          zoom={initialZoom}
          style={{ height: 360, width: "100%" }}
          scrollWheelZoom
          zoomControl={false}
        >
          <ZoomControl position="topleft" zoomInTitle="Aproximar" zoomOutTitle="Afastar" />
          <TileLayer
            attribution='Mapa &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contribuidores &copy; <a href="https://carto.com/attributions">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
            subdomains={["a", "b", "c", "d"]}
            maxZoom={20}
          />
          <MapClickHandler onClick={onMapClick} />
          {position && <Recenter position={position} />}
          {position && (
            <>
              <Marker position={position} draggable eventHandlers={{ dragend: onMarkerDragEnd }} ref={markerRef} />
              <Circle center={position} radius={Number(radius) || 15} pathOptions={{ color: "#0f172a", fillColor: "#0f172a", fillOpacity: 0.18, weight: 2 }} />
            </>
          )}
        </MapContainer>
        {!position && (
          <div style={{ position: "absolute", top: 12, right: 12, background: "white", padding: "8px 12px", borderRadius: 12, border: "1px solid #e2e8f0", boxShadow: "0 8px 20px rgba(0,0,0,.08)", fontSize: 12, color: "#475569", maxWidth: 240, zIndex: 500 }}>
            Digite um endereço, use o GPS, ou <strong>clique no mapa</strong> para posicionar o pino
          </div>
        )}
        {position && (
          <div style={{ position: "absolute", bottom: 12, left: 12, background: "white", padding: "6px 10px", borderRadius: 999, border: "1px solid #e2e8f0", boxShadow: "0 4px 10px rgba(0,0,0,.08)", fontSize: 11, color: "#475569", zIndex: 500 }}>
            ️ Clique no mapa para mover • arraste o pino para ajuste fino
          </div>
        )}
      </div>

      <div style={{ marginTop: 10 }}>
        <Field label={`Raio: ${Number(radius)} metros`}>
          <input
            data-testid="map-radius-slider"
            type="range"
            min={5}
            max={300}
            step={1}
            value={radius}
            onChange={(e) => setRadius(Number(e.target.value))}
            style={{ width: "100%" }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", color: "#94a3b8", fontSize: 11 }}>
            <span>5 m</span><span>15 m (recomendado)</span><span>50 m</span><span>100 m</span><span>300 m</span>
          </div>
        </Field>
      </div>

      {position && (
        <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: 10, fontSize: 13, color: "#475569", marginBottom: 10 }}>
          <strong>Posição:</strong> {position[0].toFixed(6)}, {position[1].toFixed(6)}<br />
          <strong>Endereço:</strong> {resolvedAddress || addressInput || "—"}<br />
          <span style={{ color: "#94a3b8", fontSize: 12 }}>Você pode arrastar o pino no mapa para ajustar a posição exata.</span>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Button
          onClick={save}
          disabled={busy}
          variant={position && name.trim() ? "primary" : "soft"}
          data-testid="map-save-btn"
        >
          {busy ? "Salvando..." : submitLabel}
        </Button>
        {onCancel && <Button variant="secondary" onClick={onCancel}>Cancelar</Button>}
        {!position && (
          <span style={{ color: "#94a3b8", fontSize: 13 }}>
            ️ Posicione no mapa primeiro (clique, GPS, ou endereço)
          </span>
        )}
        {position && !name.trim() && (
          <span style={{ color: "#92400e", fontSize: 13, fontWeight: 700, background: "#fef3c7", padding: "4px 10px", borderRadius: 999 }}>
            ️ Preencha o nome
          </span>
        )}
        {position && name.trim() && (
          <span style={{ color: "#166534", fontSize: 13, fontWeight: 700 }}>
            ✅ Pronto para salvar
          </span>
        )}
      </div>
    </div>
  );
}
