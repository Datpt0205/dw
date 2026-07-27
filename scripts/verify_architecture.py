"""Verify that every workspace package only imports what it declares.

Complements import-linter: import-linter enforces direction/boundaries between
known modules, this script enforces that no package "borrows" a third-party or
workspace dependency it has not declared in its own pyproject (blueprint §8.1).

Usage: uv run python scripts/verify_architecture.py
Exit code 0 = clean, 1 = violations found.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Import name -> distribution name for third-party packages we use.
IMPORT_TO_DIST = {
    "pydantic": "pydantic",
    "pydantic_settings": "pydantic-settings",
    "fastapi": "fastapi",
    "starlette": "fastapi",  # starlette ships with fastapi's dependency tree
    "uvicorn": "uvicorn",
    "sqlalchemy": "sqlalchemy",
    "alembic": "alembic",
    "asyncpg": "asyncpg",
    "langgraph": "langgraph",
    "qdrant_client": "qdrant-client",
    "redis": "redis",
    "httpx": "httpx",
    "minio": "minio",
    "docling": "docling",
    "boto3": "boto3",
    "opentelemetry": "opentelemetry-api",
    "langfuse": "langfuse",
    "jwt": "pyjwt",
    "yaml": "pyyaml",
    "langchain_core": "langchain-core",
    "dw_kernel": "dw-kernel",
    "dw_platform": "dw-platform",
    "dw_agent_runtime": "dw-agent-runtime",
    "dw_knowledge": "dw-knowledge",
    "dw_memory": "dw-memory",
    "dw_connectors": "dw-connectors",
    "dw_tender": "dw-tender",
    "dw_work_ops": "dw-work-ops",
    "dw_observability": "dw-observability",
    "dw_evals": "dw-evals",
    "dw_api": "dw-api",
    "dw_worker": "dw-worker",
}


def declared_dependencies(pyproject: Path) -> set[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps: set[str] = set()
    project = data.get("project", {})
    specs = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        specs.extend(group)
    for spec in specs:
        name = (
            spec.split("[")[0]
            .split(">")[0]
            .split("<")[0]
            .split("=")[0]
            .split("!")[0]
            .split(";")[0]
            .strip()
        )
        deps.add(name.lower())
    return deps


def imported_top_levels(src_dir: Path) -> dict[str, list[Path]]:
    imports: dict[str, list[Path]] = {}
    for py_file in src_dir.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover — parse errors fail loudly
            print(f"SYNTAX ERROR in {py_file}: {exc}")
            sys.exit(1)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.setdefault(alias.name.split(".")[0], []).append(py_file)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.setdefault(node.module.split(".")[0], []).append(py_file)
    return imports


def check_package(package_dir: Path) -> list[str]:
    pyproject = package_dir / "pyproject.toml"
    src_dir = package_dir / "src"
    if not pyproject.exists() or not src_dir.exists():
        return []

    own_modules = {p.name for p in src_dir.iterdir() if p.is_dir()}
    declared = declared_dependencies(pyproject)
    violations: list[str] = []

    for module, files in sorted(imported_top_levels(src_dir).items()):
        if module in own_modules or module in sys.stdlib_module_names:
            continue
        dist = IMPORT_TO_DIST.get(module)
        if dist is None:
            violations.append(
                f"{package_dir.name}: unknown third-party import {module!r} "
                f"(add to IMPORT_TO_DIST) in {files[0].relative_to(REPO_ROOT)}"
            )
        elif dist.lower() not in declared:
            violations.append(
                f"{package_dir.name}: imports {module!r} but does not declare "
                f"{dist!r} in {pyproject.relative_to(REPO_ROOT)} "
                f"(first seen in {files[0].relative_to(REPO_ROOT)})"
            )
    return violations


def main() -> int:
    package_dirs = sorted(
        [
            *(REPO_ROOT / "packages" / "python").iterdir(),
            REPO_ROOT / "apps" / "api",
            REPO_ROOT / "apps" / "worker",
        ]
    )
    all_violations: list[str] = []
    checked = 0
    for package_dir in package_dirs:
        if package_dir.is_dir():
            all_violations.extend(check_package(package_dir))
            checked += 1

    if all_violations:
        print(f"Declared-dependency check FAILED ({len(all_violations)} violations):")
        for violation in all_violations:
            print(f"  - {violation}")
        return 1
    print(f"Declared-dependency check passed for {checked} packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
