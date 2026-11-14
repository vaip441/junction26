"""Speech to text with an ordinary Gemini model: one short recording in, the words said in it out."""
import base64
import json
import logging
import os

import httpx

log = logging.getLogger(__name__)
MAX_BYTES = 1_500_000  # about 45 seconds of 16 kHz mono WAV; the screen sends one sentence at a time
TYPES = {"audio/wav", "audio/x-wav", "audio/mp3", "audio/mpeg", "audio/aac", "audio/ogg", "audio/flac",
         "audio/aiff", "audio/webm"}
PROMPT = """Transcribe the speech in this recording, word for word, in the language it is spoken in.
It was recorded in a loud hall: write only what the nearest speaker clearly says, with normal punctuation.
Do not translate, summarise, answer or describe sounds. If nobody clearly says anything, the text is empty.
Reply with JSON only: {"text": "..."}"""


class SpeechError(Exception):
    pass


def model() -> str:
    return os.environ.get("GEMINI_SPEECH_MODEL") or os.environ.get("GEMINI_TEXT_MODEL", "gemini-3.8-flash")


async def transcribe(audio: bytes, mime: str = "audio/wav") -> str:
    """The words said in a recording, or "" when nothing was. SpeechError if the model call fails."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model()}:generateContent",
                             headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                             json={"contents": [{"parts": [
                                       {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}},
                                       {"text": PROMPT}]}],
                                   "generationConfig": {"responseMimeType": "application/json", "temperature": 0}})
            r.raise_for_status()
            answer = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
        text = answer.get("text") if isinstance(answer, dict) else None
        if not isinstance(text, str):
            raise ValueError("no text in the answer")
    except Exception as e:
        log.warning("transcription failed: %s: %s", type(e).__name__, str(e)[:150])
        raise SpeechError(f"{type(e).__name__}: {str(e)[:150]}") from e
    return " ".join(text.split())[:500]
