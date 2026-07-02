"""Execute rulespec companion tests against patched variant YAML.

Structural validation (validate_proposal) proves a patch doesn't mangle
the YAML; this module proves it *runs*: each patched variant is swapped
into a scratch copy of the rulespec checkout and its companion
`.test.yaml` is executed with `axiom-encode test` (which drives
axiom-rules-engine). Historical test cases must still pass — the
version model guarantees back-dated computation is untouched, and this
is the executable check of that guarantee.

This is how we caught both real defect classes: pre-validator LLM
drafts that rewrote history, and the engine's current inability to load
versioned formulas on `derived` rules at all.

Requires the axiom-encode toolchain; point AXIOM_ENCODE_BIN at the CLI
(default: `axiom-encode` on PATH).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from .db import DEFAULT_DB


def _run_tests(encode_bin: str, root: Path, test_file: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [encode_bin, "test", "--root", str(root), str(test_file)],
        capture_output=True, text=True, timeout=600,
    )
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out.splitlines()[-1] if out else ""


def verify_all(db_path: str = DEFAULT_DB, *,
               rulespec_root: str | None = None,
               encode_bin: str | None = None) -> dict[str, int]:
    """Run companion tests for every variant with patched YAML.

    Writes the outcome into the variant's note (prefixed
    'engine-test:'), so reviewers and the UI can see executable status
    alongside the draft.
    """
    root = Path(rulespec_root or os.environ.get(
        "RULESPEC_US_ROOT", str(Path.home() / "rulespec-us" / "us")))
    encode_bin = encode_bin or os.environ.get("AXIOM_ENCODE_BIN", "axiom-encode")

    counts = {"patched": 0, "passed": 0, "failed": 0, "no_tests": 0}
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, file_path, patched_yaml, note FROM rule_variants
        WHERE patched_yaml IS NOT NULL
    """).fetchall()

    for row in rows:
        counts["patched"] += 1
        rel = Path(row["file_path"])
        test_rel = rel.with_suffix("").with_suffix(".test.yaml") \
            if rel.suffix == ".yaml" else None
        if test_rel is None or not (root / test_rel).exists():
            counts["no_tests"] += 1
            continue

        # Scratch copy of the checkout so imports resolve and the real
        # tree is never mutated.
        with tempfile.TemporaryDirectory(prefix="variant-verify-") as tmp:
            scratch = Path(tmp) / "root"
            shutil.copytree(root, scratch, symlinks=True,
                            ignore=shutil.ignore_patterns(".git"))
            (scratch / rel).write_text(row["patched_yaml"])
            ok, tail = _run_tests(encode_bin, scratch, scratch / test_rel)

        verdict = "pass" if ok else f"FAIL — {tail[:180]}"
        counts["passed" if ok else "failed"] += 1
        base_note = (row["note"] or "").split(" | engine-test:")[0]
        note = f"{base_note} | engine-test: {verdict}" if base_note \
            else f"engine-test: {verdict}"
        conn.execute("UPDATE rule_variants SET note = ? WHERE id = ?",
                     (note, row["id"]))
    conn.close()
    return counts
