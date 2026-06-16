"""
Scripting Agent
Generates structured short video scripts from a topic using local Ollama (preferred) or OpenAI-compatible endpoints.
Cheap, fast, private by default.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests
import yaml
from pydantic import BaseModel, Field, ValidationError


class Scene(BaseModel):
    id: int
    narration: str = Field(..., min_length=5, max_length=400)
    image_prompt: str = Field(..., min_length=20)
    duration_hint_sec: float = Field(..., ge=1.5, le=12.0)
    notes: str = ""


class VideoScript(BaseModel):
    title: str = Field(..., min_length=5, max_length=120)
    hook: str
    overall_style: str = Field(..., min_length=10)
    music_suggestion: str = ""
    scenes: list[Scene] = Field(..., min_items=3, max_items=12)


class ScriptAgent:
    def __init__(self, config_path: str | Path = "config.yaml"):
        self.config_path = Path(config_path)
        self.cfg = self._load_config()
        self.provider = self.cfg.get("scripting", {}).get("provider", "ollama")

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            # Fall back to example if no config yet (dev convenience)
            example = self.config_path.parent / "config.example.yaml"
            if example.exists():
                with open(example) as f:
                    return yaml.safe_load(f) or {}
            return {}
        with open(self.config_path) as f:
            return yaml.safe_load(f) or {}

    def _get_scripting_cfg(self) -> dict:
        return self.cfg.get("scripting", {})

    def generate(self, topic: str, max_retries: int = 2) -> VideoScript:
        """
        Generate a VideoScript for the given topic.
        """
        system_prompt = self._load_system_prompt()
        user_prompt = f"Create an engaging short vertical video script about:\n{topic}\n\nRemember: output ONLY valid JSON matching the exact schema."

        raw = self._call_llm(system_prompt, user_prompt, max_retries=max_retries)
        script = self._parse_and_validate(raw)
        return script

    def _load_system_prompt(self) -> str:
        prompt_path = Path(__file__).parent.parent / "prompts" / "script_system.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        # Fallback minimal prompt
        return "You are an expert short video scriptwriter. Output ONLY valid JSON for a vertical short script following the schema in the instructions."

    def _call_llm(self, system: str, user: str, max_retries: int = 2) -> str:
        scripting = self._get_scripting_cfg()
        provider = self.provider

        if provider == "ollama":
            return self._call_ollama(scripting, system, user, max_retries)
        elif provider == "openai_compatible":
            return self._call_openai_compatible(scripting, system, user, max_retries)
        else:
            raise ValueError(f"Unknown scripting provider: {provider}")

    def _call_ollama(self, scripting_cfg: dict, system: str, user: str, max_retries: int) -> str:
        ollama_cfg = scripting_cfg.get("ollama", {})
        base_url = ollama_cfg.get("base_url", "http://localhost:11434").rstrip("/")
        model = ollama_cfg.get("model", "qwen2.5:7b-instruct")
        temperature = ollama_cfg.get("temperature", 0.7)
        timeout = ollama_cfg.get("timeout", 120)

        url = f"{base_url}/api/chat"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(url, json=payload, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                return content.strip()
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    continue
        raise RuntimeError(f"Ollama call failed after retries: {last_err}")

    def _call_openai_compatible(self, scripting_cfg: dict, system: str, user: str, max_retries: int) -> str:
        oc = scripting_cfg.get("openai_compatible", {})
        base_url = oc.get("base_url", "https://api.openai.com/v1").rstrip("/")
        api_key = oc.get("api_key") or os.environ.get("OPENAI_API_KEY") or ""
        model = oc.get("model", "gpt-4o-mini")
        temperature = oc.get("temperature", 0.7)

        if not api_key:
            # Try to read from ${VAR} style in yaml (very basic)
            api_key = self._resolve_env_var(oc.get("api_key", ""))

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        url = f"{base_url}/chat/completions"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": False,
        }

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=120)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content.strip()
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    continue
        raise RuntimeError(f"OpenAI-compatible call failed: {last_err}")

    def _resolve_env_var(self, val: str) -> str:
        if not val or not isinstance(val, str):
            return val
        m = re.match(r"\$\{(.+)\}", val)
        if m:
            return os.environ.get(m.group(1), "")
        return val

    def _parse_and_validate(self, raw: str) -> VideoScript:
        # Try to extract the first JSON object if the model added extra text
        raw = raw.strip()
        if raw.startswith("```"):
            # strip common code fences
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()

        # Find the first { ... } block
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = raw[start : end + 1]
        else:
            candidate = raw

        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON from LLM response. Raw snippet: {raw[:300]}...") from e

        try:
            script = VideoScript.model_validate(data)
        except ValidationError as e:
            # One more rescue attempt: sometimes models use "scenes" with slightly different keys
            raise ValueError(f"Script JSON did not match expected schema: {e}\nData: {data}") from e

        # Light post-processing / normalization
        for i, scene in enumerate(script.scenes):
            scene.id = i + 1  # enforce sequential ids
            scene.narration = scene.narration.strip()
            scene.image_prompt = scene.image_prompt.strip()

        return script

    def save_script(self, script: VideoScript, out_path: str | Path) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(script.model_dump(), f, indent=2, ensure_ascii=False)
        return out_path
