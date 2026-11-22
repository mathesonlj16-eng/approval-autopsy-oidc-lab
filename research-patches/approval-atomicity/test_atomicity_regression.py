"""Regression against a controlled two-stage parallel-vote interleaving.

On original pinned source, two test cases should FAIL with chain_tampered.
After the candidate transaction patch, all three tests should PASS.
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
)


class SnapshotGateStore(InMemoryApprovalStore):
    """Force both readers to race on original code; patched code serializes."""

    def __init__(self):
        super().__init__()
        self.barrier = threading.Barrier(2)
        self.local = threading.local()

    def get_entries(self, approval_request_id):
        snapshot = super().get_entries(approval_request_id)
        if (
            threading.current_thread().name.startswith("atomicity-voter")
            and not getattr(self.local, "first_read", False)
        ):
            self.local.first_read = True
            try:
                self.barrier.wait(timeout=0.7)
            except threading.BrokenBarrierError:
                # A working store-scoped transaction prevents concurrent
                # readers from reaching this gate; expiry is expected then.
                pass
        return snapshot


class ApprovalSubmissionAtomicityRegression(unittest.TestCase):
    def setUp(self):
        self.binding = ActionBinding(
            operation="tool.invoke",
            agent_id="research-fixture-agent",
            target=ActionTarget("synthetic_effect", "1", resource="fake:doc"),
            parameters={"name": "synthetic"},
        )
        self.chain = ApprovalChain(
            "two-stage-approvals", "1",
            (
                ApprovalStage(0, allowed_identities=frozenset({"alice"})),
                ApprovalStage(1, allowed_identities=frozenset({"bob"})),
            ),
        )

    def setup_case(self, gated):
        store = SnapshotGateStore() if gated else InMemoryApprovalStore()
        coord = ApprovalCoordinator(store, {self.chain.chain_id: self.chain})
        _, request = coord.open_request(
            self.binding,
            policy_rule_id="fake-risky-action",
            policy_version="v1",
            chain_id=self.chain.chain_id,
            ttl_seconds=600,
        )
        return store, coord, request.approval_request_id

    def vote(self, coord, request_id, stage, identity):
        return coord.submit_entry(
            request_id,
            stage_index=stage,
            approver_kind=ApproverKind.HUMAN,
            approver_identity=identity,
            identity_assurance="fixture",
            decision=EntryDecision.ALLOW,
        )

    def finish(self, store, coord, request_id):
        entries = store.get_entries(request_id)
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            {e.stage_index for e in entries}, {0, 1},
        )
        self.assertTrue(all(e.verify_digest() for e in entries))
        self.assertIsNone(entries[0].previous_entry_digest)
        self.assertEqual(
            entries[1].previous_entry_digest, entries[0].entry_digest,
            "each valid approval must extend the prior entry's hash chain",
        )
        resolution = store.get_resolution(request_id)
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.outcome, Outcome.ALLOW)
        verdict = coord.validate_for_execution(
            request_id,
            current_action_digest=self.binding.digest(),
            current_policy_version="v1",
            current_chain_version="1",
        )
        self.assertTrue(verdict.allowed, f"execution denied: {verdict.reason_code}")

    def test_01_sequential_control(self):
        store, coord, req = self.setup_case(gated=False)
        self.vote(coord, req, 0, "alice")
        self.vote(coord, req, 1, "bob")
        self.finish(store, coord, req)

    def test_02_parallel_votes_one_coordinator(self):
        store, coord, req = self.setup_case(gated=True)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="atomicity-voter"
        ) as pool:
            a = pool.submit(self.vote, coord, req, 0, "alice")
            b = pool.submit(self.vote, coord, req, 1, "bob")
            a.result(timeout=10)
            b.result(timeout=10)
        self.finish(store, coord, req)

    def test_03_parallel_votes_two_coordinators_one_store(self):
        store, coord_a, req = self.setup_case(gated=True)
        coord_b = ApprovalCoordinator(store, {self.chain.chain_id: self.chain})
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="atomicity-voter"
        ) as pool:
            a = pool.submit(self.vote, coord_a, req, 0, "alice")
            b = pool.submit(self.vote, coord_b, req, 1, "bob")
            a.result(timeout=10)
            b.result(timeout=10)
        self.finish(store, coord_a, req)


if __name__ == "__main__":
    unittest.main()
