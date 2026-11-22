"""Disposable SQLite effect-adapter integration exercising Microsoft's pinned approval protocol.

All effects are synthetic ticket records. Approval is produced using the actual
ApprovalCoordinator; adapter-level effect idempotency is ours, not Microsoft's.
No external services, production accounts, or secrets are used.
"""
import concurrent.futures
import sqlite3
import tempfile
import unittest
from pathlib import Path

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


class InjectedFailure(Exception):
    """Simulate a process failing at an exact effect boundary."""


class Conflict(Exception):
    """Same operation key must not refer to different approved content."""


class TicketEffects:
    """Our experimental adapter: SQLite transaction and idempotency ledger."""

    def __init__(self, file_path):
        self.file_path = str(file_path)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS tickets ("
                "operation_id TEXT PRIMARY KEY, digest TEXT NOT NULL, "
                "payload TEXT NOT NULL)"
            )

    def connect(self):
        return sqlite3.connect(self.file_path, timeout=10)

    def count(self):
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM tickets").fetchone()[0]

    def get(self, operation_id):
        with self.connect() as db:
            return db.execute(
                "SELECT digest, payload FROM tickets WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()

    def apply(self, binding, fail_at=None):
        op_id = binding.parameters["operation_id"]
        payload = binding.parameters["payload"]
        digest = binding.digest()
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT digest, payload FROM tickets WHERE operation_id = ?",
                (op_id,),
            ).fetchone()
            if existing:
                if existing != (digest, payload):
                    raise Conflict("operation key reused for a different approved action")
                db.commit()
                return "already_applied"
            db.execute(
                "INSERT INTO tickets(operation_id, digest, payload) VALUES (?, ?, ?)",
                (op_id, digest, payload),
            )
            if fail_at == "before_commit":
                raise InjectedFailure("crash before transaction commit")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        if fail_at == "after_commit":
            raise InjectedFailure("effect committed but response lost")
        return "applied"


class EffectIntegrityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "fake-tickets.sqlite"
        self.adapter = TicketEffects(self.database)
        self.chain = ApprovalChain(
            chain_id="synthetic-approval",
            version="1",
            stages=(ApprovalStage(0, allowed_identities=frozenset({"human-reviewer"})),),
        )
        self.coordinator = ApprovalCoordinator(
            InMemoryApprovalStore(), {self.chain.chain_id: self.chain}
        )

    def action(self, op_id="job-001", payload="create simulated ticket"):
        return ActionBinding(
            operation="tool.invoke",
            agent_id="fixture-agent",
            target=ActionTarget("ticket_create", "1", resource="fixture:tickets"),
            parameters={"operation_id": op_id, "payload": payload},
            subject_id="test-user",
        )

    def authorize(self, binding):
        _, request = self.coordinator.open_request(
            binding,
            policy_rule_id="synthetic-ticket-write",
            policy_version="v1",
            chain_id=self.chain.chain_id,
            ttl_seconds=600,
        )
        self.coordinator.submit_entry(
            request.approval_request_id,
            stage_index=0,
            approver_kind=ApproverKind.HUMAN,
            approver_identity="human-reviewer",
            identity_assurance="synthetic-test",
            decision=EntryDecision.ALLOW,
        )
        return request.approval_request_id

    def run_effect(self, binding, approval_id, fail_at=None):
        verdict = self.coordinator.validate_for_execution(
            approval_id,
            current_action_digest=binding.digest(),
            current_policy_version="v1",
            current_chain_version=self.chain.version,
        )
        if not verdict.allowed:
            return verdict.reason_code
        if fail_at == "after_consume":
            raise InjectedFailure("approval consumed, before effect dispatch")
        return self.adapter.apply(binding, fail_at=fail_at)

    def test_01_one_approved_effect(self):
        binding = self.action()
        self.assertEqual(self.run_effect(binding, self.authorize(binding)), "applied")
        self.assertEqual(self.adapter.count(), 1)

    def test_02_crash_after_consume_before_effect_requires_new_approval(self):
        binding = self.action()
        approval = self.authorize(binding)
        with self.assertRaises(InjectedFailure):
            self.run_effect(binding, approval, fail_at="after_consume")
        self.assertEqual(self.adapter.count(), 0)
        self.assertEqual(
            self.run_effect(binding, approval), ReasonCode.ALREADY_CONSUMED
        )
        # A new explicit approval authorizes recovery; the old approval stays spent.
        self.assertEqual(self.run_effect(binding, self.authorize(binding)), "applied")
        self.assertEqual(self.adapter.count(), 1)

    def test_03_response_lost_after_commit_reconciles(self):
        binding = self.action()
        approval = self.authorize(binding)
        with self.assertRaises(InjectedFailure):
            self.run_effect(binding, approval, fail_at="after_commit")
        self.assertEqual(self.adapter.count(), 1)
        self.assertEqual(
            self.run_effect(binding, approval), ReasonCode.ALREADY_CONSUMED
        )
        self.assertIsNotNone(self.adapter.get("job-001"))
        self.assertEqual(
            self.run_effect(binding, self.authorize(binding)), "already_applied"
        )
        self.assertEqual(self.adapter.count(), 1)

    def test_04_concurrent_distinct_approvals_one_effect(self):
        binding = self.action()
        approvals = [self.authorize(binding) for _ in range(12)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(
                lambda approval: self.run_effect(binding, approval), approvals
            ))
        self.assertEqual(outcomes.count("applied"), 1)
        self.assertEqual(outcomes.count("already_applied"), 11)
        self.assertEqual(self.adapter.count(), 1)

    def test_05_same_operation_id_changed_payload_rejected(self):
        original = self.action()
        self.assertEqual(
            self.run_effect(original, self.authorize(original)), "applied"
        )
        changed = self.action(payload="create a different simulated ticket")
        with self.assertRaises(Conflict):
            self.run_effect(changed, self.authorize(changed))
        self.assertEqual(self.adapter.count(), 1)
        self.assertEqual(self.adapter.get("job-001")[1], "create simulated ticket")

    def test_06_new_operation_id_is_new_legitimate_effect(self):
        first, second = self.action(), self.action(op_id="job-002")
        self.assertEqual(self.run_effect(first, self.authorize(first)), "applied")
        self.assertEqual(self.run_effect(second, self.authorize(second)), "applied")
        self.assertEqual(self.adapter.count(), 2)

    def test_07_adapter_restarted_still_deduplicates(self):
        binding = self.action()
        self.assertEqual(
            self.run_effect(binding, self.authorize(binding)), "applied"
        )
        self.adapter = TicketEffects(self.database)
        self.assertEqual(
            self.run_effect(binding, self.authorize(binding)), "already_applied"
        )
        self.assertEqual(self.adapter.count(), 1)

    def test_08_before_commit_failure_rolls_back(self):
        binding = self.action()
        with self.assertRaises(InjectedFailure):
            self.run_effect(binding, self.authorize(binding), fail_at="before_commit")
        self.assertEqual(self.adapter.count(), 0)
        self.assertEqual(
            self.run_effect(binding, self.authorize(binding)), "applied"
        )
        self.assertEqual(self.adapter.count(), 1)

    def test_09_action_substitution_blocked_before_effect(self):
        originally_approved = self.action()
        approval_id = self.authorize(originally_approved)
        changed = self.action(payload="unapproved action content")
        self.assertEqual(
            self.run_effect(changed, approval_id), ReasonCode.ACTION_DIGEST_MISMATCH
        )
        self.assertEqual(self.adapter.count(), 0)


if __name__ == "__main__":
    unittest.main()
