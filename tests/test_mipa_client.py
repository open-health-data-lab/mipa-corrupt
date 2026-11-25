"""What the client does when OpenRouter misbehaves.

Every interesting path here is a failure path, and none of them can be ordered
on demand from a live API — you cannot ask for a 429 storm, a truncated
response, or a socket reset at a chosen moment. So the transport is scripted
(`httpx.MockTransport`) and the assertions are about behaviour: how many
requests were issued, whether the note survived into the retry, and whether the
per-model budget moved in the right direction.

Backoff is set to zero in the retry tests so they run in milliseconds; the
jitter and `Retry-After` arithmetic is tested separately as a pure function,
where it can be checked over its whole range instead of at one sampled point.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from mipa.client import (
    DEFAULT_MODELS,
    OPENROUTER_URL,
    AdaptiveLimit,
    ClientConfig,
    OpenRouterClient,
    load_api_key,
)
from mipa.protocol import ParseStatus

MODEL = DEFAULT_MODELS[0]
PHENOTYPE = "hypertension"
NOTE = "Discharge Summary\n\nThe patient has a history of hypertension."

#: Backoff off, retries plentiful. Real sleeps would make this suite take
#: minutes to assert something that has nothing to do with wall clock.
FAST = ClientConfig(base_backoff_s=0.0, max_backoff_s=0.0, max_retries=4)


def ok_body(status: str = "1", **usage: object) -> dict[str, object]:
    content = json.dumps({"phenotype": PHENOTYPE, "status": status})
    body: dict[str, object] = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage:
        body["usage"] = usage
    return body


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


async def call(
    handler: Callable[[httpx.Request], httpx.Response],
    config: ClientConfig = FAST,
    note: str = NOTE,
):  # type: ignore[no-untyped-def]
    async with OpenRouterClient(
        "sk-test", config=config, transport=httpx.MockTransport(handler)
    ) as client:
        attempt = await client.classify(MODEL, PHENOTYPE, note)
        return attempt, client


# -- the happy path -------------------------------------------------------


def test_successful_call_returns_a_parsed_prediction() -> None:
    attempt, _ = run(call(lambda _r: httpx.Response(200, json=ok_body("1"))))
    assert attempt.y_pred == 1
    assert attempt.parse_status == ParseStatus.OK
    assert attempt.attempts == 1


def test_usage_is_captured_when_the_provider_reports_it() -> None:
    body = ok_body("0", prompt_tokens=3550, completion_tokens=12, cost=0.00021)
    attempt, _ = run(call(lambda _r: httpx.Response(200, json=body)))
    assert attempt.y_pred == 0
    assert attempt.prompt_tokens == 3550
    assert attempt.cost == pytest.approx(0.00021)


def test_missing_usage_is_not_an_error() -> None:
    """Not every provider reports usage. A cost of `None` is a null, not a zero."""
    attempt, _ = run(call(lambda _r: httpx.Response(200, json=ok_body())))
    assert attempt.parse_status == ParseStatus.OK
    assert attempt.cost is None
    assert attempt.prompt_tokens is None


def test_request_carries_the_protocol_parameters() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=ok_body())

    run(call(handler))
    payload = seen[0]
    assert payload["model"] == MODEL
    assert payload["temperature"] == 0.5
    assert payload["response_format"] == {"type": "json_object"}
    # MIPA sets no max_tokens, top_p, seed or stop; sending any of them would be
    # a silent protocol change.
    assert not {"max_tokens", "top_p", "seed", "stop"} & set(payload)


def test_system_prompt_is_sent() -> None:
    """A documented departure from MIPA's async path, so it is asserted, not assumed."""
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=ok_body())

    run(call(handler))
    roles = [m["role"] for m in seen[0]["messages"]]  # type: ignore[index]
    assert roles == ["system", "user"]


# -- transport failures ---------------------------------------------------


def test_retries_on_500_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500, text="upstream boom")
        return httpx.Response(200, json=ok_body())

    attempt, _ = run(call(handler))
    assert attempt.y_pred == 1
    assert attempt.attempts == 3
    assert calls["n"] == 3


def test_retries_on_timeout() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=ok_body())

    attempt, _ = run(call(handler))
    assert attempt.parse_status == ParseStatus.OK
    assert calls["n"] == 2


def test_timeout_that_never_recovers_is_recorded_as_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    attempt, _ = run(call(handler))
    assert attempt.y_pred is None
    assert attempt.parse_status == ParseStatus.TIMEOUT
    assert attempt.attempts == FAST.max_retries


def test_network_error_is_recorded_as_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    attempt, _ = run(call(handler))
    assert attempt.parse_status == ParseStatus.HTTP_ERROR


def test_retry_budget_is_finite() -> None:
    """A permanently 503-ing provider must not hold a unit forever."""
    calls = {"n": 0}

    def handler(_r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    attempt, _ = run(call(handler))
    assert calls["n"] == FAST.max_retries
    assert attempt.y_pred is None
    assert attempt.parse_status == ParseStatus.HTTP_ERROR


@pytest.mark.parametrize("status", [401, 403, 404])
def test_configuration_errors_fail_fast(status: int) -> None:
    """A bad key or a nonexistent slug must stop the run, not retry 672,000 times."""
    calls = {"n": 0}

    def handler(_r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status, json={"error": {"message": "no such model"}})

    with pytest.raises(SystemExit):
        run(call(handler))
    assert calls["n"] == 1


def test_a_provider_passthrough_is_retried_not_fatal() -> None:
    """The bug the live smoke test caught, and the reason it is not still latent.

    OpenRouter fans each request across providers and relays an upstream
    failure with the *provider's* status code. A 404 reading "The model
    `gemma4-31b-it` does not exist" arrived for a request that asked for
    `google/gemma-3-27b-it` — one provider in the pool had a broken mapping.
    Treating it as a configuration error killed the entire run, and under
    systemd would have restarted straight back into it.
    """
    calls = {"n": 0}
    upstream = {
        "error": {
            "message": "Provider returned error",
            "code": 404,
            "metadata": {
                "provider_name": "Nebius",
                "raw": "The model `gemma4-31b-it` does not exist.",
            },
        }
    }

    def handler(_r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(404, json=upstream)
        return httpx.Response(200, json=ok_body())

    attempt, _ = run(call(handler))
    assert attempt.parse_status == ParseStatus.OK, "must route around the broken provider"
    assert calls["n"] == 2


def test_an_auth_failure_is_fatal_even_shaped_like_a_passthrough() -> None:
    """No upstream provider can make our OpenRouter key invalid."""

    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "Provider returned error", "metadata": {"p": "x"}}},
        )

    with pytest.raises(SystemExit):
        run(call(handler))


def test_a_persistent_provider_error_exhausts_rather_than_crashing() -> None:
    """If every provider is broken the unit fails — it does not take the run down.

    `http_error` stays retriable across restarts, so a provider outage is
    recovered later rather than recorded as a model result.
    """

    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": {"message": "Provider returned error", "metadata": {"p": "x"}}}
        )

    attempt, _ = run(call(handler))
    assert attempt.y_pred is None
    assert attempt.parse_status == ParseStatus.HTTP_ERROR


# -- parse failures -------------------------------------------------------


def test_unparseable_response_is_retried_with_the_note_attached() -> None:
    """The bug in MIPA's own retry, asserted against.

    `llm_module.py:1719-1726` replaces the message list with a bare "return
    JSON" instruction on one branch, so the retry asks the model to classify a
    note it can no longer see. Every retry here must still contain the note.
    """
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) < 3:
            return httpx.Response(200, json={"choices": [{"message": {"content": "Sure! Yes."}}]})
        return httpx.Response(200, json=ok_body())

    attempt, _ = run(call(handler))
    assert attempt.parse_status == ParseStatus.OK
    assert len(bodies) == 3
    for body in bodies:
        user = body["messages"][-1]["content"]  # type: ignore[index]
        assert NOTE in user


def test_persistent_garbage_reports_the_last_parse_status() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "no json here"}}]})

    attempt, _ = run(call(handler))
    assert attempt.y_pred is None
    assert attempt.parse_status == ParseStatus.NO_JSON
    assert attempt.raw_output == "no json here"
    assert attempt.attempts == FAST.max_retries


def test_empty_choices_does_not_crash() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    attempt, _ = run(call(handler))
    assert attempt.y_pred is None
    assert attempt.raw_output is None


def test_content_as_typed_parts_is_joined() -> None:
    """Some providers return content as a list of parts rather than a string."""
    parts = [
        {"type": "text", "text": '{"phenotype": "hypertension",'},
        {"type": "text", "text": ' "status": "1"}'},
    ]

    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": parts}}]})

    attempt, _ = run(call(handler))
    assert attempt.y_pred == 1


# -- the adaptive limiter -------------------------------------------------


class FakeClock:
    """A clock the test advances by hand.

    The limiter's policy is now expressed in seconds, and the intervals it uses
    are a minute and half a minute. Sleeping through those would make the suite
    unrunnable, and shrinking them to milliseconds would test different numbers
    than the ones that ship.
    """

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_429_halves_the_per_model_budget() -> None:
    clock = FakeClock()
    limit = AdaptiveLimit(limit=8, maximum=16, clock=clock)
    limit.rejected()
    assert limit.limit == 4
    clock.advance(31)  # a separate rejection event, not the same burst
    limit.rejected()
    assert limit.limit == 2


def test_one_burst_halves_only_once() -> None:
    """The regression that pinned the run at a single slot for days.

    A rejection arrives once per request already in flight, so halving on each
    turned one event into a collapse: 12 -> 6 -> 3 -> 1 within a few seconds.
    The budget must track rejection *events*, not the queue depth at the moment
    the first one landed.
    """
    clock = FakeClock()
    limit = AdaptiveLimit(limit=12, maximum=16, cooldown_s=30.0, clock=clock)
    for _ in range(12):  # the whole in-flight batch comes back 429
        clock.advance(0.2)
        limit.rejected()
    assert limit.limit == 6, "one burst, one halving"


def test_budget_never_reaches_zero() -> None:
    """At zero the model would stall forever with no path back."""
    clock = FakeClock()
    limit = AdaptiveLimit(limit=2, maximum=16, clock=clock)
    for _ in range(10):
        clock.advance(31)
        limit.rejected()
    assert limit.limit == 1


def test_recovery_is_additive_and_timed() -> None:
    clock = FakeClock()
    limit = AdaptiveLimit(limit=2, maximum=16, recover_after_s=60.0, clock=clock)
    clock.advance(59)
    limit.succeeded()
    assert limit.limit == 2, "recovers only after a sustained quiet window"
    clock.advance(2)
    limit.succeeded()
    assert limit.limit == 3, "one slot at a time, not back to where it was"
    limit.succeeded()
    assert limit.limit == 3, "and not twice in the same window"


def test_recovery_does_not_depend_on_how_fast_the_model_is() -> None:
    """Why the clock replaced the counter.

    A slow model returns few responses per minute, so a count-based threshold
    made its recovery arbitrarily slower — at 15s/request and limit=1, one extra
    slot cost ~50 minutes. The slow model is the one that needs the slots most.
    """
    slow, fast = FakeClock(), FakeClock()
    slow_limit = AdaptiveLimit(limit=1, maximum=16, recover_after_s=60.0, clock=slow)
    fast_limit = AdaptiveLimit(limit=1, maximum=16, recover_after_s=60.0, clock=fast)

    for _ in range(4):  # four responses in five minutes
        slow.advance(75)
        slow_limit.succeeded()
    for _ in range(300):  # three hundred, over the same five minutes
        fast.advance(1)
        fast_limit.succeeded()

    # Not identical — a limiter can only raise when a response arrives, so the
    # slow model's opportunities come 75s apart rather than 60s. Within one
    # slot is the point: the same five minutes buys both of them the same
    # recovery, where a count-based rule gave the slow model none at all.
    assert abs(slow_limit.limit - fast_limit.limit) <= 1
    assert slow_limit.limit >= 5, "four responses were enough, because time passed"


def test_recovery_stops_at_the_ceiling() -> None:
    clock = FakeClock()
    limit = AdaptiveLimit(limit=3, maximum=3, recover_after_s=1.0, clock=clock)
    for _ in range(20):
        clock.advance(10)
        limit.succeeded()
    assert limit.limit == 3


def test_a_rejection_postpones_recovery() -> None:
    """A 429 costs one quiet window — a bounded price, unlike a reset counter."""
    clock = FakeClock()
    limit = AdaptiveLimit(limit=4, maximum=16, recover_after_s=60.0, clock=clock)
    clock.advance(50)
    limit.succeeded()
    assert limit.limit == 4, "not yet quiet long enough"

    limit.rejected()
    assert limit.limit == 2
    clock.advance(59)
    limit.succeeded()
    assert limit.limit == 2, "the quiet window restarts at the rejection"
    clock.advance(2)
    limit.succeeded()
    assert limit.limit == 3


def test_a_burst_still_postpones_recovery_while_cooling_down() -> None:
    """The cooldown suppresses the halving, not the evidence.

    Rejections arriving inside the cooldown are still the provider saying it is
    unhappy. If they did not push the quiet window back, the limiter could raise
    its budget in the middle of an ongoing 429 storm.
    """
    clock = FakeClock()
    limit = AdaptiveLimit(limit=4, maximum=16, recover_after_s=60.0, cooldown_s=30.0, clock=clock)
    limit.rejected()
    assert limit.limit == 2
    for _ in range(20):  # the rest of the burst, all inside the cooldown
        clock.advance(1)
        limit.rejected()
    assert limit.limit == 2, "still one halving"

    clock.advance(50)
    limit.succeeded()
    assert limit.limit == 2, "60s is measured from the LAST rejection, not the first"
    clock.advance(11)
    limit.succeeded()
    assert limit.limit == 3


def test_a_live_429_moves_the_budget() -> None:
    """End to end: the limiter reacts to what the API actually returned."""
    calls = {"n": 0}

    def handler(_r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json=ok_body())

    config = ClientConfig(base_backoff_s=0.0, max_backoff_s=0.0, per_model_concurrency=4)
    attempt, client = run(call(handler, config=config))
    assert attempt.parse_status == ParseStatus.OK
    assert client.snapshot()[MODEL] == 2


def test_a_5xx_does_not_move_the_budget() -> None:
    """503 is the provider being unwell, not us being too fast."""
    calls = {"n": 0}

    def handler(_r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503 if calls["n"] == 1 else 200, json=ok_body())

    config = ClientConfig(base_backoff_s=0.0, max_backoff_s=0.0, per_model_concurrency=4)
    _, client = run(call(handler, config=config))
    assert client.snapshot()[MODEL] == 4


def test_limit_admits_no_more_than_its_budget() -> None:
    """The property that matters: concurrency never exceeds `limit`."""

    async def scenario() -> int:
        limit = AdaptiveLimit(limit=3, maximum=8, recover_after_s=1e9)
        peak = 0

        async def one() -> None:
            nonlocal peak
            async with limit.slot():
                peak = max(peak, limit.in_flight)
                await asyncio.sleep(0)

        await asyncio.gather(*(one() for _ in range(20)))
        return peak

    assert run(scenario()) <= 3


def test_shrinking_takes_effect_for_waiters() -> None:
    """A halving must bind the next admission, not the next process restart.

    This is why the limiter is a counter under a Condition rather than a
    Semaphore: `asyncio.Semaphore` has no way to lower its capacity, and the
    usual workaround — spawning tasks to eat the surplus permits — leaves the
    effective limit dependent on scheduling order.
    """

    async def scenario() -> int:
        limit = AdaptiveLimit(limit=4, maximum=8, recover_after_s=1e9)
        released = asyncio.Event()
        peak_after = 0

        async def early() -> None:
            async with limit.slot():
                limit.rejected()  # budget is now 2
                await released.wait()

        async def late() -> None:
            nonlocal peak_after
            async with limit.slot():
                peak_after = max(peak_after, limit.in_flight)
                await asyncio.sleep(0)

        task = asyncio.create_task(early())
        await asyncio.sleep(0)
        latecomers = [asyncio.create_task(late()) for _ in range(6)]
        await asyncio.sleep(0)
        released.set()
        await asyncio.gather(task, *latecomers)
        return peak_after

    assert run(scenario()) <= 2


# -- key handling ---------------------------------------------------------


def test_key_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "  sk-from-env  ")
    assert load_api_key() == "sk-from-env"


def test_explicit_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-from-env")
    assert load_api_key("sk-explicit") == "sk-explicit"


def test_key_file_is_a_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    path = tmp_path / "key.txt"
    path.write_text("sk-from-file\n")
    assert load_api_key(key_file=path) == "sk-from-file"


def test_missing_key_exits_with_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        load_api_key()
    assert "OPENROUTER_API_KEY" in str(excinfo.value)


def test_key_is_sent_as_a_bearer_header_and_nowhere_else() -> None:
    """The key belongs in one header and must not leak into the body or the URL."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ok_body())

    run(call(handler))
    request = seen[0]
    assert request.headers["authorization"] == "Bearer sk-test"
    assert "sk-test" not in request.content.decode()
    assert "sk-test" not in str(request.url)


# -- backoff arithmetic ---------------------------------------------------


def test_backoff_grows_and_is_capped() -> None:
    client = OpenRouterClient("sk-test", ClientConfig(base_backoff_s=1.0, max_backoff_s=30.0))
    for attempt in range(12):
        window = min(30.0, 2.0**attempt)
        for _ in range(20):
            assert 0.0 <= client._backoff(attempt, None) <= window


def test_backoff_is_jittered() -> None:
    """Undithered backoff retries N coroutines in lockstep and rebuilds the burst."""
    client = OpenRouterClient("sk-test", ClientConfig(base_backoff_s=1.0))
    waits = {client._backoff(6, None) for _ in range(50)}
    assert len(waits) > 40


def test_retry_after_is_a_floor() -> None:
    client = OpenRouterClient("sk-test", ClientConfig(base_backoff_s=0.0, max_backoff_s=0.0))
    assert client._backoff(0, 7.5) == pytest.approx(7.5)


def test_retry_after_does_not_shorten_a_longer_backoff() -> None:
    client = OpenRouterClient("sk-test", ClientConfig(base_backoff_s=1.0))
    for _ in range(50):
        assert client._backoff(8, 0.001) >= 0.001


def test_unparseable_retry_after_is_ignored() -> None:
    """`Retry-After` may be an HTTP date; an unusable value must not crash the run."""
    calls = {"n": 0}

    def handler(_r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
        return httpx.Response(200, json=ok_body())

    attempt, _ = run(call(handler))
    assert attempt.parse_status == ParseStatus.OK


# -- model discovery ------------------------------------------------------


def test_list_models_returns_the_served_slugs() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": m} for m in DEFAULT_MODELS]})

    async def scenario() -> set[str]:
        async with OpenRouterClient("sk-test", transport=httpx.MockTransport(handler)) as client:
            return await client.list_models()

    assert run(scenario()) == set(DEFAULT_MODELS)


def test_requests_go_to_openrouter() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=ok_body())

    run(call(handler))
    assert seen == [OPENROUTER_URL]
