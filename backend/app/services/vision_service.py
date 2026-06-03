import base64
import json

import anthropic

from app.config import settings

_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

_SYSTEM_PROMPT = (
    "You are a nutrition analyst with vision capabilities. When shown an image:\n\n"
    "If it contains food or a meal, respond with ONLY this JSON (no markdown fences):\n"
    '{"is_food": true, "dish_name": "...", "calories_kcal": <number>, '
    '"protein_g": <number>, "carbs_g": <number>, "fat_g": <number>, '
    '"fiber_g": <number>, "notes": "brief note on portion size or confidence"}\n\n'
    "If it does NOT contain food, respond with ONLY this JSON:\n"
    '{"is_food": false, "reply": "your natural conversational response to the image"}\n\n'
    "For nutrition estimates assume a standard single-serving portion unless the image "
    "suggests otherwise. All numbers must be realistic integers or floats. "
    "Return valid JSON only — no explanation, no markdown."
)


async def analyze_image(image_bytes: bytes, caption: str = "") -> dict:
    """
    Analyze an image with Claude claude-sonnet-4-6 vision.
    Returns a dict with is_food=True and nutrition fields, or is_food=False and a reply.
    """
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    user_content: list[dict] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": b64,
            },
        },
        {
            "type": "text",
            "text": f"Caption from user: {caption}" if caption else "Analyze this image.",
        },
    ]

    msg = await _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = msg.content[0].text.strip()

    # Strip accidental markdown fences
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

    return json.loads(raw)
