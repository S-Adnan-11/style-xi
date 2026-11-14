"""Frozen evaluation inputs tested with fictional collection and temporary files."""

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

from examples.synthetic_demo import body, fixture
from style_xi.campaign import Campaign, COMPLETED
from style_xi.evaluation_snapshot import capture_evaluation_snapshot, read_evaluation_snapshot, verify_evaluation_snapshot
from style_xi.storage import DataError, atomic_json, exclusive, read_json


class EvaluationSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.account = self.root / "account.json"
        self.gate = self.root / "gate.json"
        self.holds = self.root / "holds.json"
        self.protocol = self.root / "protocol.md"
        self.code = self.root / "fictional_runner.py"
        self.protocol.write_text("Fictional evaluation protocol.\n", encoding="utf-8")
        self.code.write_text("# Fictional code input.\n", encoding="utf-8")
        atomic_json(self.holds, {"version": 1, "cases": {}})
        atomic_json(self.gate, {"allow_box_scores": True, "real_comparison_allowed": False,
                                "real_integration_allowed": False})
        atomic_json(self.account, {"attempts": [], "observation": {}})
        config = {"version": 1, "season": 2025, "cap": 1800, "daily_cap": 90, "reserve": 10,
                  "regular_stage_rule": "Regular Season - [1-9][0-9]*", "completed_states": list(COMPLETED),
                  "competitions": [{"id": 900301 + i, "name": "Fictional league " + str(i)} for i in range(5)],
                  "interval_seconds": 1, "state": str(self.root / "state"), "account": str(self.account),
                  "history": [], "baseline_files": [], "validation_gate": str(self.gate)}
        self.config = self.root / "campaign.json"
        atomic_json(self.config, config)
        self.calls, self.remaining = [], 100
        self.campaign = Campaign(self.config, transport=self.transport, sleeper=lambda _: None)
        self.campaign.initialize()
        self.campaign.run("fictional-token", max_new_attempts=10)
        self.output = self.root / "snapshots/first"

    def transport(self, endpoint, params, token):
        self.calls.append(endpoint)
        self.remaining -= 1
        if endpoint == "/matches":
            rows = []
            for index in range(2):
                row = fixture(match=params["leagueId"] * 100 + index)
                row["league"]["id"] = params["leagueId"]
                row["date"] = "2025-08-16T15:00:00Z"
                rows.append(row)
            payload = {"data": rows, "pagination": {"offset": 0, "limit": 100, "totalCount": 2},
                       "plan": {"tier": "BASIC"}}
        else:
            payload = body()
        return 200, {"x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": str(self.remaining)}, json.dumps(payload).encode()

    def capture(self, output=None, **kwargs):
        return capture_evaluation_snapshot(self.campaign, output or self.output, protocol=self.protocol,
            match_holds=self.holds, implementation_files={"runner.py": self.code},
            engine_files={"fictional_engine.py": self.code}, code_revision="fictional-revision", **kwargs)

    def frozen_files(self):
        descriptor = read_json(self.output / "snapshot.json")
        return [self.output / entry["path"] for entry in descriptor["files"].values()]

    def test_capture_preserves_exact_control_and_manifest_bytes_without_transport(self):
        # Formatting is part of the evidence, even when parsed JSON is unchanged.
        self.account.write_text(json.dumps(read_json(self.account), indent=3) + "\n", encoding="utf-8")
        before = {name: path.read_bytes() for name, path in (
            ("ledger.json", self.campaign.root / "requests.json"), ("account.json", self.account),
            ("checkpoint.json", self.campaign.root / "checkpoint.json"))}
        count = len(self.calls)
        receipt = self.capture()
        for name, raw in before.items():
            self.assertEqual((self.output / name).read_bytes(), raw)
        self.assertEqual(len(self.calls), count)
        verified = verify_evaluation_snapshot(self.output,
            expected_snapshot_sha256=receipt["snapshot_sha256"],
            expected_input_manifest_sha256=receipt["input_manifest_sha256"])
        self.assertEqual(verified["campaign_attempts"], 10)
        self.assertEqual(verified["regular_matches"], 5)
        second = self.root / "snapshots/second"
        self.capture(second, input_manifest=self.output / "input-manifest.json")
        self.assertEqual((second / "input-manifest.json").read_bytes(), (self.output / "input-manifest.json").read_bytes())

    def test_collection_advances_without_invalidating_frozen_verification(self):
        self.capture()
        frozen = verify_evaluation_snapshot(self.output)
        resumed = self.campaign.run("fictional-token")
        self.assertEqual(resumed["campaign_attempts"], 15)
        self.assertEqual(verify_evaluation_snapshot(self.output), frozen)
        self.assertEqual(len(read_evaluation_snapshot(self.output)["ledger"]["attempts"]), 10)

    def test_verifier_works_after_live_inputs_and_code_are_unavailable(self):
        self.capture()
        expected = verify_evaluation_snapshot(self.output)
        self.campaign.root.rename(self.root / "moved-live-state")
        for path in (self.account, self.config, self.protocol, self.code, self.holds, self.gate):
            path.unlink()
        with patch("style_xi.campaign.Campaign.inspect", side_effect=AssertionError("live inspection forbidden")):
            self.assertEqual(verify_evaluation_snapshot(self.output), expected)

    def test_verification_is_read_only_and_reads_only_bundle_json(self):
        self.capture()
        before = {str(p): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        from style_xi.evaluation_snapshot import _file

        def inside_only(root, relative):
            self.assertEqual(root, self.output.resolve())
            path = _file(root, relative)
            self.assertTrue(path.resolve().is_relative_to(self.output.resolve()))
            return path

        with patch("style_xi.evaluation_snapshot._file", side_effect=inside_only):
            verify_evaluation_snapshot(self.output)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.output.rglob("*") if p.is_file()})

    def test_public_readers_cannot_bypass_publication_checks(self):
        self.capture()
        for reader in (read_evaluation_snapshot, verify_evaluation_snapshot):
            with self.assertRaises(TypeError):
                reader(self.output, published=False)

    def test_nonobject_json_fails_with_bounded_diagnostic(self):
        self.capture()
        (self.output / "snapshot.json").write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(DataError, "invalid_document"):
            verify_evaluation_snapshot(self.output)

    def test_parser_uses_the_exact_bytes_that_passed_hash_verification(self):
        self.capture()
        from style_xi.evaluation_snapshot import _json
        ledger = (self.output / "ledger.json").read_bytes()

        def alter_after_hash(raw):
            if raw == ledger:
                (self.output / "ledger.json").write_bytes(b"{}")
            return _json(raw)

        with patch("style_xi.evaluation_snapshot._json", side_effect=alter_after_hash):
            loaded = read_evaluation_snapshot(self.output)
        self.assertEqual(len(loaded["ledger"]["attempts"]), 10)
        with self.assertRaisesRegex(DataError, "file_changed"):
            verify_evaluation_snapshot(self.output)

    def test_complete_bundle_can_move_and_cli_reports_only_verification_metadata(self):
        self.capture()
        expected = verify_evaluation_snapshot(self.output)
        relocated = self.root / "relocated"
        self.output.rename(relocated)
        self.assertEqual(verify_evaluation_snapshot(relocated), expected)
        from scripts.evaluation_snapshot import main
        output = io.StringIO()
        with redirect_stdout(output):
            main(["verify", str(relocated), "--expected-sha256", expected["snapshot_sha256"]])
        self.assertEqual(json.loads(output.getvalue()), expected)
        self.assertNotIn("player_matches", output.getvalue())

    def test_capture_cli_freezes_existing_local_inputs_without_collection(self):
        script = Path(__file__).resolve().parents[1] / "scripts/evaluation_snapshot.py"
        process = subprocess.run([sys.executable, "-B", str(script), "capture", "--campaign", str(self.config),
            "--protocol", str(self.protocol), "--match-holds", str(self.holds), "--output", str(self.output),
            "--implementation-file", "runner.py", str(self.code),
            "--engine-file", "fictional_engine.py", str(self.code), "--code-revision", "fictional-revision"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        receipt = json.loads(process.stdout)
        self.assertEqual(receipt["campaign_attempts"], 10)
        self.assertEqual(len(self.campaign.client.ledger()["attempts"]), 10)
        verify_evaluation_snapshot(self.output, expected_snapshot_sha256=receipt["snapshot_sha256"])

    def test_missing_or_modified_files_fail_including_control_artifacts(self):
        self.capture()
        for path in [*self.frozen_files(), self.output / "snapshot.json", self.output / "READY.json"]:
            with self.subTest(file=path.relative_to(self.output)):
                raw = path.read_bytes()
                path.unlink()
                with self.assertRaises(DataError):
                    verify_evaluation_snapshot(self.output)
                path.write_bytes(raw + b" ")
                with self.assertRaises(DataError):
                    verify_evaluation_snapshot(self.output)
                path.write_bytes(raw)
        verify_evaluation_snapshot(self.output)

    def test_collector_locks_exclude_capture_and_remain_held_during_inspection(self):
        for lock in (self.account.with_suffix(".run.lock"), self.campaign.root / "campaign.lock"):
            with self.subTest(lock=lock.name), exclusive(lock):
                with self.assertRaisesRegex(DataError, "another_process"):
                    self.capture()
        inspect = self.campaign.inspect

        def while_locked():
            with self.assertRaisesRegex(DataError, "another_process"):
                self.campaign.run(None)
            return inspect()

        with patch.object(self.campaign, "inspect", side_effect=while_locked):
            self.capture()

    def test_interruption_during_copy_never_publishes_or_resumes_partial_capture(self):
        with patch("style_xi.evaluation_snapshot.os.fsync", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.capture()
        self.assertFalse(self.output.exists())
        partials = list(self.output.parent.glob(".capture-*"))
        self.assertEqual(len(partials), 1)
        with self.assertRaises(DataError):
            verify_evaluation_snapshot(partials[0])
        self.capture()
        verify_evaluation_snapshot(self.output)
        self.assertTrue(partials[0].exists())

    def test_interruption_at_publication_leaves_no_valid_partial_snapshot(self):
        with patch("style_xi.evaluation_snapshot.os.link", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.capture()
        self.assertTrue(self.output.exists())
        self.assertFalse((self.output / "READY.json").exists())
        with self.assertRaises(DataError):
            verify_evaluation_snapshot(self.output)
        with self.assertRaisesRegex(DataError, "destination_exists"):
            self.capture()
        for partial in self.output.parent.glob(".capture-*"):
            self.assertTrue((partial / "READY.json").exists())
            with self.assertRaisesRegex(DataError, "capture_not_published"):
                verify_evaluation_snapshot(partial)

    def test_destination_reservation_does_not_replace_a_racing_creator(self):
        original = Path.mkdir

        def competing_creator(path, *args, **kwargs):
            if path == self.output.resolve():
                original(path)
                (path / "keep.txt").write_text("Unrelated content", encoding="utf-8")
            return original(path, *args, **kwargs)

        with patch.object(Path, "mkdir", new=competing_creator):
            with self.assertRaisesRegex(DataError, "destination_exists"):
                self.capture()
        self.assertEqual((self.output / "keep.txt").read_text(encoding="utf-8"), "Unrelated content")
        self.assertEqual([p.name for p in self.output.iterdir()], ["keep.txt"])

    def test_copied_inputs_are_verified_before_publication(self):
        from style_xi.evaluation_snapshot import _read_snapshot

        def damage(stage, **kwargs):
            (stage / "checkpoint.json").write_bytes(b"{}")
            return _read_snapshot(stage, **kwargs)

        with patch("style_xi.evaluation_snapshot._read_snapshot", side_effect=damage):
            with self.assertRaisesRegex(DataError, "file_changed"):
                self.capture()
        self.assertFalse(self.output.exists())

    def test_existing_output_and_stale_input_manifest_are_never_overwritten(self):
        self.capture()
        before = (self.output / "snapshot.json").read_bytes()
        with self.assertRaisesRegex(DataError, "destination_exists"):
            self.capture()
        self.campaign.run("fictional-token")
        with self.assertRaisesRegex(DataError, "input_manifest_changed"):
            self.capture(self.root / "snapshots/stale", input_manifest=self.output / "input-manifest.json")
        self.assertEqual((self.output / "snapshot.json").read_bytes(), before)
        self.assertFalse((self.root / "snapshots/stale").exists())

    def test_halted_or_uncertain_campaign_cannot_publish(self):
        path = self.campaign.root / "checkpoint.json"
        checkpoint = read_json(path)
        atomic_json(path, {**checkpoint, "halted": "fictional_validation_failure"})
        with self.assertRaisesRegex(DataError, "campaign_not_ready"):
            self.capture()
        atomic_json(path, checkpoint)
        ledger = self.campaign.client.ledger()
        ledger["attempts"][-1]["outcome"] = "reserved"
        atomic_json(self.campaign.root / "requests.json", ledger)
        with self.assertRaisesRegex(DataError, "campaign_not_ready"):
            self.capture()
        self.assertFalse(self.output.exists())

    def test_external_fingerprint_and_unsafe_file_paths_fail(self):
        self.capture()
        with self.assertRaisesRegex(DataError, "descriptor_changed"):
            verify_evaluation_snapshot(self.output, expected_snapshot_sha256="changed")
        with self.assertRaisesRegex(DataError, "manifest_changed"):
            verify_evaluation_snapshot(self.output, expected_input_manifest_sha256="changed")
        descriptor = read_json(self.output / "snapshot.json")
        descriptor["files"]["ledger"]["path"] = "../account.json"
        atomic_json(self.output / "snapshot.json", descriptor)
        atomic_json(self.output / "READY.json", {"version": 1,
            "snapshot_sha256": hashlib.sha256((self.output / "snapshot.json").read_bytes()).hexdigest(),
            "input_manifest_sha256": descriptor["input_manifest_sha256"]})
        with self.assertRaisesRegex(DataError, "invalid_file_path"):
            verify_evaluation_snapshot(self.output)

    def test_outputs_inside_a_worktree_are_rejected(self):
        parent = self.root / "fictional-worktree"
        parent.mkdir()
        (parent / ".git").write_text("gitdir: fictional\n", encoding="utf-8")
        with self.assertRaisesRegex(DataError, "must_be_outside_worktree"):
            self.capture(parent / "ignored/snapshot")

    def test_reserved_staging_name_cannot_be_a_published_destination(self):
        with self.assertRaisesRegex(DataError, "reserved_destination_name"):
            self.capture(self.root / "snapshots/.capture-final")


if __name__ == "__main__":
    unittest.main()
