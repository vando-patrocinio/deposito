"""Isabella Queue Worker — processo SEPARADO do uvicorn HTTP.

Após OPERAÇÃO SEPARAR WORKER ISABELLA, este script é gerenciado pelo
supervisor como o programa `isabella-worker`. NÃO compartilha o event
loop do uvicorn principal — o webhook fica isolado.

Variáveis de ambiente:
  ISABELLA_WORKER_CONCURRENCY  (default 10)
  ISABELLA_WORKER_POLL_MS      (default 100)
  ISABELLA_WORKER_MAX_RETRIES  (default 3)
  ISABELLA_LLM_TIMEOUT_S       (default 6.0) — fallback canned acima disso

Uso direto:
  cd /app/backend && python3 workers/isabella_queue_worker.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

# Garante que o root do backend está em sys.path quando rodado standalone
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BACKEND, ".env"))

logging.basicConfig(
    level=os.environ.get("ISABELLA_WORKER_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("isabella_worker")

# Imports DEPOIS do load_dotenv e sys.path
from services.isabella_queue import (  # noqa: E402
    start_workers, stop_workers, _pool_size,
)


async def _main() -> None:
    n = _pool_size()
    logger.info("┌─ Isabella Queue Worker standalone")
    logger.info("│  concurrency:  %d", n)
    logger.info("│  poll_ms:      %s", os.environ.get(
        "ISABELLA_WORKER_POLL_MS", "100"))
    logger.info("│  llm_timeout:  %ss", os.environ.get(
        "ISABELLA_LLM_TIMEOUT_S", "6.0"))
    logger.info("│  max_retries:  %s", os.environ.get(
        "ISABELLA_WORKER_MAX_RETRIES", "3"))
    logger.info("└─ Mongo:        %s",
                 os.environ.get("MONGO_URL", "(missing)")[:40] + "…")

    await start_workers()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _graceful(*_a):
        logger.info("sinal recebido → shutdown graceful")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _graceful)
        except NotImplementedError:
            pass

    await stop_event.wait()
    await stop_workers()
    logger.info("Isabella worker terminado")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
