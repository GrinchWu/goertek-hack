#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/12/14 15:28
@Author  : alexanderwu
@File    : project_management_an.py
"""
from typing import List, Optional

from metagpt.actions.action_node import ActionNode

REQUIRED_PACKAGES = ActionNode(
    key="Required packages",
    expected_type=Optional[List[str]],
    instruction="Provide required packages The response language should correspond to the context and requirements.",
    example=["flask==1.1.2", "bcrypt==3.2.0"],
)

REQUIRED_OTHER_LANGUAGE_PACKAGES = ActionNode(
    key="Required Other language third-party packages",
    expected_type=List[str],
    instruction="List down the required packages for languages other than Python.",
    example=["No third-party dependencies required"],
)

LOGIC_ANALYSIS = ActionNode(
    key="Logic Analysis",
    expected_type=List[List[str]],
    instruction="Provide a list of files with the classes/methods/functions to be implemented, "
    "including dependency analysis and imports."
    "Ensure consistency between System Design and Logic Analysis; the files must match exactly. "
    "For full-stack web applications, include all files needed to install and run the generated project, including "
    "backend and frontend package manifests, Vite/Tailwind/PostCSS configs when applicable, entry points, Tailwind "
    "CSS entry files such as `frontend/src/index.css`, route files, "
    "data seed files, and shared API utilities. Ensure JavaScript module format is consistent: Vite frontend packages "
    "that use ESM configs must include `type: module`, otherwise configs must be CommonJS. "
    "If the file is written in Vue or React, use Tailwind CSS for styling. "
    "For frontend projects, plan a complete operational interface rather than a landing page: include routing, "
    "navigation, form validation, loading and error states, empty states, admin views when required, responsive "
    "layouts, and a consistent design system. Avoid mixing multiple UI frameworks unless the requirement explicitly "
    "asks for it. Never mark required behavior as demo-only, placeholder, TODO, simplified, or future work; authentication, "
    "admin/user flows, CSV persistence, and required third-party-system simulations must be implemented as working local code.",
    example=[
        ["game.py", "Contains Game class and ... functions"],
        ["main.py", "Contains main function, from game import Game"],
    ],
)

REFINED_LOGIC_ANALYSIS = ActionNode(
    key="Refined Logic Analysis",
    expected_type=List[List[str]],
    instruction="Review and refine the logic analysis by merging the Legacy Content and Incremental Content. "
    "Provide a comprehensive list of files with classes/methods/functions to be implemented or modified incrementally. "
    "Include dependency analysis, consider potential impacts on existing code, and document necessary imports. "
    "For full-stack web applications, preserve the chosen `backend/` plus `frontend/` structure and include all "
    "runtime manifests/configuration/seed-data files needed to install and run the system. "
    "For frontend projects, keep the UI architecture consistent with the existing stack and preserve complete "
    "operational screens, responsive states, validation states, loading states, and admin/user workflows. "
    "Do not downgrade any required feature to demo-only, placeholder, TODO, simplified, or future work.",
    example=[
        ["game.py", "Contains Game class and ... functions"],
        ["main.py", "Contains main function, from game import Game"],
        ["new_feature.py", "Introduces NewFeature class and related functions"],
        ["utils.py", "Modifies existing utility functions to support incremental changes"],
    ],
)

TASK_LIST = ActionNode(
    key="Task list",
    expected_type=List[str],
    instruction="Break down the tasks into a list of filenames, prioritized by dependency order. The task list must "
    "match Logic Analysis exactly and include install/runtime files such as package.json files, Vite/Tailwind/PostCSS "
    "configs, server entry points, frontend entry points, and CSV seed data when the architecture needs them. Use one "
    "architecture only; for a full-stack web app prefer `backend/...` and `frontend/...` paths and do not add duplicate "
    "root-level source stacks.",
    example=["game.py", "main.py"],
)

REFINED_TASK_LIST = ActionNode(
    key="Refined Task list",
    expected_type=List[str],
    instruction="Review and refine the combined task list after the merger of Legacy Content and Incremental Content, "
    "and consistent with Refined File List. Ensure that tasks are organized in a logical and prioritized order, "
    "considering dependencies for a streamlined and efficient development process. Keep install/runtime manifests, "
    "configuration files, entry points, and seed data in the list. Remove duplicate competing architecture paths. ",
    example=["new_feature.py", "utils", "game.py", "main.py"],
)

FULL_API_SPEC = ActionNode(
    key="Full API spec",
    expected_type=str,
    instruction="Describe all APIs using OpenAPI 3.0 spec that may be used by both frontend and backend. If front-end "
    "and back-end communication is not required, leave it blank.",
    example="openapi: 3.0.0 ...",
)

SHARED_KNOWLEDGE = ActionNode(
    key="Shared Knowledge",
    expected_type=str,
    instruction="Detail any shared knowledge, like common utility functions or configuration variables.",
    example="`game.py` contains functions shared across the project.",
)

REFINED_SHARED_KNOWLEDGE = ActionNode(
    key="Refined Shared Knowledge",
    expected_type=str,
    instruction="Update and expand shared knowledge to reflect any new elements introduced. This includes common "
    "utility functions, configuration variables for team collaboration. Retain content that is not related to "
    "incremental development but important for consistency and clarity.",
    example="`new_module.py` enhances shared utility functions for improved code reusability and collaboration.",
)


ANYTHING_UNCLEAR_PM = ActionNode(
    key="Anything UNCLEAR",
    expected_type=str,
    instruction="Mention any unclear aspects in the project management context and try to clarify them.",
    example="Clarification needed on how to start and initialize third-party libraries.",
)

NODES = [
    REQUIRED_PACKAGES,
    REQUIRED_OTHER_LANGUAGE_PACKAGES,
    LOGIC_ANALYSIS,
    TASK_LIST,
    FULL_API_SPEC,
    SHARED_KNOWLEDGE,
    ANYTHING_UNCLEAR_PM,
]

REFINED_NODES = [
    REQUIRED_PACKAGES,
    REQUIRED_OTHER_LANGUAGE_PACKAGES,
    REFINED_LOGIC_ANALYSIS,
    REFINED_TASK_LIST,
    FULL_API_SPEC,
    REFINED_SHARED_KNOWLEDGE,
    ANYTHING_UNCLEAR_PM,
]

PM_NODE = ActionNode.from_children("PM_NODE", NODES)
REFINED_PM_NODE = ActionNode.from_children("REFINED_PM_NODE", REFINED_NODES)
