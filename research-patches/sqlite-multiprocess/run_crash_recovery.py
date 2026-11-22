"""Actual worker-process termination during SQLite-backed approval submission.

Compare old coordinator's committed partial entry with candidate transaction
semantics. The child exits deliberately after append_entry; no real external
actions or production data are involved.
"""
from __future__ import annotations

import multiprocessing
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research-support"))
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

EXIT_AFTER_APPEND = 87


def make_chain():
    return ApprovalChain(
        "single-stage-fixture", "1",
        (ApprovalStage(0, allowed_identities=frozenset({"alice"})),),
    )


def make_binding():
    return ActionBinding(
        operation="tool.invoke",
        agent_id="synthetic",
        target=ActionTarget("dry_run_tool", "1", resource="fixture:none"),
        parameters={"value": "fake"},
    )


class CrashOnAppendSQLiteStore(SQLiteApprovalStore):
    def append_entry(self, entry):
        super().append_entry(entry)
        # A real worker-process crash, NOT a Python exception or rollback.
        os._exit(EXIT_AFTER_APPEND)


def crash_worker(db_path, request_id):
    store = CrashOnAppendSQLiteStore(db_path)
    chain = make_chain()
    coordinator = ApprovalCoordinator(store, {chain.chain_id: chain})
    coordinator.submit_entry(
        request_id,
        stage_index=0,
        approver_kind=ApproverKind.HUMAN,
        approver_identity="alice",
        identity_assurance="fixture",
        decision=EntryDecision.ALLOW,
    )
    raise AssertionError("Crash hook did not execute")


def run(mode):
    with tempfile.TemporaryDirectory(prefix="approval-crash-fixture-") as temp:
        path = str(Path(temp) / "fixture.db")
        store = SQLiteApprovalStore(path)
        chain = make_chain()
        coordinator = ApprovalCoordinator(store, {chain.chain_id: chain})
        action = make_binding()
        _, request = coordinator.open_request(
            action, policy_rule_id="dummy", policy_version="v1",
            chain_id=chain.chain_id, ttl_seconds=600,
        )
        ctx = multiprocessing.get_context("spawn")
        worker = ctx.Process(target=crash_worker, args=(path, request.approval_request_id))
        worker.start()
        worker.join(timeout=15)
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=3)
            raise AssertionError("Crash test subprocess hung")
        assert worker.exitcode == EXIT_AFTER_APPEND, worker.exitcode

        # Reopen from a new SQLite connection after the worker was terminated.
        store = SQLiteApprovalStore(path)
        before_entries = store.get_entries(request.approval_request_id)
        assert store.get_resolution(request.approval_request_id) is None
        if mode == "patched":
            assert len(before_entries) == 0, len(before_entries)
        else:
            assert len(before_entries) == 1, len(before_entries)

        # Recover using a new, valid approval vote. Both modes can finish,
        # but only the patched path guarantees no partial committed record.
        recovered = ApprovalCoordinator(store, {chain.chain_id: chain})
        recovered.submit_entry(
            request.approval_request_id,
            stage_index=0,
            approver_kind=ApproverKind.HUMAN,
            approver_identity="alice",
            identity_assurance="fixture",
            decision=EntryDecision.ALLOW,
        )
        resolution = store.get_resolution(request.approval_request_id)
        assert resolution is not None and resolution.outcome == Outcome.ALLOW
        verdict = recovered.validate_for_execution(
            request.approval_request_id,
            current_action_digest=action.digest(),
            current_policy_version="v1",
            current_chain_version=chain.version,
        )
        assert verdict.allowed and verdict.reason_code == ReasonCode.OK
        print(
            f"PASS: {mode}, before_retry_entries={len(before_entries)}, "
            f"after_retry_entries={len(store.get_entries(request.approval_request_id))}, "
            f"validation={verdict.reason_code}",
            flush=True,
        )


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"original", "patched"}:
        raise SystemExit("Usage: run_crash_recovery.py {original|patched}")
    run(sys.argv[1])
