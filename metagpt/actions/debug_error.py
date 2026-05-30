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
import re
from typing import Optional

from pydantic import BaseModel, Field

from metagpt.actions.action import Action
from metagpt.logs import logger
from metagpt.schema import RunCodeContext, RunCodeResult
from metagpt.utils.common import CodeParser
from metagpt.utils.project_repo import ProjectRepo
from metagpt.actions.write_test import get_test_profile, normalize_test_code, sanitize_python_code

PROMPT_TEMPLATE = """
NOTICE
1. Role: You are a Development Engineer or QA engineer;
2. Task: You received this message from another Development Engineer or QA engineer who ran or tested your code. 
Based on the message, first, figure out your own role, i.e. Engineer or QaEngineer,
then rewrite the development code or the test code based on your role, the error, and the summary, such that all bugs are fixed and the code performs well.
Attention: Return raw code only for the one file that must be rewritten. Do not include markdown headings,
explanations, or ``` fences.
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

    async def run(self, *args, **kwargs) -> str:
        output_doc = await self.repo.test_outputs.get(filename=self.i_context.output_filename)
        if not output_doc:
            return ""
        output_detail = RunCodeResult.loads(output_doc.content)
        pattern = r"Ran (\d+) tests in ([\d.]+)s\n\nOK"
        matches = re.search(pattern, output_detail.stderr)
        if matches:
            return ""

        logger.info(f"Debug and rewrite {self.i_context.test_filename}")
        code_doc = await self.repo.srcs.get(filename=self.i_context.code_filename)
        if not code_doc:
            return ""
        test_doc = await self.repo.tests.get(filename=self.i_context.test_filename)
        if not test_doc:
            return ""
        source_profile = get_test_profile(self.i_context.code_filename)
        test_profile = get_test_profile(self.i_context.test_filename)
        prompt = PROMPT_TEMPLATE.format(
            code=code_doc.content,
            test_code=test_doc.content,
            logs=output_detail.stderr,
            source_code_block_type=source_profile.code_block_type,
            test_code_block_type=test_profile.code_block_type,
        )

        rsp = await self._aask(prompt)
        code = CodeParser.parse_code(text=rsp)

        return normalize_test_code(
            sanitize_python_code(code),
            self.i_context.test_filename,
            code_doc.root_relative_path.replace("\\", "/"),
        )
