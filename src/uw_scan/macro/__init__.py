"""Cross-domain point-in-time macro assemblers."""

from .contracts import DomainObservation, MacroDomainState
from .inflation import compute_inflation_state
from .policy import assemble_policy_paths

__all__ = [
    "DomainObservation",
    "MacroDomainState",
    "assemble_policy_paths",
    "compute_inflation_state",
]
