"""Explicit match-level analytical holds; no private registry is loaded implicitly."""

from .normalize import positive_id
from .storage import DataError


def held_matches(registry):
    """Read the version-1 registry. Legacy provider-less cases mean Highlightly."""
    if registry is None:
        return set()
    if (not isinstance(registry, dict) or type(registry.get("version")) is not int
            or registry["version"] != 1 or not isinstance(registry.get("cases"), dict)):
        raise DataError("invalid_match_analytical_holds_registry")
    held = set()
    for key, case in registry["cases"].items():
        if not isinstance(case, dict):
            raise DataError("invalid_match_analytical_hold_case")
        mid, provider = case.get("match_id"), case.get("provider", "highlightly")
        if (not positive_id(mid) or key != str(mid) or not isinstance(provider, str) or not provider
                or case.get("hold_scope") != "match" or type(case.get("analytical_use_allowed")) is not bool):
            raise DataError("invalid_match_analytical_hold_case")
        if not case["analytical_use_allowed"]:
            held.add((provider, mid))
    return held
