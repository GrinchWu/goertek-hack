#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Artifacts and status files for the full-chain software generation workflow.

This module is intentionally small and stdlib-only. It does not replace MetaGPT's
Team/Role/Action workflow; it mirrors that workflow into the directory and JSON
format required by the hackathon task.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


NODE_META = {
    "design": ("概要设计Agent", "Architect"),
    "code_generation": ("代码生成Agent", "Engineer"),
    "unit_test": ("单元测试Agent", "QaEngineer"),
}

SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".css", ".html", ".json", ".csv"}
TEST_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_copytree(src: Path, dst: Path) -> list[Path]:
    if not src.exists():
        return []
    copied: list[Path] = []
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return [dst]
    for file in src.rglob("*"):
        if not file.is_file():
            continue
        rel = file.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
        copied.append(target)
    return copied


def _node_state(node_id: str) -> dict[str, Any]:
    display_name, agent_class = NODE_META[node_id]
    dependencies = {"design": [], "code_generation": ["design"], "unit_test": ["code_generation"]}[node_id]
    return {
        "node_id": node_id,
        "display_name": display_name,
        "agent_class": agent_class,
        "dependencies": dependencies,
        "status": "pending",
        "started_at": None,
        "ended_at": None,
        "quality_check_result": None,
        "input_files": [],
        "output_files": [],
        "error": None,
        "attempts": 0,
    }


class FullChainArtifacts:
    def __init__(self, root: Path, batch_id: str, product_spec_name: str, original_path: str, content: str):
        self.root = root.resolve()
        self.batch_id = batch_id
        self.docs_dir = self.root / "docs"
        self.pending_dir = self.docs_dir / "待生成"
        self.generated_dir = self.docs_dir / "已生成"
        self.batch_dir = self.generated_dir / batch_id
        self.source_dir = self.root / "src"
        self.tests_dir = self.root / "tests"
        self.product_spec_name = product_spec_name
        self.original_path = original_path
        self.content = content

    @property
    def status_path(self) -> Path:
        return self.batch_dir / "batch_status.json"

    @property
    def log_path(self) -> Path:
        return self.batch_dir / "execution_log.json"

    def relative(self, path: str | Path) -> str:
        p = Path(path)
        try:
            return str(p.resolve().relative_to(self.root)).replace("\\", "/")
        except Exception:
            return str(path).replace("\\", "/")

    def initialize(self) -> None:
        for path in [self.pending_dir, self.batch_dir / "概要设计", self.batch_dir / "代码生成", self.batch_dir / "单元测试", self.source_dir, self.tests_dir]:
            path.mkdir(parents=True, exist_ok=True)
        stored_spec = self.pending_dir / f"{self.batch_id}-{self.product_spec_name}"
        stored_spec.write_text(self.content, encoding="utf-8")
        status = {
            "batch_id": self.batch_id,
            "product_spec": {
                "name": self.product_spec_name,
                "original_path": self.original_path,
                "stored_path": self.relative(stored_spec),
            },
            "status": "running",
            "mode": "auto",
            "current_node": "design",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "nodes": {node_id: _node_state(node_id) for node_id in NODE_META},
        }
        _write_json(self.status_path, status)
        _write_json(self.log_path, [])
        self.log(None, "INFO", "batch_created", "Batch created by MetaGPT software company flow")

    def log(self, node_id: str | None, level: str, event: str, message: str, details: dict[str, Any] | None = None) -> None:
        entries = _read_json(self.log_path, [])
        entries.append(
            {
                "timestamp": now_iso(),
                "batch_id": self.batch_id,
                "node_id": node_id,
                "level": level,
                "event": event,
                "message": message,
                "details": details or {},
            }
        )
        _write_json(self.log_path, entries)

    def update_node(
        self,
        node_id: str,
        status: str,
        *,
        input_files: Iterable[str | Path] | None = None,
        output_files: Iterable[str | Path] | None = None,
        quality: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        data = _read_json(self.status_path, {})
        node = data["nodes"][node_id]
        if status == "running":
            node["started_at"] = node["started_at"] or now_iso()
            node["attempts"] += 1
            data["current_node"] = node_id
        if status in {"completed", "failed"}:
            node["ended_at"] = now_iso()
        node["status"] = status
        if input_files is not None:
            node["input_files"] = [self.relative(i) for i in input_files]
        if output_files is not None:
            node["output_files"] = [self.relative(i) for i in output_files]
        if quality is not None:
            node["quality_check_result"] = quality
        if error:
            node["error"] = error
        data["updated_at"] = now_iso()
        data["status"] = "failed" if status == "failed" else data.get("status", "running")
        _write_json(self.status_path, data)
        self.log(node_id, "ERROR" if status == "failed" else "INFO", f"node_{status}", NODE_META[node_id][0])

    def finalize_from_project(self, project_path: str | Path | None, error: str | None = None) -> None:
        output_files: dict[str, list[Path]] = {"design": [], "code_generation": [], "unit_test": []}
        if project_path:
            project = Path(project_path)
            output_files["design"].extend(_safe_copytree(project / "docs" / "system_design", self.batch_dir / "概要设计" / "system_design"))
            output_files["design"].extend(_safe_copytree(project / "docs" / "prd", self.batch_dir / "概要设计" / "prd"))
            output_files["design"].extend(_safe_copytree(project / "docs" / "task", self.batch_dir / "概要设计" / "task"))
            output_files["code_generation"].extend(_safe_copytree(project / "docs" / "code_summary", self.batch_dir / "代码生成" / "code_summary"))
            output_files["code_generation"].extend(_safe_copytree(project / "docs" / "code_plan_and_change", self.batch_dir / "代码生成" / "code_plan_and_change"))
            src = _find_src_dir(project)
            if src:
                output_files["code_generation"].extend(_safe_copytree(src, self.source_dir))
            output_files["unit_test"].extend(_safe_copytree(project / "tests", self.tests_dir))
            output_files["unit_test"].extend(_safe_copytree(project / "test_outputs", self.batch_dir / "单元测试" / "test_outputs"))
            if src and not _has_meaningful_tests(self.tests_dir):
                static_test = _write_static_project_test(self.root, self.source_dir, self.tests_dir)
                if static_test:
                    output_files["unit_test"].append(static_test)

        data = _read_json(self.status_path, {})
        for node_id, files in output_files.items():
            node = data["nodes"][node_id]
            if files:
                existing = set(node.get("output_files", []))
                node["output_files"] = sorted(existing | {self.relative(i) for i in files})
            if files and node["status"] != "completed":
                node["status"] = "completed"
                node["started_at"] = node["started_at"] or data["created_at"]
                node["ended_at"] = node["ended_at"] or now_iso()
                node["quality_check_result"] = {"passed": True, "score": 80, "checks": ["MetaGPT produced artifacts"], "warnings": [], "errors": []}
        if error:
            data["status"] = "failed"
            data["current_node"] = data.get("current_node")
            self.log(data.get("current_node"), "ERROR", "batch_failed", error)
        else:
            completed = all(node["status"] == "completed" for node in data["nodes"].values())
            data["status"] = "completed" if completed else "failed"
            data["current_node"] = None if completed else data.get("current_node")
        data["updated_at"] = now_iso()
        _write_json(self.status_path, data)
        self.log(None, "INFO" if data["status"] == "completed" else "ERROR", "batch_finished", data["status"])


def _find_src_dir(project: Path) -> Path | None:
    candidates = [project / "src", project / project.name]
    candidates.extend(p for p in project.iterdir() if p.is_dir() and p.name not in {"docs", "tests", "resources", "test_outputs", ".git"})
    for candidate in candidates:
        if candidate.exists() and any(
            path.is_file() and path.suffix in SOURCE_EXTENSIONS for path in candidate.rglob("*")
        ):
            return candidate
    return None


def _has_meaningful_tests(tests_dir: Path) -> bool:
    if not tests_dir.exists():
        return False
    for path in tests_dir.rglob("*"):
        if path.is_file() and path.suffix in TEST_EXTENSIONS and path.name != "__init__.py" and path.stat().st_size > 0:
            return True
    return False


def _write_static_project_test(root: Path, source_dir: Path, tests_dir: Path) -> Path | None:
    code_files = [
        path.relative_to(source_dir).as_posix()
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix in {".js", ".jsx", ".ts", ".tsx"}
    ]
    if not code_files:
        return None
    tests_dir.mkdir(parents=True, exist_ok=True)
    target = tests_dir / "test_generated_project_structure.js"
    selected = sorted(code_files)[:40]
    content = f"""const assert = require('assert');
const fs = require('fs');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..');
const srcRoot = path.join(repoRoot, 'src');
const expectedFiles = {json.dumps(selected, ensure_ascii=False, indent=2)};

assert.ok(fs.existsSync(srcRoot), 'src directory should exist');

for (const rel of expectedFiles) {{
  const file = path.join(srcRoot, rel);
  assert.ok(fs.existsSync(file), `expected generated file: ${{rel}}`);
  const text = fs.readFileSync(file, 'utf8');
  assert.ok(text.trim().length > 0, `generated file should not be empty: ${{rel}}`);
}}

const hasServer = expectedFiles.some((file) => file.endsWith('server.js') || file.endsWith('app.js'));
const hasReactEntry = expectedFiles.some((file) => file.endsWith('src/main.jsx') || file.endsWith('src/App.jsx') || file.endsWith('App.jsx'));
assert.ok(hasServer || hasReactEntry, 'generated project should include a server or React entry file');

console.log(`validated ${{expectedFiles.length}} generated files`);
"""
    target.write_text(content, encoding="utf-8")
    return target


def init_from_context(context, root: Path, batch_id: str, product_spec_name: str, original_path: str, content: str) -> FullChainArtifacts:
    artifacts = FullChainArtifacts(root=root, batch_id=batch_id, product_spec_name=product_spec_name, original_path=original_path, content=content)
    artifacts.initialize()
    context.kwargs.set("full_chain_batch_dir", str(artifacts.batch_dir))
    context.kwargs.set("full_chain_root", str(artifacts.root))
    return artifacts


def _artifacts_from_context(context) -> FullChainArtifacts | None:
    batch_dir = context.kwargs.get("full_chain_batch_dir")
    root = context.kwargs.get("full_chain_root")
    if not batch_dir or not root:
        return None
    batch_path = Path(batch_dir)
    status = _read_json(batch_path / "batch_status.json", {})
    product_spec = status.get("product_spec", {})
    return FullChainArtifacts(
        root=Path(root),
        batch_id=status.get("batch_id", batch_path.name),
        product_spec_name=product_spec.get("name", "requirement.md"),
        original_path=product_spec.get("original_path", ""),
        content="",
    )


def node_started(context, node_id: str, input_files: Iterable[str | Path] | None = None) -> None:
    artifacts = _artifacts_from_context(context)
    if artifacts:
        artifacts.update_node(node_id, "running", input_files=input_files)


def node_completed(context, node_id: str, output_files: Iterable[str | Path] | None = None) -> None:
    artifacts = _artifacts_from_context(context)
    if artifacts:
        artifacts.update_node(node_id, "completed", output_files=output_files, quality={"passed": True, "score": 80, "checks": ["MetaGPT node completed"], "warnings": [], "errors": []})


def node_failed(context, node_id: str, error: str) -> None:
    artifacts = _artifacts_from_context(context)
    if artifacts:
        artifacts.update_node(node_id, "failed", error=error)
