"""Campaign safeguards exercised with fictional fixtures and temporary accounts."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.synthetic_demo import body, fixture
from style_xi.acquire import daily_usage
from style_xi.campaign import Campaign, COMPLETED, classification, inventory
from style_xi.storage import DataError, atomic_json, exclusive, read_json

TOKEN = "fictional-test-token"


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.account = self.root / "account.json"
        atomic_json(self.account, {"attempts": [], "observation": {}})
        self.manifest = {"version": 1, "season": 2025, "cap": 1800, "daily_cap": 90, "reserve": 10,
                         "regular_stage_rule": "Regular Season - [1-9][0-9]*", "completed_states": list(COMPLETED),
                         "competitions": [{"id": 900301 + i, "name": "Fictional league " + str(i)} for i in range(5)],
                         "interval_seconds": 1, "state": str(self.root / "state"), "account": str(self.account),
                         "history": [], "baseline_files": []}
        self.path = self.root / "manifest.json"
        atomic_json(self.path, self.manifest)
        self.calls = []
        self.remaining = 100
        self.per_league = 1
        self.campaign = self.make()
        self.campaign.initialize()

    def make(self, transport=None):
        return Campaign(self.path, transport=transport or self.transport, sleeper=lambda _: None)

    def transport(self, path, params, key):
        self.assertEqual(read_json(self.root / "state/requests.json")["attempts"][-1]["outcome"], "reserved")
        self.calls.append((path, params))
        self.remaining -= 1
        if path == "/matches":
            rows = []
            for i in range(self.per_league):
                f = fixture(match=params["leagueId"] * 100 + i)
                f["league"]["id"] = params["leagueId"]
                f["date"] = "2025-08-16T15:00:00Z"
                rows.append(f)
            start, limit = params["offset"], params["limit"]
            value = {"data": rows[start:start + limit], "pagination": {"offset": start, "limit": limit, "totalCount": len(rows)},
                     "plan": {"tier": "BASIC"}}
        else:
            value = body()
        return 200, {"x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": str(self.remaining)}, json.dumps(value).encode()

    def test_five_league_inventory_then_boxes_and_cache_only_resume(self):
        result = self.campaign.run(TOKEN)
        self.assertEqual(result["new_attempts"], 10)
        self.assertFalse(result["workflow_halted"])
        self.assertEqual([p["leagueId"] for _, p in self.calls[:5]], list(range(900301, 900306)))
        self.assertTrue(all(path.startswith("/box-score/") for path, _ in self.calls[5:]))
        before = (self.account.read_bytes(), (self.root / "state/requests.json").read_bytes())
        again = self.make(lambda *args: self.fail("cache must not dispatch")).run(None)
        self.assertEqual(again["new_attempts"], 0)
        self.assertEqual(before, (self.account.read_bytes(), (self.root / "state/requests.json").read_bytes()))
        self.assertTrue(all(g["usable_boxes"] == 1 for g in again["leagues"]))

    def test_daily_90_and_reserve_survive_restart(self):
        self.per_league = 30
        result = self.campaign.run(TOKEN)
        self.assertEqual(result["new_attempts"], 90)
        self.assertEqual(result["daily_usage"], 90)
        self.assertEqual(self.remaining, 10)
        self.assertEqual(self.make().run(TOKEN)["new_attempts"], 0)
        self.assertEqual([g["usable_boxes"] for g in result["leagues"]], [17] * 5)

    def test_bounded_checkpoint_then_resume_shares_daily_and_campaign_counters(self):
        self.per_league = 30
        first = self.campaign.run(TOKEN, max_new_attempts=15)
        self.assertEqual(first["stop_reason"], "invocation_attempt_limit")
        self.assertFalse(first["workflow_halted"])
        self.assertEqual(first["new_attempts"], 15)  # Five inventories, two boxes per league.
        self.assertEqual([g["usable_boxes"] for g in first["leagues"]], [2] * 5)
        second = self.make().run(TOKEN)
        self.assertEqual(second["new_attempts"], 75)
        self.assertEqual((second["daily_usage"], second["campaign_attempts"], self.remaining), (90, 90, 10))
        self.assertEqual(len({json.dumps(c, sort_keys=True) for c in self.calls}), 90)

    def test_invalid_invocation_limit_never_mutates_or_dispatches(self):
        before = (self.account.read_bytes(), (self.root / "state/requests.json").read_bytes())
        for limit in (0, -1, True, 1.5, "10"):
            with self.assertRaisesRegex(DataError, "invalid_invocation_attempt_limit"):
                self.campaign.run(TOKEN, max_new_attempts=limit)
        self.assertEqual(before, (self.account.read_bytes(), (self.root / "state/requests.json").read_bytes()))
        self.assertFalse(self.calls)

    def test_current_reserve_does_not_bootstrap_and_status_is_read_only(self):
        account = read_json(self.account)
        account["observation"] = {"observed_utc": datetime.now(timezone.utc).isoformat(), "remaining": 10}
        atomic_json(self.account, account)
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(self.campaign.status()["network_requests"], 0)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertEqual(self.campaign.run(TOKEN)["new_attempts"], 0)
        self.assertFalse(self.calls)

    def test_shared_orphan_reservation_blocks_without_reset(self):
        account = read_json(self.account)
        account["attempts"].append({"request_id": "uncertain", "budget_id": self.campaign.client.budget_id,
                                    "reserved_utc": datetime.now(timezone.utc).isoformat()})
        atomic_json(self.account, account)
        with self.assertRaisesRegex(DataError, "uncertain_campaign_reservation"):
            self.campaign.status()
        self.assertEqual(len(read_json(self.account)["attempts"]), 1)
        self.assertEqual(self.campaign.run(TOKEN)["new_attempts"], 0)

    def test_lock_blocks_second_invocation(self):
        with exclusive(self.account.with_suffix(".run.lock")):
            with self.assertRaisesRegex(DataError, "another_process"):
                self.make().run(TOKEN)
        self.assertFalse(self.calls)

    def test_day_change_during_pacing_stops_before_transport(self):
        def boundary(_):
            self.campaign.client.run_day = "2000-01-01"
        self.campaign.sleeper = boundary
        result = self.campaign.run(TOKEN)
        self.assertEqual(result["stop_reason"], "utc_day_boundary")
        self.assertEqual(result["new_attempts"], 0)

    def test_missing_quota_and_failure_stop_after_one_attempt(self):
        for code in (200, 401, 403, 429, 500):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temp:
                m = dict(self.manifest, state=str(Path(temp) / "state"), account=str(Path(temp) / "account.json"))
                atomic_json(m["account"], {"attempts": [], "observation": {}})
                path = Path(temp) / "manifest.json"
                atomic_json(path, m)
                def response(*args):
                    return code, {}, b'{"data": [], "pagination":{"limit":100,"offset":0,"totalCount":0},"plan":{"tier":"BASIC"}}'
                c = Campaign(path, transport=response, sleeper=lambda _: None)
                c.initialize()
                self.assertEqual(c.run(TOKEN)["new_attempts"], 1)
                self.assertEqual(c.run(TOKEN)["new_attempts"], 0)

    def test_interruption_after_reservation_is_conservative(self):
        def interrupt(*args):
            raise KeyboardInterrupt()
        result = self.make(interrupt).run(TOKEN)
        self.assertEqual(result["new_attempts"], 1)
        self.assertEqual(result["stop_reason"], "user_interruption")
        self.assertEqual(self.make().run(TOKEN)["new_attempts"], 0)
        self.assertEqual(len(read_json(self.account)["attempts"]), 1)

    def test_snapshot_written_before_interruption_recovers_without_refetch(self):
        original = __import__("style_xi.acquire", fromlist=["atomic_json"]).atomic_json
        def interrupted(path, value):
            if Path(path).name == "requests.json" and value["attempts"][-1]["outcome"] == "success":
                raise KeyboardInterrupt()
            original(path, value)
        with patch("style_xi.acquire.atomic_json", side_effect=interrupted):
            self.campaign.run(TOKEN)
        self.assertEqual(len(self.calls), 1)
        result = self.make().run(TOKEN)
        self.assertEqual(result["new_attempts"], 9)
        self.assertEqual(len(self.calls), 10)
        self.assertTrue(all(a["outcome"] == "success" for a in self.campaign.client.ledger()["attempts"]))

    def test_campaign_ceiling_and_prior_day_survive_restart(self):
        ledger = self.campaign.client.ledger()
        account = read_json(self.account)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        for i in range(1800):
            entry = {"number": i + 1, "request_id": str(i), "reserved_utc": yesterday, "outcome": "failed",
                     "endpoint": "https://soccer.highlightly.net/matches", "parameters": {},
                     "scope": {"competition_id": 900301}}
            ledger["attempts"].append(entry)
            account["attempts"].append({**entry, "budget_id": self.campaign.client.budget_id})
        atomic_json(self.root / "state/requests.json", ledger)
        atomic_json(self.account, account)
        result = self.make().run(TOKEN)
        self.assertEqual(result["stop_reason"], "request_budget_exhausted")
        self.assertEqual(result["campaign_attempts"], 1800)
        self.assertEqual(result["daily_usage"], 0)
        self.assertFalse(self.calls)

    def test_external_usage_and_duplicate_history_are_conservative(self):
        at = datetime.now(timezone.utc)
        attempt = {"request_id": "one", "reserved_utc": at.isoformat()}
        account = {"external_usage": {at.date().isoformat(): 88}, "observation": {}}
        self.assertEqual(daily_usage(account, [attempt, attempt], at), 89)
        account["observation"] = {"observed_utc": at.isoformat(), "remaining": 5}
        self.assertEqual(daily_usage(account, [attempt], at), 95)

    def test_scope_and_baseline_corruption_fail_closed(self):
        altered = deepcopy(self.manifest)
        altered["competitions"][0]["id"] = 999999
        atomic_json(self.path, altered)
        with self.assertRaises(DataError):
            self.make().status()
        atomic_json(self.path, self.manifest)
        path = self.root / "state/checkpoint.json"
        atomic_json(path, {"manifest_sha256": "changed"})
        with self.assertRaisesRegex(DataError, "checkpoint_changed"):
            self.make().status()

    def test_effective_pagination_gaps_duplicates_and_changed_totals(self):
        def page(offset, limit, total, ids, requested=100):
            rows = [fixture(match=i) for i in ids]
            return {"endpoint": "https://soccer.highlightly.net/matches", "parameters": {
                "leagueId": 900301, "season": 2025, "offset": offset, "limit": requested},
                "body": {"pagination": {"offset": offset, "limit": limit, "totalCount": total}, "data": rows}}
        first = page(0, 2, 6, [900001, 900002])
        last = page(4, 2, 6, [900005, 900006])
        groups, _ = inventory([last, first], self.manifest["competitions"], 2025)
        self.assertEqual(groups[0]["next_page"], {"offset": 2, "limit": 2})
        mid = page(2, 2, 6, [900003, 900004])
        self.assertTrue(inventory([mid, first, last], self.manifest["competitions"], 2025)[0][0]["provider_manifest_complete"])
        for invalid in (page(2, 2, 6, [900001, 900002]), page(2, 2, 7, [900003, 900004])):
            with self.assertRaises(DataError):
                inventory([first, invalid, last], self.manifest["competitions"], 2025)

    def test_stage_and_completion_are_explicit(self):
        f = fixture()
        self.assertEqual(classification(f), "target")
        f["round"] = None
        self.assertEqual(classification(f), "unresolved_stage")
        f["round"] = "Final"
        self.assertEqual(classification(f), "excluded_stage")
        for label in ("Semi-finals", "Relegation round - Quarter-finals"):
            f["round"] = label
            self.assertEqual(classification(f), "excluded_stage")
        f["round"] = "Regular Season - 1"
        f["state"]["description"] = "Postponed"
        self.assertEqual(classification(f), "unfinished")
        f["state"]["description"] = None
        self.assertEqual(classification(f), "unresolved_completion")

    def test_field_gate_allows_inventory_and_persists_box_pause(self):
        gate = self.root / "gate.json"
        atomic_json(gate, {"allow_box_scores": False, "reason": "independent_field_discrepancy"})
        manifest = dict(self.manifest, validation_gate=str(gate), state=str(self.root / "gated-state"),
                        account=str(self.root / "gated-account.json"))
        atomic_json(manifest["account"], {"attempts": [], "observation": {}})
        manifest_path = self.root / "gated-manifest.json"
        atomic_json(manifest_path, manifest)
        def response(path, params, key):
            self.calls.append((path, params))
            return 200, {"x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": str(100-len(self.calls))}, json.dumps({
                "data": [], "pagination": {"offset": 0, "limit": 100, "totalCount": 0}, "plan": {"tier": "BASIC"}}).encode()
        # Include target fixtures in the five synthetic responses.
        def targets(path, params, key):
            status, headers, raw = response(path, params, key)
            value = json.loads(raw)
            f = fixture(match=params["leagueId"] * 100)
            f["league"]["id"] = params["leagueId"]
            f["date"] = "2025-08-16T15:00:00Z"
            value["data"] = [f]
            value["pagination"]["totalCount"] = 1
            return status, headers, json.dumps(value).encode()
        campaign = Campaign(manifest_path, transport=targets, sleeper=lambda _: None)
        campaign.initialize()
        result = campaign.run(TOKEN)
        self.assertEqual(result["new_attempts"], 5)
        self.assertEqual(result["stop_reason"], "field_validation_pause_before_box_collection")
        restarted = Campaign(manifest_path, transport=lambda *args: self.fail("gate must prevent transport"), sleeper=lambda _: None)
        self.assertEqual(restarted.run(TOKEN)["new_attempts"], 0)
        atomic_json(gate, {"allow_box_scores": True, "real_comparison_allowed": False,
                           "reason": "collection_only_after_source_contract_review"})
        self.remaining = 95
        def boxes(path, params, key):
            self.assertTrue(path.startswith("/box-score/"))
            self.calls.append((path, params))
            self.remaining -= 1
            return 200, {"x-ratelimit-requests-limit": "100",
                         "x-ratelimit-requests-remaining": str(self.remaining)}, json.dumps(body()).encode()
        cleared = Campaign(manifest_path, transport=boxes, sleeper=lambda _: None).run(TOKEN)
        self.assertEqual(cleared["new_attempts"], 5)
        self.assertFalse(cleared["field_validation_gate"]["real_comparison_allowed"])
        self.assertTrue(cleared["real_comparison_readiness"].startswith("blocked_"))

    def test_missing_completed_snapshot_cannot_be_marked_usable_or_refetched(self):
        self.campaign.run(TOKEN)
        next((self.root / "state/responses").glob("*.json")).unlink()
        with self.assertRaisesRegex(DataError, "completed_response_missing"):
            self.make().status()
        self.assertEqual(self.make().run(TOKEN)["new_attempts"], 0)

    def test_changed_baseline_bytes_block_before_transport(self):
        path = self.root / "baseline.json"
        atomic_json(path, {"fictional": True})
        self.campaign.manifest["baseline_files"] = [{"path": str(path), "sha256": "invalid", "snapshot": False}]
        with self.assertRaisesRegex(DataError, "baseline_evidence_changed"):
            self.campaign.status()
        self.assertFalse(self.calls)


if __name__ == "__main__":
    unittest.main()
