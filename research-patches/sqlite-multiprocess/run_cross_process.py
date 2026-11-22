"""Two-worker-process SQLite approval-chain race and patch verification.

Usage:
  python research-patches/sqlite-multiprocess/run_cross_process.py original
  python research-patches/sqlite-multiprocess/run_cross_process.py patched
The working directory is the research repository root, and the Microsoft
upstream checkout must already exist at the pinned revision.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research-support"))
if os.environ.get("AEI_USE_INSTALLED_PACKAGE") != "1":
    from agentmesh_protocol_bootstrap import install
    install()
from agentmesh.governance.approval_protocol import (
    ActionBinding,
    ActionTarget,
    ApprovalChain,
    ApprovalCoordinator,
    ApprovalStage,
    ApproverKind,
    EntryDecision,
    Outcome,
    ReasonCode,
)
from sqlite_approval_store import SQLiteApprovalStore


def chain():
    return ApprovalChain(
        chain_id="synthetic-two-stage",
        version="1",
        stages=(
            ApprovalStage(0, allowed_identities=frozenset({"alice"})),
            ApprovalStage(1, allowed_identities=frozenset({"bob"})),
        ),
    )


def binding():
    return ActionBinding(
        operation="tool.invoke",
        agent_id="research-agent",
        target=ActionTarget("synthetic_ticket", "1", resource="fixture:ticket-1"),
        parameters={"operation_id": "fake-001", "payload": "do-nothing"},
        subject_id="research-only",
    )


def voter(db_path, request_id, stage, who, start_gate, vote_gate, result_queue):
    try:
        # A completely separate coordinator and SQLite connection per process.
        store = SQLiteApprovalStore(db_path, vote_gate=vote_gate)
        coordinator = ApprovalCoordinator(store, {chain().chain_id: chain()})
        start_gate.wait(timeout=12)
        entry = coordinator.submit_entry(
            request_id,
            stage_index=stage,
            approver_kind=ApproverKind.HUMAN,
            approver_identity=who,
            identity_assurance="synthetic",
            decision=EntryDecision.ALLOW,
        )
        result_queue.put({
            "pid": os.getpid(),
            "stage": stage,
            "entry_id": entry.chain_entry_id,
            "ok": True,
        })
    except Exception as exc:
        result_queue.put({
            "pid": os.getpid(),
            "stage": stage,
            "ok": False,
            "error": repr(exc),
        })


def make_request(db_path):
    coord = ApprovalCoordinator(
        SQLiteApprovalStore(db_path), {chain().chain_id: chain()}
    )
    _, request = coord.open_request(
        binding(),
        policy_rule_id="synthetic-two-person-approval",
        policy_version="v1",
        chain_id=chain().chain_id,
        ttl_seconds=600,
    )
    return request.approval_request_id


def validate(db_path, request_id):
    store = SQLiteApprovalStore(db_path)
    coord = ApprovalCoordinator(store, {chain().chain_id: chain()})
    resolution = store.get_resolution(request_id)
    entries = store.get_entries(request_id)
    verdict = coord.validate_for_execution(
        request_id,
        current_action_digest=binding().digest(),
        current_policy_version="v1",
        current_chain_version="1",
    )
    return {
        "entry_count": len(entries),
        "stages": sorted(e.stage_index for e in entries),
        "first_previous_digest": entries[0].previous_entry_digest if entries else "MISSING",
        "second_previous_matches_first": (
            entries[1].previous_entry_digest == entries[0].entry_digest
            if len(entries) == 2 else False
        ),
        "resolution": resolution.outcome.value if resolution else None,
        "allowed": verdict.allowed,
        "reason": verdict.reason_code,
    }


def run_parallel(ctx, db_path, request_id):
    result_queue = ctx.Queue()
    start_gate = ctx.Barrier(2)
    # Test scheduling: the unpatched coordinator has two readers who can
    # simultaneously observe an empty ledger. Patched coordinator holds
    # BEGIN IMMEDIATE through submission, preventing that simultaneous read.
    vote_gate = ctx.Barrier(2)
    workers = [
        ctx.Process(
            target=voter,
            args=(db_path, request_id, 0, "alice", start_gate, vote_gate, result_queue),
        ),
        ctx.Process(
            target=voter,
            args=(db_path, request_id, 1, "bob", start_gate, vote_gate, result_queue),
        ),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=18)
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=3)
            raise AssertionError("Approval subprocess exceeded 18 seconds")
        if worker.exitcode != 0:
            raise AssertionError(f"Approval subprocess exited with {worker.exitcode}")
    outcomes = [result_queue.get(timeout=4) for _ in workers]
    result_queue.close()
    if not all(x["ok"] for x in outcomes):
        raise AssertionError(f"Worker failure: {outcomes}")
    if len({x["pid"] for x in outcomes}) != 2:
        raise AssertionError("Did not observe two independent process IDs")
    if {x["stage"] for x in outcomes} != {0, 1}:
        raise AssertionError("Did not observe both independent required votes")
    return outcomes


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"original", "patched"}:
        raise SystemExit("Usage: run_cross_process.py {original|patched}")
    mode = sys.argv[1]
    expected = (
        ReasonCode.CHAIN_TAMPERED if mode == "original" else ReasonCode.OK
    )
    ctx = multiprocessing.get_context("spawn")
    # Repeat to ensure this is reproducible rather than one coincidental run.
    for iteration in range(1, 4):
        with tempfile.TemporaryDirectory(prefix="approval-sqlite-fixture-") as temp:
            db_path = str(Path(temp) / "synthetic.db")
            request_id = make_request(db_path)
            workers = run_parallel(ctx, db_path, request_id)
            result = validate(db_path, request_id)
            report = {
                "mode": mode,
                "iteration": iteration,
                "process_count": len(workers),
                **result,
            }
            print(json.dumps(report, sort_keys=True), flush=True)
            assert result["entry_count"] == 2, report
            assert result["stages"] == [0, 1], report
            assert result["resolution"] == Outcome.ALLOW.value, report
            assert result["reason"] == expected, report
            if mode == "patched":
                assert result["allowed"], report
                assert result["second_previous_matches_first"], report
            else:
                assert not result["allowed"], report
                assert not result["second_previous_matches_first"], report
    print(f"PASS: {mode} cross-process SQLite approval behavior verified in 3/3 trials")


if __name__ == "__main__":
    main()
