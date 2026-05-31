#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/5/11 17:45
@Author  : alexanderwu
@File    : write_code.py
@Modified By: mashenquan, 2023-11-1. In accordance with Chapter 2.1.3 of RFC 116, modify the data type of the `cause_by`
            value of the `Message` object.
@Modified By: mashenquan, 2023-11-27.
        1. Mark the location of Design, Tasks, Legacy Code and Debug logs in the PROMPT_TEMPLATE with markdown
        code-block formatting to enhance the understanding for the LLM.
        2. Following the think-act principle, solidify the task parameters when creating the WriteCode object, rather
        than passing them in when calling the run function.
        3. Encapsulate the input of RunCode into RunCodeContext and encapsulate the output of RunCode into
        RunCodeResult to standardize and unify parameter passing between WriteCode, RunCode, and DebugError.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_random_exponential

from metagpt.actions.action import Action
from metagpt.actions.project_management_an import REFINED_TASK_LIST, TASK_LIST
from metagpt.actions.write_code_plan_and_change_an import REFINED_TEMPLATE
from metagpt.logs import logger
from metagpt.schema import CodingContext, Document, RunCodeResult
from metagpt.utils.common import CodeParser, get_markdown_code_block_type
from metagpt.utils.project_repo import ProjectRepo
from metagpt.utils.report import EditorReporter

DEFAULT_MAX_LEGACY_CODE_FILES = 8
DEFAULT_MAX_LEGACY_CODE_CHARS = 24000
DEFAULT_MAX_SINGLE_LEGACY_FILE_CHARS = 6000

PROMPT_TEMPLATE = """
NOTICE
Role: You are a professional engineer; the main goal is to write google-style, elegant, modular, easy to read and maintain code
Language: Please use the same language as the user requirement, but the title and code should be still in English. For example, if the user speaks Chinese, the specific text of your answer should also be in Chinese.
ATTENTION: Use '##' to SPLIT SECTIONS, not '#'. Output format carefully referenced "Format example".

# Context
## Design
{design}

## Task
{task}

## Legacy Code
{code}

## Debug logs
```text
{logs}

{summary_log}
```

## Bug Feedback logs
```text
{feedback}
```

# Format example
## Code: {demo_filename}.py
```python
## {demo_filename}.py
...
```
## Code: {demo_filename}.js
```javascript
// {demo_filename}.js
...
```

# Instruction: Based on the context, follow "Format example", write code.

## Code: {filename}. Write code with triple quoto, based on the following attentions and context.
1. Only One file: do your best to implement THIS ONLY ONE FILE.
2. COMPLETE CODE: Your code will be part of the entire project, so please implement complete, reliable, reusable code snippets.
3. Set default value: If there is any setting, ALWAYS SET A DEFAULT VALUE, ALWAYS USE STRONG TYPE AND EXPLICIT VARIABLE. AVOID circular import.
4. Follow design: YOU MUST FOLLOW "Data structures and interfaces". DONT CHANGE ANY DESIGN. Do not use public member functions that do not exist in your design.
5. CAREFULLY CHECK THAT YOU DONT MISS ANY NECESSARY CLASS/FUNCTION IN THIS FILE.
6. Before using a external variable/module, make sure you import it first.
7. Write out EVERY CODE DETAIL, DON'T LEAVE TODO.
8. Frontend quality bar: If this file is part of a frontend, implement the actual usable application screen, not a marketing page. Keep the UI quiet, work-focused, responsive, and consistent; include real navigation, forms, validation, loading/error/empty states, admin/user workflows when relevant, accessible labels, and stable layouts. Prefer one coherent styling approach such as Tailwind CSS; avoid decorative-only gradients, nested cards, placeholder text, and unfinished mock content.
9. Full-stack completeness bar: Required behavior must be working local code. Do not leave TODOs, placeholders, demo-only branches, simplified stubs, fake success responses, or "future extension" notes for authentication, admin/user workflows, CSV persistence, payment simulation, or external-system simulation when the requirement asks for them. If this is a package/config file, include every script and dependency needed to install, test, build, and run the generated project.
10. JavaScript module consistency: For Vite/React frontends, either set `"type": "module"` in `frontend/package.json` when using `import`/`export` syntax in `vite.config.js`, `tailwind.config.js`, or `postcss.config.js`, or write those config files as CommonJS. The generated frontend must pass `npm run build` without module-format errors.
11. Frontend import/export consistency: When React components import named symbols such as contexts, hooks, API helpers, or utilities, the defining file must export those exact names. Keep context value names consistent across all consumers, for example do not mix `addToast` and `showToast` unless both are provided.
12. CommonJS import/export consistency: If backend modules are consumed with named destructuring such as `const {{ CSVHelper }} = require('../models/csvHelper')` or `const {{ CSVHandler }} = require('../utils/csvHandler')`, the required module must expose that named property. Prefer exporting both the default value and the named property for shared utilities when in doubt.

"""


class WriteCode(Action):
    name: str = "WriteCode"
    i_context: Document = Field(default_factory=Document)
    repo: Optional[ProjectRepo] = Field(default=None, exclude=True)
    input_args: Optional[BaseModel] = Field(default=None, exclude=True)

    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
    async def write_code(self, prompt) -> str:
        code_rsp = await self._aask(prompt)
        code = CodeParser.parse_code(text=code_rsp)
        return code

    async def run(self, *args, **kwargs) -> CodingContext:
        bug_feedback = None
        if self.input_args and hasattr(self.input_args, "issue_filename"):
            bug_feedback = await Document.load(self.input_args.issue_filename)
        coding_context = CodingContext.loads(self.i_context.content)
        if not coding_context.code_plan_and_change_doc:
            coding_context.code_plan_and_change_doc = await self.repo.docs.code_plan_and_change.get(
                filename=coding_context.task_doc.filename
            )
        test_doc = await self.repo.test_outputs.get(filename="test_" + coding_context.filename + ".json")
        requirement_doc = await Document.load(self.input_args.requirements_filename)
        summary_doc = None
        if coding_context.design_doc and coding_context.design_doc.filename:
            summary_doc = await self.repo.docs.code_summary.get(filename=coding_context.design_doc.filename)
        logs = ""
        if test_doc:
            test_detail = RunCodeResult.loads(test_doc.content)
            logs = test_detail.stderr

        if self.config.inc or bug_feedback:
            code_context = await self.get_codes(
                coding_context.task_doc, exclude=self.i_context.filename, project_repo=self.repo, use_inc=True
            )
        else:
            code_context = await self.get_codes(
                coding_context.task_doc, exclude=self.i_context.filename, project_repo=self.repo
            )

        if self.config.inc:
            prompt = REFINED_TEMPLATE.format(
                user_requirement=requirement_doc.content if requirement_doc else "",
                code_plan_and_change=coding_context.code_plan_and_change_doc.content
                if coding_context.code_plan_and_change_doc
                else "",
                design=coding_context.design_doc.content if coding_context.design_doc else "",
                task=coding_context.task_doc.content if coding_context.task_doc else "",
                code=code_context,
                logs=logs,
                feedback=bug_feedback.content if bug_feedback else "",
                filename=self.i_context.filename,
                demo_filename=Path(self.i_context.filename).stem,
                summary_log=summary_doc.content if summary_doc else "",
            )
        else:
            prompt = PROMPT_TEMPLATE.format(
                design=coding_context.design_doc.content if coding_context.design_doc else "",
                task=coding_context.task_doc.content if coding_context.task_doc else "",
                code=code_context,
                logs=logs,
                feedback=bug_feedback.content if bug_feedback else "",
                filename=self.i_context.filename,
                demo_filename=Path(self.i_context.filename).stem,
                summary_log=summary_doc.content if summary_doc else "",
            )
        logger.info(f"Writing {coding_context.filename}..")
        async with EditorReporter(enable_llm_stream=True) as reporter:
            await reporter.async_report({"type": "code", "filename": coding_context.filename}, "meta")
            code = await self.write_code(prompt)
            code = self._normalize_generated_code(coding_context.filename, code)
            if not coding_context.code_doc:
                # avoid root_path pydantic ValidationError if use WriteCode alone
                coding_context.code_doc = Document(
                    filename=coding_context.filename, root_path=str(self.repo.src_relative_path)
                )
            coding_context.code_doc.content = code
            await reporter.async_report(coding_context.code_doc, "document")
        return coding_context

    @staticmethod
    def _normalize_generated_code(filename: str, code: str) -> str:
        """Apply narrow, deterministic repairs for common cross-file JS generation mistakes."""
        suffix = Path(filename).suffix.lower()
        if suffix == ".csv":
            return code if code.endswith("\n") else code + "\n"

        if suffix not in {".md", ".markdown"}:
            code = WriteCode._strip_markdown_code_wrapper(code)

        if suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            return code

        for context_name in ("AuthContext", "AppContext"):
            if re.search(rf"\bconst\s+{context_name}\s*=\s*createContext\b", code) and not re.search(
                rf"\bexport\s+const\s+{context_name}\b", code
            ):
                code = re.sub(rf"\bconst\s+{context_name}\b", f"export const {context_name}", code, count=1)

        if "axios.create" in code and re.search(r"\bconst\s+api\s*=", code) and not re.search(r"\bexport\s+const\s+api\b", code):
            code = re.sub(r"\bconst\s+api\s*=", "export const api =", code, count=1)
        if Path(filename).as_posix().lower().endswith("csvhandler.js"):
            code = WriteCode._normalize_csv_handler_commonjs_export(code)
        if Path(filename).as_posix().lower().endswith("csvhelper.js"):
            code = WriteCode._normalize_csv_helper_commonjs_export(code)
        return code

    @staticmethod
    def _normalize_csv_handler_commonjs_export(code: str) -> str:
        if not re.search(r"\bclass\s+CSVHandler\b", code):
            return code
        if re.search(r"module\.exports\.CSVHandler\s*=", code):
            return code
        return re.sub(
            r"module\.exports\s*=\s*CSVHandler\s*;?",
            "module.exports = CSVHandler;\nmodule.exports.CSVHandler = CSVHandler;",
            code,
            count=1,
        )

    @staticmethod
    def _normalize_csv_helper_commonjs_export(code: str) -> str:
        if not re.search(r"\bmodule\.exports\s*=", code):
            return code
        if re.search(r"module\.exports\.CSVHelper\s*=", code):
            return code
        if not re.search(r"\b(readCSV|writeCSV|appendCSV|updateCSV)\b", code):
            return code
        return code.rstrip() + "\nmodule.exports.CSVHelper = module.exports;\n"

    @staticmethod
    def _strip_markdown_code_wrapper(code: str) -> str:
        """Recover raw source if the model returned a markdown section despite the prompt."""
        if "```" not in code:
            return code
        matches = re.findall(r"```(?:[a-z0-9_+-]+)?\s*\n(.*?)\n```", code, flags=re.DOTALL | re.IGNORECASE)
        if matches:
            code = max(matches, key=len).strip()
        lines = code.splitlines()
        while lines and (not lines[0].strip() or lines[0].lstrip().startswith("##")):
            lines.pop(0)
        cleaned = [line for line in lines if not line.strip().startswith("```")]
        return "\n".join(cleaned).strip() + ("\n" if cleaned else "")

    @staticmethod
    def _get_int_env(name: str, default: int) -> int:
        value = os.getenv(name)
        if not value:
            return default
        try:
            parsed = int(value)
        except ValueError:
            logger.warning(f"Invalid {name}={value!r}, fallback to {default}")
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _rank_legacy_file(filename: str, exclude: str) -> tuple[int, str]:
        normalized = Path(filename).as_posix().lower()
        target = Path(exclude).as_posix().lower()
        target_parent = Path(target).parent.as_posix()
        source_parent = Path(normalized).parent.as_posix()

        if normalized == target:
            return (0, normalized)
        if source_parent == target_parent:
            return (10, normalized)

        shared_files = {
            "package.json",
            "vite.config.js",
            "src/app.jsx",
            "src/main.jsx",
            "src/theme.js",
            "src/services/api.js",
            "server/index.js",
            "server/database.js",
        }
        if normalized in shared_files:
            return (20, normalized)

        if target.startswith("server/") and normalized.startswith("server/"):
            if "/models/" in normalized or "/routes/" in normalized or "/mock/" in normalized:
                return (30, normalized)
            return (40, normalized)

        if target.startswith("src/") and normalized.startswith("src/"):
            if "/services/" in normalized or "/hooks/" in normalized or "/components/" in normalized:
                return (30, normalized)
            return (40, normalized)

        return (90, normalized)

    @staticmethod
    def _truncate_legacy_content(content: str, filename: str, max_chars: int) -> str:
        if len(content) <= max_chars:
            return content
        head = max_chars // 2
        tail = max_chars - head
        return (
            content[:head]
            + f"\n\n... <MetaGPT omitted middle of {filename} to keep WriteCode prompt within budget> ...\n\n"
            + content[-tail:]
        )

    @classmethod
    def _select_legacy_files(cls, filenames: list[str], exclude: str, use_inc: bool) -> list[str]:
        max_files = cls._get_int_env("METAGPT_MAX_LEGACY_CODE_FILES", DEFAULT_MAX_LEGACY_CODE_FILES)
        unique_filenames = list(dict.fromkeys(filenames))
        if use_inc and exclude in unique_filenames:
            unique_filenames.remove(exclude)
            unique_filenames.insert(0, exclude)
        ranked = sorted(unique_filenames, key=lambda item: cls._rank_legacy_file(item, exclude))
        return ranked[:max_files]

    @staticmethod
    async def get_codes(task_doc: Document, exclude: str, project_repo: ProjectRepo, use_inc: bool = False) -> str:
        """
        Get codes for generating the exclude file in various scenarios.

        Attributes:
            task_doc (Document): Document object of the task file.
            exclude (str): The file to be generated. Specifies the filename to be excluded from the code snippets.
            project_repo (ProjectRepo): ProjectRepo object of the project.
            use_inc (bool): Indicates whether the scenario involves incremental development. Defaults to False.

        Returns:
            str: Codes for generating the exclude file.
        """
        if not task_doc:
            return ""
        if not task_doc.content:
            task_doc = project_repo.docs.task.get(filename=task_doc.filename)
        m = json.loads(task_doc.content)
        code_filenames = m.get(TASK_LIST.key, []) if not use_inc else m.get(REFINED_TASK_LIST.key, [])
        codes = []
        max_total_chars = WriteCode._get_int_env(
            "METAGPT_MAX_LEGACY_CODE_CHARS", DEFAULT_MAX_LEGACY_CODE_CHARS
        )
        max_file_chars = WriteCode._get_int_env(
            "METAGPT_MAX_SINGLE_LEGACY_FILE_CHARS", DEFAULT_MAX_SINGLE_LEGACY_FILE_CHARS
        )
        src_file_repo = project_repo.srcs
        # Incremental development scenario
        if use_inc:
            selected_filenames = WriteCode._select_legacy_files(src_file_repo.all_files, exclude, use_inc=True)
            for filename in selected_filenames:
                code_block_type = get_markdown_code_block_type(filename)
                # Exclude the current file from the all code snippets
                if filename == exclude:
                    # If the file is in the old workspace, use the old code
                    # Exclude unnecessary code to maintain a clean and focused main.py file, ensuring only relevant and
                    # essential functionality is included for the project’s requirements
                    if filename != "main.py":
                        # Use old code
                        doc = await src_file_repo.get(filename=filename)
                    # If the file is in the src workspace, skip it
                    else:
                        continue
                    content = WriteCode._truncate_legacy_content(doc.content, filename, max_file_chars)
                    codes.insert(
                        0, f"### The name of file to rewrite: `{filename}`\n```{code_block_type}\n{content}```\n"
                    )
                    logger.info(f"Prepare to rewrite `{filename}`")
                # The code snippets are generated from the src workspace
                else:
                    doc = await src_file_repo.get(filename=filename)
                    # If the file does not exist in the src workspace, skip it
                    if not doc:
                        continue
                    content = WriteCode._truncate_legacy_content(doc.content, filename, max_file_chars)
                    codes.append(f"### File Name: `{filename}`\n```{code_block_type}\n{content}```\n\n")

        # Normal scenario
        else:
            selected_filenames = WriteCode._select_legacy_files(code_filenames, exclude, use_inc=False)
            for filename in selected_filenames:
                # Exclude the current file to get the code snippets for generating the current file
                if filename == exclude:
                    continue
                doc = await src_file_repo.get(filename=filename)
                if not doc:
                    continue
                code_block_type = get_markdown_code_block_type(filename)
                content = WriteCode._truncate_legacy_content(doc.content, filename, max_file_chars)
                codes.append(f"### File Name: `{filename}`\n```{code_block_type}\n{content}```\n\n")

        joined = "\n".join(codes)
        if len(joined) > max_total_chars:
            logger.info(
                f"Legacy code context for {exclude} trimmed from {len(joined)} to {max_total_chars} characters"
            )
            joined = joined[:max_total_chars] + "\n\n... <MetaGPT omitted remaining legacy files> ...\n"
        logger.info(
            f"Prepared {len(codes)} legacy code snippets for {exclude}, prompt code context chars={len(joined)}"
        )
        return joined
