import logging
import os
import signal
import sys
import time

from dotenv import load_dotenv

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    logger.info("Signal %s empfangen — beende nach aktuellem Zyklus", signum)
    _shutdown = True


def main() -> None:
    load_dotenv()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        from src.graph import build_graph
        from src.config import config
        graph = build_graph()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    interval = config.loop_interval_seconds
    logger.info("Agent gestartet — Intervall: %ds", interval)

    while not _shutdown:
        logger.info("--- Zyklus startet ---")
        try:
            graph.invoke({})
        except Exception:
            logger.error("Fehler im Zyklus", exc_info=True)

        if _shutdown:
            break

        logger.debug("Warte %ds bis zum nächsten Zyklus", interval)
        for _ in range(interval):
            if _shutdown:
                break
            time.sleep(1)

    logger.info("Agent beendet")


if __name__ == "__main__":
    main()
