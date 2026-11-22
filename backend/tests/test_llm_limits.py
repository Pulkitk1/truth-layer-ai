"""Groq rate-limit handling: pacing by token budget, waiting as told, and honest error messages."""
import threading
import time
from types import SimpleNamespace

import groq
import httpx
import pytest

from app import llm
from app.llm import LlmError


def _resp(status=429, headers=None):
    return httpx.Response(status, headers=headers or {}, request=httpx.Request("POST", "https://api.groq.com/x"))


def rate_limit(message, retry_after=None):
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    return groq.RateLimitError(message, response=_resp(429, headers), body=None)


TPM_MSG = "Rate limit reached for model `openai/gpt-oss-120b` on tokens per minute (TPM): Limit 8000, Used 7900, Requested 3000. Please try again in 6.5s."
RPD_MSG = "Rate limit reached for model `openai/gpt-oss-120b` on requests per day (RPD): Limit 1000, Used 1000, Requested 1. Please try again in 23m2.4s."


class FakeGroq:
    """Plays back a script of outcomes; each is an exception to raise or (content, headers) to return."""

    def __init__(self, script):
        self.script, self.calls = list(script), 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=self._create)))

    def _create(self, **kw):
        self.calls += 1
        out = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(out, Exception):
            raise out
        content, headers = out
        completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
        return SimpleNamespace(headers=headers, parse=lambda: completion)


@pytest.fixture()
def sleeps(monkeypatch):
    log = []
    monkeypatch.setattr(llm, "_sleep", lambda s: log.append(round(s, 2)))
    monkeypatch.setenv("GROQ_API_KEY", "k")
    return log


def use(monkeypatch, fake):
    monkeypatch.setattr(llm, "get_client", lambda: fake)


MSGS = [{"role": "user", "content": "hello"}]


def test_parse_duration():
    assert llm.parse_duration("922ms") == pytest.approx(0.922)
    assert llm.parse_duration("7.66s") == pytest.approx(7.66)
    assert llm.parse_duration("1m3.2s") == pytest.approx(63.2)
    assert llm.parse_duration("23m2.4s") == pytest.approx(1382.4)
    assert llm.parse_duration("") is None and llm.parse_duration("soon") is None


def test_waits_for_the_time_groq_asks_for_then_succeeds(monkeypatch, sleeps):
    fake = FakeGroq([rate_limit(TPM_MSG, retry_after=7), ('{"ok": true}', {})])
    use(monkeypatch, fake)
    assert llm.complete(MSGS) == '{"ok": true}'
    assert fake.calls == 2
    assert sleeps and sleeps[-1] == pytest.approx(7.5)  # Retry-After (7s) plus half a second


def test_falls_back_to_the_try_again_in_hint_when_there_is_no_header(monkeypatch, sleeps):
    fake = FakeGroq([rate_limit(TPM_MSG), ('{"ok": true}', {})])
    use(monkeypatch, fake)
    llm.complete(MSGS)
    assert sleeps[-1] == pytest.approx(7.0)  # "try again in 6.5s" + 0.5


def test_gives_up_after_a_few_retries_and_names_the_limit(monkeypatch, sleeps):
    fake = FakeGroq([rate_limit(TPM_MSG, retry_after=5)])
    use(monkeypatch, fake)
    with pytest.raises(LlmError) as e:
        llm.complete(MSGS)
    assert fake.calls == llm.MAX_RATE_RETRIES + 1
    assert e.value.code == "groq_rate_limited" and e.value.status == 429
    assert "tokens per minute" in e.value.message and "per-minute" in e.value.message


def test_daily_limit_is_reported_as_such_and_not_retried(monkeypatch, sleeps):
    fake = FakeGroq([rate_limit(RPD_MSG, retry_after=1382)])
    use(monkeypatch, fake)
    with pytest.raises(LlmError) as e:
        llm.complete(MSGS)
    assert fake.calls == 1 and sleeps == []
    assert e.value.code == "groq_daily_limit" and "requests per day" in e.value.message
    assert "23 minutes" in e.value.message


def test_a_very_long_wait_is_reported_instead_of_blocking(monkeypatch, sleeps):
    fake = FakeGroq([rate_limit(TPM_MSG, retry_after=300)])
    use(monkeypatch, fake)
    with pytest.raises(LlmError) as e:
        llm.complete(MSGS)
    assert fake.calls == 1 and e.value.code == "groq_rate_limited"
    assert "5 minutes" in e.value.message


def test_paces_the_next_request_when_the_minute_budget_is_nearly_spent(monkeypatch, sleeps):
    big = [{"role": "user", "content": "x" * 9000}]  # about 3000 tokens + the 1500 reserved for the answer
    headers = {"x-ratelimit-remaining-tokens": "1000", "x-ratelimit-limit-tokens": "8000"}
    fake = FakeGroq([('{"a": 1}', headers), ('{"a": 2}', headers)])
    use(monkeypatch, fake)
    llm.complete(MSGS)  # tiny request: learns that only 1000 tokens are left this minute
    assert sleeps == []
    llm.complete(big)  # needs about 4500: must wait for the budget to refill, not fire immediately
    assert len(sleeps) == 1 and 20 < sleeps[0] < 30  # (4500 - 1000) tokens at 8000/minute is about 26 seconds


def test_does_not_wait_when_there_is_plenty_of_budget(monkeypatch, sleeps):
    headers = {"x-ratelimit-remaining-tokens": "7800", "x-ratelimit-limit-tokens": "8000"}
    fake = FakeGroq([('{"a": 1}', headers)])
    use(monkeypatch, fake)
    llm.complete(MSGS)
    llm.complete(MSGS)
    assert sleeps == []


def test_a_request_bigger_than_the_whole_budget_is_still_attempted(monkeypatch, sleeps):
    huge = [{"role": "user", "content": "x" * 60000}]
    headers = {"x-ratelimit-remaining-tokens": "100", "x-ratelimit-limit-tokens": "8000"}
    use(monkeypatch, FakeGroq([('{"a": 1}', headers)]))
    llm.complete(MSGS)
    llm.complete(huge)  # capped wait, no infinite loop
    assert all(s <= llm.MAX_WAIT_SECONDS + 1 for s in sleeps)


def test_calls_are_serialised_so_parallel_requests_cannot_overspend(monkeypatch, sleeps):
    active, peak, lock = 0, 0, threading.Lock()

    class Slow:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=self.create)))

        def create(self, **kw):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])
            return SimpleNamespace(headers={}, parse=lambda: completion)

    use(monkeypatch, Slow())
    threads = [threading.Thread(target=llm.complete, args=(MSGS,)) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak == 1


@pytest.mark.parametrize(
    "text,kind,daily",
    [
        (TPM_MSG, "tokens per minute", False),
        ("on requests per minute (RPM): Limit 30", "requests per minute", False),
        (RPD_MSG, "requests per day", True),
        ("on tokens per day (TPD): Limit 200000", "tokens per day", True),
        ("something unexpected", "rate", False),
    ],
)
def test_limit_kind_detection(text, kind, daily):
    assert llm._limit_kind(text) == (kind, daily)
