"""Synthetic conformance probes against a pinned Microsoft AgentMesh source revision.

These characterize an approval protocol; they are NOT vulnerability claims.
No external resources, secrets, or network calls are used by the tests.
"""
import concurrent.futures
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
    ReasonCode,
)


class ApprovalEffectBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.chain = ApprovalChain(
            chain_id="research-synthetic",
            version="1",
            stages=(ApprovalStage(0, allowed_identities=frozenset({"researcher"})),),
        )
        self.coordinator = ApprovalCoordinator(
            InMemoryApprovalStore(), {self.chain.chain_id: self.chain}
        )
        self.binding = ActionBinding(
            operation="tool.invoke",
            agent_id="synthetic-agent",
            target=ActionTarget("synthetic_effect", "v1", resource="fake:task-1"),
            parameters={"title": "Review fake task"},
            subject_id="researcher",
        )
        self.effects = []
        _, request = self.coordinator.open_request(
            self.binding,
            policy_rule_id="synthetic-only",
            policy_version="v1",
            chain_id=self.chain.chain_id,
            ttl_seconds=600,
        )
        self.request_id = request.approval_request_id
        self.coordinator.submit_entry(
            self.request_id,
            stage_index=0,
            approver_kind=ApproverKind.HUMAN,
            approver_identity="researcher",
            identity_assurance="synthetic",
            decision=EntryDecision.ALLOW,
        )

    def validate(self, action=None):
        return self.coordinator.validate_for_execution(
            self.request_id,
            current_action_digest=(action or self.binding).digest(),
            current_policy_version="v1",
            current_chain_version=self.chain.version,
        )

    def test_changed_action_parameters_denied(self):
        changed = ActionBinding(
            operation="tool.invoke",
            agent_id="synthetic-agent",
            target=ActionTarget("synthetic_effect", "v1", resource="fake:task-1"),
            parameters={"title": "DIFFERENT fake task"},
            subject_id="researcher",
        )
        result = self.validate(changed)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason_code, ReasonCode.ACTION_DIGEST_MISMATCH)
        self.assertEqual(self.effects, [])

    def test_concurrent_validation_allows_one(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            decisions = list(pool.map(lambda _: self.validate(), range(30)))
        self.assertEqual(sum(int(x.allowed) for x in decisions), 1)
        self.effects.extend("fake_effect" for x in decisions if x.allowed)
        self.assertEqual(len(self.effects), 1)

    def test_crash_after_consume_before_effect_requires_reconciliation(self):
        first = self.validate()
        self.assertTrue(first.allowed)
        # Injected crash boundary: do not commit the synthetic effect.
        retry = self.validate()
        self.assertFalse(retry.allowed)
        self.assertEqual(retry.reason_code, ReasonCode.ALREADY_CONSUMED)
        self.assertEqual(self.effects, [])
        # Expected protocol behavior, not a claimed upstream vulnerability.


if __name__ == "__main__":
    unittest.main()
