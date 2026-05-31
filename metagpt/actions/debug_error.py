#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/5/11 17:46
@Author  : alexanderwu
@File    : debug_error.py
@Modified By: mashenquan, 2023/11/27.
        1. Divide the context into three components: legacy code, unit test code, and console log.
        2. According to Section 2.2.3.1 of RFC 135, replace file data in the message with the file name.
"""
import os
import re
from typing import Optional

from pydantic import BaseModel, Field

from metagpt.actions.action import Action
from metagpt.configs.llm_config import LLMConfig, LLMType
from metagpt.logs import logger
from metagpt.provider.llm_provider_registry import create_llm_instance
from metagpt.schema import RunCodeContext, RunCodeResult
from metagpt.utils.common import CodeParser
from metagpt.utils.project_repo import ProjectRepo
from metagpt.actions.write_test import (
    build_minimal_node_source_contract_test,
    get_test_profile,
    normalize_test_code,
    sanitize_python_code,
)

DEFAULT_ADVANCED_DEBUG_MODEL = "claude-opus-4-8"
DEFAULT_ADVANCED_DEBUG_BASE_URL = "https://api.xstx.info"

PROMPT_TEMPLATE = """
NOTICE
1. Role: You are the QA engineer repairing a failing generated test.
2. Task: Rewrite ONLY the unit test file shown in "# Unit Test Code".
3. Do NOT rewrite the application source file from "# Legacy Code". Use it only as reference.
4. The corrected test must be executable from the project workspace with the same test command. For JavaScript/TypeScript projects, use CommonJS plus node:test/assert/strict and source-contract tests when the source is JSX/TSX/ESM/browser code.
5. Prefer behavior-relevant, whitespace-tolerant assertions. Do not fail only because imports, labels, classes, hooks, or JSX props are formatted differently or implemented with a different but equivalent structure.
Attention: Return raw test code only for the test file. Do not include markdown headings, explanations, or ``` fences.
The message is as follows:
# Legacy Code
```{source_code_block_type}
{code}
```
---
# Unit Test Code
```{test_code_block_type}
{test_code}
```
---
# Console logs
```text
{logs}
```
---
Now you should start rewriting the code:
Write the corrected file content. Do your best to implement THIS IN ONLY ONE FILE. Return raw executable code only.
"""


class DebugError(Action):
    i_context: RunCodeContext = Field(default_factory=RunCodeContext)
    repo: Optional[ProjectRepo] = Field(default=None, exclude=True)
    input_args: Optional[BaseModel] = Field(default=None, exclude=True)
    use_advanced_model: bool = False

    def _build_advanced_llm(self):
        api_key = self._advanced_api_key()
        if not api_key:
            logger.warning("Advanced DebugError requested but no advanced API key was configured; using primary LLM.")
            return self.llm

        config = LLMConfig(
            api_type=LLMType.OPENAI,
            api_key=api_key,
            base_url=os.getenv("METAGPT_ADVANCED_BASE_URL", DEFAULT_ADVANCED_DEBUG_BASE_URL),
            model=os.getenv("METAGPT_ADVANCED_MODEL", DEFAULT_ADVANCED_DEBUG_MODEL),
            max_token=int(os.getenv("METAGPT_ADVANCED_MAX_TOKEN", os.getenv("METAGPT_MAX_TOKEN", "12000"))),
            temperature=float(os.getenv("METAGPT_ADVANCED_TEMPERATURE", "0")),
            stream=os.getenv("METAGPT_ADVANCED_STREAM", "true").lower() != "false",
        )
        llm = create_llm_instance(config)
        llm.cost_manager = self.llm.cost_manager
        return llm

    @staticmethod
    def _advanced_api_key():
        return (
            os.getenv("METAGPT_ADVANCED_API_KEY")
            or os.getenv("AGENTDEV_ADVANCED_API_KEY")
            or os.getenv("OPENAI_ADVANCED_API_KEY")
        )

    async def run(self, *args, **kwargs) -> str:
        output_doc = await self.repo.test_outputs.get(filename=self.i_context.output_filename)
        if not output_doc:
            return ""
        output_detail = RunCodeResult.loads(output_doc.content)
        pattern = r"Ran (\d+) tests in ([\d.]+)s\n\nOK"
        matches = re.search(pattern, output_detail.stderr)
        if matches:
            return ""

        if self.use_advanced_model:
            logger.info(
                f"Debug and rewrite {self.i_context.test_filename} with advanced model "
                f"{os.getenv('METAGPT_ADVANCED_MODEL', DEFAULT_ADVANCED_DEBUG_MODEL)}"
            )
        else:
            logger.info(f"Debug and rewrite {self.i_context.test_filename}")
        code_doc = await self.repo.srcs.get(filename=self.i_context.code_filename)
        if not code_doc:
            return ""
        test_doc = await self.repo.tests.get(filename=self.i_context.test_filename)
        if not test_doc:
            return ""
        if self.use_advanced_model and not self._advanced_api_key():
            logger.warning(
                f"{self.i_context.test_filename} repeatedly failed but no advanced model key is configured; "
                "using a conservative source-contract test fallback."
            )
            return build_minimal_node_source_contract_test(code_doc.root_relative_path.replace("\\", "/"))
        source_profile = get_test_profile(self.i_context.code_filename)
        test_profile = get_test_profile(self.i_context.test_filename)
        prompt = PROMPT_TEMPLATE.format(
            code=code_doc.content,
            test_code=test_doc.content,
            logs=output_detail.stderr,
            source_code_block_type=source_profile.code_block_type,
            test_code_block_type=test_profile.code_block_type,
        )

        llm = self._build_advanced_llm() if self.use_advanced_model else self.llm
        rsp = await llm.aask(prompt)
        code = CodeParser.parse_code(text=rsp)

        normalized = normalize_test_code(
            sanitize_python_code(code),
            self.i_context.test_filename,
            code_doc.root_relative_path.replace("\\", "/"),
        )
        return self._guard_test_rewrite(normalized, code_doc.root_relative_path.replace("\\", "/"))

    def _guard_test_rewrite(self, code: str, source_relative_path: str) -> str:
        suffix = os.path.splitext(self.i_context.test_filename)[1].lower()
        if suffix not in {".js", ".cjs", ".mjs"}:
            return code
        looks_like_node_test = "node:test" in code or "require('test')" in code or 'require("test")' in code
        if looks_like_node_test:
            return code
        logger.warning(
            f"DebugError returned non-test code for {self.i_context.test_filename}; "
            "falling back to a minimal source-contract test."
        )
        return build_minimal_node_source_contract_test(source_relative_path)
