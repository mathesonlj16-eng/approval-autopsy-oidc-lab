"""Controlled parallel voting experiment against Microsoft's unchanged approval protocol.

The barrier replaces scheduling luck with a reproducible concurrent interleaving.
This test only characterizes the InMemoryApprovalStore reference implementation;
it is not a general claim about every storage backend or a security advisory.
"""
import concurrent.futures
import threading
import unittest

from agentmesh.governance.approval_protocol import (
    ActionBinding,
    ActionTarget,
    ApprovalChain,
    ApprovalCoordinator,
    ApprovalStage,
    ApproverKind,
    EntryDecision,
    InMemoryApprovalStore,
    Outcome,
    ReasonCode,
)


class ConcurrentSnapshotStore(InMemoryApprovalStore):
    """Synchronize the first prior-entry read of each voting thread."""

    def __init__(self):
        super().__init__()
        self.barrier = threading.Barrier(2)
        self.local = threading.local()

    def get_entries(self, approval_request_id):
        snapshot = super().get_entries(approval_request_id)
        if (
            threading.current_thread().name.startswith("approval-voter")
            and not getattr(self.local, "read_once", False)
        ):
            self.local.read_once = True
            self.barrier.wait(timeout=8)
        return snapshot


class ConcurrentApprovalExperiment(unittest.TestCase):
    def setUp(self):
        self.binding = ActionBinding(
            operation="tool.invoke",
            agent_id="fixture-agent",
            target=ActionTarget("synthetic_write", "1", resource="fixture:resource"),
            parameters={"value": "harmless"},
        )
        self.chain = ApprovalChain(
            chain_id="two-independent-human-stages",
            version="1",
            stages=(
                ApprovalStage(0, allowed_identities=frozenset({"alice"})),
                ApprovalStage(1, allowed_identities=frozenset({"bob"})),
            ),
        )

    def new_request(self, store):
        coordinator = ApprovalCoordinator(
            store, {self.chain.chain_id: self.chain}
        )
        _, request = coordinator.open_request(
            self.binding,
            policy_rule_id="synthetic-only",
            policy_version="v1",
            chain_id=self.chain.chain_id,
            ttl_seconds=600,
        )
        return coordinator, request.approval_request_id

    def vote(self, coordinator, request_id, stage, identity):
        return coordinator.submit_entry(
            request_id,
            stage_index=stage,
            approver_kind=ApproverKind.HUMAN,
            approver_identity=identity,
            identity_assurance="synthetic",
            decision=EntryDecision.ALLOW,
        )

    def validate(self, coordinator, request_id):
        return coordinator.validate_for_execution(
            request_id,
            current_action_digest=self.binding.digest(),
            current_policy_version="v1",
            current_chain_version=self.chain.version,
        )

    def test_sequential_independent_stages_allow(self):
        store = InMemoryApprovalStore()
        coord, req = self.new_request(store)
        self.vote(coord, req, 0, "alice")
        self.vote(coord, req, 1, "bob")
        resolution = store.get_resolution(req)
        self.assertEqual(resolution.outcome, Outcome.ALLOW)
        self.assertTrue(self.validate(coord, req).allowed)

    def test_controlled_parallel_required_stages_characterization(self):
        store = ConcurrentSnapshotStore()
        coord, req = self.new_request(store)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="approval-voter"
        ) as pool:
            first = pool.submit(self.vote, coord, req, 0, "alice")
            second = pool.submit(self.vote, coord, req, 1, "bob")
            first.result(timeout=12)
            second.result(timeout=12)

        entries = store.get_entries(req)
        self.assertEqual(len(entries), 2)
        self.assertEqual({entry.stage_index for entry in entries}, {0, 1})
        resolution = store.get_resolution(req)
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.outcome, Outcome.ALLOW)

        # Characterize rather than presume a bug: two entries captured the
        # same empty predecessor snapshot, so the recorded hash chain breaks.
        self.assertIsNone(entries[0].previous_entry_digest)
        self.assertIsNone(entries[1].previous_entry_digest)
        verdict = self.validate(coord, req)
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.reason_code, ReasonCode.CHAIN_TAMPERED)


if __name__ == "__main__":
    unittest.main()
