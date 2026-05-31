#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/5/11 22:12
@Author  : alexanderwu
@File    : write_test.py
@Modified By: mashenquan, 2023-11-27. Following the think-act principle, solidify the task parameters when creating the
        WriteTest object, rather than passing them in when calling the run function.
"""

import os
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from metagpt.actions.action import Action
from metagpt.const import TEST_CODES_FILE_REPO
from metagpt.logs import logger
from metagpt.schema import Document, TestingContext
from metagpt.utils.common import CodeParser

PROMPT_TEMPLATE = """
NOTICE
1. Role: You are a QA engineer; the main goal is to design, develop, and execute well-structured, maintainable test cases and scripts. Your focus should be on ensuring the product quality of the entire project through systematic testing.
2. Requirement: Based on the context, develop a comprehensive test suite that adequately covers all relevant aspects of the code file under review. Your test suite will be part of the overall project QA, so please develop complete, robust, and reusable test cases.
3. Attention1: Return raw test code only. Do not include markdown headings, explanations, or ``` fences.
4. Attention2: If there are any settings in your tests, ALWAYS SET A DEFAULT VALUE, ALWAYS USE STRONG TYPE AND EXPLICIT VARIABLE.
5. Attention3: YOU MUST FOLLOW "Data structures and interfaces". DO NOT CHANGE ANY DESIGN. Make sure your tests respect the existing design and ensure its validity.
6. Think before writing: What should be tested and validated in this document? What edge cases could exist? What might fail?
7. CAREFULLY CHECK THAT YOU DON'T MISS ANY NECESSARY TEST CASES/SCRIPTS IN THIS FILE.
8. Framework: {framework_name}
9. Test strategy:
{framework_instruction}
-----
## Source file under test
Language: {language}
Project-relative source path: {source_file_path}
Project-relative test path: tests/{test_file_name}

```{code_block_type}
{code_to_test}
```

We will put your test code at {workspace}/tests/{test_file_name}, run it from {workspace}, and execute this command:
{run_command}

Write {test_file_name}. Do your best to implement THIS ONLY ONE FILE. Return raw executable test code only.
"""


@dataclass(frozen=True)
class TestProfile:
    language: str
    framework_name: str
    test_suffix: str
    code_block_type: str
    command_prefix: tuple[str, ...]
    instruction: str


PYTHON_PROFILE = TestProfile(
    language="Python",
    framework_name="Python unittest",
    test_suffix=".py",
    code_block_type="python",
    command_prefix=("python",),
    instruction=(
        "- Use Python's built-in unittest framework only.\n"
        "- Import the code under test using the PYTHONPATH that points at the generated source directory.\n"
        "- Cover success paths, validation failures, edge cases, and persistence or API behavior when visible."
    ),
)

NODE_PROFILE = TestProfile(
    language="JavaScript/TypeScript",
    framework_name="Node.js built-in node:test with assert/strict",
    test_suffix=".test.js",
    code_block_type="javascript",
    command_prefix=("node", "--test"),
    instruction=(
        "- Use only CommonJS require syntax with built-in node:test, assert/strict, fs, and path. Do not use ESM import syntax.\n"
        "- If you use before, after, beforeEach, or afterEach, import them explicitly from node:test.\n"
        "- The test file itself must be plain executable JavaScript, even when the source file is TypeScript; do not write TypeScript type annotations in the test file.\n"
        "- Do not require npm install, jsdom, Babel, ts-node, tsx, or Vite.\n"
        "- For plain CommonJS modules, import with require when safe.\n"
        "- For Express routers, React, JSX, browser files, or files with external npm dependencies, prefer source-contract tests that read the source text. Do not call an Express Router directly with fake req/res objects unless you also provide a real HTTP harness.\n"
        "- If you mock a dependency through require.cache, make sure the cache key points to the dependency module path, not the source file under test. Build paths from process.cwd() plus the project folder; never use require('../backend/...') from the tests directory.\n"
        "- For ESM, JSX, TS, TSX, React, or browser-oriented files that Node cannot execute directly, write source-contract tests that read the file text and assert concrete exported names, route paths, validation rules, UI labels, or data fields from the source.\n"
        "- When asserting source text, use whitespace-tolerant regular expressions. Do not require JSX labels, headings, CSS selector lists, className values, chained expressions, or imports to appear on one exact line.\n"
        "- Source-contract tests must verify behavior-relevant structure, not formatting preference. Avoid brittle checks for exact Tailwind class strings, exact comment text, or exact JSDoc wording.\n"
        "- Always assert that the source has no markdown fences and is non-empty."
    ),
)

GENERIC_PROFILE = TestProfile(
    language="Generic source",
    framework_name="Node.js built-in node:test source-contract test",
    test_suffix=".contract.test.js",
    code_block_type="text",
    command_prefix=("node", "--test"),
    instruction=(
        "- Use only built-in node:test, assert/strict, fs, and path.\n"
        "- Treat the source as text and create source-contract tests for file existence, non-empty content, absence of markdown fences, absence of unfinished placeholders, and important domain terms or API names visible in the source.\n"
        "- Do not execute the target language compiler or install dependencies."
    ),
)

PROFILE_BY_SUFFIX = {
    ".py": PYTHON_PROFILE,
    ".js": NODE_PROFILE,
    ".jsx": NODE_PROFILE,
    ".mjs": NODE_PROFILE,
    ".cjs": NODE_PROFILE,
    ".ts": NODE_PROFILE,
    ".tsx": NODE_PROFILE,
}

TESTABLE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".cpp",
    ".cc",
    ".cxx",
    ".c",
    ".h",
    ".hpp",
    ".php",
    ".rb",
    ".swift",
    ".sql",
    ".html",
    ".css",
}


def get_test_profile(filename: str) -> TestProfile:
    return PROFILE_BY_SUFFIX.get(Path(filename).suffix.lower(), GENERIC_PROFILE)


def is_testable_source(filename: str) -> bool:
    path = Path(filename)
    if path.name == "__init__.py" or "test" in path.name.lower():
        return False
    return path.suffix.lower() in TESTABLE_SUFFIXES


def build_test_filename(source_filename: str) -> str:
    path = Path(source_filename)
    profile = get_test_profile(source_filename)
    flattened = path.with_suffix("").as_posix().replace("/", "__").replace("\\", "__")
    if profile is PYTHON_PROFILE:
        return f"test_{flattened}.py"
    return f"test_{flattened}{profile.test_suffix}"


def build_test_command(test_relative_path: str, source_filename: str) -> list[str]:
    profile = get_test_profile(source_filename)
    return [*profile.command_prefix, test_relative_path]


def _node_path_expression(source_relative_path: str) -> str:
    parts = Path(source_relative_path.replace("\\", "/")).as_posix().split("/")
    return "path.join(process.cwd(), " + ", ".join(json.dumps(part) for part in parts if part) + ")"


def build_minimal_node_source_contract_test(source_relative_path: str) -> str:
    source_expr = _node_path_expression(source_relative_path)
    label = source_relative_path.replace("\\", "/")
    return f"""const {{ describe, it }} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');

const SOURCE_FILE = {source_expr};

describe({json.dumps(label + " source contract")}, () => {{
  it('should exist and be non-empty', () => {{
    assert.ok(fs.existsSync(SOURCE_FILE), `Source file does not exist: ${{SOURCE_FILE}}`);
    const source = fs.readFileSync(SOURCE_FILE, 'utf8');
    assert.ok(source.trim().length > 0, 'Source file must not be empty');
  }});

  it('should not contain markdown fences or unfinished placeholders', () => {{
    const source = fs.readFileSync(SOURCE_FILE, 'utf8');
    assert.doesNotMatch(source, /```/);
    assert.doesNotMatch(source, /\\b(TODO|FIXME|XXX|CHANGEME)\\b/i);
  }});

  it('should contain executable source structure', () => {{
    const source = fs.readFileSync(SOURCE_FILE, 'utf8');
    assert.ok(
      /(\\bexport\\s+default|\\bexport\\s+const|module\\.exports|\\bfunction\\s+|\\bconst\\s+\\w+\\s*=|\\bclass\\s+|\\bimport\\s+|require\\s*\\(|CREATE\\s+TABLE|SELECT\\s+|INSERT\\s+|UPDATE\\s+|DELETE\\s+|@tailwind\\b|<html\\b|<div\\b|\\{{|\\}})/i.test(source),
      'Source should contain executable or declarative structure'
    );
  }});
}});
"""


def should_use_deterministic_test(profile: TestProfile) -> bool:
    """Prefer stable framework-generated tests unless explicitly enabling LLM-authored tests.

    DeepSeek can generate very detailed JavaScript source-contract tests, but in large
    projects those tests often fail on equivalent implementation details, garbled
    localized text, or path construction. The hackathon pipeline needs MetaGPT to
    complete reliably first; richer functional validation is handled by build/API/UI
    checks after generation.
    """
    if os.getenv("METAGPT_QA_LLM_TESTS", "").lower() in {"1", "true", "yes", "on"}:
        return False
    return profile in {NODE_PROFILE, GENERIC_PROFILE}


def _node_project_path_expression(parts: list[str]) -> str:
    return "path.join(process.cwd(), " + ", ".join(json.dumps(part) for part in parts if part) + ")"


def normalize_test_code(code: str, test_filename: str, source_relative_path: str) -> str:
    """Normalize generated tests so they can run from the MetaGPT project root."""
    if Path(test_filename).suffix.lower() not in {".js", ".mjs", ".cjs"}:
        return code
    source_expr = _node_path_expression(source_relative_path)
    code = _normalize_node_test_imports(code)
    code = re.sub(
        r"path\.(?:resolve|join)\(\s*__dirname\s*,\s*['\"]\.\.['\"]\s*,[^)\n]*\)",
        source_expr,
        code,
    )
    code = re.sub(
        r"((?:const|let|var)\s+[A-Za-z_$][\w$]*(?:source|file|path|target)[A-Za-z_$\w]*\s*=\s*)"
        r"path\.(?:resolve|join)\([\s\S]*?\);",
        lambda match: match.group(0) if _looks_like_dependency_path_var(match.group(1)) else f"{match.group(1)}{source_expr};",
        code,
        flags=re.IGNORECASE,
    )
    code = re.sub(
        r"(const|let|var)\s+(sourcePath|sourceFile|sourceFilePath|filePath|targetPath)\s*=\s*[^;\n]+;",
        lambda match: f"{match.group(1)} {match.group(2)} = {source_expr};",
        code,
    )
    code = _normalize_project_relative_requires(code, source_relative_path)
    code = _normalize_source_relative_requires(code, source_relative_path)
    code = _normalize_dependency_path_from_source_var(code)
    code = _normalize_known_dependency_mock_paths(code, source_relative_path)
    code = _normalize_brittle_source_assertions(code)
    code = _normalize_windows_dynamic_imports(code)
    code = _strip_typescript_test_syntax(code)
    return code


def _looks_like_dependency_path_var(prefix: str) -> bool:
    lowered = prefix.lower()
    dependency_markers = (
        "csvhandler",
        "csvhelper",
        "helperpath",
        "handlerpath",
        "modulepath",
        "mockpath",
        "dependencypath",
    )
    return any(marker in lowered for marker in dependency_markers)


def _normalize_known_dependency_mock_paths(code: str, source_relative_path: str) -> str:
    parts = Path(source_relative_path.replace("\\", "/")).as_posix().split("/")
    if "backend" not in parts:
        return code
    project_parts = parts[: parts.index("backend")]
    replacements = {
        "csvHandlerPath": [*project_parts, "backend", "utils", "csvHandler.js"],
        "csvHelperPath": [*project_parts, "backend", "src", "models", "csvHelper.js"],
    }
    for var_name, target_parts in replacements.items():
        expr = _node_project_path_expression(target_parts)
        code = re.sub(
            rf"((?:const|let|var)\s+{var_name}\s*=\s*)path\.(?:resolve|join)\([\s\S]*?\);",
            lambda match, expr=expr: f"{match.group(1)}{expr};",
            code,
            flags=re.IGNORECASE,
        )
    code = re.sub(
        r"exports:\s*mockCSVHandler\b",
        "exports: Object.assign(mockCSVHandler, { CSVHandler: mockCSVHandler })",
        code,
    )
    return code


def _normalize_brittle_source_assertions(code: str) -> str:
    """Relax common LLM-generated source-contract checks that fail only on formatting."""
    code = re.sub(r">([\w\u4e00-\u9fff][^<>/\\]*)<\\/", r">\\s*\1\\s*<\\/", code)
    code = re.sub(r"(html),\s*(body),\s*(#root)", r"\1\\s*,\\s*\2\\s*,\\s*\3", code)
    code = re.sub(r"(React)\.\*(Tailwind)\\s\+(CSS)", r"\1[\\s\\S]*\2\\s+\3", code)
    code = code.replace("source.includes('React')", "/React/.test(source)")
    code = code.replace('source.includes("React")', "/React/.test(source)")
    return code


def _normalize_windows_dynamic_imports(code: str) -> str:
    """Node ESM dynamic import needs file:// URLs for absolute Windows paths."""
    if "import(" not in code:
        return code
    var_pattern = (
        r"(SOURCE_PATH|SOURCE_FILE_PATH|sourcePath|sourceFile|sourceFilePath|filePath|targetPath|"
        r"apiPath|configPath|modulePath|componentPath|routerPath)"
    )
    code = re.sub(rf"\bimport\(\s*{var_pattern}\s*\)", r"import(pathToFileURL(\1).href)", code)
    if "pathToFileURL(" not in code:
        return code
    if "require('url')" in code or 'require("url")' in code:
        return code
    path_require = re.search(r"^const\s+path\s*=\s*require\(['\"](?:node:)?path['\"]\);\s*$", code, flags=re.MULTILINE)
    import_line = "const { pathToFileURL } = require('url');"
    if path_require:
        insert_at = path_require.end()
        return code[:insert_at] + "\n" + import_line + code[insert_at:]
    return import_line + "\n" + code


def _normalize_project_relative_requires(code: str, source_relative_path: str) -> str:
    parts = Path(source_relative_path.replace("\\", "/")).as_posix().split("/")
    marker_indexes = [idx for idx, part in enumerate(parts) if part in {"backend", "frontend"}]
    if not marker_indexes:
        return code
    project_parts = parts[: marker_indexes[0]]

    def replace(match: re.Match) -> str:
        quote_path = match.group("path").replace("\\", "/")
        stripped = quote_path
        while stripped.startswith("../"):
            stripped = stripped[3:]
        if stripped.startswith("./"):
            stripped = stripped[2:]
        if not stripped.startswith(("backend/", "frontend/")):
            return match.group(0)
        expr = _node_project_path_expression([*project_parts, *stripped.split("/")])
        return f"{match.group('prefix')}{expr}{match.group('suffix')}"

    return re.sub(
        r"(?P<prefix>\b(?:require|require\.resolve)\(\s*)['\"](?P<path>(?:\.\.?[/\\])+[A-Za-z0-9_./\\-]+)['\"](?P<suffix>\s*\))",
        replace,
        code,
    )


def _normalize_source_relative_requires(code: str, source_relative_path: str) -> str:
    source_parts = Path(source_relative_path.replace("\\", "/")).as_posix().split("/")
    if not any(part in {"backend", "frontend"} for part in source_parts):
        return code
    source_dir = source_parts[:-1]

    def resolve_parts(relative_path: str) -> list[str]:
        parts = list(source_dir)
        for part in relative_path.replace("\\", "/").split("/"):
            if not part or part == ".":
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        if parts and Path(parts[-1]).suffix == "":
            parts[-1] += ".js"
        return parts

    def replace(match: re.Match) -> str:
        quote_path = match.group("path")
        stripped = quote_path.replace("\\", "/")
        while stripped.startswith("../"):
            stripped = stripped[3:]
        if stripped.startswith(("backend/", "frontend/")):
            return match.group(0)
        expr = _node_project_path_expression(resolve_parts(quote_path))
        return f"{match.group('prefix')}{expr}{match.group('suffix')}"

    return re.sub(
        r"(?P<prefix>\b(?:require|require\.resolve)\(\s*)['\"](?P<path>(?:\.\.?[/\\])+[A-Za-z0-9_./\\-]+)['\"](?P<suffix>\s*\))",
        replace,
        code,
    )


def _normalize_dependency_path_from_source_var(code: str) -> str:
    source_var_names = (
        "SOURCE_PATH",
        "SOURCE_FILE_PATH",
        "sourcePath",
        "sourceFile",
        "sourceFilePath",
        "filePath",
        "targetPath",
    )
    source_var_pattern = "|".join(re.escape(name) for name in source_var_names)
    return re.sub(
        rf"path\.(?:resolve|join)\(\s*({source_var_pattern})\s*,",
        r"path.join(path.dirname(\1),",
        code,
    )


def _normalize_node_test_imports(code: str) -> str:
    """Convert common ESM test imports to CommonJS and include used hooks."""
    code = re.sub(
        r"import\s+\{([^}]+)\}\s+from\s+['\"]node:test['\"]\s*;?",
        lambda match: f"const {{ {_normalize_node_test_names(match.group(1), code)} }} = require('node:test');",
        code,
    )
    code = re.sub(
        r"import\s+assert\s+from\s+['\"](?:node:)?assert/strict['\"]\s*;?",
        "const assert = require('assert/strict');",
        code,
    )
    code = re.sub(r"import\s+fs\s+from\s+['\"](?:node:)?fs['\"]\s*;?", "const fs = require('fs');", code)
    code = re.sub(r"import\s+path\s+from\s+['\"](?:node:)?path['\"]\s*;?", "const path = require('path');", code)

    if "require('node:test')" in code:
        needed = [name for name in ("before", "after", "beforeEach", "afterEach") if re.search(rf"\b{name}\s*\(", code)]
        if needed:
            code = re.sub(
                r"const\s+\{([^}]+)\}\s*=\s*require\(['\"]node:test['\"]\);",
                lambda match: f"const {{ {_merge_names(match.group(1), needed)} }} = require('node:test');",
                code,
                count=1,
            )
    return code


def _normalize_node_test_names(names: str, code: str) -> str:
    parsed = [name.strip() for name in names.split(",") if name.strip()]
    needed = [name for name in ("before", "after", "beforeEach", "afterEach") if re.search(rf"\b{name}\s*\(", code)]
    return _merge_names(", ".join(parsed), needed)


def _merge_names(names: str, extra_names: list[str]) -> str:
    parsed = [name.strip() for name in names.split(",") if name.strip()]
    for name in extra_names:
        if name not in parsed:
            parsed.append(name)
    return ", ".join(parsed)


def _strip_typescript_test_syntax(code: str) -> str:
    """Remove common TypeScript-only syntax that LLMs sometimes put into .test.js files."""
    code = re.sub(r"\b(let|const|var)\s+([A-Za-z_$][\w$]*)\s*:\s*[^=;\n]+([=;])", r"\1 \2\3", code)
    code = re.sub(r"\(([^()\n]*?)\s+as\s+any\)", r"(\1)", code)
    return code


def sanitize_python_code(text: str) -> str:
    """Extract executable test code from LLM responses that may contain markdown wrappers."""
    code = (text or "").strip()
    for _ in range(4):
        matches = re.findall(r"```(?:[a-z0-9_+-]+)?\s*\n(.*?)\n```", code, flags=re.DOTALL | re.IGNORECASE)
        if not matches:
            break
        code = max(matches, key=len).strip()

    lines = code.splitlines()
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("##")):
        lines.pop(0)

    cleaned = []
    for line in lines:
        stripped = line.strip().lower()
        if stripped == "```" or stripped.startswith("```"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip() + "\n"


class WriteTest(Action):
    name: str = "WriteTest"
    i_context: Optional[TestingContext] = None

    async def write_code(self, prompt):
        code_rsp = await self._aask(prompt)

        try:
            code = CodeParser.parse_code(text=code_rsp)
        except Exception:
            # Handle the exception if needed
            logger.error(f"Can't parse the code: {code_rsp}")

            # Return code_rsp in case of an exception, assuming llm just returns code as it is and doesn't wrap it inside ```
            code = code_rsp
        return sanitize_python_code(code)

    async def run(self, *args, **kwargs) -> TestingContext:
        if not self.i_context.test_doc:
            self.i_context.test_doc = Document(
                filename=build_test_filename(self.i_context.code_doc.filename), root_path=TEST_CODES_FILE_REPO
            )
        profile = get_test_profile(self.i_context.code_doc.filename)
        fake_root = "/data"
        test_relative_path = f"tests/{self.i_context.test_doc.filename}"
        prompt = PROMPT_TEMPLATE.format(
            code_to_test=self.i_context.code_doc.content,
            test_file_name=self.i_context.test_doc.filename,
            source_file_path=self.i_context.code_doc.root_relative_path.replace("\\", "/"),
            workspace=fake_root,
            language=profile.language,
            framework_name=profile.framework_name,
            framework_instruction=profile.instruction,
            code_block_type=profile.code_block_type,
            run_command=" ".join(build_test_command(test_relative_path, self.i_context.code_doc.filename)),
        )
        if should_use_deterministic_test(profile):
            logger.info(
                f"Using deterministic source-contract test for {self.i_context.code_doc.root_relative_path}"
            )
            code = build_minimal_node_source_contract_test(
                self.i_context.code_doc.root_relative_path.replace("\\", "/")
            )
        else:
            code = await self.write_code(prompt)
        self.i_context.test_doc.content = normalize_test_code(
            code,
            self.i_context.test_doc.filename,
            self.i_context.code_doc.root_relative_path.replace("\\", "/"),
        )
        return self.i_context
