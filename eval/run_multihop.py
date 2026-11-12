"""Run the multi-hop questions through eval/run.py with their own questions and config.

Usage: uv run python eval/run_multihop.py --name multihop [--baseline] [run.py options]
"""

import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL))

import run  # noqa: E402  (eval/ must be on the path first, as run.py imports grade)


# Point run.py at the multi-hop questions and config, then hand over to its main.
def main() -> int:
    run.QUESTIONS = EVAL / "questions_multihop.yaml"
    run.CONFIG = EVAL / "config_multihop.toml"
    return run.main()


if __name__ == "__main__":
    sys.exit(main())
