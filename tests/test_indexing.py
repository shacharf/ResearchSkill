import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest
from rs import indexing


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("RS_DISABLE_WORKER", "1")
    indexing.configure(tmp_path)
    return tmp_path


def test_queue_coalesces_persists_and_rejects_outside_paths(project):
    indexing.enqueue(project, ["TODO.md", "threads/001.md"])
    indexing.enqueue(project, ["TODO.md"])
    state = indexing.state(project)
    assert state["lexical_pending"] == ["TODO.md", "threads/001.md"]
    assert state["semantic_pending"]
    assert json.loads((project / ".rs/index-state.json").read_text()) == state
    with pytest.raises(ValueError):
        indexing.enqueue(project, ["../outside.md"])


def test_enqueue_does_not_call_gno(project, monkeypatch):
    monkeypatch.setattr(indexing, "_run", lambda *args: pytest.fail("blocking sync"))
    before = time.perf_counter()
    indexing.enqueue(project, ["TODO.md"])
    assert time.perf_counter() - before < 0.5


def test_generation_preserves_edit_during_sync(project, monkeypatch):
    indexing.enqueue(project, ["TODO.md"])
    monkeypatch.setattr(indexing, "_run", lambda root, args: indexing.enqueue(root, ["TODO.md"]))
    indexing.flush(project, semantic=False)
    assert indexing.state(project)["lexical_pending"] == ["TODO.md"]


def test_failed_lexical_keeps_retry_task(project, monkeypatch):
    indexing.enqueue(project, ["TODO.md"])
    def fail(*args):
        raise RuntimeError("failed conversion")
    monkeypatch.setattr(indexing, "_run", fail)
    with pytest.raises(RuntimeError, match="failed conversion"):
        indexing.flush(project)
    assert indexing.state(project)["lexical_pending"] == ["TODO.md"]
    assert indexing.state(project)["lexical_error"] == "failed conversion"
    monkeypatch.setattr(indexing, "_run", lambda *args: "")
    indexing.flush(project, semantic=False)
    assert indexing.state(project)["lexical_error"] is None
    assert indexing.state(project)["semantic_pending"]


def test_invalidation_only_runs_lexical(project, monkeypatch):
    calls = []
    monkeypatch.setattr(indexing, "_run", lambda root, args: calls.append(args))
    result = indexing.invalidate(project, "deleted.md")
    assert calls == [["update"]]
    assert result["semantic_pending"] and not result["lexical_pending"]
    (project / "exists.md").write_text("preserve")
    with pytest.raises(ValueError, match="Delete the source"):
        indexing.invalidate(project, "exists.md")


def test_search_is_scoped_bounded_and_never_syncs(project, monkeypatch):
    calls = []
    def run(root, args):
        calls.append(args)
        return json.dumps({"results": [{"uri": "gno://research/threads/001.md?index=research",
                                        "line": 17, "snippet": "x" * 5000}]})
    monkeypatch.setattr(indexing, "_run", run)
    result = indexing.search(project, "invariant", mode="hybrid")
    assert calls == [["query", "invariant", "--collection", "research", "--limit", "5", "--json", "--fast"]]
    assert result["results"][0]["line"] == 17
    assert len(result["results"][0]["snippet"]) == 2400
    command = indexing._command(project, calls[0])
    assert command[1:5] == ["--config", str(project / ".rs/gno.yaml"), "--index", "research"]
    assert indexing._env(project)["GNO_DATA_DIR"] == str(project / ".rs/gno-data")


def test_private_config_preserved_on_conflict(project):
    file = project / ".rs/gno.yaml"
    file.write_text("modified: true\n")
    with pytest.raises(ValueError, match="Conflicting"):
        indexing.configure(project)
    assert file.read_text() == "modified: true\n"


@pytest.mark.skipif(not shutil.which("gno") or os.environ.get("RS_TEST_GNO") != "1",
                    reason="Set RS_TEST_GNO=1 for actual installed GNO integration")
def test_real_gno_scoping_tags_delete_and_latency(project, tmp_path_factory):
    other = tmp_path_factory.mktemp("gno-other")
    indexing.configure(other)
    (other / "other.md").write_text("Private quokka unrelated evidence")
    indexing.enqueue(other, ["other.md"])
    indexing.flush(other, semantic=False)
    note = project / "threads/001.md"
    note.parent.mkdir()
    note.write_text('---\nid: "001"\nstatus: obsolete\ntags: [reasoning]\n---\n'
                    '# Quokka invariant\nOur quokka algorithm preserves the invariant.\n')
    indexing.enqueue(project, [note])
    before = time.perf_counter()
    indexing.flush(project, semantic=False)
    sync_latency = time.perf_counter() - before
    durations = []
    for _ in range(2):
        before = time.perf_counter()
        result = indexing.search(project, "quokka")
        durations.append(time.perf_counter() - before)
        assert len(result["results"]) == 1
        assert result["results"][0]["source"] == str(note)
        assert result["results"][0]["status"] == "obsolete"
        assert result["results"][0]["line"] > 0
    tagged = json.loads(indexing._run(project, ["search", "quokka", "--collection", "research",
                                              "--tags-all", "reasoning", "--json"]))
    assert len(tagged["results"]) == 1
    # An incremental update picks up changed text without introducing the other project.
    note.write_text(note.read_text() + "\nNew wombat reasoning.\n")
    indexing.enqueue(project, [note])
    indexing.flush(project, semantic=False)
    assert indexing.search(project, "wombat")["results"]
    note.unlink()
    indexing.invalidate(project, note)
    assert indexing.search(project, "quokka")["results"] == []
    assert indexing.search(other, "quokka")["results"]
    print(f"actual GNO lexical sync={sync_latency:.3f}s cold search={durations[0]:.3f}s warm={durations[1]:.3f}s")
