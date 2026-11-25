"""`mipa-exp1` — the Experiment 1 runner.

    preflight   check everything that could fail, before anything costs money
    sample      choose the 500 notes, once, and write them down
    upload      push the inference inputs to GCS
    run         execute predictions, resumably
    status      what has been done so far
    analyze     the three result tables

`run` is built to be killed. SSH drops, systemd restarts, OpenRouter has an
outage, someone reboots the VM — each of those must cost the requests in flight
and nothing else. Every answer is written the moment it lands, keyed by content,
so a restart is a set-difference against what is already in the store. There is
no run state anywhere except that database.

Work is enqueued **baseline first, then every condition at once**, partitioned
per model. Baseline first because a partial run is only interpretable if the
reference arm is complete — every delta needs it. Every condition at once
because running them in sequence puts a barrier at each boundary, and with two
models of different speed the fast one spends most of the run idle: measured
live, 4b sat at 98.5% of a condition, with five untouched conditions of its own
work queued behind the barrier, while 12b ground through the same condition at
30.9%.

Only the **sampled** notes are read, not the corpora — 500 notes is ~5 MB per
condition where the full tree is 450 MB — so holding every condition open costs
tens of MB, not hundreds, and stays well inside the 1.5 GB the service allows.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mipa import corpora as mipa_corpora
from mipa import metrics as mipa_metrics
from mipa import sample as mipa_sample
from mipa.client import (
    DEFAULT_MODELS,
    ClientConfig,
    OpenRouterClient,
    load_api_key,
)
from mipa.protocol import PHENOTYPES, departures
from mipa.store import Prediction, PredictionStore, prediction_key

DEFAULT_EXPERIMENTS = Path("data/experiments")
DEFAULT_OUTPUT = Path("data/mipa_exp1")

#: How often the store is flushed and the checkpoint pushed. Fifteen minutes of
#: work is ~2,000 predictions; losing that to a hard kill is an acceptable
#: exposure, and checkpointing more often would spend the run's time on GCS
#: round trips.
CHECKPOINT_EVERY_S = 900

#: Predictions per transaction. Large enough that SQLite is not the bottleneck,
#: small enough that a `SIGKILL` between commits loses seconds, not minutes.
WRITE_BATCH = 100


@dataclass
class Progress:
    """Counters for the log line, so a two-day run is legible while it runs."""

    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    started: float = field(default_factory=time.monotonic)

    def line(self, label: str, cost: float, limits: dict[str, int]) -> str:
        elapsed = max(time.monotonic() - self.started, 1e-6)
        rate = self.done / elapsed
        remaining = (self.total - self.done) / rate if rate > 0 else 0.0
        budget = " ".join(f"{m.rsplit('/', 1)[-1]}={n}" for m, n in limits.items())
        return (
            f"[{label}] {self.done}/{self.total} done  {self.failed} unparsed  "
            f"{self.skipped} resumed  {rate:.1f}/s  eta {remaining / 3600:.1f}h  "
            f"${cost:.2f}  [{budget}]"
        )


@dataclass(frozen=True, slots=True)
class Unit:
    """One prediction to make. `note` is a shared reference, not a copy."""

    document_id: str
    model: str
    condition: mipa_corpora.Condition
    phenotype: str
    note: str

    @property
    def key(self) -> str:
        return prediction_key(self.document_id, self.model, self.condition.name, self.phenotype)


# -- run ------------------------------------------------------------------


async def run_conditions(
    *,
    client: OpenRouterClient,
    store: PredictionStore,
    work: Sequence[tuple[mipa_corpora.Condition, dict[str, str]]],
    models: Sequence[str],
    completed: set[str],
    progress: Progress,
    stopping: asyncio.Event,
    workers: int,
    label: str,
) -> None:
    """Every (condition x note x model x phenotype) still outstanding.

    **All conditions at once, not one at a time.** Running them in sequence puts
    a barrier at each condition boundary, and with two models of very different
    speed that barrier is expensive: measured live, 4b reached 98.5% of
    `homoglyph/high` and then sat idle — five untouched conditions of its own
    work queued behind a barrier — while 12b ground through the same condition
    at 30.9%. The fast model finishes early and waits, every single condition.

    Flattening the queues removes the barrier entirely. Each model streams
    through the whole experiment at whatever rate its provider allows, and a
    model that is being throttled costs only its own share instead of stalling
    the other one at every boundary.

    Memory is why this was sequential to begin with, and it still bounds the
    design: units hold a *reference* to the note, never a copy, so the cost of
    flattening is one dict of note text per condition (~5 MB each) plus ~200
    bytes per outstanding unit — tens of MB for a whole experiment, against the
    1.5 GB the service is allowed.
    """
    # One queue per model, not one shared queue.
    #
    # A shared queue interleaves models, so a worker that draws a unit for a slow
    # model blocks on that model's semaphore while holding a worker slot. With
    # enough such units every worker ends up parked on the slow model and the
    # fast ones starve behind them — head-of-line blocking. Observed live:
    # DeepInfra's 12b endpoint degraded to 13 s/request, the limiter floored it
    # to one concurrent slot, and overall throughput collapsed from 4.4/s to
    # 0.3/s even though 4b was still answering in 0.4 s.
    #
    # Partitioned, each model drains at whatever rate its provider allows and a
    # degraded one costs only its own share.
    queues: dict[str, asyncio.Queue[Unit]] = {model: asyncio.Queue() for model in models}
    for condition, notes in work:
        for document_id, note in notes.items():
            for model in models:
                for phenotype in PHENOTYPES:
                    unit = Unit(document_id, model, condition, phenotype, note)
                    if unit.key in completed:
                        progress.skipped += 1
                        continue
                    queues[model].put_nowait(unit)

    pending = sum(q.qsize() for q in queues.values())
    progress.total += pending
    if not pending:
        print(f"[{label}] already complete, skipping", flush=True)
        return
    print(
        f"[{label}] {pending:,} to do across {len(work)} conditions: "
        + ", ".join(f"{m.rsplit('/', 1)[-1]}={q.qsize():,}" for m, q in queues.items()),
        flush=True,
    )

    results: asyncio.Queue[Prediction | None] = asyncio.Queue(maxsize=WRITE_BATCH * 4)
    writer = asyncio.create_task(drain(store, results, progress, label, client))

    async def worker(model: str) -> None:
        queue = queues[model]
        while not stopping.is_set():
            try:
                unit = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            attempt = await client.classify(unit.model, unit.phenotype, unit.note)
            await results.put(
                Prediction(
                    document_id=unit.document_id,
                    model=unit.model,
                    condition=unit.condition.name,
                    corruption=unit.condition.corruption,
                    severity=unit.condition.severity,
                    phenotype=unit.phenotype,
                    y_pred=attempt.y_pred,
                    parse_status=attempt.parse_status,
                    raw_output=attempt.raw_output if attempt.y_pred is None else None,
                    attempts=attempt.attempts,
                    latency_ms=attempt.latency_ms,
                    prompt_tokens=attempt.prompt_tokens,
                    completion_tokens=attempt.completion_tokens,
                    cost=attempt.cost,
                )
            )

    # `workers` per model rather than `workers` in total. The client's per-model
    # semaphore is what actually bounds concurrency, so extra coroutines here
    # cost a few KB and park on it; what they buy is that a fast model always has
    # a worker ready the instant a slot frees, independent of how badly another
    # model is behaving.
    await asyncio.gather(*(worker(model) for model in models for _ in range(workers)))
    await results.put(None)
    await writer


async def drain(
    store: PredictionStore,
    results: asyncio.Queue[Prediction | None],
    progress: Progress,
    label: str,
    client: OpenRouterClient,
) -> None:
    """Batch predictions into the store, and log while doing it.

    A single writer, because SQLite wants one and because batching is what keeps
    the commit rate off the critical path. `raw_output` is only ever stored for
    a failed parse: it is model text about a clinical note, and 672,000 of them
    would be both a large database and a data-handling question nobody needs to
    answer.
    """
    batch: list[Prediction] = []
    last_log = time.monotonic()

    while True:
        item = await results.get()
        if item is not None:
            batch.append(item)
            progress.done += 1
            if item.parse_status != "ok":
                progress.failed += 1

        if len(batch) >= WRITE_BATCH or (item is None and batch):
            store.put_many(batch)
            batch = []

        if item is None:
            print(progress.line(label, store.cost_so_far(), client.snapshot()), flush=True)
            return

        if time.monotonic() - last_log > 60:
            last_log = time.monotonic()
            print(progress.line(label, store.cost_so_far(), client.snapshot()), flush=True)


async def run(args: argparse.Namespace) -> int:
    sample = mipa_sample.read_sample(args.sample)
    if args.max_notes:
        # A prefix of the sample, not a random subset: `sample.csv` has a fixed
        # order, so the smoke run's notes are a subset of the full run's and
        # every prediction it makes is one the full run would have made anyway.
        # Re-running without `--max-notes` therefore resumes rather than
        # discards — the smoke test is the first slice of the real run, not a
        # throwaway.
        sample = sample[: args.max_notes]
        print(f"--max-notes {args.max_notes}: smoke run over the first {len(sample)} notes")
    wanted = {note.hadm_id for note in sample}
    conditions = select_conditions(args)
    models = tuple(args.models)

    store = PredictionStore(args.store)
    completed = store.completed_keys()
    expected = len(wanted) * len(models) * len(PHENOTYPES) * len(conditions)
    print(
        f"{len(conditions)} conditions x {len(models)} models x {len(wanted)} notes x "
        f"{len(PHENOTYPES)} phenotypes = {expected:,} predictions; "
        f"{len(completed):,} already in {args.store}",
        flush=True,
    )

    store.set_meta("models", json.dumps(list(models)))
    store.set_meta("sample", str(args.sample))
    store.set_meta("departures", json.dumps(departures()))

    stopping = asyncio.Event()
    install_signal_handlers(stopping)

    config = ClientConfig(
        global_concurrency=args.concurrency,
        per_model_concurrency=args.per_model_concurrency,
        max_per_model_concurrency=args.max_per_model_concurrency,
    )
    progress = Progress()

    # Read every condition's notes up front. This is the memory trade the
    # sequential version avoided; at 500 sampled notes it is ~5 MB per condition
    # and the barrier it removes was costing more than the RAM is worth.
    work = [(c, mipa_corpora.read_notes(c.notes_csv, keep=wanted)) for c in conditions]

    async with OpenRouterClient(resolve_key(args), config=config, models=models) as client:
        await run_conditions(
            client=client,
            store=store,
            work=work,
            models=models,
            completed=completed,
            progress=progress,
            stopping=stopping,
            workers=max(args.concurrency, args.max_per_model_concurrency),
            label=args.experiment,
        )

    checkpoint(args, store)
    # `completed_count`, not `count`: a row recording a transport failure is not
    # an answered prediction, and treating it as one would let a run that spent
    # an hour inside an OpenRouter outage exit 0 and stay stopped. Scoped to
    # this run's conditions, because the store also holds every other
    # experiment — unscoped, exp2 counted exp1's rows and reported
    # `451,293/64,000 answered; -387,293 remain`.
    answered = store.completed_count({c.name for c in conditions}, models)
    remaining = expected - answered
    print(
        f"stopped with {answered:,}/{expected:,} answered"
        + (f"; {remaining:,} remain — rerun `run` to resume" if remaining else "; complete"),
        flush=True,
    )
    store.close()
    # Nonzero on an incomplete run so `systemd` with `Restart=always` picks it
    # back up, while a genuinely finished run exits clean and stays stopped.
    return 1 if remaining else 0


def install_signal_handlers(stopping: asyncio.Event) -> None:
    """SIGTERM and SIGINT stop *enqueuing*; in-flight work is allowed to land.

    `systemctl stop` sends SIGTERM. Dropping the ~12 in-flight requests would
    waste them, and worse, killing mid-transaction is the one way to lose
    already-answered predictions. Draining takes a couple of seconds.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stopping.set)
        except NotImplementedError:  # pragma: no cover - Windows
            signal.signal(sig, lambda *_: stopping.set())


def checkpoint(args: argparse.Namespace, store: PredictionStore) -> None:
    """Push the database to GCS, if a bucket was given. Never fatal.

    A checkpoint failing is a backup problem, not a run problem: the local
    SQLite file is the source of truth and the run can continue without the
    copy. Aborting a two-day run because a bucket write 503'd would be the
    wrong trade.
    """
    if not args.bucket:
        return
    from mipa import cloud as mipa_cloud

    ref = mipa_cloud.BucketRef(args.bucket, f"{results_prefix(args)}/predictions.sqlite")
    try:
        mipa_cloud.upload(args.store, ref, project=args.project)
        print(f"checkpoint -> {ref.uri}", flush=True)
    except Exception as exc:  # a failed backup must not end the run
        print(f"checkpoint failed ({type(exc).__name__}); continuing", file=sys.stderr, flush=True)
        del exc


def results_prefix(args: argparse.Namespace) -> str:
    """Where a run publishes: `results/<experiment>/<run-id>/`.

    The experiment belongs in the path because it is what distinguishes the
    corpora — Experiment 1 corrupts the whole document, Experiment 2 only
    clinical content — and burying that in a run-id makes the bucket unreadable
    the moment there is more than one experiment. An earlier build hardcoded
    `results/experiment_1/`, so an Experiment 2 run published under Experiment
    1's name.

    The run-id stays *stable across batches of the same experiment*. Experiment 2
    evaluates typographical errors first and homoglyphs later against the same
    store, and those are one result set rather than two: the second batch
    resumes, re-analyses everything, and republishes the complete table over the
    first batch's partial one. A run-id per batch would leave a permanently
    incomplete directory sitting beside the real answer.
    """
    return f"results/{args.experiment}/{args.run_id}"


def select_conditions(args: argparse.Namespace) -> list[mipa_corpora.Condition]:
    conditions = mipa_corpora.discover(args.experiments, experiment=args.experiment)
    if not conditions:
        raise SystemExit(
            f"no corpora under {args.experiments}. Expected "
            f"{args.experiments}/baseline/notes.csv and "
            f"{args.experiments}/exp1/<corruption>/<severity>/notes.csv"
        )
    if args.conditions:
        wanted = set(args.conditions)
        conditions = [c for c in conditions if c.name in wanted]
        if missing := wanted - {c.name for c in conditions}:
            raise SystemExit(f"unknown condition(s): {sorted(missing)}")
    return conditions


def resolve_key(args: argparse.Namespace) -> str:
    """The OpenRouter key, from wherever this deployment keeps it.

    Environment first (how the VM's systemd unit supplies it), then Secret
    Manager when a project is configured, then an explicit file for local work.
    Never a default path and never the repository: a key that can be picked up
    implicitly from the working directory is one that eventually gets committed.

    The value is returned and put in one Authorization header. It is not logged,
    not echoed, not written to any output file, and not copied to the VM.
    """
    if os.environ.get("OPENROUTER_API_KEY"):
        return load_api_key()
    if args.api_key_file and args.api_key_file.exists():
        # Ahead of Secret Manager: an explicit `--api-key-file` is an
        # instruction, and reaching past it to the network would make a local
        # run depend on cloud credentials it does not otherwise need.
        return load_api_key(key_file=args.api_key_file)

    if args.project:
        from mipa import cloud as mipa_cloud

        try:
            mipa_cloud.load_key_into_env(project=args.project)
        except Exception as exc:
            # One redacted line, not a gRPC traceback: this runs inside
            # `preflight`, where an unhandled raise would discard the checks that
            # already passed. `redact` because the error may quote the request.
            detail = mipa_cloud.redact(str(exc)).splitlines()[0]
            raise SystemExit(
                f"could not read the `{mipa_cloud.SECRET_NAME}` secret from "
                f"project {args.project}: {detail}"
            ) from exc
    return load_api_key(key_file=args.api_key_file)


# -- preflight ------------------------------------------------------------


#: Baseline plus 9 corruptions x 3 severities.
EXPECTED_CONDITIONS = 28


@dataclass(frozen=True, slots=True)
class Check:
    ok: bool
    message: str


def check_local(args: argparse.Namespace) -> tuple[list[Check], list[mipa_sample.Note]]:
    """Corpora, sample, join and labels — everything that costs nothing to verify."""
    checks = []

    conditions = mipa_corpora.discover(args.experiments, experiment=args.experiment)
    expected = (
        EXPECTED_CONDITIONS if args.experiment == mipa_corpora.EXPERIMENT else len(conditions)
    )
    checks.append(
        Check(
            len(conditions) == expected,
            f"corpora: {len(conditions)} {args.experiment} conditions under "
            f"{args.experiments} (expected {expected})",
        )
    )

    sample = mipa_sample.read_sample(args.sample) if args.sample.exists() else []
    checks.append(Check(bool(sample), f"sample: {len(sample)} notes from {args.sample}"))

    if sample and conditions:
        wanted = {n.hadm_id for n in sample}
        try:
            # One corpus is enough to catch the failure this guards against: the
            # sample and the corpora being built from different note sets.
            mipa_corpora.read_notes(conditions[0].notes_csv, keep=wanted)
            checks.append(Check(True, f"join: all {len(wanted)} sampled notes present in corpora"))
        except SystemExit as exc:
            checks.append(Check(False, f"join: {exc}"))

    if not args.labels.exists():
        checks.append(Check(False, f"labels: {args.labels} not found"))
    elif sample:
        unlabelled = {n.hadm_id for n in sample} - set(mipa_sample.read_labels(args.labels))
        checks.append(
            Check(not unlabelled, f"labels: {len(unlabelled)} sampled notes without a gold label")
        )

    return checks, sample


async def check_api(args: argparse.Namespace, sample: list[mipa_sample.Note]) -> list[Check]:
    """The key resolves, the model slugs exist, and — with `--live` — they answer."""
    try:
        key = resolve_key(args)
    except SystemExit as exc:
        return [Check(False, f"key: {exc}")]

    checks = [Check(True, "key: OPENROUTER_API_KEY resolves")]
    async with OpenRouterClient(key, models=tuple(args.models)) as client:
        served = await client.list_models()
        checks.extend(Check(model in served, f"model: {model}") for model in args.models)

        conditions = mipa_corpora.discover(args.experiments, experiment=args.experiment)
        if args.live and sample and conditions:
            notes = mipa_corpora.read_notes(conditions[0].notes_csv, keep={sample[0].hadm_id})
            note = next(iter(notes.values()))
            for model in args.models:
                attempt = await client.classify(model, PHENOTYPES[0], note)
                checks.append(
                    Check(attempt.parse_status == "ok", f"live: {model} -> {attempt.parse_status}")
                )
    return checks


def check_bucket(args: argparse.Namespace) -> list[Check]:
    from mipa import cloud as mipa_cloud

    try:
        ref = mipa_cloud.BucketRef(args.bucket, args.gcs_prefix)
        blobs = mipa_cloud.list_blobs(ref, project=args.project)
        notes = sum(1 for b in blobs if b.endswith("/notes.csv"))
        # Count corpora, not objects: "240 objects" says nothing about whether
        # the tree is the one the runner can read.
        return [
            Check(
                notes >= EXPECTED_CONDITIONS,
                f"bucket: {notes} notes.csv under {ref.uri} "
                f"(expected {EXPECTED_CONDITIONS}), {len(blobs)} objects total",
            ),
            Check(
                any(b.endswith("sample.csv") for b in blobs)
                and any(b.endswith("golden_labels.csv") for b in blobs),
                "bucket: sample.csv and golden_labels.csv present "
                "(the VM reads the selection, it never re-derives it)",
            ),
        ]
    # `SystemExit` as well as `Exception`, because a missing `google-cloud-storage`
    # raises one and it is not an `Exception` — without it, a machine that has
    # not installed the `cloud` extra loses the eleven checks that already
    # passed, which defeats the point of running them all in one pass.
    except (Exception, SystemExit) as exc:
        # `redact` because a gcloud error can quote the failing request, and the
        # request carries an Authorization header.
        detail = mipa_cloud.redact(str(exc)).splitlines()[0]
        return [Check(False, f"bucket: {type(exc).__name__}: {detail}")]


async def preflight(args: argparse.Namespace) -> int:
    """Everything that can fail, checked before anything costs money.

    Cheapest-first, and it does not stop at the first failure: finding out about
    three problems in one pass beats three round trips, especially when one of
    them needs a browser login to fix.
    """
    checks, sample = check_local(args)
    checks += await check_api(args, sample)
    if args.bucket:
        checks += check_bucket(args)

    for check in checks:
        print(f"  {'PASS' if check.ok else 'FAIL'}  {check.message}")

    conditions = mipa_corpora.discover(args.experiments, experiment=args.experiment)
    if sample and conditions:
        total = len(sample) * len(args.models) * len(PHENOTYPES) * len(conditions)
        print(f"\n{total:,} predictions to make")

    passed = sum(1 for c in checks if c.ok)
    print(f"\n{passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


# -- the other subcommands ------------------------------------------------


def sample_cmd(args: argparse.Namespace) -> int:
    corpus = mipa_sample.load_corpus(args.notes, args.labels, args.cache)
    chosen = mipa_sample.select(corpus, n=args.n, salt=args.salt, min_positives=args.min_positives)
    mipa_sample.write_sample(chosen, args.sample)
    print(mipa_sample.summarise(chosen, corpus))
    print(f"\nwrote {len(chosen)} notes to {args.sample}")
    return 0


def upload_cmd(args: argparse.Namespace) -> int:
    """Push everything the VM needs to run, and nothing it does not."""
    from mipa import cloud as mipa_cloud

    if not args.bucket:
        raise SystemExit("upload needs --bucket (or MIPA_BUCKET)")

    ref = mipa_cloud.BucketRef(args.bucket, args.gcs_prefix)
    uploaded = mipa_cloud.upload_corpora(args.experiments, ref, project=args.project)
    print(f"corpora: {len(uploaded)} object(s) -> {ref.uri}")
    print("  edits.jsonl and dose.jsonl deliberately excluded — 1.3 GB of corruption")
    print("  provenance that inference never reads.")

    # The sample and the labels travel with the corpora. The VM must *read* the
    # selection, never re-derive it: re-running the sampler there would make it
    # depend on the concept cache and the full corpus being present too, and a
    # resume after any change could silently evaluate a different 500 notes than
    # the predictions already in the store belong to.
    for local, name in ((args.sample, "sample.csv"), (args.labels, "golden_labels.csv")):
        if not local.exists():
            raise SystemExit(f"{local} not found; run `sample` before `upload`")
        target = ref.child(name)
        mipa_cloud.upload(local, target, project=args.project)
        print(f"  {name} -> {target.uri}")
    return 0


def publish_results(args: argparse.Namespace) -> list[str]:
    """Copy the result tables to GCS. Returns the URIs written."""
    from mipa import cloud as mipa_cloud

    if not args.bucket:
        return []
    base = mipa_cloud.BucketRef(args.bucket, results_prefix(args))
    written = []
    for path in sorted(args.results.iterdir()):
        if path.is_file():
            written.append(mipa_cloud.upload(path, base.child(path.name), project=args.project))
    return written


def status_cmd(args: argparse.Namespace) -> int:
    if not args.store.exists():
        print(f"no store at {args.store}; nothing has run yet")
        return 1

    store = PredictionStore(args.store)
    counts = store.counts_by_condition()
    per_condition = len({n.hadm_id for n in mipa_sample.read_sample(args.sample)}) * len(PHENOTYPES)

    print(f"{store.count():,} predictions  ${store.cost_so_far():.2f}\n")
    for (model, condition), n in sorted(counts.items()):
        bar = "#" * int(20 * min(n / per_condition, 1.0)) if per_condition else ""
        print(f"  {model:<28} {condition:<38} {n:>6}/{per_condition:<6} {bar}")

    statuses = store.parse_status_counts()
    total = sum(statuses.values()) or 1
    print("\nparse status:")
    for status, n in sorted(statuses.items(), key=lambda kv: -kv[1]):
        print(f"  {status:<12} {n:>8}  {100 * n / total:5.2f}%")
    store.close()
    return 0


def analyze_cmd(args: argparse.Namespace) -> int:
    store = PredictionStore(args.store)
    labels = mipa_sample.read_labels(args.labels)
    arms = mipa_metrics.build_arms(store.iter_rows(), labels)

    args.results.mkdir(parents=True, exist_ok=True)
    deltas = mipa_metrics.delta_rows(arms)
    written = [
        # The unaggregated matrix, for anything with note-level structure —
        # paired tests, bootstrap CIs over notes, mixed-effects models. It cannot
        # be recovered from the aggregate tables.
        mipa_metrics.write_csv_gz(
            args.results / "predictions.csv.gz",
            mipa_metrics.prediction_rows(store.iter_rows(), labels),
        ),
        mipa_metrics.write_csv(
            args.results / "overall_metrics.csv", mipa_metrics.overall_rows(arms)
        ),
        mipa_metrics.write_csv(
            args.results / "phenotype_metrics.csv", mipa_metrics.phenotype_rows(arms)
        ),
        mipa_metrics.write_csv(args.results / "robustness_deltas.csv", deltas),
        mipa_metrics.write_csv(args.results / "parse_failures.csv", list(store.iter_failures())),
        # Gzipped like `predictions`: same 672,000-row scale, and 64 MB of
        # latency integers is not a thing to hand anyone uncompressed.
        mipa_metrics.write_csv_gz(args.results / "operational.csv.gz", store.operational_rows()),
    ]

    summary = {
        "models": sorted({a.model for a in arms.values()}),
        "conditions": sorted({a.condition for a in arms.values()}),
        "predictions": store.count(),
        "cost_usd": round(store.cost_so_far(), 4),
        "parse_status": store.parse_status_counts(),
        "protocol_departures": departures(),
        "sample": str(args.sample),
    }
    (args.results / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(mipa_metrics.summarise(deltas))
    print("\nwrote:")
    for path in [*written, args.results / "run_summary.json"]:
        print(f"  {path}")

    published = publish_results(args)
    if published:
        print(f"\npublished {len(published)} file(s) to gs://{args.bucket}/{results_prefix(args)}/")
    store.close()
    return 0


# -- argument parsing -----------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mipa-exp1",
        description="MIPA zero-shot phenotyping over the Experiment 1 corruption corpora.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--experiments", type=Path, default=DEFAULT_EXPERIMENTS)
        p.add_argument(
            "--experiment",
            default=mipa_corpora.EXPERIMENT,
            help="which corruption tree to evaluate: exp1 corrupts the whole "
            "document, exp2 restricts to clinical content. Both include the clean "
            "baseline, so a shared store answers it once.",
        )
        p.add_argument("--sample", type=Path, default=DEFAULT_OUTPUT / "sample.csv")
        p.add_argument("--labels", type=Path, default=Path("data/golden_labels.csv"))
        p.add_argument("--store", type=Path, default=DEFAULT_OUTPUT / "predictions.sqlite")
        p.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
        p.add_argument("--bucket", default=os.environ.get("MIPA_BUCKET"))
        p.add_argument("--project", default=os.environ.get("MIPA_PROJECT"))
        p.add_argument(
            "--gcs-prefix",
            default=os.environ.get("MIPA_GCS_PREFIX", ""),
            help="prefix the corpora live under in the bucket (default: the root)",
        )
        p.add_argument(
            "--api-key-file",
            type=Path,
            default=None,
            help="read the OpenRouter key from this file (never logged or copied)",
        )

    pre = sub.add_parser("preflight", help="check everything before spending money")
    common(pre)
    pre.add_argument(
        "--live",
        action="store_true",
        help="also make one real call per model (costs a few cents)",
    )

    smp = sub.add_parser("sample", help="choose the notes, once")
    common(smp)
    smp.add_argument("--notes", type=Path, default=Path("data/golden_notes.csv"))
    smp.add_argument("--cache", type=Path, default=Path("data/concept_cache"))
    smp.add_argument("-n", type=int, default=mipa_sample.DEFAULT_SAMPLE_SIZE)
    smp.add_argument("--salt", default="rep0")
    smp.add_argument("--min-positives", type=int, default=mipa_sample.DEFAULT_MIN_POSITIVES)

    up = sub.add_parser("upload", help="push notes.csv and manifest.json to GCS")
    common(up)

    rn = sub.add_parser("run", help="make predictions, resumably")
    common(rn)
    rn.add_argument("--concurrency", type=int, default=12)
    rn.add_argument("--per-model-concurrency", type=int, default=3)
    # The ceiling the adaptive limiter may climb to. It used to be fixed at 16,
    # which was invisible until it became the binding constraint: with a BYOK
    # provider key the 429s stopped entirely and goodput went linear in
    # concurrency, so the cap — not the provider — was setting the rate.
    rn.add_argument("--max-per-model-concurrency", type=int, default=16)
    rn.add_argument("--conditions", nargs="+", help="restrict to these condition names")
    rn.add_argument("--run-id", default="run1")
    rn.add_argument(
        "--max-notes",
        type=int,
        default=None,
        help="only the first N sampled notes — a smoke test whose predictions "
        "the full run then resumes from rather than repeats",
    )

    st = sub.add_parser("status", help="how far along the run is")
    common(st)

    an = sub.add_parser("analyze", help="write the result tables")
    common(an)
    an.add_argument("--results", type=Path, default=DEFAULT_OUTPUT / "results")
    an.add_argument("--run-id", default="run1")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "preflight":
        return asyncio.run(preflight(args))
    if args.command == "sample":
        return sample_cmd(args)
    if args.command == "upload":
        return upload_cmd(args)
    if args.command == "run":
        return asyncio.run(run(args))
    if args.command == "status":
        return status_cmd(args)
    if args.command == "analyze":
        return analyze_cmd(args)
    raise AssertionError(f"unreachable: {args.command}")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = [
    "Progress",
    "Unit",
    "build_parser",
    "main",
    "resolve_key",
    "run_conditions",
    "select_conditions",
]
