"""Initialize the isolated Funding shadow observer without reading market history."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quant_competition.funding_shadow import FundingShadowRuntime


if __name__ == "__main__":
    FundingShadowRuntime()
    print("FUNDING SHADOW READY")
