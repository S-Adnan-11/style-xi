"""Execute only an explicit, bounded request plan; checkpoint every response."""

from .coverage import inspect_pages
from .pipeline import load_snapshots
from .storage import DataError, atomic_json, digest, exclusive, read_json


def read_plan(path):
    plan = read_json(path)
    if not isinstance(plan, dict) or not isinstance(plan.get("calls"), list) or not 1 <= len(plan["calls"]) <= 50:
        raise DataError("plan_requires_1_to_50_explicit_calls")
    calls = []
    for item in plan["calls"]:
        if not isinstance(item, dict) or set(item) != {"path", "parameters", "scope"}:
            raise DataError("invalid_plan_call")
        path, params, scope = (item[k] for k in ("path", "parameters", "scope"))
        if not isinstance(path, str) or not isinstance(params, dict) or not isinstance(scope, dict):
            raise DataError("invalid_plan_call")
        if path == "/matches" and (scope.get("competition_id") != params.get("leagueId")
                                   or scope.get("season") != params.get("season")
                                   or scope.get("stage") != "all_provider_stages"):
            raise DataError("plan_scope_mismatch")
        if not all(k in scope for k in ("competition_id", "season", "stage")):
            raise DataError("explicit_acquisition_scope_required")
        calls.append((path, params, scope))
    return calls


def run_plan(client, calls, key):
    # Separate runner lock avoids nested acquisition locks and prevents concurrent checkpoint edits.
    with exclusive(client.root / "checkpoint.lock"):
        checkpoint_path = client.root / "checkpoint.json"
        identity = digest(calls)
        if checkpoint_path.exists():
            checkpoint = read_json(checkpoint_path)
            if checkpoint.get("plan_sha256") != identity:
                raise DataError("changed_request_plan_requires_review")
        else:
            checkpoint = {"plan_sha256": identity, "completed_call_indexes": [], "coverage_history": []}
        for index, (path, params, scope) in enumerate(calls):
            # Cached requests are rechecked, including completed checkpoint indexes.
            client.get(path, params, scope, key)
            pages = load_snapshots(client.root / "responses")
            acquired = {int(s["endpoint"].rsplit("/", 1)[1]) for s in pages if "/box-score/" in s["endpoint"]}
            coverage = inspect_pages(pages, acquired)
            checkpoint["coverage"] = coverage
            checkpoint["coverage_history"].append({"call_index": index, "coverage_sha256": digest(coverage)})
            fatal = sorted({issue for group in coverage for issue in group["issues"]
                            if issue not in ("manifest_not_fully_acquired", "page_gap_or_overlap")})
            checkpoint["halted"] = fatal or None
            if index not in checkpoint["completed_call_indexes"]:
                checkpoint["completed_call_indexes"].append(index)
            atomic_json(checkpoint_path, checkpoint)
            if fatal:
                raise DataError("manifest_validation_failed:" + ",".join(fatal))
        return checkpoint
