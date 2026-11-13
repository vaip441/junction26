"""What to search for: queries written from a market's title and rules by an ordinary Gemini model."""
import json
import logging
import os

import httpx

log = logging.getLogger(__name__)
PROMPT = """You help track news that could move a prediction market.

Market: {title}
Rules: {rules}

Write 3 to 5 short web search queries (2 to 6 words each) that would find breaking news bearing on how this
market resolves. Use the names of the people, companies and events involved. Reply with a JSON array of strings only."""


async def ask_json(prompt: str):
    model = os.environ.get("GEMINI_TEXT_MODEL", "gemini-3.8-flash")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                         headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                         json={"contents": [{"parts": [{"text": prompt}]}],
                               "generationConfig": {"responseMimeType": "application/json"}})
        r.raise_for_status()
        return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])


async def queries_for(title: str, rules: str) -> list[str]:
    """3 to 5 search queries for a market; just its title if the model call fails."""
    try:
        answer = await ask_json(PROMPT.format(title=title, rules=rules[:1500]))
        queries = [q.strip() for q in answer if isinstance(q, str) and q.strip()][:5]
        return queries or [title]
    except Exception as e:
        log.warning("query writing failed for %r: %s", title, e)
        return [title]
