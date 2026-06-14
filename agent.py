import logging
import os
import sys

from dotenv import load_dotenv

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()

    try:
        from src.graph import build_graph
        graph = build_graph()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        graph.invoke({})
    except Exception:
        logger.critical("Unexpected error during graph execution", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
