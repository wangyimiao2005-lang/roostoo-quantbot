"""Factory for the competition PaperRunner with optional frozen Funding support."""
from pathlib import Path

from .funding_provider import BinanceUSDMFundingProvider
from .paper_runner import PaperRunner


def build_competition_paper_runner(provider, broker, state, mode="DRY_RUN", cache_dir=None):
    """Construct the normal runner with a causal funding source ready if selected.

    The funding provider performs no network access at construction time. If the
    final gate selects Baseline A, the provider is never consulted by the active
    strategy path.
    """
    cache = Path(cache_dir) if cache_dir else Path("data/funding_competition_live")
    funding = BinanceUSDMFundingProvider(cache_dir=cache)
    return PaperRunner(provider, broker, state, mode=mode, funding_history_provider=funding)
