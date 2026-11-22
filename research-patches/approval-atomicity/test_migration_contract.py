"""Compatibility contract tests for optional atomic approval-store migration."""
import unittest
import warnings

from agentmesh.governance.approval_protocol import (
    ActionBinding,
    ActionTarget,
    ApprovalChain,
    ApprovalCoordinator,
    ApprovalProtocolError,
    ApprovalStage,
    AtomicApprovalStore,
    ApprovalStore,
    ApproverKind,
    EntryDecision,
    InMemoryApprovalStore,
)


class LegacyStore:
    """An unchanged third-party store implementing the original eight methods."""

    def __init__(self):
        self.underlying = InMemoryApprovalStore()

    def save_request(self, request):
        return self.underlying.save_request(request)

    def get_request(self, request_id):
        return self.underlying.get_request(request_id)

    def set_status(self, request_id, status):
        return self.underlying.set_status(request_id, status)

    def append_entry(self, entry):
        return self.underlying.append_entry(entry)

    def get_entries(self, request_id):
        return self.underlying.get_entries(request_id)

    def save_resolution(self, resolution):
        return self.underlying.save_resolution(resolution)

    def get_resolution(self, request_id):
        return self.underlying.get_resolution(request_id)

    def consume(self, request_id):
        return self.underlying.consume(request_id)


class StoreMigrationContractTests(unittest.TestCase):
    def setUp(self):
        self.chain = ApprovalChain(
            "legacy-chain", "1",
            (ApprovalStage(0, allowed_identities=frozenset({"human"})),),
        )
        self.binding = ActionBinding(
            operation="tool.invoke",
            agent_id="synthetic-agent",
            target=ActionTarget("noop", "1", resource="fixture:only"),
            parameters={"amount": 1},
        )

    def coordinator_with_open_request(self, store, strict=False):
        coord = ApprovalCoordinator(
            store,
            {self.chain.chain_id: self.chain},
            require_atomic_submission=strict,
        )
        _, request = coord.open_request(
            self.binding,
            policy_rule_id="synthetic",
            policy_version="v1",
            chain_id=self.chain.chain_id,
            ttl_seconds=600,
        )
        return coord, request.approval_request_id

    def vote(self, coord, request_id):
        coord.submit_entry(
            request_id,
            stage_index=0,
            approver_kind=ApproverKind.HUMAN,
            approver_identity="human",
            identity_assurance="synthetic",
            decision=EntryDecision.ALLOW,
        )

    def verdict(self, coord, request_id):
        return coord.validate_for_execution(
            request_id,
            current_action_digest=self.binding.digest(),
            current_policy_version="v1",
            current_chain_version="1",
        )

    def test_01_original_protocol_contract_remains_supported(self):
        legacy = LegacyStore()
        self.assertIsInstance(legacy, ApprovalStore)
        self.assertNotIsInstance(legacy, AtomicApprovalStore)
        coord, request_id = self.coordinator_with_open_request(legacy)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.vote(coord, request_id)
        self.assertTrue(any("non-atomic" in str(w.message).lower()
                            or "Legacy ApprovalStore" in str(w.message)
                            for w in caught))
        self.assertTrue(self.verdict(coord, request_id).allowed)

    def test_02_strict_mode_fails_closed_for_legacy_backend(self):
        legacy = LegacyStore()
        coord, request_id = self.coordinator_with_open_request(legacy, strict=True)
        with self.assertRaisesRegex(ApprovalProtocolError, "strict atomic"):
            self.vote(coord, request_id)
        self.assertEqual(legacy.get_entries(request_id), [])
        self.assertIsNone(legacy.get_resolution(request_id))

    def test_03_built_in_store_advertises_atomic_capability(self):
        store = InMemoryApprovalStore()
        self.assertIsInstance(store, ApprovalStore)
        self.assertIsInstance(store, AtomicApprovalStore)
        coord, request_id = self.coordinator_with_open_request(store, strict=True)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.vote(coord, request_id)
        self.assertFalse(caught)
        self.assertTrue(self.verdict(coord, request_id).allowed)

    def test_04_strict_flag_is_additive_no_constructor_break(self):
        store = InMemoryApprovalStore()
        coord = ApprovalCoordinator(store, {self.chain.chain_id: self.chain})
        self.assertFalse(coord.require_atomic_submission)
        self.assertTrue(callable(store.approval_transaction))


if __name__ == "__main__":
    unittest.main()
