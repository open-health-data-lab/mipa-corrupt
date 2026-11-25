"""Talking to OpenRouter for days without being throttled or losing work.

The workload is entirely network-bound — 672,000 requests, each a few thousand
tokens of clinical note — so the only questions that matter are how many are in
flight, what happens when the provider pushes back, and what happens when a
response is not the JSON we asked for.

**No rate limit is assumed.** OpenRouter's limits vary by model, by account and
by time of day, and hardcoding a number would either throttle the run
unnecessarily or spend the day generating 429s. Instead concurrency starts
conservative and *adapts*: sustained rejections halve the per-model limit, a
clean stretch raises it back one step at a time. The run finds the ceiling
rather than being told it.

**Backoff is jittered, and that is not cosmetic.** With N coroutines hitting one
429 wave, undithered exponential backoff retries them in lockstep and reproduces
the burst that caused the rejection. Full jitter spreads the retry over the whole
window.

**A parse failure is retried with the note still attached.** MIPA's own retry
(`llm_module.py:1719-1726`) replaces the message list with a bare "please return
JSON" on one branch, dropping the clinical text — so the retry asks the model to
classify nothing. That behaviour is deliberately not reproduced.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import random
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from mipa.protocol import (
    RESPONSE_FORMAT,
    TEMPERATURE,
    ParseStatus,
    build_messages,
    parse_prediction,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"

#: The three models the experiment runs. `google/gemma-4-31b-it` from the brief
#: does not exist — Gemma 3 is the current generation — so the ladder is the
#: three sizes that do, verified against `/models` during preflight.
DEFAULT_MODELS: tuple[str, ...] = (
    "google/gemma-3-4b-it",
    "google/gemma-3-12b-it",
    "google/gemma-3-27b-it",
)

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


@dataclass
class ClientConfig:
    """Every knob, so none of them is buried in the code."""

    global_concurrency: int = 12
    per_model_concurrency: int = 3
    max_retries: int = 8
    request_timeout_s: float = 120.0
    #: Ceiling for the adaptive limiter. It will not raise past this even on a
    #: perfectly clean run, so a misconfiguration cannot become a thundering herd.
    max_per_model_concurrency: int = 16
    #: Seconds of quiet before the limiter tries one more slot. Timed rather
    #: than counted: a count of clean *responses* makes recovery slower the
    #: slower the model is, which is backwards — a 15s/request model needs the
    #: slots most and earns them least. See `AdaptiveLimit.succeeded`.
    recover_after_s: float = 60.0
    #: After halving, how long further rejections are treated as the same burst.
    #: Roughly the p99 request latency, which is how long requests admitted
    #: under the old limit take to drain. See `AdaptiveLimit.rejected`.
    reject_cooldown_s: float = 30.0
    base_backoff_s: float = 1.0
    max_backoff_s: float = 120.0


@dataclass
class AdaptiveLimit:
    """A per-model concurrency budget that responds to what the API says.

    Halve on a burst of rejections, add one back after a long clean stretch.
    Multiplicative decrease and additive increase, for the reason TCP uses it:
    backing off hard is cheap and recovering greedily is what re-triggers the
    problem.

    A counter guarded by a `Condition`, not a `Semaphore`, because a semaphore's
    capacity cannot be *lowered*. The obvious workaround — spawning tasks to
    consume the surplus slots — makes the effective limit depend on when those
    tasks happen to be scheduled, which is precisely the property a rate limiter
    must not have. Here `limit` is a plain integer read at admission time, so a
    halving takes effect for the very next waiter.
    """

    limit: int
    maximum: int
    #: Seconds without a rejection before one slot is added back.
    recover_after_s: float = 60.0
    #: After a halving, how long to treat further rejections as the same burst.
    #: See `rejected`.
    cooldown_s: float = 30.0
    #: Injectable so the policy can be tested without sleeping through it.
    clock: Callable[[], float] = time.monotonic
    _in_flight: int = 0
    _last_rejection: float = field(default=0.0, init=False)
    _last_halving: float = field(default=-1e9, init=False)
    _last_raise: float = field(default=0.0, init=False)
    _cond: asyncio.Condition = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._cond = asyncio.Condition()
        # A limiter that has never been rejected should be free to climb after
        # one clean interval, not one interval measured from the epoch.
        self._last_rejection = self._last_raise = self.clock()

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        async with self._cond:
            await self._cond.wait_for(lambda: self._in_flight < self.limit)
            self._in_flight += 1
        try:
            yield
        finally:
            async with self._cond:
                self._in_flight -= 1
                # notify_all rather than notify(1): a raise from `succeeded`
                # opens more than one slot's worth of room, and waking a single
                # waiter would let the new capacity trickle in one release at a
                # time. Waiters that still do not fit re-check and go back to
                # sleep, and there are never more than `global_concurrency` of
                # them.
                self._cond.notify_all()

    def rejected(self) -> None:
        """A 429. Halve at most once per burst, floored at one.

        The floor is one, never zero, or the model stalls forever.

        Halving on *every* rejection collapses the budget on a single event:
        the requests already admitted under the old limit are still in flight,
        they are rejected too, and each of them halves again. Observed exactly
        that — a limit of 12 fell 12 -> 6 -> 3 -> 1 on one burst, a sixteen-fold
        cut in response to one piece of information. The cooldown makes the
        response proportional to the number of *rejection events*, which is what
        the signal actually is, rather than to the number of requests that
        happened to be in flight when the first one arrived.
        """
        now = self.clock()
        # Recorded even while cooling down: the burst is still evidence that the
        # provider is unhappy, so it must postpone recovery.
        self._last_rejection = now
        if now - self._last_halving < self.cooldown_s:
            return
        self._last_halving = now
        self.limit = max(1, self.limit // 2)

    def succeeded(self) -> None:
        """A clean response. Add a slot if the stretch has been long enough.

        Timed, not counted. The counted version needed `recover_after` clean
        responses, which at limit=1 and ~15s/request meant a single extra slot
        cost ~50 minutes of unbroken success and a climb back to 16 cost hours —
        and any lone 429 reset the counter to zero. Under intermittent
        throttling that is not slow recovery, it is no recovery: the run sat at
        1 slot for days, and the measured throughput matched
        `sum(limit / latency)` to three decimals.

        Against a clock the cost of a rejection is bounded — one interval, not
        an unbounded number of responses that may never arrive.
        """
        if self.limit >= self.maximum:
            return
        now = self.clock()
        quiet = now - self._last_rejection
        since_raise = now - self._last_raise
        if quiet >= self.recover_after_s and since_raise >= self.recover_after_s:
            self._last_raise = now
            self.limit += 1


@dataclass
class Attempt:
    """What came back, whether or not it was usable."""

    y_pred: int | None
    parse_status: str
    raw_output: str | None
    attempts: int
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost: float | None = None


def load_api_key(explicit: str | None = None, key_file: Path | None = None) -> str:
    """The OpenRouter key, from the least surprising place available.

    Order: explicit argument, `OPENROUTER_API_KEY`, then a file. Secret Manager
    is handled by the CLI, which writes the value into the environment before
    this is called — keeping the GCP dependency out of the hot path.

    The key is never logged, never echoed and never written to an output file.
    """
    if explicit:
        return explicit.strip()
    env = os.environ.get("OPENROUTER_API_KEY")
    if env:
        return env.strip()
    if key_file and key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    raise SystemExit(
        "no OpenRouter key. Set OPENROUTER_API_KEY, pass --api-key-file, or "
        "provision the `openrouter-api-key` secret and run via the CLI."
    )


class OpenRouterClient:
    """Bounded, backing-off, adaptive OpenRouter caller."""

    def __init__(
        self,
        api_key: str,
        config: ClientConfig | None = None,
        models: tuple[str, ...] = DEFAULT_MODELS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.config = config or ClientConfig()
        self._global = asyncio.Semaphore(self.config.global_concurrency)
        self._limits = {
            model: AdaptiveLimit(
                limit=self.config.per_model_concurrency,
                maximum=self.config.max_per_model_concurrency,
                recover_after_s=self.config.recover_after_s,
                cooldown_s=self.config.reject_cooldown_s,
            )
            for model in models
        }
        # Tests pass an `httpx.MockTransport` here. Retry, backoff and the
        # adaptive limiter are the parts most likely to be wrong and the parts
        # hardest to provoke against a live API — a 429 storm cannot be ordered
        # on demand — so they are exercised against scripted responses instead.
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> OpenRouterClient:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.request_timeout_s),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                # OpenRouter attributes traffic by these; without them a large
                # run is harder for them to reason about and for us to support.
                "HTTP-Referer": "https://github.com/open-health-data-lab/RobustEHR",
                "X-Title": "RobustEHR MIPA Experiment 1",
            },
            limits=httpx.Limits(max_connections=self.config.global_concurrency * 2),
            transport=self._transport,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:  # pragma: no cover
            raise RuntimeError("use OpenRouterClient as an async context manager")
        return self._client

    def limit_for(self, model: str) -> AdaptiveLimit:
        if model not in self._limits:
            self._limits[model] = AdaptiveLimit(
                limit=self.config.per_model_concurrency,
                maximum=self.config.max_per_model_concurrency,
                recover_after_s=self.config.recover_after_s,
                cooldown_s=self.config.reject_cooldown_s,
            )
        return self._limits[model]

    def snapshot(self) -> dict[str, int]:
        """Current per-model budget, for `status` and the log."""
        return {model: limit.limit for model, limit in sorted(self._limits.items())}

    async def list_models(self) -> set[str]:
        """Model ids OpenRouter currently serves — preflight checks slugs against this."""
        response = await self.client.get(MODELS_URL)
        response.raise_for_status()
        return {m["id"] for m in response.json().get("data", [])}

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        """Full jitter, with `Retry-After` taken as a floor when the server sends one."""
        window = min(self.config.max_backoff_s, self.config.base_backoff_s * (2**attempt))
        wait = random.uniform(0, window)  # jitter, not cryptography
        return max(wait, retry_after or 0.0)

    async def classify(self, model: str, phenotype: str, note: str) -> Attempt:
        """One (note, phenotype) prediction, with retries.

        Two distinct retry reasons, deliberately kept apart:

        * **transport** — 429/5xx/timeout/network. The request never produced an
          answer, so it is reissued unchanged after a jittered wait.
        * **unparseable** — a 200 whose body is not the JSON asked for. Reissued
          *with the original messages*, because the model needs the note to
          answer the question. Charged against the same retry budget so a model
          that never returns JSON cannot spin forever.
        """
        messages = build_messages(phenotype, note)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": TEMPERATURE,
            "response_format": RESPONSE_FORMAT,
        }
        limit = self.limit_for(model)
        started = time.monotonic()
        last_status = ParseStatus.EXHAUSTED
        last_raw: str | None = None

        for attempt in range(self.config.max_retries):
            # No point sleeping after the attempt that exhausts the budget: at
            # the top of the ladder that is up to `max_backoff_s` of dead time
            # per abandoned unit, and nothing follows it.
            final = attempt == self.config.max_retries - 1

            try:
                # Per-model slot FIRST, then the global one. The reverse order
                # holds a global slot while waiting on a throttled model, so one
                # degraded provider drains the global budget and starves every
                # healthy model. Observed live: DeepInfra's 12b endpoint went to
                # 13 s/request and the adaptive limiter floored it to one slot,
                # at which point workers queued on 12b held global slots and 4b
                # — answering in 0.4 s — dropped to a trickle. Overall
                # throughput fell from 4.4/s to 0.3/s.
                #
                # The order is the same everywhere, so it cannot deadlock.
                async with limit.slot(), self._global:
                    response = await self.client.post(OPENROUTER_URL, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_status = (
                    ParseStatus.TIMEOUT
                    if isinstance(exc, httpx.TimeoutException)
                    else ParseStatus.HTTP_ERROR
                )
                if not final:
                    await asyncio.sleep(self._backoff(attempt, None))
                continue

            if response.status_code in RETRYABLE_STATUS:
                if response.status_code == 429:
                    limit.rejected()
                retry_after = _retry_after(response)
                last_status = ParseStatus.HTTP_ERROR
                if not final:
                    await asyncio.sleep(self._backoff(attempt, retry_after))
                continue

            if response.status_code >= 400:
                # A 4xx is fatal only when **OpenRouter** is rejecting the
                # request — a bad key, a slug that does not exist. Retrying that
                # cannot help and would burn the budget 672,000 times.
                #
                # But OpenRouter fans each request out across providers, and it
                # relays an upstream provider's failure with the *provider's*
                # status code. A 404 reading "The model `gemma4-31b-it` does not
                # exist" arrived here for a request that asked for
                # `google/gemma-3-27b-it` — one provider in the pool has a broken
                # mapping. Treating that as fatal killed the whole run, and under
                # systemd would have restarted straight back into it.
                #
                # A passthrough is retryable: OpenRouter routes to a different
                # provider next time. Observed live during the smoke test, which
                # is the only reason this is not still a latent bug.
                if _is_provider_error(response):
                    last_status = ParseStatus.HTTP_ERROR
                    if not final:
                        await asyncio.sleep(self._backoff(attempt, _retry_after(response)))
                    continue

                raise SystemExit(
                    f"OpenRouter returned {response.status_code} for {model}: "
                    f"{response.text[:300]}. This is a configuration error, not a "
                    "transient one — check the key and the model slug."
                )

            limit.succeeded()
            body = response.json()
            raw = _content(body)
            last_raw = raw
            y_pred, status = parse_prediction(raw or "")
            if status == ParseStatus.OK:
                usage = body.get("usage") or {}
                return Attempt(
                    y_pred=y_pred,
                    parse_status=status,
                    raw_output=raw,
                    attempts=attempt + 1,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    cost=usage.get("cost"),
                )
            last_status = status
            # Unparseable: same messages, so the note is still there.
            if not final:
                await asyncio.sleep(self._backoff(attempt, None))

        return Attempt(
            y_pred=None,
            parse_status=last_status,
            raw_output=last_raw,
            attempts=self.config.max_retries,
            latency_ms=int((time.monotonic() - started) * 1000),
        )


#: Always ours, never a provider's: no upstream can make our key invalid.
FATAL_STATUS = frozenset({401, 403})


def _is_provider_error(response: httpx.Response) -> bool:
    """Is this OpenRouter relaying an upstream failure, rather than rejecting us?

    OpenRouter marks a passthrough by attaching `error.metadata` naming the
    provider (`provider_name`, `raw`, `previous_errors`). A request-level
    rejection — bad key, unknown slug — carries no such metadata.

    Auth failures are never treated as passthroughs regardless of shape: no
    upstream provider can make our OpenRouter key invalid, so a 401/403 is
    always ours to fix.
    """
    if response.status_code in FATAL_STATUS:
        return False
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return False
    metadata = error.get("metadata") or {}
    return bool(metadata) or error.get("message") == "Provider returned error"


def _retry_after(response: httpx.Response) -> float | None:
    """`Retry-After` in seconds, when the server sends a usable one."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _content(body: dict[str, Any]) -> str | None:
    """The assistant message, tolerating the shapes providers actually return."""
    choices = body.get("choices") or []
    if not choices:
        return None
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    # Some providers return content as a list of typed parts.
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return None


__all__ = [
    "DEFAULT_MODELS",
    "MODELS_URL",
    "OPENROUTER_URL",
    "AdaptiveLimit",
    "Attempt",
    "ClientConfig",
    "OpenRouterClient",
    "load_api_key",
]
