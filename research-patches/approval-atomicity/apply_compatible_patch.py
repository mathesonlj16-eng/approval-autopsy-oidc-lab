"""Apply a compatibility-aware atomic-submission candidate to an ephemeral checkout.

The original ApprovalStore protocol remains unchanged: old custom backends stay
source-compatible, but their non-atomic path emits a warning. Opt-in strict mode
fails closed when a backend has not provided cross-worker transactions.

Not a submitted or production-ready Microsoft patch.
"""
from __future__ import annotations
from pathlib import Path

ROOT = (Path(__file__).resolve().parents[2] / "upstream" /
        "agent-governance-python" / "agent-mesh" / "src" / "agentmesh" /
        "governance" / "approval_protocol")


def replace_once(code, needle, replacement, name):
    if code.count(needle) != 1:
        raise RuntimeError(f"{name}: expected exactly one anchor, found {code.count(needle)}")
    return code.replace(needle, replacement, 1)


def patch_store():
    path = ROOT / "store.py"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "import threading\nfrom typing import Optional, Protocol, runtime_checkable",
        "import threading\nfrom contextlib import contextmanager\nfrom typing import ContextManager, Optional, Protocol, runtime_checkable",
        "imports",
    )
    source = replace_once(
        source,
        "\n\nclass InMemoryApprovalStore:\n",
        '''\n\n@runtime_checkable
class AtomicApprovalStore(ApprovalStore, Protocol):
    """Optional stronger store interface. ApprovalStore stays backwards compatible."""

    def approval_transaction(self, approval_request_id: str) -> ContextManager[None]:
        """Serialize a complete approval submission across all worker processes."""
        ...


class InMemoryApprovalStore:
''',
        "optional atomic store protocol",
    )
    source = replace_once(
        source,
        "    def save_request(self, request: ApprovalRequest) -> None:\n        with self._lock:",
        '''    @contextmanager
    def approval_transaction(self, approval_request_id: str):
        """Serialize votes on a shared in-memory store (single process only)."""
        with self._lock:
            yield

    def save_request(self, request: ApprovalRequest) -> None:
        with self._lock:''',
        "in-memory transaction",
    )
    path.write_text(source, encoding="utf-8")


def patch_coordinator():
    path = ROOT / "coordinator.py"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "from dataclasses import dataclass, field\n",
        "from dataclasses import dataclass, field\nfrom functools import wraps\nimport warnings\n",
        "coordinator imports",
    )
    source = replace_once(
        source,
        "@dataclass\nclass ApprovalCoordinator:",
        '''def _atomic_approval_submission(func):
    """Use atomic stores; warn for legacy stores, or reject in opt-in strict mode."""
    @wraps(func)
    def guarded(self, approval_request_id, *args, **kwargs):
        transaction = getattr(self.store, "approval_transaction", None)
        if callable(transaction):
            with transaction(approval_request_id):
                return func(self, approval_request_id, *args, **kwargs)
        if self.require_atomic_submission:
            raise ApprovalProtocolError(
                "approval store has no approval_transaction; strict atomic "
                "submission requires a transactional backend"
            )
        warnings.warn(
            "Legacy ApprovalStore has no approval_transaction: concurrent "
            "submissions may invalidate the hash chain; migrate to "
            "AtomicApprovalStore or enable require_atomic_submission",
            RuntimeWarning,
            stacklevel=2,
        )
        return func(self, approval_request_id, *args, **kwargs)
    return guarded


@dataclass
class ApprovalCoordinator:''',
        "guarded submission decorator",
    )
    source = replace_once(
        source,
        "    clock: Callable[[], datetime] = field(default=utcnow)\n",
        "    clock: Callable[[], datetime] = field(default=utcnow)\n    require_atomic_submission: bool = False\n",
        "strict option",
    )
    source = replace_once(
        source,
        "    def submit_entry(\n",
        "    @_atomic_approval_submission\n    def submit_entry(\n",
        "entry guard",
    )
    path.write_text(source, encoding="utf-8")


def patch_exports():
    path = ROOT / "__init__.py"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "from .store import ApprovalStore, InMemoryApprovalStore",
        "from .store import ApprovalStore, AtomicApprovalStore, InMemoryApprovalStore",
        "store export",
    )
    source = replace_once(
        source,
        '    "InMemoryApprovalStore",',
        '    "InMemoryApprovalStore",\n    "AtomicApprovalStore",',
        "all export",
    )
    path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    if not (ROOT / "coordinator.py").is_file():
        raise SystemExit(f"Missing pinned checkout at {ROOT}")
    patch_store()
    patch_coordinator()
    patch_exports()
    print("Applied compatibility-aware optional AtomicApprovalStore prototype")
