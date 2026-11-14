import asyncio
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from terminal import speech
from terminal.api import create_app


def gemini(monkeypatch, handler):
    """Answer the model call with handler(request) instead of the network."""
    real = httpx.AsyncClient
    monkeypatch.setattr(speech.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("GEMINI_API_KEY", "k")


def answer(text):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def test_transcribe_sends_the_recording_with_the_shared_key_and_returns_its_words(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return answer(json.dumps({"text": "  That is\n clever. "}))

    gemini(monkeypatch, handler)
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "gemini-test")
    monkeypatch.delenv("GEMINI_SPEECH_MODEL", raising=False)
    assert asyncio.run(speech.transcribe(b"RIFFdata", "audio/wav")) == "That is clever."
    assert seen[0].headers["x-goog-api-key"] == "k" and "/models/gemini-test:generateContent" in str(seen[0].url)
    part = json.loads(seen[0].content)["contents"][0]["parts"][0]["inline_data"]
    assert part == {"mime_type": "audio/wav", "data": base64.b64encode(b"RIFFdata").decode()}


def test_speech_model_can_be_named_separately(monkeypatch):
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "a")
    monkeypatch.setenv("GEMINI_SPEECH_MODEL", "b")
    assert speech.model() == "b"


def test_silence_is_an_empty_text(monkeypatch):
    gemini(monkeypatch, lambda r: answer('{"text": ""}'))
    assert asyncio.run(speech.transcribe(b"x")) == ""


@pytest.mark.parametrize("reply", [httpx.Response(500), answer("not json"), answer('{"words": 1}'),
                                   httpx.Response(200, json={"candidates": []})])
def test_a_failed_or_odd_answer_is_a_speech_error(monkeypatch, reply):
    gemini(monkeypatch, lambda r: reply)
    with pytest.raises(speech.SpeechError):
        asyncio.run(speech.transcribe(b"x"))


def client(tmp_path, key=""):
    return TestClient(create_app(db_path=str(tmp_path / "t.db"), poll=False, key=key))


def test_transcribe_route(tmp_path, monkeypatch):
    async def heard(audio, mime):
        assert audio == b"RIFF" and mime == "audio/wav"
        return "hello there"

    monkeypatch.setattr(speech, "transcribe", heard)
    with client(tmp_path) as c:
        r = c.post("/transcribe", content=b"RIFF", headers={"content-type": "audio/wav"})
        assert r.status_code == 200 and r.json() == {"text": "hello there"}
        assert c.post("/transcribe", content=b"x", headers={"content-type": "text/plain"}).status_code == 415
        assert c.post("/transcribe", content=b"", headers={"content-type": "audio/wav"}).status_code == 422
        big = b"x" * (speech.MAX_BYTES + 1)
        assert c.post("/transcribe", content=big, headers={"content-type": "audio/wav"}).status_code == 413


def test_transcribe_needs_the_terminal_key_and_reports_a_model_failure(tmp_path, monkeypatch):
    async def down(audio, mime):
        raise speech.SpeechError("down")

    monkeypatch.setattr(speech, "transcribe", down)
    with client(tmp_path, key="s") as c:
        wav = {"content-type": "audio/wav"}
        assert c.post("/transcribe", content=b"x", headers=wav).status_code == 401
        r = c.post("/transcribe", content=b"x", headers={**wav, "X-Terminal-Key": "s"})
        assert r.status_code == 502 and r.json()["detail"] == "could not reach the speech model, try again"


def test_a_transcription_model_is_sent_the_recording_alone_and_answers_in_its_own_shape(monkeypatch):
    # gemini-3.5-transcribe refuses JSON mode ("JSON mode is not enabled for this model"), answers with an
    # audioTranscription part, and with no content at all when nobody speaks (checked on 14 Nov)
    seen, replies = [], [
        {"candidates": [{"content": {"parts": [{"audioTranscription": {"text": " The birch canoe\n slid. "}}]}}]},
        {"candidates": [{"finishReason": "STOP", "index": 0}]}]

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=replies[len(seen) - 1])

    gemini(monkeypatch, handler)
    monkeypatch.setenv("GEMINI_SPEECH_MODEL", "gemini-3.5-transcribe")
    assert asyncio.run(speech.transcribe(b"RIFFdata")) == "The birch canoe slid."
    assert asyncio.run(speech.transcribe(b"RIFFdata")) == ""
    assert "generationConfig" not in seen[0] and [list(p) for p in seen[0]["contents"][0]["parts"]] == [["inline_data"]]
