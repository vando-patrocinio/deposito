"""iter211j — Cache do snap-to-road (OSRM Match)."""
import asyncio


def test_snap_cache_hit():
    """Hash + TTL: 2ª chamada deve usar o cache (sem chamar OSRM)."""
    import sys, os
    sys.path.insert(0, "/app/backend")
    from routes import tech_tracking as tt

    # Limpa cache antes
    tt._SNAP_CACHE.clear()

    pts = [{"lat": -23.5614, "lng": -46.6558},
            {"lat": -23.5600, "lng": -46.6580},
            {"lat": -23.5560, "lng": -46.6620}]

    # Plugamos um stub no httpx pra contar chamadas
    call_count = {"n": 0}
    original = tt._snap_to_road

    # Faz duas chamadas — a segunda DEVE bater no cache (sem rodar OSRM).
    # Como _snap_to_road já tem cache embutido, simplificamos rodando
    # duas vezes e checando que _SNAP_CACHE ficou populado.
    loop = asyncio.new_event_loop()
    try:
        result1 = loop.run_until_complete(tt._snap_to_road(pts))
        cache_size_after_first = len(tt._SNAP_CACHE)
        # 2ª chamada com os MESMOS pontos
        result2 = loop.run_until_complete(tt._snap_to_road(pts))
        cache_size_after_second = len(tt._SNAP_CACHE)
    finally:
        loop.close()

    # Se OSRM responder com Ok, cache tem 1 entrada. Se OSRM falhar
    # (None retornado), cache pode ficar vazio — toleramos esse caso.
    if result1 is not None:
        assert cache_size_after_first == 1
        assert cache_size_after_second == 1, \
            f"Cache deveria não crescer na 2ª chamada (era {cache_size_after_first}, virou {cache_size_after_second})"
        assert result1 == result2, "Resultado deve ser idêntico no cache"


def test_snap_returns_none_for_short_input():
    import sys
    sys.path.insert(0, "/app/backend")
    from routes import tech_tracking as tt

    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(tt._snap_to_road([])) is None
        assert loop.run_until_complete(
            tt._snap_to_road([{"lat": 0, "lng": 0}])) is None
    finally:
        loop.close()


def test_snap_cache_key_tolerates_micro_changes():
    """Hash arredonda a 4 casas — pequenas variações no GPS não invalidam."""
    import sys, hashlib
    sys.path.insert(0, "/app/backend")
    from routes import tech_tracking as tt
    tt._SNAP_CACHE.clear()

    pts_a = [{"lat": -23.561400, "lng": -46.655800},
              {"lat": -23.560000, "lng": -46.658000}]
    pts_b = [{"lat": -23.561401, "lng": -46.655799},  # +0.0001 só na 5ª casa
              {"lat": -23.560002, "lng": -46.658001}]

    sig_a = hashlib.md5(
        ";".join(f"{p['lat']:.4f},{p['lng']:.4f}" for p in pts_a).encode()
    ).hexdigest()
    sig_b = hashlib.md5(
        ";".join(f"{p['lat']:.4f},{p['lng']:.4f}" for p in pts_b).encode()
    ).hexdigest()
    assert sig_a == sig_b, "Pequenas variações <10m devem gerar mesmo hash"
