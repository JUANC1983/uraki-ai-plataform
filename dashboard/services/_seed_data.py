# dashboard/services/_seed_data.py
"""
REMOVED — seed data is no longer part of this system.

URAKI OPS connects exclusively to the production backend.
There is no demo mode, no fallback data, and no simulated decisions.

If you see this error, locate the import and remove it.
"""
raise ImportError(
    "_seed_data is not available. "
    "URAKI OPS requires a real backend (URAKI_API_URL). "
    "Remove all imports of _seed_data from your code."
)
