"""
Ready-made settings for popular AI providers (used by the GUI "พรีเซ็ต" dropdown).

Every value was checked against the provider's official docs (see `source`, checked 2026-10-18).
Model names change often: they are only *editable defaults* - pick any model your account has.
The user always types their own API key; it is stored in .env, never in config.yaml.
"""
from __future__ import annotations

import copy
from typing import Any

ANTHROPIC_BODY = {
    "model": "{model}",
    "max_tokens": "{max_tokens}",
    "system": "{system_prompt}",
    "messages": [{"role": "user", "content": "{prompt}"}],
}

PRESETS: list[dict[str, Any]] = [
    {
        "id": "openai", "label": "OpenAI (ChatGPT)", "name": "openai",
        "cfg": {"type": "openai-compatible", "url": "https://api.openai.com/v1", "model": "gpt-5.5",
                "auth_type": "bearer", "description": "OpenAI Chat Completions"},
        "key_url": "https://platform.openai.com/api-keys",
        "note": "ต้องมี API key จาก platform.openai.com • รุ่น (model) เปลี่ยนได้ เช่น gpt-5.4-mini",
        "source": "https://platform.openai.com/docs/api-reference/chat/create",
    },
    {
        "id": "anthropic", "label": "Anthropic (Claude)", "name": "claude",
        "cfg": {"type": "http", "url": "https://api.anthropic.com/v1/messages", "method": "POST",
                "auth_type": "header", "auth_header": "x-api-key",
                "headers": {"anthropic-version": "2023-06-01"},
                "model": "claude-sonnet-5-5", "max_tokens": 4096,
                "body_template": copy.deepcopy(ANTHROPIC_BODY),
                "response_path": "content[0].text", "description": "Anthropic Messages API"},
        "key_url": "https://console.anthropic.com/settings/keys",
        "note": "ใช้ Messages API (ไม่ใช่รูปแบบ OpenAI) — header anthropic-version และ max_tokens จำเป็น "
                "• รุ่นอื่น: claude-opus-5-5, claude-haiku-5-5",
        "source": "https://docs.anthropic.com/en/api/messages",
    },
    {
        "id": "gemini", "label": "Google Gemini", "name": "gemini",
        "cfg": {"type": "openai-compatible", "url": "https://generativelanguage.googleapis.com/v1beta/openai",
                "model": "gemini-3.8-flash", "auth_type": "bearer",
                "description": "Google Gemini (OpenAI-compatible endpoint)"},
        "key_url": "https://aistudio.google.com/apikey",
        "note": "ใช้ endpoint แบบ OpenAI-compatible ของ Gemini • ขอกุญแจฟรีได้ที่ Google AI Studio",
        "source": "https://ai.google.dev/gemini-api/docs/openai",
    },
    {
        "id": "openrouter", "label": "OpenRouter (รวมหลายเจ้า)", "name": "openrouter",
        "cfg": {"type": "openai-compatible", "url": "https://openrouter.ai/api/v1",
                "model": "~openai/gpt-sol-latest", "auth_type": "bearer",
                "headers": {"X-OpenRouter-Title": "AI Agent Router"},
                "description": "OpenRouter"},
        "key_url": "https://openrouter.ai/settings/keys",
        "note": "model ตัวอย่างนำมาจากเอกสาร OpenRouter — แนะนำให้เปลี่ยนเป็นรุ่นที่ต้องการจาก openrouter.ai/models "
                "(รูปแบบ ผู้ให้บริการ/รุ่น)",
        "source": "https://openrouter.ai/docs/quickstart",
    },
    {
        "id": "groq", "label": "Groq", "name": "groq",
        "cfg": {"type": "openai-compatible", "url": "https://api.groq.com/openai/v1",
                "model": "llama-3.3-70b-versatile", "auth_type": "bearer", "description": "Groq (fast inference)"},
        "key_url": "https://console.groq.com/keys",
        "note": "รุ่นอื่น: openai/gpt-oss-120b, llama-3.1-8b-instant",
        "source": "https://console.groq.com/docs/openai",
    },
    {
        "id": "ollama", "label": "Ollama (ในเครื่อง)", "name": "ollama",
        "cfg": {"type": "openai-compatible", "url": "http://localhost:11434/v1", "model": "gpt-oss:20b",
                "auth_type": "none", "timeout": 600, "description": "Ollama on this computer"},
        "key_url": "",
        "note": "ไม่ต้องใช้กุญแจ • ต้องเปิด Ollama และโหลดรุ่นไว้ก่อน (ollama pull <ชื่อรุ่น>) "
                "แล้วใส่ชื่อรุ่นให้ตรง",
        "source": "https://docs.ollama.com/api/openai-compatibility",
    },
    {
        "id": "lmstudio", "label": "LM Studio (ในเครื่อง)", "name": "lmstudio",
        "cfg": {"type": "openai-compatible", "url": "http://localhost:1234/v1", "model": "",
                "auth_type": "none", "timeout": 600, "description": "LM Studio local server"},
        "key_url": "",
        "note": "ไม่ต้องใช้กุญแจ • เปิด Developer → Start Server ใน LM Studio แล้วใส่ model ให้ตรงกับ "
                "identifier ของรุ่นที่โหลดไว้ (ช่อง model ต้องกรอกเอง)",
        "source": "https://lmstudio.ai/docs/developer/openai-compat",
    },
    {
        "id": "xai", "label": "xAI (Grok)", "name": "xai",
        "cfg": {"type": "openai-compatible", "url": "https://api.x.ai/v1", "model": "grok-4.7",
                "auth_type": "bearer", "description": "xAI Grok"},
        "key_url": "https://console.x.ai/",
        "note": "ชื่อนี้ใช้กุญแจ XAI_API_KEY ตัวเดียวกับช่อง \"กุญแจ xAI\" • รุ่นอื่น: grok-4.6",
        "source": "https://docs.x.ai/docs/models",
    },
    {
        "id": "http", "label": "HTTP ทั่วไป / Webhook (กำหนดเอง)", "name": "my-agent",
        "cfg": {"type": "http", "url": "", "method": "POST", "auth_type": "none",
                "description": "Custom HTTP endpoint"},
        "key_url": "",
        "note": "ส่ง JSON {message, context, from_agent, target} ไปที่ URL — หรือกำหนดรูปแบบเองใน Body template",
        "source": "",
    },
]


def get_preset(preset_id: str) -> dict[str, Any] | None:
    for p in PRESETS:
        if p["id"] == preset_id:
            return copy.deepcopy(p)
    return None
