#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/12/26
@Author  : mannaandpoem
@File    : write_code_plan_and_change_an.py
"""
from typing import List, Optional

from pydantic import BaseModel, Field

from metagpt.actions.action import Action
from metagpt.actions.action_node import ActionNode
from metagpt.logs import logger
from metagpt.schema import CodePlanAndChangeContext, Document
from metagpt.utils.common import get_markdown_code_block_type
from metagpt.utils.project_repo import ProjectRepo

DEVELOPMENT_PLAN = ActionNode(
    key="Development Plan",
    expected_type=List[str],
    instruction="Develop a comprehensive and step-by-step incremental development plan, providing the detail "
    "changes to be implemented at each step based on the order of 'Task List'",
    example=[
        "Enhance the functionality of `calculator.py` by extending it to incorporate methods for subtraction, ...",
        "Update the existing codebase in main.py to incorporate new API endpoints for subtraction, ...",
    ],
)

INCREMENTAL_CHANGE = ActionNode(
    key="Incremental Change",
    expected_type=List[str],
    instruction="Write a concise file-level incremental change summary based on the context. "
    "Do NOT output complete source code, code blocks, or git diff patches. "
    "Each item must be a short sentence with the target file path, change type, and change summary only. "
    "The later WriteCode action will generate or rewrite each file.",
    example=[
        "calculator.py: rename subtraction method and add complete arithmetic operation behavior.",
        "main.py: add API routes for subtraction, multiplication, and division with validation.",
    ],
)

CODE_PLAN_AND_CHANGE_CONTEXT = """
## User New Requirements
{requirement}

## Issue
{issue}

## PRD
{prd}

## Design
{design}

## Task
{task}

## Legacy Code
{code}
"""

REFINED_TEMPLATE = """
NOTICE
Role: You are a professional engineer; The main goal is to complete incremental development by combining legacy code and plan and Incremental Change, ensuring the integration of new features.

# Context
## User New Requirements
{user_requirement}

## Code Plan And Change
{code_plan_and_change}

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

# Instruction: Based on the context, follow "Format example", write or rewrite code.
## Write/Rewrite Code: Only write one file {filename}, write or rewrite complete code using triple quotes based on the following attentions and context.
1. Only One file: do your best to implement THIS ONLY ONE FILE.
2. COMPLETE CODE: Your code will be part of the entire project, so please implement complete, reliable, reusable code snippets.
3. Set default value: If there is any setting, ALWAYS SET A DEFAULT VALUE, ALWAYS USE STRONG TYPE AND EXPLICIT VARIABLE. AVOID circular import.
4. Follow design: YOU MUST FOLLOW "Data structures and interfaces". DONT CHANGE ANY DESIGN. Do not use public member functions that do not exist in your design.
5. Follow Code Plan And Change: If there is any "Incremental Change" summary, implement the relevant change for "{filename}" according to the "Development Plan".
6. CAREFULLY CHECK THAT YOU DONT MISS ANY NECESSARY CLASS/FUNCTION IN THIS FILE.
7. Before using a external variable/module, make sure you import it first.
8. Write out EVERY CODE DETAIL, DON'T LEAVE TODO.
9. Attention: Retain details that are not related to incremental development but are important for maintaining the consistency and clarity of the old code.
"""

CODE_PLAN_AND_CHANGE = [DEVELOPMENT_PLAN, INCREMENTAL_CHANGE]

WRITE_CODE_PLAN_AND_CHANGE_NODE = ActionNode.from_children("WriteCodePlanAndChange", CODE_PLAN_AND_CHANGE)


class WriteCodePlanAndChange(Action):
    name: str = "WriteCodePlanAndChange"
    i_context: CodePlanAndChangeContext = Field(default_factory=CodePlanAndChangeContext)
    repo: Optional[ProjectRepo] = Field(default=None, exclude=True)
    input_args: Optional[BaseModel] = Field(default=None, exclude=True)

    async def run(self, *args, **kwargs):
        self.llm.system_prompt = "You are a professional software engineer, your primary responsibility is to "
        "craft concise incremental development plans and file-level change summaries without writing source code"
        prd_doc = await Document.load(filename=self.i_context.prd_filename)
        design_doc = await Document.load(filename=self.i_context.design_filename)
        task_doc = await Document.load(filename=self.i_context.task_filename)
        context = CODE_PLAN_AND_CHANGE_CONTEXT.format(
            requirement=f"```text\n{self.i_context.requirement}\n```",
            issue=f"```text\n{self.i_context.issue}\n```",
            prd=prd_doc.content,
            design=design_doc.content,
            task=task_doc.content,
            code=await self.get_old_codes(),
        )
        logger.info("Writing code plan and change..")
        return await WRITE_CODE_PLAN_AND_CHANGE_NODE.fill(req=context, llm=self.llm, schema="json")

    async def get_old_codes(self) -> str:
        old_codes = await self.repo.srcs.get_all()
        codes = [
            f"### File Name: `{code.filename}`\n```{get_markdown_code_block_type(code.filename)}\n{code.content}```\n"
            for code in old_codes
        ]
        return "\n".join(codes)
