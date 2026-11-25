"""Durable state for a run measured in days, not minutes.

672,000 predictions at a few per second is roughly nine hours of uninterrupted
API traffic. It will not be uninterrupted: SSH drops, the VM reboots, OpenRouter
has an outage, someone stops the service to change the concurrency. Every one of
those must cost the work in flight and nothing else.

So each prediction is written the moment it lands, keyed by what *determines* it:

    sha256(document_id | model | condition | phenotype)

Not by row order, not by an autoincrement. A content-addressed key means restart
is a set-difference — load the completed keys, skip them, do the rest — and it
means a prediction can never be double-counted even if the same unit is enqueued
twice by two different code paths.

SQLite rather than a directory of JSON: 672k files is hostile to both the
filesystem and to `analyze`, and rather than Parquet because Parquet cannot be
appended to safely from a process that may be killed at any moment. WAL mode so
the periodic checkpointer can read a consistent snapshot while the writer
continues.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mipa.protocol import ParseStatus

SCHEMA_VERSION = 1

#: The model was asked and responded. Final — never retried, never overwritten.
#: An unparseable response is a measurement of the model; retrying it until it
#: parsed would be resampling until the answer was agreeable.
TERMINAL_STATUSES = frozenset(
    {ParseStatus.OK, ParseStatus.NO_JSON, ParseStatus.NO_STATUS, ParseStatus.BAD_VALUE}
)

#: The request never produced a response. Nothing was learned about the model,
#: so these stay retriable across restarts and any real answer replaces them.
RETRIABLE_STATUSES = frozenset({ParseStatus.HTTP_ERROR, ParseStatus.TIMEOUT, ParseStatus.EXHAUSTED})


def _marks(values: Sequence[Any]) -> str:
    """`?` placeholders for an IN clause — never interpolate the values."""
    return ",".join("?" * len(values))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    key             TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL,
    model           TEXT NOT NULL,
    condition       TEXT NOT NULL,
    corruption      TEXT NOT NULL,
    severity        TEXT NOT NULL,
    phenotype       TEXT NOT NULL,
    y_pred          INTEGER,
    parse_status    TEXT NOT NULL,
    raw_output      TEXT,
    attempts        INTEGER NOT NULL DEFAULT 1,
    latency_ms      INTEGER,
    prompt_tokens   INTEGER,
    completion_tokens INTEGER,
    cost            REAL,
    created_at      TEXT NOT NULL
);
-- The two axes `analyze` groups by, and the one `status` counts by.
CREATE INDEX IF NOT EXISTS ix_model_condition ON predictions (model, condition);
CREATE INDEX IF NOT EXISTS ix_parse_status ON predictions (parse_status);

CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


def prediction_key(document_id: str, model: str, condition: str, phenotype: str) -> str:
    """The identity of one prediction.

    Unit-separator joined rather than concatenated: a model id containing a
    hyphen and a condition containing one must not be able to collide by
    reassociation, and `\\x1f` cannot occur in any of these fields.
    """
    material = "\x1f".join((document_id, model, condition, phenotype))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Prediction:
    """One (document, model, condition, phenotype) answer."""

    document_id: str
    model: str
    condition: str
    corruption: str
    severity: str
    phenotype: str
    y_pred: int | None
    parse_status: str
    raw_output: str | None = None
    attempts: int = 1
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost: float | None = None

    @property
    def key(self) -> str:
        return prediction_key(self.document_id, self.model, self.condition, self.phenotype)

    def as_row(self) -> tuple[Any, ...]:
        return (
            self.key,
            self.document_id,
            self.model,
            self.condition,
            self.corruption,
            self.severity,
            self.phenotype,
            self.y_pred,
            self.parse_status,
            self.raw_output,
            self.attempts,
            self.latency_ms,
            self.prompt_tokens,
            self.completion_tokens,
            self.cost,
            datetime.now(UTC).isoformat(timespec="seconds"),
        )


@dataclass
class PredictionStore:
    """Append-only prediction log with O(1) resume."""

    path: Path
    _conn: sqlite3.Connection | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=60.0, isolation_level=None)
        # WAL lets `status` and the GCS checkpointer read while the runner
        # writes. NORMAL rather than FULL: a crash may lose the last few
        # predictions, which the resume logic simply redoes — paying an fsync per
        # prediction to avoid redoing three of them would be a poor trade.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO meta (k, v) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:  # pragma: no cover - closed stores are not reused
            raise RuntimeError("store is closed")
        return self._conn

    # -- resume ------------------------------------------------------------

    def completed_keys(self) -> set[str]:
        """Every key the model has actually answered, for the skip set.

        **Not every stored key.** The distinction is the difference between a
        result and a non-result:

        * `ok`, `no_json`, `no_status`, `bad_value` — the model was asked and
          responded. Even an unusable response *is* a measurement, and asking
          again until the answer parses would be resampling until the number is
          agreeable. These are final.
        * `http_error`, `timeout`, `exhausted` — the request never produced a
          response. Nothing was learned about the model, only about the network.

        Treating the second group as answered is how a twenty-minute OpenRouter
        outage turns into permanent, unrecoverable "degradation" — and it would
        land disproportionately on whichever conditions happened to be running
        at the time, which is a confound with corruption severity itself. So
        transport failures stay retriable across restarts: the row is kept for
        the operational record, the key is not.

        Loaded once at startup and held in memory: 672k 64-char keys is about
        60 MB, and the alternative — a SELECT per unit — is 672k round trips
        against a database on the same disk as the writer.
        """
        statuses = tuple(sorted(TERMINAL_STATUSES))
        sql = f"SELECT key FROM predictions WHERE parse_status IN ({_marks(statuses)})"
        return {row[0] for row in self.conn.execute(sql, statuses)}

    def completed_count(
        self,
        conditions: Collection[str] | None = None,
        models: Collection[str] | None = None,
    ) -> int:
        """How many predictions are final. What `run` measures completeness by.

        Both filters scope the count to the run that asked for it. One store
        holds every experiment and every model, so an unscoped count answers a
        different question than the caller's: exp2 reported `451,293/64,000
        answered; -387,293 remain`, having counted exp1's 448,000 rows. Passing
        the run's own conditions and models makes the number mean what it says,
        which matters because the process exit code is derived from it.
        """
        statuses = tuple(sorted(TERMINAL_STATUSES))
        sql = f"SELECT COUNT(*) FROM predictions WHERE parse_status IN ({_marks(statuses)})"
        params: tuple[Any, ...] = statuses
        for column, values in (("condition", conditions), ("model", models)):
            if values is None:
                continue
            names = tuple(sorted(values))
            if not names:  # an empty filter selects nothing, not everything
                return 0
            sql += f" AND {column} IN ({_marks(names)})"
            params += names
        row = self.conn.execute(sql, params).fetchone()
        return int(row[0])

    def has(self, key: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM predictions WHERE key = ?", (key,)).fetchone()
        return row is not None

    # -- writing -----------------------------------------------------------

    def put(self, prediction: Prediction) -> None:
        self.put_many([prediction])

    def put_many(self, predictions: Iterable[Prediction]) -> int:
        """Insert a batch. A real answer wins; a re-answer of one does not.

        Not `REPLACE` and not a plain `INSERT OR IGNORE`, but a conditional
        upsert:

        * an existing **answer** is never overwritten — a prediction is what the
          model said the first time it was asked, and letting a rerun rewrite it
          would make the artifact depend on how many times the run was resumed;
        * an existing **transport failure** is overwritten by anything, because
          it was never an answer in the first place and the whole point of
          retrying it after an outage is to replace it.
        """
        rows = [p.as_row() for p in predictions]
        if not rows:
            return 0
        retriable = ",".join(f"'{s}'" for s in sorted(RETRIABLE_STATUSES))
        with self.conn:
            cursor = self.conn.executemany(
                "INSERT INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "  y_pred = excluded.y_pred,"
                "  parse_status = excluded.parse_status,"
                "  raw_output = excluded.raw_output,"
                "  attempts = predictions.attempts + excluded.attempts,"
                "  latency_ms = excluded.latency_ms,"
                "  prompt_tokens = excluded.prompt_tokens,"
                "  completion_tokens = excluded.completion_tokens,"
                "  cost = excluded.cost,"
                "  created_at = excluded.created_at "
                f"WHERE predictions.parse_status IN ({retriable})",
                rows,
            )
        return cursor.rowcount

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                (key, value),
            )

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
        return row[0] if row else None

    # -- reading -----------------------------------------------------------

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0])

    def counts_by_condition(self) -> dict[tuple[str, str], int]:
        return {
            (row[0], row[1]): row[2]
            for row in self.conn.execute(
                "SELECT model, condition, COUNT(*) FROM predictions GROUP BY model, condition"
            )
        }

    def parse_status_counts(self) -> dict[str, int]:
        return {
            row[0]: row[1]
            for row in self.conn.execute(
                "SELECT parse_status, COUNT(*) FROM predictions GROUP BY parse_status"
            )
        }

    def cost_so_far(self) -> float:
        row = self.conn.execute("SELECT COALESCE(SUM(cost), 0.0) FROM predictions").fetchone()
        return float(row[0])

    def iter_rows(self, *, with_raw: bool = False) -> Iterator[dict[str, Any]]:
        """Every prediction, for `analyze`.

        `raw_output` is excluded by default — it is model text about a clinical
        note and has no place in a results table. `parse_failures.csv` asks for
        it explicitly, because adjudicating a failure requires seeing it.
        """
        columns = [
            "document_id",
            "model",
            "condition",
            "corruption",
            "severity",
            "phenotype",
            "y_pred",
            "parse_status",
        ]
        if with_raw:
            columns.append("raw_output")
        sql = f"SELECT {', '.join(columns)} FROM predictions"  # identifiers are fixed above
        for row in self.conn.execute(sql):
            yield dict(zip(columns, row, strict=True))

    def iter_failures(self) -> Iterator[dict[str, Any]]:
        columns = [
            "document_id",
            "model",
            "condition",
            "phenotype",
            "parse_status",
            "attempts",
            "raw_output",
        ]
        sql = f"SELECT {', '.join(columns)} FROM predictions WHERE parse_status != 'ok'"
        for row in self.conn.execute(sql):
            yield dict(zip(columns, row, strict=True))

    def operational_rows(self) -> Iterator[dict[str, Any]]:
        """Latency, attempts, tokens, cost — kept out of the results table."""
        columns = [
            "document_id",
            "model",
            "condition",
            "phenotype",
            "attempts",
            "latency_ms",
            "prompt_tokens",
            "completion_tokens",
            "cost",
        ]
        sql = f"SELECT {', '.join(columns)} FROM predictions"  # identifiers are fixed above
        for row in self.conn.execute(sql):
            yield dict(zip(columns, row, strict=True))

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> PredictionStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


__all__ = [
    "RETRIABLE_STATUSES",
    "SCHEMA_VERSION",
    "TERMINAL_STATUSES",
    "Prediction",
    "PredictionStore",
    "prediction_key",
]
