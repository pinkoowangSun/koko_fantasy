"""
External tool implementations for the Koko AI agent.

Tools are exposed to the LLM as OpenAI-compatible function definitions and
executed on demand during the Phase-2 agentic loop.
"""
import ast
import asyncio
import math
import operator
import re
from typing import Any

import httpx
import yfinance as yf

from app.config import settings

# ── Tool schemas (OpenAI function-calling format) ─────────────────────────────

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information, news, facts, or anything "
                "that requires up-to-date knowledge beyond your training data. "
                "Use for recent events, current prices (non-stock), product info, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_price",
            "description": (
                "Get the live price, recent 5-day history, and key metrics for a stock "
                "or cryptocurrency. Use standard ticker symbols."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": (
                            "Ticker symbol. Stocks: AAPL, MSFT, TSLA, 9988.HK. "
                            "Crypto: BTC-USD, ETH-USD, SOL-USD."
                        ),
                    }
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather conditions and a 4-day forecast for any location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City or place name, e.g. 'Singapore', 'New York', 'Tokyo'",
                    }
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Evaluate a mathematical expression precisely. Supports arithmetic, "
                "percentages ('15% of 120'), powers, sqrt, log, trig functions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Expression to evaluate, e.g. '15% of 120', 'sqrt(144)', '2**10 / 3'",
                    }
                },
                "required": ["expression"],
            },
        },
    },
]


# ── Web search (Tavily) ───────────────────────────────────────────────────────

async def web_search(query: str) -> dict:
    if not settings.TAVILY_API_KEY:
        return {"error": "Web search is not configured (TAVILY_API_KEY not set)."}
    try:
        from tavily import AsyncTavilyClient
        client = AsyncTavilyClient(api_key=settings.TAVILY_API_KEY)
        result = await client.search(query, max_results=5, search_depth="basic")
        return {
            "query": query,
            "results": [
                {
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "snippet": (r.get("content") or "")[:400],
                }
                for r in result.get("results", [])
            ],
        }
    except Exception as exc:
        return {"error": f"Search failed: {exc}"}


# ── Stock / crypto prices (yfinance → Yahoo Finance) ─────────────────────────

def _fetch_stock_sync(symbol: str) -> dict:
    try:
        ticker = yf.Ticker(symbol)
        fast = ticker.fast_info
        hist = ticker.history(period="5d")

        price = getattr(fast, "last_price", None)
        prev_close = getattr(fast, "previous_close", None)
        market_cap = getattr(fast, "market_cap", None)
        currency = getattr(fast, "currency", "USD")

        change_pct = None
        if price and prev_close and prev_close > 0:
            change_pct = round((price - prev_close) / prev_close * 100, 2)

        recent: list[dict] = []
        if not hist.empty:
            for ts, row in hist.tail(5).iterrows():
                recent.append({
                    "date": str(ts.date()),
                    "close": round(float(row["Close"]), 4),
                    "volume": int(row.get("Volume", 0)),
                })

        return {
            "symbol": symbol.upper(),
            "currency": currency,
            "current_price": round(price, 4) if price else None,
            "previous_close": round(prev_close, 4) if prev_close else None,
            "change_pct_today": change_pct,
            "market_cap": market_cap,
            "recent_5d": recent,
        }
    except Exception as exc:
        return {"error": f"Could not fetch data for {symbol}: {exc}"}


async def get_stock_price(symbol: str) -> dict:
    return await asyncio.to_thread(_fetch_stock_sync, symbol.upper())


# ── Weather (Open-Meteo — free, no API key) ───────────────────────────────────

_WMO: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Rain showers", 81: "Moderate showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm + hail", 99: "Thunderstorm + heavy hail",
}


async def get_weather(location: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": location, "count": 1, "language": "en", "format": "json"},
            )
            geo.raise_for_status()
            results = geo.json().get("results")
            if not results:
                return {"error": f"Location '{location}' not found."}

            place = results[0]
            lat, lon = place["latitude"], place["longitude"]
            place_name = f"{place.get('name', location)}, {place.get('country', '')}"

            wx = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weathercode",
                    "daily": "temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum",
                    "forecast_days": 4,
                    "timezone": "auto",
                },
            )
            wx.raise_for_status()
            data = wx.json()

        cur = data.get("current", {})
        daily = data.get("daily", {})

        def _safe(lst: list, i: int):
            return lst[i] if lst and i < len(lst) else None

        dates = daily.get("time", [])
        forecast = [
            {
                "date": dates[i],
                "condition": _WMO.get(_safe(daily.get("weathercode", []), i) or 0, "Unknown"),
                "high_c": _safe(daily.get("temperature_2m_max", []), i),
                "low_c": _safe(daily.get("temperature_2m_min", []), i),
                "precip_mm": _safe(daily.get("precipitation_sum", []), i),
            }
            for i in range(len(dates[:4]))
        ]

        return {
            "location": place_name,
            "current": {
                "temp_c": cur.get("temperature_2m"),
                "humidity_pct": cur.get("relative_humidity_2m"),
                "wind_kph": cur.get("wind_speed_10m"),
                "condition": _WMO.get(cur.get("weathercode", 0), "Unknown"),
            },
            "forecast_4d": forecast,
        }
    except Exception as exc:
        return {"error": f"Weather fetch failed: {exc}"}


# ── Calculator (safe AST-based eval) ─────────────────────────────────────────

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}

_FUNS: dict[str, Any] = {
    "sqrt": math.sqrt, "abs": abs, "round": round,
    "log": math.log, "log10": math.log10, "log2": math.log2,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "ceil": math.ceil, "floor": math.floor,
    "pi": math.pi, "e": math.e,
}


def _eval(node: ast.expr) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Unsupported literal: {node.value!r}")
    if isinstance(node, ast.BinOp):
        fn = _OPS.get(type(node.op))
        if not fn:
            raise ValueError(f"Unsupported operator: {node.op}")
        return fn(_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp):
        fn = _OPS.get(type(node.op))
        if not fn:
            raise ValueError(f"Unsupported unary op: {node.op}")
        return fn(_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = _FUNS.get(node.func.id)
        if not callable(fn):
            raise ValueError(f"Unknown function: {node.func.id}")
        return fn(*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name):
        v = _FUNS.get(node.id)
        if isinstance(v, float):
            return v
        raise ValueError(f"Unknown name: {node.id}")
    raise ValueError(f"Unsupported expression type: {type(node).__name__}")


async def calculate(expression: str) -> dict:
    pct = re.match(r"^\s*([\d.]+)\s*%\s*of\s*([\d.]+)\s*$", expression, re.IGNORECASE)
    if pct:
        result = float(pct.group(1)) / 100 * float(pct.group(2))
        return {"expression": expression, "result": result, "formatted": f"{result:g}"}
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _eval(tree.body)
        return {"expression": expression, "result": result, "formatted": f"{result:g}"}
    except Exception as exc:
        return {"error": f"Cannot evaluate '{expression}': {exc}"}


# ── Dispatcher ────────────────────────────────────────────────────────────────

async def execute_tool(name: str, arguments: dict) -> Any:
    if name == "web_search":
        return await web_search(arguments.get("query", ""))
    if name == "get_stock_price":
        return await get_stock_price(arguments.get("symbol", ""))
    if name == "get_weather":
        return await get_weather(arguments.get("location", ""))
    if name == "calculate":
        return await calculate(arguments.get("expression", ""))
    return {"error": f"Unknown tool: {name}"}
