# ruff: noqa: E402,I001
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from craft.grid2op_health import main


if __name__ == "__main__":
    raise SystemExit(main())

