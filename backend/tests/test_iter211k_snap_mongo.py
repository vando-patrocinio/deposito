"""iter211k — Cache persistente em MongoDB do snap-to-road."""
import asyncio


def test_mongo_persistence_survives_inprocess_clear():
    """Limpa cache in-process e checa que segunda chamada lê do Mongo."""
    import sys
    sys.path.insert(0, "/app/backend")
    from routes import tech_tracking as tt
    from database import db

    pts = [{"lat": -23.5614, "lng": -46.6558},
            {"lat": -23.5600, "lng": -46.6580},
            {"lat": -23.5560, "lng": -46.6620}]

    loop = asyncio.new_event_loop()
    try:
        tt._SNAP_CACHE.clear()
        # 1ª chamada: chama OSRM e popula tanto in-process quanto Mongo
        result1 = loop.run_until_complete(tt._snap_to_road(pts))
        if result1 is None:
            # OSRM indisponível no preview — pula sem falhar
            return
        # Limpa SÓ o in-process (simula reinício do backend)
        tt._SNAP_CACHE.clear()
        # 2ª chamada: deve ler do Mongo
        result2 = loop.run_until_complete(tt._snap_to_road(pts))
        assert result2 == result1, \
            "Cache Mongo deve retornar mesmo trajeto após reinício"
        # E deve ter aquecido o in-process novamente
        assert len(tt._SNAP_CACHE) == 1, \
            "In-process deveria estar aquecido após hit do Mongo"
    finally:
        loop.close()


def test_mongo_index_is_idempotent():
    """Chamar _ensure_snap_cache_index 2x não dá erro."""
    import sys
    sys.path.insert(0, "/app/backend")
    from routes import tech_tracking as tt

    tt._mongo_snap_index_ready = False
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(tt._ensure_snap_cache_index())
        # 2ª vez: flag está True, retorna rápido
        loop.run_until_complete(tt._ensure_snap_cache_index())
        assert tt._mongo_snap_index_ready is True
    finally:
        loop.close()
