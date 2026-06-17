"""Curated content catalog pro Ligo TV.

Mix de fontes pra MVP_LIGHT:
  - YouTube Live BR (24/7, embed via iframe) — notícias/cultura/lives
  - IPTV BR público (iptv-org) — TVs federais + canais locais
  - Pluto TV — canais que ainda funcionam de IP cloud (fallback p/ depois)

NÃO há licenciamento envolvido aqui. YouTube Live embed segue ToS oficiais;
IPTV BR puxa apenas listas públicas de transmissão aberta.
"""
from __future__ import annotations

from typing import Any, Dict, List


# ─────────────────── YouTube Live BR (24/7) ───────────────────
# IDs de vídeo "live_stream" estáveis. Pra atualizar use yt-dlp.
# `kind: youtube_live` é renderizado via <iframe> no frontend.
YOUTUBE_LIVE_CHANNELS: List[Dict[str, Any]] = [
    # Música/ambiência — 24/7 estáveis (video IDs fixos há anos)
    {
        "id": "yt-lofi-girl",
        "slug": "lofi-girl",
        "name": "Lofi Girl — Beats to Study",
        "category": "Música",
        "youtube_video_id": "jfKfPfyJRdk",
        "logo": "https://i.ytimg.com/vi/jfKfPfyJRdk/maxresdefault_live.jpg",
        "tile": "https://i.ytimg.com/vi/jfKfPfyJRdk/maxresdefault_live.jpg",
        "summary": "Lofi 24/7 — beats relaxantes pra estudar e trabalhar.",
        "kind": "youtube_live",
        "number": 1,
    },
    {
        "id": "yt-lofi-sleep",
        "slug": "lofi-sleep",
        "name": "Lofi Girl — Sleepy Beats",
        "category": "Música",
        "youtube_video_id": "rUxyKA_-grg",
        "logo": "https://i.ytimg.com/vi/rUxyKA_-grg/maxresdefault_live.jpg",
        "tile": "https://i.ytimg.com/vi/rUxyKA_-grg/maxresdefault_live.jpg",
        "summary": "Música pra dormir 24/7.",
        "kind": "youtube_live",
        "number": 2,
    },
    {
        "id": "yt-synthwave",
        "slug": "synthwave-radio",
        "name": "Synthwave Radio",
        "category": "Música",
        "youtube_video_id": "MVPTGNGiI-4",
        "logo": "https://i.ytimg.com/vi/MVPTGNGiI-4/maxresdefault_live.jpg",
        "tile": "https://i.ytimg.com/vi/MVPTGNGiI-4/maxresdefault_live.jpg",
        "summary": "Synthwave/80s 24h — beats retro pra trabalhar.",
        "kind": "youtube_live",
        "number": 3,
    },
    # Natureza
    {
        "id": "yt-iss-earth",
        "slug": "iss-earth",
        "name": "Terra vista da ISS",
        "category": "Natureza",
        "youtube_video_id": "DIgkvm2nmHc",
        "logo": "https://i.ytimg.com/vi/DIgkvm2nmHc/maxresdefault_live.jpg",
        "tile": "https://i.ytimg.com/vi/DIgkvm2nmHc/maxresdefault_live.jpg",
        "summary": "Câmera ao vivo da Estação Espacial Internacional (NASA).",
        "kind": "youtube_live",
        "number": 4,
    },
    # Notícias BR — Globo (sinal aberto via YouTube oficial)
    {
        "id": "yt-globonews-ao-vivo",
        "slug": "globonews-ao-vivo",
        "name": "GloboNews — Ao Vivo (oficial)",
        "category": "Notícias",
        "youtube_video_id": "1DZxr8ZbAk0",
        "logo": "https://i.ytimg.com/vi/1DZxr8ZbAk0/maxresdefault_live.jpg",
        "tile": "https://i.ytimg.com/vi/1DZxr8ZbAk0/maxresdefault_live.jpg",
        "summary": "Sinal aberto GloboNews via canal oficial.",
        "kind": "youtube_live",
        "number": 5,
    },
    {
        "id": "yt-cnn-brasil",
        "slug": "cnn-brasil",
        "name": "CNN Brasil — Ao Vivo",
        "category": "Notícias",
        "youtube_channel_id": "UCYYBb7nheaY26FKfKLcj1Eg",
        "logo": "https://yt3.googleusercontent.com/-bL3WGiQ_ZBtPnukrgFw82AXEAcOZ1AvVTeZw_DUKFnsHF3xLDVz_xkc-vYIb8z1JlNohrR_=s176-c-k-c0x00ffffff-no-rj",
        "summary": "CNN Brasil 24h ao vivo.",
        "kind": "youtube_live",
        "number": 6,
    },
    {
        "id": "yt-jovem-pan",
        "slug": "jovem-pan-news",
        "name": "Jovem Pan News",
        "category": "Notícias",
        "youtube_channel_id": "UCV306eHqgg0LvBf3Mh36AHg",
        "summary": "Jovem Pan News 24h.",
        "kind": "youtube_live",
        "number": 7,
    },
    {
        "id": "yt-band-jornalismo",
        "slug": "band-jornalismo",
        "name": "BandJornalismo",
        "category": "Notícias",
        "youtube_channel_id": "UCoa-D_VfMkFrCYodrOC9-mA",
        "summary": "Band Jornalismo ao vivo.",
        "kind": "youtube_live",
        "number": 8,
    },
    # Institucional BR — sinal aberto via canais oficiais YouTube
    {
        "id": "yt-tv-camara",
        "slug": "tv-camara",
        "name": "TV Câmara",
        "category": "Institucional",
        "youtube_channel_id": "UCXdgVF8wMc0bnNW5lnTbY1g",
        "summary": "TV Câmara dos Deputados ao vivo.",
        "kind": "youtube_live",
        "number": 9,
    },
    {
        "id": "yt-tv-senado",
        "slug": "tv-senado",
        "name": "TV Senado",
        "category": "Institucional",
        "youtube_channel_id": "UCJ1JsKCJzkk68wOA4O2NoZA",
        "summary": "TV Senado ao vivo.",
        "kind": "youtube_live",
        "number": 10,
    },
]


# ─────────────────── Câmeras-demo (HLS test streams) ───────────────────
# Fonte: streams HLS públicos de teste rotulados como "Câmera Bairro X".
# Pra produção, troque pelos streams reais das câmeras Ligo via
# `POST /api/ligo-tv/cameras` ou seed na collection `ligo_tv_cameras`.
DEMO_CAMERAS: List[Dict[str, Any]] = [
    {
        "id": "cam-demo-praca-central",
        "name": "Praça Central — Demo",
        "neighborhood": "Centro",
        "city": "Volta Redonda",
        "uf": "RJ",
        "cep_prefix": "27240",
        "hls_url": "https://cph-p2p-msl.akamaized.net/hls/live/2000341/test/master.m3u8",
        "thumbnail": "https://images.unsplash.com/photo-1519999482648-25049ddd37b1?w=800",
        "active": True,
    },
    {
        "id": "cam-demo-av-principal",
        "name": "Av. Brasil — Demo",
        "neighborhood": "Aterrado",
        "city": "Volta Redonda",
        "uf": "RJ",
        "cep_prefix": "27215",
        "hls_url": "https://test-streams.mux.dev/test_001/stream.m3u8",
        "thumbnail": "https://images.unsplash.com/photo-1480714378408-67cf0d13bc1b?w=800",
        "active": True,
    },
    {
        "id": "cam-demo-escola-municipal",
        "name": "Escola Municipal — Demo",
        "neighborhood": "Niterói",
        "city": "Volta Redonda",
        "uf": "RJ",
        "cep_prefix": "27260",
        "hls_url": "https://demo.unified-streaming.com/k8s/features/stable/video/tears-of-steel/tears-of-steel.ism/.m3u8",
        "thumbnail": "https://images.unsplash.com/photo-1576267423445-b2e0074d68a4?w=800",
        "active": True,
    },
    {
        "id": "cam-demo-rodoviaria",
        "name": "Rodoviária — Demo",
        "neighborhood": "Vila Santa Cecília",
        "city": "Volta Redonda",
        "uf": "RJ",
        "cep_prefix": "27260",
        "hls_url": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
        "thumbnail": "https://images.unsplash.com/photo-1502920917128-1aa500764cbd?w=800",
        "active": True,
    },
]


def get_youtube_channels() -> List[Dict[str, Any]]:
    return [dict(c) for c in YOUTUBE_LIVE_CHANNELS]


def get_demo_cameras() -> List[Dict[str, Any]]:
    return [dict(c) for c in DEMO_CAMERAS]
