"""Generate the immutable release manifest (blueprint §23).

Collects every versioned artifact — platform, API, workers, graphs, prompt
bundles, toolsets, policies, knowledge index, eval datasets — plus the git SHA,
canonicalizes to JSON and derives a content-addressed reference:

    sha256:<hex>          → contracts/release/manifest.json
                            contracts/release/manifest.ref
                            contracts/release/history/manifest-<hex12>.json

Worker runs persist this reference (release_manifest_ref) so any run can be
traced back to the exact artifact set that produced it.

Usage:
    uv run python scripts/release_manifest.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = REPO_ROOT / "contracts" / "release"


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _project_version(pyproject: Path) -> str:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version", "0.0.0")
    return str(version)


def _workers() -> list[dict[str, Any]]:
    workers = []
    for path in sorted((REPO_ROOT / "configs" / "workers").glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        workers.append(
            {
                "worker_id": raw["worker_id"],
                "worker_version": raw["worker_version"],
                "graph_version": raw["graph_version"],
                "prompt_bundle_version": raw["prompt_bundle_version"],
                "toolset_version": raw["toolset_version"],
                "policy_version": raw["policy_version"],
                "memory_policy_version": raw["memory_policy_version"],
                "autonomy_level": raw.get("autonomy_level", "A2"),
            }
        )
    return workers


def _prompt_bundles() -> list[dict[str, str]]:
    bundles = []
    for path in sorted((REPO_ROOT / "configs" / "prompts").rglob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        bundles.append(
            {
                "prompt_id": raw["prompt_id"],
                "version": raw["version"],
                "checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return bundles


def _policies() -> list[dict[str, str]]:
    policies = []
    for path in sorted((REPO_ROOT / "configs" / "policies").glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        policies.append(
            {
                "policy_id": path.stem,
                "version": str(raw.get("policy_version", raw.get("version", "1.0.0"))),
                "checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return policies


def _toolsets() -> list[dict[str, str]]:
    """Tool versions come from the real registered definitions, never duplicated."""
    from dw_connectors.adapters.mock_task_connector import MockTaskConnectorAdapter
    from dw_work_ops.adapters.dispatch.tool import DispatchToolFactory

    definition = DispatchToolFactory(MockTaskConnectorAdapter()).build().definition
    return [
        {
            "tool": definition.name,
            "version": definition.version,
            "side_effect_level": str(definition.side_effect_level),
            "approval_policy": str(definition.approval_policy),
        }
    ]


def _eval_datasets() -> list[dict[str, str]]:
    datasets = []
    for path in sorted((REPO_ROOT / "evals" / "datasets").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        datasets.append(
            {
                "dataset_id": raw["dataset_id"],
                "version": raw["dataset_version"],
                "checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return datasets


def build_manifest() -> dict[str, Any]:
    from dw_knowledge.gateway import INDEX_VERSION
    from dw_memory.policy import MemoryWritePolicy

    return {
        "schema_version": "1.0",
        "platform_version": _project_version(REPO_ROOT / "pyproject.toml"),
        "git_sha": _git_sha(),
        "api_version": _project_version(REPO_ROOT / "apps" / "api" / "pyproject.toml"),
        "workers": _workers(),
        "prompt_bundles": _prompt_bundles(),
        "toolsets": _toolsets(),
        "policies": _policies(),
        "knowledge_index_version": INDEX_VERSION,
        "memory_policy_version": MemoryWritePolicy().policy_version,
        "eval_datasets": _eval_datasets(),
    }


def manifest_ref(manifest: dict[str, Any]) -> str:
    """Content-addressed over the artifact set. ``git_sha`` is informational —
    excluding it keeps the ref stable across commits that change no artifact."""
    hashable = {k: v for k, v in manifest.items() if k != "git_sha"}
    canonical = json.dumps(hashable, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def write_manifest(manifest: dict[str, Any]) -> tuple[Path, str]:
    ref = manifest_ref(manifest)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "history").mkdir(exist_ok=True)

    payload = json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    current = RELEASE_DIR / "manifest.json"
    current.write_text(payload, encoding="utf-8")
    (RELEASE_DIR / "manifest.ref").write_text(ref + "\n", encoding="utf-8")

    # History entries are immutable: the artifact set only (no git_sha), keyed
    # by its own hash — re-releasing identical artifacts is a no-op.
    hashable = {k: v for k, v in manifest.items() if k != "git_sha"}
    history_payload = json.dumps(hashable, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    digest12 = ref.removeprefix("sha256:")[:12]
    history = RELEASE_DIR / "history" / f"manifest-{digest12}.json"
    if history.exists() and history.read_text(encoding="utf-8") != history_payload:
        raise SystemExit(f"ERROR: manifest history collision for {history.name}")
    history.write_text(history_payload, encoding="utf-8")
    return current, ref


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify the committed manifest matches the repo"
    )
    args = parser.parse_args()

    manifest = build_manifest()
    ref = manifest_ref(manifest)

    if args.check:
        ref_file = RELEASE_DIR / "manifest.ref"
        if not ref_file.exists():
            print("ERROR: contracts/release/manifest.ref missing — run make release-manifest")
            return 1
        committed = ref_file.read_text(encoding="utf-8").strip()
        if committed != ref:
            print(f"ERROR: manifest is stale.\n  committed: {committed}\n  actual:    {ref}")
            print("Run: make release-manifest")
            return 1
        print(f"OK: release manifest up to date ({ref})")
        return 0

    path, ref = write_manifest(manifest)
    print(f"wrote {path.relative_to(REPO_ROOT)}")
    print(f"release_manifest_ref = {ref}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
