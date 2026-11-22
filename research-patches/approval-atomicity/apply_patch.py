"""Prototype-only fix applied to an ephemeral checkout of Microsoft source.

This intentionally changes only approval_protocol/store.py and coordinator.py.
It illustrates an API-contract choice, NOT a ready upstream PR: persistent
ApprovalStore implementations must provide cross-process atomic transactions.
"""
from __future__ import annotations

from pathlib import Path

ROOT = (Path(__file__).resolve().parents[2] / "upstream" /
        "agent-governance-python" / "agent-mesh" / "src" / "agentmesh" /
        "governance" / "approval_protocol")


def replace_once(source: str, needle: str, replacement: str, label: str) -> str:
    count = source.count(needle)
    if count != 1:
        raise ValueError(f"{label}: expected one anchor; found {count}")
    return source.replace(needle, replacement, 1)


def patch_store() -> None:
    path = ROOT / "store.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text, "import threading\nfrom typing import Optional, Protocol, runtime_checkable",
        "import threading\nfrom contextlib import contextmanager\nfrom typing import ContextManager, Optional, Protocol, runtime_checkable",
        "store imports",
    )
    text = replace_once(
        text,
        "class ApprovalStore(Protocol):\n    \"\"\"Persistence contract for the approval coordinator.\"\"\"\n",
        """class ApprovalStore(Protocol):
    \"\"\"Persistence contract for the approval coordinator.

    For correctness across coordinators/workers, an implementation MUST
    serialize each entire submission and resolution per request. Production
    backends should use a database transaction with row or advisory locking.
    \"\"\"

    def approval_transaction(self, approval_request_id: str) -> ContextManager[None]:
        \"\"\"Hold the approval request's transaction through entry + resolution.\"\"\"
        ...
""",
        "store contract",
    )
    text = replace_once(
        text,
        "    def save_request(self, request: ApprovalRequest) -> None:\n        with self._lock:",
        """    @contextmanager
    def approval_transaction(self, approval_request_id: str):
        \"\"\"Serialize whole submissions across coordinators sharing this store.

        This is process-local. Persistent backends must provide cross-process
        transactional semantics rather than a Python threading lock.
        \"\"\"
        with self._lock:
            yield

    def save_request(self, request: ApprovalRequest) -> None:
        with self._lock:""",
        "in-memory transaction",
    )
    path.write_text(text, encoding="utf-8")


def patch_coordinator() -> None:
    path = ROOT / "coordinator.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from dataclasses import dataclass, field\n",
        "from dataclasses import dataclass, field\nfrom functools import wraps\n",
        "coordinator import",
    )
    text = replace_once(
        text,
        "@dataclass\nclass ApprovalCoordinator:",
        """def _atomic_approval_submission(func):
    \"\"\"Prevent independently valid votes from racing at a store boundary.\"\"\"
    @wraps(func)
    def serialized(self, approval_request_id, *args, **kwargs):
        transaction = getattr(self.store, "approval_transaction", None)
        if not callable(transaction):
            raise ApprovalProtocolError(
                "approval store lacks required atomic submission transaction"
            )
        with transaction(approval_request_id):
            return func(self, approval_request_id, *args, **kwargs)
    return serialized


@dataclass
class ApprovalCoordinator:""",
        "coordinator decorator",
    )
    text = replace_once(
        text,
        "    def submit_entry(\n",
        "    @_atomic_approval_submission\n    def submit_entry(\n",
        "submit_entry decorator",
    )
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if not (ROOT / "coordinator.py").is_file():
        raise SystemExit(f"Missing pinned upstream checkout: {ROOT}")
    patch_store()
    patch_coordinator()
    print("Applied prototype atomic approval-submission patch to pinned source")
