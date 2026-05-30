#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/5/11 22:12
@Author  : alexanderwu
@File    : write_test.py
@Modified By: mashenquan, 2023-11-27. Following the think-act principle, solidify the task parameters when creating the
        WriteTest object, rather than passing them in when calling the run function.
"""

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
        "- Use only built-in node:test, assert/strict, fs, and path. Do not require npm install, jsdom, Babel, or Vite.\n"
        "- For plain CommonJS modules, import with require when safe.\n"
        "- For ESM, JSX, TS, TSX, React, or browser-oriented files that Node cannot execute directly, write source-contract tests that read the file text and assert concrete exported names, route paths, validation rules, UI labels, or data fields from the source.\n"
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


def normalize_test_code(code: str, test_filename: str, source_relative_path: str) -> str:
    """Normalize generated tests so they can run from the MetaGPT project root."""
    if Path(test_filename).suffix.lower() not in {".js", ".mjs", ".cjs"}:
        return code
    source_expr = _node_path_expression(source_relative_path)
    code = re.sub(
        r"path\.(?:resolve|join)\(\s*__dirname\s*,\s*['\"]\.\.['\"]\s*,[^)\n]*\)",
        source_expr,
        code,
    )
    code = re.sub(
        r"(const|let|var)\s+(sourcePath|sourceFile|sourceFilePath|filePath|targetPath)\s*=\s*[^;\n]+;",
        lambda match: f"{match.group(1)} {match.group(2)} = {source_expr};",
        code,
    )
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
        code = await self.write_code(prompt)
        self.i_context.test_doc.content = normalize_test_code(
            code,
            self.i_context.test_doc.filename,
            self.i_context.code_doc.root_relative_path.replace("\\", "/"),
        )
        return self.i_context
