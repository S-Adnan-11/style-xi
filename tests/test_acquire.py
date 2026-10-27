"""Synthetic HTTP responses only; no credentials or live network integration."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.synthetic_demo import fixture
from style_xi.acquire import Downloader, fresh_remaining
from style_xi.runner import run_plan
from style_xi.storage import DataError, atomic_json, read_json

SCOPE = {"competition_id": 900301, "season": 2025, "stage": "all_provider_stages"}
PARAMS = {"leagueId": 900301, "season": 2025, "offset": 0, "limit": 1}
TOKEN = "fictional-test-token"


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.account = self.root / "account.json"
        atomic_json(self.account, {"observation": {"observed_utc": datetime.now(timezone.utc).isoformat(),
                                                   "remaining": 20}, "attempts": []})
        self.calls = 0

    def transport(self, path, params, key):
        self.calls += 1
        # Reservation must already be durable when any network dispatch begins.
        state = read_json(self.root / "budget" / "requests.json")
        self.assertEqual(state["attempts"][-1]["outcome"], "reserved")
        return 200, {"x-ratelimit-requests-remaining": "19"}, json.dumps({
            "data": [fixture()], "pagination": {"offset": 0, "limit": 1, "totalCount": 1},
            "plan": {"tier": "BASIC"}}).encode()

    def client(self, cap=50, transport=None):
        return Downloader(self.root / "budget", self.account, cap, transport=transport or self.transport)

    def get(self, client):
        return client.get("/matches", PARAMS, SCOPE, TOKEN)

    def test_cache_hit_after_restart_no_new_requests_or_key(self):
        first = self.get(self.client())
        second = self.client().get("/matches", PARAMS, SCOPE, None)
        self.assertEqual(first, second)
        self.assertEqual(self.calls, 1)
        self.assertEqual(len(self.client().ledger()["attempts"]), 1)

    def test_dry_run_no_network_no_files_or_credential(self):
        self.account.unlink()
        plan = self.client().plan([("/matches", PARAMS, SCOPE)])
        self.assertEqual(plan["network_requests"], 0)
        self.assertFalse((self.root / "budget").exists())
        self.assertEqual(self.calls, 0)

    def test_failures_count_and_stop_across_restart(self):
        for status in (301, 401, 402, 403, 429, 500):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                account = root / "account.json"
                atomic_json(account, read_json(self.account))
                client = Downloader(root / "budget", account, transport=lambda *args: (status, {}, b"{}"))
                with self.assertRaises(DataError):
                    self.get(client)
                self.assertEqual(len(client.ledger()["attempts"]), 1)
                with self.assertRaises(DataError):
                    self.get(client)
                self.assertEqual(len(client.ledger()["attempts"]), 1)

    def test_transport_error_does_not_echo_secret_or_retry(self):
        def failing(*args):
            raise OSError(TOKEN)
        client = self.client(transport=failing)
        with self.assertRaisesRegex(DataError, "transport_schema_or_storage_failure"):
            self.get(client)
        self.assertNotIn(TOKEN, (client.root / "requests.json").read_text())
        self.assertEqual(len(client.ledger()["attempts"]), 1)

    def test_budget_persists_and_cannot_be_reset_by_changing_cap(self):
        self.get(self.client(cap=1))
        client = self.client(cap=1)
        with self.assertRaisesRegex(DataError, "request_budget_exhausted"):
            client.get("/box-score/900001", {}, SCOPE, TOKEN)
        with self.assertRaisesRegex(DataError, "cap_changed"):
            self.client(cap=2).ledger()
        self.assertEqual(self.calls, 1)

    def test_stale_missing_or_reserved_daily_balance_blocks_dispatch(self):
        for observation in ({}, {"observed_utc": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), "remaining": 73},
                            {"observed_utc": datetime.now(timezone.utc).isoformat(), "remaining": 10}):
            atomic_json(self.account, {"observation": observation})
            with self.assertRaises(DataError):
                self.get(self.client())
        self.assertEqual(self.calls, 0)

    def test_other_known_usage_debits_account(self):
        at = datetime.now(timezone.utc)
        observation = {"observed_utc": (at - timedelta(seconds=5)).isoformat(), "remaining": 12}
        attempts = [{"reserved_utc": (at - timedelta(seconds=1)).isoformat()}] * 2
        self.assertEqual(fresh_remaining(observation, attempts, at), 10)

    def test_interruption_after_cache_write_recovers_without_dispatch(self):
        snapshot = self.get(self.client())
        path = self.root / "budget" / "requests.json"
        state = read_json(path)
        state["attempts"][0]["outcome"] = "reserved"
        atomic_json(path, state)
        self.assertEqual(self.get(self.client()), snapshot)
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.client().ledger()["attempts"][0]["outcome"], "success")

    def test_uncertain_interrupted_request_is_counted_and_not_redispatched(self):
        self.get(self.client())
        client = self.client()
        for path in (client.root / "responses").glob("*.json"):
            path.unlink()
        state = client.ledger()
        state["attempts"][0]["outcome"] = "reserved"
        atomic_json(client.root / "requests.json", state)
        with self.assertRaisesRegex(DataError, "uncertain_interrupted_request"):
            self.get(client)
        self.assertEqual(self.calls, 1)

    def test_atomic_write_interruption_keeps_previous_file(self):
        path = self.root / "state.json"
        atomic_json(path, {"old": True})
        with patch("style_xi.storage.os.replace", side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError):
                atomic_json(path, {"new": True})
        self.assertEqual(read_json(path), {"old": True})

    def test_secret_echo_is_redacted_from_cached_body_and_raw(self):
        def echo(*args):
            return 200, {}, json.dumps({"echo": TOKEN, "apiKey": TOKEN}).encode()
        snapshot = self.get(self.client(transport=echo))
        self.assertNotIn(TOKEN, json.dumps(snapshot))
        self.assertFalse(snapshot["raw_body_retained"])

    def test_corrupted_cache_is_not_a_network_retry(self):
        self.get(self.client())
        path = next((self.root / "budget" / "responses").glob("*.json"))
        value = read_json(path)
        value["body"]["data"] = []
        atomic_json(path, value)
        with self.assertRaisesRegex(DataError, "cache_integrity_failure"):
            self.get(self.client())
        self.assertEqual(self.calls, 1)

    def test_checkpoint_resume_and_plan_change_guard(self):
        calls = [("/matches", PARAMS, SCOPE)]
        checkpoint = run_plan(self.client(), calls, TOKEN)
        self.assertTrue(checkpoint["coverage"][0]["provider_manifest_complete"])
        run_plan(self.client(), calls, None)
        self.assertEqual(self.calls, 1)
        with self.assertRaisesRegex(DataError, "changed_request_plan"):
            run_plan(self.client(), [("/box-score/900001", {}, SCOPE)], TOKEN)

    def test_endpoint_allowlist_prevents_unrelated_requests(self):
        for endpoint in ("/odds", "/players/900201", "/highlights", "https://example.com/"):
            with self.assertRaises(DataError):
                self.client().get(endpoint, {}, SCOPE, TOKEN)
        self.assertEqual(self.calls, 0)

    def test_shared_account_reservation_blocks_second_budget_at_reserve(self):
        def response(*args):
            return 200, {"x-ratelimit-requests-remaining": "10"}, b"[]"
        first = self.client(transport=response)
        first.get("/box-score/900001", {}, SCOPE, TOKEN)
        second = Downloader(self.root / "another-budget", self.account, transport=response)
        with self.assertRaisesRegex(DataError, "daily_reserve_reached"):
            second.get("/box-score/900002", {}, SCOPE, TOKEN)
        self.assertEqual(len(read_json(self.account)["attempts"]), 1)

    def test_runner_repeated_page_stops_before_next_request(self):
        def page(path, params, key):
            self.calls += 1
            return 200, {"x-ratelimit-requests-remaining": "18"}, json.dumps({
                "data": [fixture()], "pagination": {"offset": params["offset"], "limit": 1, "totalCount": 3}}).encode()
        calls = [("/matches", PARAMS | {"offset": offset}, SCOPE) for offset in range(3)]
        with self.assertRaisesRegex(DataError, "repeated_page"):
            run_plan(self.client(transport=page), calls, TOKEN)
        self.assertEqual(self.calls, 2)
        self.assertIn("repeated_page", read_json(self.root / "budget" / "checkpoint.json")["halted"])

    def test_secret_as_response_dictionary_key_is_redacted(self):
        snapshot = self.get(self.client(transport=lambda *args: (200, {}, json.dumps({TOKEN: "echo"}).encode())))
        self.assertNotIn(TOKEN, json.dumps(snapshot))

    def test_raw_cache_corruption_is_detected(self):
        self.get(self.client())
        path = next((self.root / "budget" / "responses").glob("*.json"))
        value = read_json(path)
        value["raw_body_utf8"] = "{}"
        atomic_json(path, value)
        with self.assertRaisesRegex(DataError, "raw_cache_integrity_failure"):
            self.get(self.client())
        self.assertEqual(self.calls, 1)

    def test_shared_history_prevents_lost_budget_reset_after_failure(self):
        client = self.client(transport=lambda *args: (_ for _ in ()).throw(OSError()))
        with self.assertRaises(DataError):
            self.get(client)
        (client.root / "requests.json").unlink()
        account = read_json(self.account)
        account["halted"] = None  # Even an accidentally cleared halt cannot reset the missing budget.
        atomic_json(self.account, account)
        with self.assertRaisesRegex(DataError, "budget_ledger_missing_with_account_history"):
            self.get(self.client())


if __name__ == "__main__":
    unittest.main()
