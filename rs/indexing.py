"""Project-scoped GNO adapter and durable, coalesced indexing queue.

Markdown is authoritative. Reads never sync; manual changes require enqueue/save.
GNO 1.5.1 syncs whole collections incrementally, rather than individual files.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import unquote, urlparse
import yaml

INDEX = "research"


def _dir(root):
    path = Path(root).resolve() / ".rs"
    path.mkdir(exist_ok=True)
    return path


@contextmanager
def _lock(root, name="index-state", blocking=True):
    with (_dir(root) / (name + ".lock")).open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _read(root):
    file = _dir(root) / "index-state.json"
    if not file.exists():
        return {"generation": 0, "lexical_pending": [], "semantic_pending": False,
                "lexical_error": None, "semantic_error": None,
                "lexical_updated": None, "semantic_updated": None}
    return json.loads(file.read_text())


def _write(root, data):
    file = _dir(root) / "index-state.json"
    temp = file.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(temp, file)


def state(root):
    """Return freshness without invoking GNO or scanning project documents."""
    with _lock(root):
        return _read(root)


def configure(root):
    """Write only a private GNO config; never invoke init (it ignores scope flags)."""
    root = Path(root).resolve()
    file = _dir(root) / "gno.yaml"
    expected = {"version": "1.0", "ftsTokenizer": "unicode61", "collections": [
        {"name": INDEX, "path": str(root), "pattern": "**/*",
         "include": [".md", ".pdf"],
         "exclude": [".rs/**", ".agents/**", ".claude/**", ".git/**", "node_modules/**"]}],
        "contexts": []}
    model = os.environ.get("RS_GNO_EMBED_MODEL")
    if model:
        expected["collections"][0]["models"] = {"embed": model}
    if file.exists():
        existing = yaml.safe_load(file.read_text())
        # A persisted local model choice remains valid when the installer is rerun
        # in a shell that does not set the one-time model environment variable.
        if not model and isinstance(existing, dict):
            collections = existing.get("collections", [])
            if len(collections) == 1 and isinstance(collections[0], dict):
                if "models" in collections[0]:
                    expected["collections"][0]["models"] = collections[0]["models"]
        if existing != expected:
            raise ValueError(f"Conflicting project GNO configuration: {file}")
    else:
        file.write_text(yaml.safe_dump(expected, sort_keys=False))
    return {"config": str(file), "index": INDEX, "data": str(_dir(root) / "gno-data")}


def _command(root, args):
    file = _dir(root) / "gno.yaml"
    if not file.exists():
        configure(root)
    return ["gno", "--config", str(file), "--index", INDEX, "--no-color", "--no-pager", *args]


def _env(root):
    return {**os.environ, "GNO_DATA_DIR": str(_dir(root) / "gno-data"),
            "GNO_CACHE_DIR": str(_dir(root) / "gno-cache"),
            "GNO_CONFIG_DIR": str(_dir(root) / "gno-config")}


def _run(root, args):
    result = subprocess.run(_command(root, args), cwd=root, env=_env(root),
                            capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[-2000:])
    return result.stdout


def enqueue(root, paths):
    """Persist work before launching one optional detached coalescing worker."""
    root = Path(root).resolve()
    relative = []
    for path in paths:
        target = Path(path)
        if not target.is_absolute():
            target = root / target
        relative.append(str(target.resolve().relative_to(root)))
    with _lock(root):
        data = _read(root)
        data["generation"] += 1
        data["lexical_pending"] = sorted(set(data["lexical_pending"]) | set(relative))
        data["semantic_pending"] = True
        _write(root, data)
    start_worker(root)
    return state(root)


def start_worker(root):
    if os.environ.get("RS_DISABLE_WORKER") == "1":
        return False
    # Reserve startup before Popen: worker itself holds a separate lifecycle lock.
    with _lock(root, "index-start"):
        with _lock(root, "index-worker", blocking=False) as acquired:
            if not acquired:
                return False
        data = state(root)
        if time.time() - data.get("worker_started", 0) < 2:
            return False
        with _lock(root):
            data = _read(root)
            data["worker_started"] = time.time()
            _write(root, data)
        env = dict(os.environ)
        package_root = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = package_root + os.pathsep + env.get("PYTHONPATH", "")
        with (_dir(root) / "index-worker.log").open("a") as output:
            subprocess.Popen([sys.executable, "-m", "rs.indexing", str(Path(root).resolve())],
                             cwd=root, env=env, stdin=subprocess.DEVNULL,
                             stdout=output, stderr=output, start_new_session=True)
    return True


def _lexical(root):
    snapshot = state(root)
    if not snapshot["lexical_pending"]:
        return
    try:
        _run(root, ["update"])
    except Exception as exc:
        with _lock(root):
            data = _read(root)
            data["lexical_error"] = str(exc)
            _write(root, data)
        raise
    with _lock(root):
        data = _read(root)
        # An edit arriving during sync must survive even if its path is identical.
        if data["generation"] == snapshot["generation"]:
            data["lexical_pending"] = []
        data["lexical_error"] = None
        data["lexical_updated"] = time.time()
        _write(root, data)


def _semantic(root):
    with _lock(root):
        snapshot = _read(root)
        if (not snapshot["semantic_pending"] or snapshot["lexical_pending"]
                or snapshot.get("invalidation_pending")):
            return
        # Publish the process under the state lock, so deletion cannot miss a
        # just-starting embed and accidentally wait for its full runtime.
        process = subprocess.Popen(_command(root, ["embed", "--collection", INDEX]),
                                   cwd=root, env=_env(root), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        snapshot["semantic_pid"] = process.pid
        _write(root, snapshot)
    try:
        stdout, stderr = process.communicate(timeout=1800)
        if process.returncode:
            raise RuntimeError((stderr or stdout).strip()[-2000:])
        with _lock(root):
            data = _read(root)
            if data["generation"] == snapshot["generation"]:
                data["semantic_pending"] = False
            data["semantic_error"] = None
            data["semantic_updated"] = time.time()
            _write(root, data)
    except Exception as exc:
        if process.poll() is None:
            process.kill()
            process.communicate()
        with _lock(root):
            data = _read(root)
            data["semantic_error"] = str(exc)
            _write(root, data)
        raise
    finally:
        with _lock(root):
            data = _read(root)
            data.pop("semantic_pid", None)
            _write(root, data)


def flush(root, semantic=True):
    """Explicit synchronous retry. A single writer protects all GNO mutations."""
    with _lock(root, "index-writer"):
        _lexical(root)
        if semantic:
            _semantic(root)
    return state(root)


def invalidate(root, path):
    """Wait for lexical deletion only; interrupt unrelated embedding if necessary."""
    root = Path(root).resolve()
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    target.resolve().relative_to(root)
    if target.exists():
        raise ValueError("Delete the source document before invalidating retrieval")
    with _lock(root):
        data = _read(root)
        data["invalidation_pending"] = str(target.relative_to(root))
        _write(root, data)
    enqueue(root, [target])
    pid = state(root).get("semantic_pid")
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    flush(root, semantic=False)
    # update removes vanished files and associated vectors in the same transaction.
    if state(root)["lexical_pending"]:
        flush(root, semantic=False)
    with _lock(root):
        data = _read(root)
        data.pop("invalidation_pending", None)
        _write(root, data)
    start_worker(root)
    return state(root)


def search(root, query, mode="keyword", limit=5):
    commands = {"keyword": "search", "semantic": "vsearch", "hybrid": "query"}
    if mode not in commands:
        raise ValueError("mode must be keyword, semantic, or hybrid")
    if not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    args = [commands[mode], query, "--collection", INDEX, "--limit", str(limit), "--json"]
    if mode == "hybrid":
        args.append("--fast")
    output = _run(root, args)
    try:
        result = json.loads(output)
    except json.JSONDecodeError:
        # node-llama-cpp can print backend initialization before --json output.
        decoder = json.JSONDecoder()
        result = None
        for position, character in enumerate(output):
            if character != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(output[position:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and "results" in candidate:
                result = candidate
                break
        if result is None:
            raise RuntimeError("GNO did not return valid search JSON")
    hits = result if isinstance(result, list) else result.get("results", [])
    root = Path(root).resolve()
    for hit in hits:
        uri = urlparse(hit.get("uri", ""))
        relative = unquote(uri.path).lstrip("/")
        target = (root / relative).resolve()
        target.relative_to(root)
        hit["source"] = str(target)
        snippet = str(hit.get("snippet", ""))
        hit["snippet"] = snippet[:2400]
        if len(snippet) > 2400:
            hit["snippet_truncated"] = True
        if target.suffix == ".md" and target.exists():
            with target.open() as handle:
                text = handle.read(16384)
            if text.startswith("---\n"):
                metadata = yaml.safe_load(text.split("---", 2)[1]) or {}
                if isinstance(metadata, dict) and "status" in metadata:
                    hit["status"] = metadata["status"]
    return {"results": hits, "freshness": state(root)}


def worker(root):
    # Explicit lifecycle unlock under index-start closes the enqueue/exit race.
    with (_dir(root) / "index-worker.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with _lock(root):
            data = _read(root)
            data["worker_started"] = 0
            _write(root, data)
        time.sleep(0.75)
        while True:
            try:
                flush(root)
            except Exception:
                with _lock(root, "index-start"):
                    fcntl.flock(handle, fcntl.LOCK_UN)
                return  # persisted error, explicit flush/enqueue can retry
            with _lock(root, "index-start"):
                data = state(root)
                if not data["lexical_pending"] and (not data["semantic_pending"]
                                                    or data.get("invalidation_pending")):
                    fcntl.flock(handle, fcntl.LOCK_UN)
                    return
            time.sleep(0.25)


if __name__ == "__main__":
    worker(Path(sys.argv[1]))
