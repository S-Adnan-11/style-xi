"""Capture and verify private evaluation inputs without following live paths."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import tempfile

from .campaign import inventory
from .holds import held_matches
from .pipeline import prepare_snapshot, replay
from .storage import DataError, atomic_json, canonical, digest, exclusive, now, read_json


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _require(condition, code):
    if not condition:
        raise DataError("evaluation_snapshot_" + code)


def _json(raw):
    value = json.loads(raw)
    canonical(value)  # Reject nonfinite JSON numbers using the existing contract.
    _require(isinstance(value, dict), "invalid_document")
    return value


def _outside_worktree(path):
    _require(not any((parent / ".git").exists() for parent in (path, *path.parents)),
             "must_be_outside_worktree")


def _file(root, relative):
    _require(isinstance(relative, str) and relative != "", "invalid_file_path")
    name = PurePosixPath(relative)
    _require(not name.is_absolute() and not PureWindowsPath(relative).drive
             and "\\" not in relative and ".." not in name.parts, "invalid_file_path")
    path = root.joinpath(*name.parts)
    _require(path.is_file() and not path.is_symlink()
             and path.resolve().is_relative_to(root.resolve()), "missing_or_unsafe_file")
    return path


def _latest_batch(campaign):
    batches = [(path, read_json(path)) for path in (campaign.root / "batches").glob("*.json")]
    completed = [(path, batch) for path, batch in batches if batch.get("finished_utc")]
    _require(bool(completed), "no_completed_batch")
    return max(completed, key=lambda entry: entry[1]["finished_utc"])


def _publish(stage, destination):
    # mkdir reserves the destination without POSIX rename's empty-directory
    # replacement behavior. Readers require the completion marker published last.
    try:
        destination.mkdir()
    except FileExistsError:
        raise DataError("evaluation_snapshot_destination_exists") from None
    for path in stage.iterdir():
        if path.name != "READY.json":
            os.rename(path, destination / path.name)
    _read_snapshot(destination, published=False)
    os.link(stage / "READY.json", destination / "READY.json")
    (stage / "READY.json").unlink()
    stage.rmdir()


def capture_evaluation_snapshot(campaign, destination, *, protocol, match_holds,
                                implementation_files=None, engine_files=None,
                                code_revision=None, input_manifest=None):
    """Freeze inputs under the same two locks used by Campaign.run().

    Code mappings associate manifest labels with local files. An existing input
    manifest may be supplied; its bytes and pins must match this locked capture.
    Otherwise the compatible manifest is built while collection is locked.
    No collection, profile fitting or player comparison is performed.
    """
    destination = Path(destination).resolve()
    _require(not destination.name.startswith(".capture-"), "reserved_destination_name")
    _outside_worktree(destination)
    _require(not destination.exists(), "destination_exists")
    implementations = {name: Path(path) for name, path in (implementation_files or {}).items()}
    if engine_files is None:
        engine_files = {"style_xi/" + path.name: path for path in sorted(Path(__file__).parent.glob("*.py"))}
    engines = {name: Path(path) for name, path in engine_files.items()}
    with exclusive(campaign.account.with_suffix(".run.lock")), exclusive(campaign.root / "campaign.lock"):
        _require(not destination.exists(), "destination_exists")
        status, imported, fixtures, _, _, snapshots = campaign.inspect()
        ledger = campaign.client.ledger()
        account = read_json(campaign.account)
        checkpoint = read_json(campaign.root / "checkpoint.json")
        batch_path, batch = _latest_batch(campaign)
        registry, gate = read_json(match_holds), status["field_validation_gate"]
        _require(not status["halted"] and not status["uncertain_attempts"] and not status["failures"],
                 "campaign_not_ready")
        _require(not imported["match_diagnostics"]
                 and not any(row["status"] == "quarantined" for row in imported["excluded_records"]),
                 "inputs_need_review")
        sources = []
        for snapshot in snapshots:
            source = Path(snapshot["source_file"])
            if not source.is_absolute():
                source = campaign.root / "responses" / source
            sources.append({"path": str(source), "source_file": snapshot["source_file"],
                            "sha256": _hash(source.read_bytes()), "snapshot_id": snapshot["snapshot_id"]})
        calendar = [{"provider": "highlightly", "match_id": mid, "date": fixture.get("date")}
                    for mid, fixture in fixtures.items()]
        impl_hashes = {name: _hash(path.read_bytes()) for name, path in implementations.items()}
        engine_hashes = {name: _hash(path.read_bytes()) for name, path in engines.items()}
        manifest = {"protocol_sha256": _hash(Path(protocol).read_bytes()),
                    "last_completed_batch": str(batch_path), "batch_sha256": _hash(batch_path.read_bytes()),
                    "batch_finished_utc": batch["finished_utc"], "campaign_attempts": len(ledger["attempts"]),
                    "ledger_sha256": digest(ledger),
                    "snapshots_sha256": digest(sorted((s["snapshot_id"], s["source_file"]) for s in snapshots)),
                    "accepted_import_sha256": digest(imported), "calendar_sha256": digest(calendar),
                    "holds_sha256": digest(registry), "gate_sha256": digest(gate),
                    "competitions": campaign.manifest["competitions"],
                    "implementation_files": impl_hashes, "implementation_sha256": digest(impl_hashes),
                    "engine_files": engine_hashes, "public_revision": code_revision, "source_files": sources}
        if input_manifest is not None:
            original = read_json(input_manifest)
            _require(original == manifest, "input_manifest_changed")
            manifest_raw = Path(input_manifest).read_bytes()
        else:
            manifest_raw = canonical(manifest) + b"\n"
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".capture-", dir=destination.parent))
        files = {}

        def save(label, relative, raw, expected=None):
            _require(expected is None or _hash(raw) == expected, "source_changed_during_capture")
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            files[label] = {"path": relative, "sha256": _hash(raw)}

        save("input_manifest", "input-manifest.json", manifest_raw)
        save("campaign", "campaign.json", campaign.path.read_bytes())
        save("ledger", "ledger.json", (campaign.root / "requests.json").read_bytes())
        save("account", "account.json", campaign.account.read_bytes())
        save("checkpoint", "checkpoint.json", (campaign.root / "checkpoint.json").read_bytes())
        save("batch", "batch.json", batch_path.read_bytes(), manifest["batch_sha256"])
        save("holds", "holds.json", Path(match_holds).read_bytes())
        if campaign.manifest.get("validation_gate"):
            save("gate", "gate.json", Path(campaign.manifest["validation_gate"]).read_bytes())
        else:
            save("gate", "gate.json", canonical(gate) + b"\n")
        save("protocol", "protocol.md", Path(protocol).read_bytes(), manifest["protocol_sha256"])
        for index, pin in enumerate(sources):
            save("source:" + str(index), f"inputs/{index:05d}.json", Path(pin["path"]).read_bytes(), pin["sha256"])
        for kind, paths in (("implementation", implementations), ("engine", engines)):
            for index, (name, path) in enumerate(paths.items()):
                save(kind + ":" + name, f"code/{kind}-{index:03d}.py", path.read_bytes(),
                     manifest[kind + "_files"][name])
        for index, pin in enumerate(campaign.manifest["baseline_files"]):
            save("baseline:" + str(index), f"baseline/{index:05d}.bin", Path(pin["path"]).read_bytes(), pin["sha256"])
        for index, path in enumerate(campaign.manifest["history"]):
            save("history:" + str(index), f"history/{index:03d}.json", Path(path).read_bytes())
        descriptor = {"version": 1, "captured_utc": now(), "source_campaign_root": str(campaign.root.resolve()),
                      "input_manifest_sha256": digest(manifest), "files": files}
        atomic_json(stage / "snapshot.json", descriptor)
        # Validate copied bytes and replay before writing the completion marker.
        _read_snapshot(stage, published=False)
        snapshot_hash = _hash((stage / "snapshot.json").read_bytes())
        atomic_json(stage / "READY.json", {"version": 1, "snapshot_sha256": snapshot_hash,
                                          "input_manifest_sha256": digest(manifest)})
        _require(not destination.exists(), "destination_exists")
        _publish(stage, destination)
        return {"snapshot_sha256": snapshot_hash, "input_manifest_sha256": digest(manifest),
                "campaign_attempts": len(ledger["attempts"]), "provider_requests": 0}


def _read_snapshot(directory, *, published=True, expected_snapshot_sha256=None,
                   expected_input_manifest_sha256=None):
    root = Path(directory).resolve()
    if published:
        _require(not root.name.startswith(".capture-"), "capture_not_published")
    descriptor_raw = _file(root, "snapshot.json").read_bytes()
    descriptor = _json(descriptor_raw)
    snapshot_hash = _hash(descriptor_raw)
    _require(descriptor.get("version") == 1 and isinstance(descriptor.get("files"), dict), "invalid_descriptor")
    if published:
        ready_raw = _file(root, "READY.json").read_bytes()
        ready = _json(ready_raw)
        _require(ready_raw == canonical(ready) + b"\n", "completion_mismatch")
        _require(ready == {"version": 1, "snapshot_sha256": snapshot_hash,
                          "input_manifest_sha256": descriptor.get("input_manifest_sha256")}, "completion_mismatch")
    _require(expected_snapshot_sha256 is None or snapshot_hash == expected_snapshot_sha256, "descriptor_changed")
    files = descriptor["files"]
    _require(len({entry["path"] for entry in files.values()}) == len(files), "duplicate_file_path")
    frozen = {}
    for label, entry in files.items():
        frozen[label] = _file(root, entry["path"]).read_bytes()
        _require(_hash(frozen[label]) == entry["sha256"], "file_changed")

    def load(label):
        _require(label in frozen, "missing_artifact")
        return _json(frozen[label])

    manifest, campaign = load("input_manifest"), load("campaign")
    _require(digest(manifest) == descriptor["input_manifest_sha256"], "manifest_changed")
    _require(expected_input_manifest_sha256 is None or digest(manifest) == expected_input_manifest_sha256,
             "manifest_changed")
    ledger, account, checkpoint = load("ledger"), load("account"), load("checkpoint")
    batch, registry, gate = load("batch"), load("holds"), load("gate")
    policy = {"manifest_sha256": digest(campaign), "cap": 1800, "daily_cap": 90, "reserve": 10}
    budget_id = digest(descriptor["source_campaign_root"])
    _require(ledger.get("campaign") == policy and account.get("campaign") == {**policy, "budget_id": budget_id}
             and checkpoint.get("manifest_sha256") == policy["manifest_sha256"], "campaign_anchor_changed")
    _require(not any(doc.get("halted") for doc in (ledger, account, checkpoint))
             and batch.get("workflow_halted") is False, "campaign_not_ready")
    attempts = ledger["attempts"]
    _require(digest(ledger) == manifest["ledger_sha256"] and len(attempts) == manifest["campaign_attempts"]
             == batch["campaign_attempts"], "ledger_changed")
    _require(all(a["outcome"] == "success" and a["reserved_utc"] <= batch["finished_utc"] for a in attempts),
             "uncertain_or_failed_attempt")
    local = {(a["request_id"], a["reserved_utc"]) for a in attempts}
    shared = {(a["request_id"], a["reserved_utc"]) for a in account.get("attempts", []) if a.get("budget_id") == budget_id}
    _require(local == shared, "shared_reservations_changed")
    _require(files["batch"]["sha256"] == manifest["batch_sha256"]
             and batch["finished_utc"] == manifest["batch_finished_utc"], "batch_changed")
    _require(digest(registry) == manifest["holds_sha256"] and digest(gate) == manifest["gate_sha256"],
             "holds_or_gate_changed")
    held_matches(registry)
    _require(gate.get("real_comparison_allowed", False) is False
             and gate.get("real_integration_allowed", False) is False, "general_gate_changed")
    _require(files["protocol"]["sha256"] == manifest["protocol_sha256"], "protocol_changed")
    for kind in ("implementation", "engine"):
        for name, expected in manifest[kind + "_files"].items():
            _require(files[kind + ":" + name]["sha256"] == expected, "code_changed")
    _require(digest(manifest["implementation_files"]) == manifest["implementation_sha256"], "code_changed")
    for index, pin in enumerate(campaign["baseline_files"]):
        _require(files["baseline:" + str(index)]["sha256"] == pin["sha256"], "baseline_changed")
    for index in range(len(campaign["history"])):
        load("history:" + str(index))
    snapshots = []
    for index, pin in enumerate(manifest["source_files"]):
        label = "source:" + str(index)
        _require(files[label]["sha256"] == pin["sha256"], "source_changed")
        snapshot = prepare_snapshot(load(label), pin["source_file"])
        _require(snapshot is not None and snapshot["snapshot_id"] == pin["snapshot_id"], "source_identity_changed")
        snapshots.append(snapshot)
    _require(digest(sorted((s["snapshot_id"], s["source_file"]) for s in snapshots)) == manifest["snapshots_sha256"],
             "source_set_changed")
    by_request = {s.get("request_id"): s for s in snapshots}
    for attempt in attempts:
        cached = by_request.get(attempt["request_id"])
        _require(cached is not None and cached.get("stored_body_sha256") == attempt.get("snapshot_id")
                 and all(cached.get(key) == attempt.get(key) for key in ("endpoint", "parameters", "scope")),
                 "response_ledger_mismatch")
    imported = replay(snapshots)
    _require(digest(imported) == manifest["accepted_import_sha256"], "replay_changed")
    _require(not imported["match_diagnostics"]
             and not any(row["status"] == "quarantined" for row in imported["excluded_records"]), "inputs_need_review")
    _require(campaign["competitions"] == manifest["competitions"], "scope_changed")
    _, fixtures = inventory(snapshots, manifest["competitions"], campaign["season"])
    calendar = [{"provider": "highlightly", "match_id": mid, "date": fixture.get("date")}
                for mid, fixture in fixtures.items()]
    _require(digest(calendar) == manifest["calendar_sha256"], "calendar_changed")
    return {"manifest": manifest, "snapshots": snapshots, "import_result": imported,
            "calendar": calendar, "holds": registry, "gate": gate,
            "ledger": ledger, "account": account, "checkpoint": checkpoint,
            "verification": {"snapshot_sha256": snapshot_hash, "input_manifest_sha256": digest(manifest),
                             "campaign_attempts": len(attempts), "source_files": len(snapshots),
                             "regular_matches": len({(r["provider"], r["match_id"]) for r in imported["player_matches"]
                                                     if r["stage"] == "regular"}),
                             "provider_requests": 0, "live_inputs_read": False}}


def read_evaluation_snapshot(directory, *, expected_snapshot_sha256=None,
                             expected_input_manifest_sha256=None):
    """Return verified frozen inputs in memory. Never follow manifest origin paths."""
    try:
        return _read_snapshot(directory, expected_snapshot_sha256=expected_snapshot_sha256,
                              expected_input_manifest_sha256=expected_input_manifest_sha256)
    except (AttributeError, KeyError, TypeError, ValueError, OSError):
        raise DataError("evaluation_snapshot_invalid_or_incomplete") from None


def verify_evaluation_snapshot(directory, *, expected_snapshot_sha256=None,
                               expected_input_manifest_sha256=None):
    """Return only aggregate verification metadata from the frozen bundle."""
    return read_evaluation_snapshot(directory, expected_snapshot_sha256=expected_snapshot_sha256,
                                     expected_input_manifest_sha256=expected_input_manifest_sha256)["verification"]
