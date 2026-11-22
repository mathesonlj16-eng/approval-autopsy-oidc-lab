"""Load Microsoft's pinned approval-protocol source without executing broad package initializers.

Upstream's consolidated package requires a currently unpublished PyPI dependency.
This test-only loader imports the unchanged source package from a GitHub Actions
checkout. It is deliberately *not* a full installation/integration test.
"""
from pathlib import Path
import sys
import types


def install():
    base = (Path(__file__).resolve().parent.parent / "upstream" /
            "agent-governance-python" / "agent-mesh" / "src" / "agentmesh")
    protocol = base / "governance" / "approval_protocol" / "__init__.py"
    if not protocol.is_file():
        raise FileNotFoundError(f"Expected pinned upstream source missing: {protocol}")
    if "agentmesh" in sys.modules or "agentmesh.governance" in sys.modules:
        raise RuntimeError("Must bootstrap before importing any agentmesh modules")
    for name, location in (
        ("agentmesh", base),
        ("agentmesh.governance", base / "governance"),
    ):
        module = types.ModuleType(name)
        module.__package__ = name
        module.__path__ = [str(location)]
        module.__file__ = str(location / "__init__.py")
        sys.modules[name] = module
    import agentmesh.governance.approval_protocol as loaded
    assert Path(loaded.__file__).resolve() == protocol.resolve()
    print(f"Loaded unchanged pinned protocol source: {loaded.__file__}", flush=True)
    return loaded
