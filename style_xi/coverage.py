"""Provider pagination evidence, distinct from independently expected coverage."""

from collections import defaultdict

from .normalize import positive_id, stage_for
from .storage import digest


def inspect_pages(snapshots, acquired=()):
    groups = defaultdict(list)
    for snapshot in snapshots:
        if snapshot["endpoint"].endswith("/matches"):
            p = snapshot.get("parameters", {})
            groups[(p.get("leagueId"), p.get("season"))].append(snapshot)
    results = []
    for (league, season), pages in sorted(groups.items(), key=lambda x: str(x[0])):
        issues, totals, by_offset, fixtures = set(), set(), {}, {}
        for page in sorted(pages, key=digest):
            body, params = page["body"], page.get("parameters", {})
            if not isinstance(body, dict):
                issues.add("invalid_page_envelope")
                continue
            pagination, rows = body.get("pagination", {}), body.get("data")
            if not isinstance(pagination, dict) or not isinstance(rows, list):
                issues.add("invalid_page_envelope")
                continue
            total, limit, offset = (pagination.get(k) for k in ("totalCount", "limit", "offset"))
            if (not all(type(v) is int for v in (total, limit, offset))
                    or total < 0 or limit <= 0 or offset < 0):
                issues.add("invalid_pagination")
                continue
            totals.add(total)
            # Providers may enforce a smaller effective page size. Advance by it.
            if (params.get("offset") != offset or type(params.get("limit")) is not int
                    or not 0 < limit <= params["limit"]):
                issues.add("pagination_request_mismatch")
            if len(rows) != min(limit, max(0, total - offset)):
                issues.add("empty_or_incomplete_page")
            page_hash = digest(body)
            if offset in by_offset:
                if by_offset[offset][0] != page_hash:
                    issues.add("changed_page_snapshot")
                continue
            ids = []
            for row in rows:
                if not isinstance(row, dict) or not positive_id(row.get("id")):
                    issues.add("invalid_fixture_identity")
                    continue
                rid = row["id"]
                attached = row.get("league")
                if not isinstance(attached, dict) or attached.get("id") != league or attached.get("season") != season:
                    issues.add("fixture_scope_mismatch")
                if rid in ids:
                    issues.add("duplicate_id_within_page")
                ids.append(rid)
                if rid in fixtures and digest(fixtures[rid]) != digest(row):
                    issues.add("changed_fixture_snapshot")
                fixtures[rid] = row
            by_offset[offset] = (page_hash, limit, ids)
        if len(totals) != 1:
            issues.add("inconsistent_totals")
        expected_offset, seen, signatures = 0, set(), set()
        for offset, (_, limit, ids) in sorted(by_offset.items()):
            if offset != expected_offset:
                issues.add("page_gap_or_overlap")
            signature = tuple(ids)
            if signature in signatures and ids:
                issues.add("repeated_page")
            signatures.add(signature)
            if seen.intersection(ids):
                issues.add("duplicate_ids_across_pages")
            seen.update(ids)
            expected_offset = offset + len(ids)
        total = next(iter(totals)) if len(totals) == 1 else None
        complete = not issues and total is not None and len(seen) == total and expected_offset == total
        if not complete and not issues:
            issues.add("manifest_not_fully_acquired")
        results.append({"competition_id": league, "season": season,
                        "requested_stage": "all_provider_stages", "provider_listed_total": total,
                        "listed_unique_matches": len(fixtures), "provider_manifest_complete": complete,
                        "independently_expected_matches": None,
                        "independent_coverage_verified": False, "issues": sorted(issues),
                        "pages": [{"offset": o, "limit": p[1], "match_ids": p[2]}
                                  for o, p in sorted(by_offset.items())],
                        "manifest_sha256": digest([fixtures[k] for k in sorted(fixtures)]),
                        "matches": [{"match_id": k, "stage": stage_for(fixtures[k]),
                                     "box_score_acquired": k in acquired} for k in sorted(fixtures)],
                        "listed_unacquired_box_scores": sorted(set(fixtures) - set(acquired)),
                        "unlisted_match_count": total - len(fixtures) if total is not None else None})
    return results
