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


class QueryError(Exception):
    pass


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
    """3 to 5 search queries for a market. QueryError if the model call fails or returns none: the
    caller retries later rather than tracking a market on a bad query forever."""
    try:
        answer = await ask_json(PROMPT.format(title=title, rules=rules[:1500]))
        queries = [q.strip() for q in answer if isinstance(q, str) and q.strip()][:5]
    except Exception as e:
        raise QueryError(f"{type(e).__name__}: {str(e)[:150]}") from e
    if not queries:
        raise QueryError("the model returned no queries")
    return queries


COMPANIES = """A prediction market is tracked for news.

Market: {title}
Rules: {rules}

Name the companies this market is about, as the press writes them (for example "Nvidia", "OpenAI"). Only
companies that are in the news under their own name: no people, countries, governments, parties or teams.
Reply with a JSON array of at most 2 strings only; an empty array if the market is not about a company."""


async def companies_for(title: str, rules: str) -> list[str]:
    """Up to 2 companies whose news bears on a market, possibly none. QueryError if the model call fails."""
    try:
        answer = await ask_json(COMPANIES.format(title=title, rules=rules[:1500]))
        return [c.strip()[:80] for c in answer if isinstance(c, str) and c.strip()][:2]
    except Exception as e:
        raise QueryError(f"{type(e).__name__}: {str(e)[:150]}") from e
