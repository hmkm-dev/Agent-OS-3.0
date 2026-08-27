"""Real unit tests against AgentWorkspace path scoping."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
os.environ["WORKSPACE_ROOT"] = tempfile.mkdtemp()

from workspace import AgentWorkspace, WorkspaceError  # noqa: E402


def test_path_for_stays_inside_workspace():
    ws = AgentWorkspace("agent-test-1")
    ws.initialize()
    p = ws.path_for("coding", "file.txt")
    assert p.startswith(ws.root)


def test_path_for_rejects_escape():
    ws = AgentWorkspace("agent-test-2")
    ws.initialize()
    try:
        ws.path_for("..", "..", "etc", "passwd")
        assert False, "expected WorkspaceError"
    except WorkspaceError:
        pass


def teardown_module(module):
    shutil.rmtree(os.environ["WORKSPACE_ROOT"], ignore_errors=True)
