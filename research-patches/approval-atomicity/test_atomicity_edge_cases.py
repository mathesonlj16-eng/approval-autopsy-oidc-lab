"""Atomic approval submission edge-case tests for the patched installed package.

These tests distinguish guarantees already provided by the coordinator from
the *separate* same-stage conflict semantics discussed in ADR-0030.
"""
from __future__ import annotations

import concurrent.futures
import unittest
from datetime import datetime, timedelta, timezone

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
    InMemoryApprovalStore,
    Outcome,
    ReasonCode,
)


class ApprovalAtomicityEdgeCases(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryApprovalStore()
        self.chain = ApprovalChain(
            "two-stage-edge", "1",
            (
                ApprovalStage(0, allowed_identities=frozenset({"alice", "bob"})),
                ApprovalStage(1, allowed_identities=frozenset({"carol"})),
            ),
        )
        self.action = ActionBinding(
            operation="tool.invoke",
            agent_id="synthetic-agent",
            target=ActionTarget("fixture", "1", resource="fixture:only"),
            parameters={"value": "synthetic"},
        )
        self.coord = ApprovalCoordinator(
            self.store, {self.chain.chain_id: self.chain},
            require_atomic_submission=True,
        )
        _, self.request = self.coord.open_request(
            self.action,
            policy_rule_id="test-rule",
            policy_version="v1",
            chain_id=self.chain.chain_id,
            ttl_seconds=600,
        )
        self.id = self.request.approval_request_id

    def vote(self, stage=0, identity="alice", decision=EntryDecision.ALLOW, entry_id=None):
        return self.coord.submit_entry(
            self.id,
            stage_index=stage,
            approver_kind=ApproverKind.HUMAN,
            approver_identity=identity,
            identity_assurance="synthetic",
            decision=decision,
            chain_entry_id=entry_id,
        )

    def verdict(self):
        return self.coord.validate_for_execution(
            self.id,
            current_action_digest=self.action.digest(),
            current_policy_version="v1",
            current_chain_version="1",
            consume=False,
        )

    def test_01_concurrent_duplicate_entry_id_appended_once(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(
                lambda _: self.vote(entry_id="ace_stable"), range(16)
            ))
        self.assertEqual({entry.chain_entry_id for entry in results}, {"ace_stable"})
        self.assertEqual(len(self.store.get_entries(self.id)), 1)
        self.assertIsNone(self.store.get_resolution(self.id))

    def test_02_duplicate_entry_id_is_idempotent_even_after_resolution(self):
        original = self.vote(entry_id="ace_first")
        self.vote(stage=1, identity="carol", entry_id="ace_second")
        replay = self.vote(entry_id="ace_first")
        self.assertIs(original, replay)
        self.assertEqual(len(self.store.get_entries(self.id)), 2)
        self.assertEqual(self.store.get_resolution(self.id).outcome, Outcome.ALLOW)
        self.assertEqual(self.verdict().reason_code, ReasonCode.OK)

    def test_03_new_vote_after_terminal_resolution_is_rejected(self):
        self.vote(entry_id="ace_first")
        self.vote(stage=1, identity="carol", entry_id="ace_second")
        with self.assertRaisesRegex(ApprovalProtocolError, "not pending"):
            self.vote(identity="bob", entry_id="ace_third")
        self.assertEqual(len(self.store.get_entries(self.id)), 2)
        self.assertEqual(self.verdict().reason_code, ReasonCode.OK)

    def test_04_expired_request_rejects_vote_without_appending(self):
        self.request.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        with self.assertRaisesRegex(ApprovalProtocolError, "expired"):
            self.vote(entry_id="ace_expired")
        self.assertEqual(len(self.store.get_entries(self.id)), 0)
        self.assertEqual(self.store.get_resolution(self.id).outcome, Outcome.EXPIRED)

    def test_05_cancelled_request_rejects_vote_without_appending(self):
        self.store.set_status(self.id, ApprovalStatus.CANCELLED)
        with self.assertRaisesRegex(ApprovalProtocolError, "not pending"):
            self.vote(entry_id="ace_cancelled")
        self.assertEqual(len(self.store.get_entries(self.id)), 0)
        self.assertIsNone(self.store.get_resolution(self.id))

    def test_06_conflicting_stage_vote_currently_resolves_deny(self):
        # ADR-0030 says conflicting submissions on one stage should be
        # rejected. The current implementation instead records both votes,
        # then DENY wins. Characterize this separately from the atomicity fix.
        self.vote(identity="alice", decision=EntryDecision.ALLOW, entry_id="ace_allow")
        self.vote(identity="bob", decision=EntryDecision.DENY, entry_id="ace_deny")
        entries = self.store.get_entries(self.id)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1].previous_entry_digest, entries[0].entry_digest)
        self.assertEqual(self.store.get_resolution(self.id).outcome, Outcome.DENY)
        self.assertFalse(self.verdict().allowed)
        self.assertEqual(self.verdict().reason_code, ReasonCode.NOT_TERMINAL_ALLOW)

    def test_07_advisory_entry_cannot_complete_stage(self):
        self.coord.submit_entry(
            self.id,
            stage_index=0,
            approver_kind=ApproverKind.LLM_ADVISORY,
            approver_identity="synthetic-advisor",
            identity_assurance="none",
            decision=EntryDecision.ALLOW,
            chain_entry_id="ace_advisory",
        )
        self.assertIsNone(self.store.get_resolution(self.id))
        self.vote(stage=0, identity="alice", entry_id="ace_human")
        self.vote(stage=1, identity="carol", entry_id="ace_carol")
        self.assertEqual(self.verdict().reason_code, ReasonCode.OK)
        chain = self.store.get_entries(self.id)
        self.assertEqual(len(chain), 3)
        self.assertEqual(chain[1].previous_entry_digest, chain[0].entry_digest)
        self.assertEqual(chain[2].previous_entry_digest, chain[1].entry_digest)


if __name__ == "__main__":
    unittest.main()
