"""Durable expiry regression for the optional transactional approval store.

When an expired vote is rejected, its terminal EXPIRED resolution must remain
durable even if the vote submission itself raises ApprovalProtocolError.
"""
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
    ApprovalProtocolError,
    ApprovalStage,
    ApprovalStatus,
    ApproverKind,
    EntryDecision,
    Outcome,
)
from sqlite_approval_store import SQLiteApprovalStore


def main():
    with tempfile.TemporaryDirectory(prefix="expiry-atomicity-") as temp:
        db = str(Path(temp) / "approvals.db")
        store = SQLiteApprovalStore(db)
        chain = ApprovalChain(
            "expiry-chain", "1",
            (ApprovalStage(0, allowed_identities=frozenset({"alice"})),),
        )
        coordinator = ApprovalCoordinator(
            store,
            {chain.chain_id: chain},
            require_atomic_submission=True,
        )
        binding = ActionBinding(
            operation="tool.invoke",
            agent_id="fixture-agent",
            target=ActionTarget("fake_action", "1", resource="fixture:none"),
            parameters={"value": 1},
        )
        _, request = coordinator.open_request(
            binding,
            policy_rule_id="fixture",
            policy_version="v1",
            chain_id=chain.chain_id,
            ttl_seconds=-10,
        )
        try:
            coordinator.submit_entry(
                request.approval_request_id,
                stage_index=0,
                approver_kind=ApproverKind.HUMAN,
                approver_identity="alice",
                identity_assurance="synthetic",
                decision=EntryDecision.ALLOW,
            )
        except ApprovalProtocolError as exc:
            assert "expired" in str(exc), repr(exc)
        else:
            raise AssertionError("Expired approval was incorrectly accepted")

        # Reopen independently to require a COMMITTED terminal state.
        fresh = SQLiteApprovalStore(db)
        current = fresh.get_request(request.approval_request_id)
        resolution = fresh.get_resolution(request.approval_request_id)
        entries = fresh.get_entries(request.approval_request_id)
        assert current.status == ApprovalStatus.EXPIRED, current.status
        assert resolution is not None and resolution.outcome == Outcome.EXPIRED
        assert len(entries) == 0, len(entries)
        print("PASS: expired approval remains terminal and durable after transaction exit")


if __name__ == "__main__":
    main()
