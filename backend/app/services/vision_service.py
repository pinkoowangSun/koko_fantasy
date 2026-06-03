import base64
import json

from openai import AsyncOpenAI

from app.config import settings

_client = AsyncOpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
)

_MODEL = "deepseek-vl2"

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
    Analyze an image with DeepSeek-VL2 via the OpenAI-compatible API.
    Returns a dict with is_food=True and nutrition fields, or is_food=False and a reply.
    """
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    user_content = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        },
        {
            "type": "text",
            "text": f"Caption from user: {caption}" if caption else "Analyze this image.",
        },
    ]

    resp = await _client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=512,
    )

    raw = resp.choices[0].message.content.strip()

    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

    return json.loads(raw)
