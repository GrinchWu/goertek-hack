#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Probe whether a DeepSeek OpenAI-compatible model returns strict JSON.

The script intentionally does not read API keys from files. Configure with:

    $env:METAGPT_API_KEY="..."
    $env:METAGPT_BASE_URL="https://api.deepseek.com"
    $env:METAGPT_MODEL="deepseek-v4-flash"
    python scripts/test_deepseek_json_strict.py

It writes raw model outputs to .json_probe_outputs/ for later inspection.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
OUTPUT_DIR = Path(".json_probe_outputs")


@dataclass
class ProbeCase:
    name: str
    system: str
    user: str
    response_format: dict[str, str] | None = None
    stream: bool = False


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def extract_json_candidate(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start_obj = stripped.find("{")
    start_arr = stripped.find("[")
    starts = [i for i in [start_obj, start_arr] if i >= 0]
    if not starts:
        return stripped
    start = min(starts)
    end_obj = stripped.rfind("}")
    end_arr = stripped.rfind("]")
    end = max(end_obj, end_arr)
    if end <= start:
        return stripped[start:]
    return stripped[start : end + 1]


def validate_json(text: str) -> tuple[bool, Any | str, str]:
    candidate = extract_json_candidate(text)
    try:
        return True, json.loads(candidate), candidate
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", candidate


async def ask(
    client: AsyncOpenAI, case: ProbeCase, model: str, temperature: float, max_tokens: int
) -> tuple[str, dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": case.system},
            {"role": "user", "content": case.user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if case.response_format:
        kwargs["response_format"] = case.response_format

    if not case.stream:
        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        usage = response.usage.model_dump() if response.usage else None
        return choice.message.content or "", {"finish_reason": choice.finish_reason, "usage": usage}

    chunks: list[str] = []
    finish_reason = None
    stream = await client.chat.completions.create(**kwargs, stream=True)
    async for chunk in stream:
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        chunks.append(choice.delta.content or "")
        finish_reason = choice.finish_reason or finish_reason
    return "".join(chunks), {"finish_reason": finish_reason, "usage": None}


def build_cases() -> list[ProbeCase]:
    strict_system = (
        "You are a JSON generator. Return exactly one valid JSON object. "
        "No markdown fences, no comments, no trailing commas. "
        "Escape all double quotes inside string values."
    )
    complex_requirement = """
Original requirement:
- 管理员关闭预约时提示："当前园区暂不开放预约"
- 取消后状态同步为 "已取消" 或 "无效"
- 缴费成功提示："缴费成功，离厂时无需支付"
- 允许 emoji in source text: ✅ ⚠️ 🔍
- Return a design summary with long Chinese strings and nested arrays.
"""
    schema_request = """
Return JSON with this shape:
{
  "resources": [
    {
      "resource_type": "string",
      "value": "string",
      "description": "string"
    }
  ],
  "project_path": null,
  "reason": "string"
}
"""
    metagpt_style = """
[CONTENT]
{
  "Implementation approach": "Write a concise implementation approach",
  "File list": ["frontend/src/App.jsx", "backend/server.js"],
  "Data structures and interfaces": "classDiagram ...",
  "Program call flow": "sequenceDiagram ...",
  "Anything UNCLEAR": "string"
}
[/CONTENT]

Requirement:
Use CSV as database. Include strings containing Chinese quotes like "当前园区暂不开放预约".
Return only the JSON object inside [CONTENT], without the tags.
"""
    return [
        ProbeCase(
            name="simple_strict_json",
            system=strict_system,
            user='Return {"ok": true, "message": "hello", "items": [1, 2, 3]} with different values.',
        ),
        ProbeCase(
            name="complex_chinese_json",
            system=strict_system,
            user=complex_requirement + "\n" + schema_request,
        ),
        ProbeCase(
            name="metagpt_style_json",
            system=strict_system,
            user=metagpt_style,
        ),
        ProbeCase(
            name="complex_chinese_json_response_format",
            system=strict_system,
            user=complex_requirement + "\n" + schema_request,
            response_format={"type": "json_object"},
        ),
        ProbeCase(
            name="complex_chinese_json_stream",
            system=strict_system,
            user=complex_requirement + "\n" + schema_request,
            stream=True,
        ),
    ]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("METAGPT_MODEL") or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--base-url", default=os.getenv("METAGPT_BASE_URL") or os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=os.getenv("METAGPT_API_KEY") or os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=2500)
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("Missing METAGPT_API_KEY or OPENAI_API_KEY")

    client = AsyncOpenAI(api_key=args.api_key, base_url=args.base_url)
    OUTPUT_DIR.mkdir(exist_ok=True)

    cases = build_cases()
    summary: list[dict[str, Any]] = []
    for idx in range(args.repeat):
        for case in cases:
            label = f"{now_stamp()}_{idx + 1}_{case.name}"
            try:
                text, meta = await ask(client, case, args.model, args.temperature, args.max_tokens)
                ok, parsed_or_error, candidate = validate_json(text)
                raw_path = OUTPUT_DIR / f"{label}.raw.txt"
                candidate_path = OUTPUT_DIR / f"{label}.candidate.json"
                raw_path.write_text(text, encoding="utf-8")
                candidate_path.write_text(candidate, encoding="utf-8")
                summary.append(
                    {
                        "case": case.name,
                        "ok": ok,
                        "stream": case.stream,
                        "response_format": case.response_format,
                        "raw_path": str(raw_path),
                        "candidate_path": str(candidate_path),
                        "finish_reason": meta.get("finish_reason"),
                        "usage": meta.get("usage"),
                        "error": None if ok else parsed_or_error,
                    }
                )
                print(f"[{'PASS' if ok else 'FAIL'}] {case.name} -> {candidate_path}")
                if not ok:
                    print(f"       {parsed_or_error}")
            except Exception as exc:
                summary.append(
                    {
                        "case": case.name,
                        "ok": False,
                        "stream": case.stream,
                        "response_format": case.response_format,
                        "raw_path": None,
                        "candidate_path": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                print(f"[ERROR] {case.name} -> {type(exc).__name__}: {exc}")

    summary_path = OUTPUT_DIR / f"{now_stamp()}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(1 for item in summary if item["ok"])
    print(f"\nSummary: {passed}/{len(summary)} passed")
    print(f"Summary file: {summary_path}")
    return 0 if passed == len(summary) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
