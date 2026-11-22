"""High-level govern() integration with a real disposable SQLite effect.

Runs Microsoft's unmodified govern.py and the protocol with a candidate
atomic-submission patch. No external tool calls, keys, or real account writes.
"""
import sqlite3
import tempfile
import unittest
import warnings
from pathlib import Path

from agentmesh.governance.approval import ApprovalDecision, CallbackApproval
from agentmesh.governance.approval_protocol import (
    ApprovalChain,
    ApprovalCoordinator,
    ApprovalStage,
    InMemoryApprovalStore,
)
from agentmesh.governance.govern import GovernanceDenied, govern
if __package__:
    from .test_migration_contract import LegacyStore
else:
    from test_migration_contract import LegacyStore

POLICY = """
apiVersion: governance.toolkit/v1
name: synthetic-tools-policy
agents: ["*"]
default_action: deny
rules:
  - name: approve-synthetic-write
    condition: "action.type == 'write'"
    action: require_approval
    approvers: ["alice"]
    priority: 100
"""


class SyntheticSQLiteTool:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "CREATE TABLE fake_actions ("
                "id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def __call__(self, *, action, operation_id, payload):
        assert action == "write"
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "INSERT OR IGNORE INTO fake_actions(id, payload) VALUES (?, ?)",
                (operation_id, payload),
            )
        return "synthetic-write-completed"

    def rows(self):
        with sqlite3.connect(self.db_path) as db:
            return db.execute("SELECT id, payload FROM fake_actions ORDER BY id").fetchall()


class GovernWrapperAcceptance(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tool = SyntheticSQLiteTool(Path(temp.name) / "fake.db")

    def coordinator(self, store=None, strict=True, two_stages=False):
        stages = [
            ApprovalStage(0, allowed_identities=frozenset({"alice"})),
        ]
        if two_stages:
            stages.append(ApprovalStage(1, allowed_identities=frozenset({"bob"})))
        chain = ApprovalChain("tool-review", "1", tuple(stages))
        coord = ApprovalCoordinator(
            store or InMemoryApprovalStore(),
            {chain.chain_id: chain},
            require_atomic_submission=strict,
        )
        return coord, chain

    def wrapped(self, *, store=None, approver="alice", approved=True, strict=True,
                two_stages=False):
        coordinator, chain = self.coordinator(store, strict, two_stages)
        fn = self.tool
        return govern(
            fn,
            policy=POLICY,
            agent_id="research-only",
            approval_handler=CallbackApproval(
                lambda req: ApprovalDecision(
                    approved=approved, approver=approver, reason="synthetic"
                )
            ),
            approval_coordinator=coordinator,
            approval_chain_id=chain.chain_id,
            audit=True,
        )

    def invoke(self, g, operation_id="task-001", payload="harmless"):
        return g(action="write", operation_id=operation_id, payload=payload)

    def test_01_approved_action_causes_one_disposable_effect_and_audit_receipt(self):
        g = self.wrapped()
        self.assertEqual(self.invoke(g), "synthetic-write-completed")
        self.assertEqual(self.tool.rows(), [("task-001", "harmless")])
        entries = g.audit_log.get_entries_by_type("approval_decision")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].outcome, "approved")
        self.assertEqual(entries[0].approver_did, "alice")
        self.assertTrue(entries[0].arguments_hash.startswith("sha256:"))
        self.assertTrue(entries[0].data["approval_request_id"])

    def test_02_rejected_approver_never_reaches_tool(self):
        g = self.wrapped(approver="mallory")
        with self.assertRaises(GovernanceDenied):
            self.invoke(g)
        self.assertEqual(self.tool.rows(), [])

    def test_03_negative_vote_never_reaches_tool(self):
        g = self.wrapped(approved=False)
        with self.assertRaises(GovernanceDenied):
            self.invoke(g)
        self.assertEqual(self.tool.rows(), [])

    def test_04_strict_legacy_store_fails_closed_through_govern(self):
        g = self.wrapped(store=LegacyStore(), strict=True)
        with self.assertRaises(GovernanceDenied):
            self.invoke(g)
        self.assertEqual(self.tool.rows(), [])

    def test_05_legacy_store_default_mode_still_runs_but_warns(self):
        g = self.wrapped(store=LegacyStore(), strict=False)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.invoke(g)
        self.assertEqual(self.tool.rows(), [("task-001", "harmless")])
        self.assertTrue(any("Legacy ApprovalStore" in str(w.message) for w in caught))

    def test_06_single_synchronous_vote_cannot_complete_two_stage_chain(self):
        g = self.wrapped(two_stages=True)
        with self.assertRaises(GovernanceDenied):
            self.invoke(g)
        self.assertEqual(self.tool.rows(), [])
        self.assertEqual(
            g.audit_log.get_entries_by_type("approval_decision")[-1].outcome,
            "rejected",
        )

    def test_07_two_separately_approved_calls_have_distinct_audit_receipts(self):
        g = self.wrapped()
        self.invoke(g, "task-001")
        self.invoke(g, "task-002")
        self.assertEqual(self.tool.rows(), [
            ("task-001", "harmless"), ("task-002", "harmless")
        ])
        entries = g.audit_log.get_entries_by_type("approval_decision")
        self.assertEqual(len(entries), 2)
        self.assertNotEqual(
            entries[0].data["approval_request_id"],
            entries[1].data["approval_request_id"],
        )


if __name__ == "__main__":
    unittest.main()
