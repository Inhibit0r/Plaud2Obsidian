from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any

import requests

from common import require_env


class LLMError(RuntimeError):
    pass


@dataclass
class LLMSettings:
    backend: str
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int
    temperature: float
    http_referer: str | None
    x_title: str | None
    codex_model: str | None
    codex_sandbox: str


def load_llm_settings() -> LLMSettings:
    backend = (os.getenv("LLM_BACKEND") or "openai_compatible").strip() or "openai_compatible"
    api_key = ""
    if backend == "openai_compatible":
        api_key = require_env("LLM_API_KEY", ["OPENAI_API_KEY"])
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    model = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL")
    if backend == "openai_compatible" and not model:
        raise LLMError("Missing LLM_MODEL (or OPENAI_MODEL).")
    return LLMSettings(
        backend=backend,
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model=model or "",
        timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
        http_referer=os.getenv("LLM_HTTP_REFERER") or None,
        x_title=os.getenv("LLM_X_TITLE") or None,
        codex_model=os.getenv("CODEX_MODEL") or None,
        codex_sandbox=(os.getenv("CODEX_SANDBOX") or "read-only").strip() or "read-only",
    )


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if fence_match:
        stripped = fence_match.group(1).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return json.loads(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError("LLM response does not contain a JSON object.")
    candidate = stripped[start : end + 1]
    return json.loads(candidate)


def _chat_json_via_openai_compatible(settings: LLMSettings, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    if not settings.api_key:
        raise LLMError("Missing API key for openai_compatible backend.")
    if not settings.model:
        raise LLMError("Missing model for openai_compatible backend.")
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }
    if settings.http_referer:
        headers["HTTP-Referer"] = settings.http_referer
    if settings.x_title:
        headers["X-Title"] = settings.x_title
    payload = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": settings.temperature,
    }
    try:
        response = requests.post(
            f"{settings.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=settings.timeout_seconds,
        )
    except requests.RequestException as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc

    if response.status_code >= 400:
        raise LLMError(f"LLM HTTP {response.status_code}: {response.text[:1000]}")

    data = response.json()
    try:
        message = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected LLM response shape: {data}") from exc
    text = _extract_text_content(message)
    return extract_json_object(text)


def _chat_json_via_codex_exec(settings: LLMSettings, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    prompt = system_prompt.strip() + "\n\n" + user_prompt.strip()
    with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", suffix=".txt", delete=False) as output_file:
        output_path = output_file.name
    command = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        settings.codex_sandbox,
        "--output-last-message",
        output_path,
        "-",
    ]
    if settings.codex_model:
        command.extend(["--model", settings.codex_model])
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=settings.timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LLMError("Codex CLI not found. Install it and run `codex login` first.") from exc
    except subprocess.TimeoutExpired as exc:
        raise LLMError(f"codex exec timed out after {settings.timeout_seconds}s") from exc

    try:
        with open(output_path, "r", encoding="utf-8") as handle:
            last_message = handle.read()
    finally:
        try:
            os.unlink(output_path)
        except OSError:
            pass

    if completed.returncode != 0:
        stderr_tail = completed.stderr[-1000:] if completed.stderr else ""
        stdout_tail = completed.stdout[-1000:] if completed.stdout else ""
        raise LLMError(
            "codex exec failed"
            + (f"; stderr: {stderr_tail}" if stderr_tail else "")
            + (f"; stdout: {stdout_tail}" if stdout_tail else "")
        )

    if not last_message.strip():
        raise LLMError("codex exec returned an empty final message.")
    return extract_json_object(last_message)


def chat_json(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    settings = load_llm_settings()
    if settings.backend == "openai_compatible":
        return _chat_json_via_openai_compatible(settings, system_prompt=system_prompt, user_prompt=user_prompt)
    if settings.backend == "codex_exec":
        return _chat_json_via_codex_exec(settings, system_prompt=system_prompt, user_prompt=user_prompt)
    raise LLMError(f"Unsupported LLM_BACKEND: {settings.backend}")

