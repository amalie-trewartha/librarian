"""Store connection, schema, clock and ids.

Everything time-related goes through :func:`now`, which honors the same
project clock as ``thinkers/_lib/project.sh`` (``PROJECT_NOW``,
``PROJECT_REAL_NOW``, ``PROJECT_TIME_SCALE``, ``started_at``) plus a
``LIBRARIAN_NOW`` pin for tests. Durations stored in the database are in
project seconds, so an accelerated run ages memories at project speed.
"""

from __future__ import annotations

import datetime as dt
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA_VERSION = 1


class StoreError(Exception):
    """Base class for store problems the CLI maps to an exit code."""


class NoStore(StoreError):
    """No store exists at the resolved path."""


class StoreBusy(StoreError):
    """Another writer held the database past the busy timeout."""


# ── clock ────────────────────────────────────────────────────────────────────

_UTC = dt.timezone.utc


def _parse_epoch_or_iso(value: str) -> Optional[dt.datetime]:
    value = value.strip()
    if not value:
        return None
    if value.lstrip("-").replace(".", "", 1).isdigit():
        return dt.datetime.fromtimestamp(float(value), tz=_UTC)
    return parse_ts(value)


def parse_ts(value: Optional[str]) -> Optional[dt.datetime]:
    """Parse an ISO-8601 string (``Z`` or offset, optional fraction) to UTC."""
    if not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Librarian writes offsets like -0700; Python wants -07:00.
    if len(s) >= 5 and s[-5] in "+-" and s[-3] != ":" and s[-4:].isdigit():
        s = s[:-2] + ":" + s[-2:]
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        try:
            d = dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            try:
                d = dt.datetime.strptime(s[:10], "%Y-%m-%d")
            except ValueError:
                return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_UTC)
    return d.astimezone(_UTC)


def _started_at(env: dict) -> Optional[float]:
    v = env.get("PROJECT_STARTED_AT", "").strip()
    if v.isdigit():
        return float(v)
    ident = env.get("IDENTITY_DIR", "")
    if ident:
        p = Path(ident) / "project-pristine" / "started_at"
        try:
            return float(p.read_text().strip())
        except (OSError, ValueError):
            return None
    return None


_warned_scale = False


def now(env: Optional[dict] = None) -> dt.datetime:
    """The librarian's notion of the current time, in UTC.

    Precedence: ``LIBRARIAN_NOW`` (epoch or ISO) → ``PROJECT_NOW`` (epoch) →
    the scaled project clock when ``PROJECT_TIME_SCALE`` > 1 and a start is
    known → real time (``PROJECT_REAL_NOW`` lets tests pin that too).
    """
    global _warned_scale
    e = os.environ if env is None else env
    pin = e.get("LIBRARIAN_NOW", "")
    if pin:
        d = _parse_epoch_or_iso(pin)
        if d is not None:
            return d
    pn = e.get("PROJECT_NOW", "").strip()
    if pn.isdigit():
        return dt.datetime.fromtimestamp(float(pn), tz=_UTC)
    real = e.get("PROJECT_REAL_NOW", "").strip()
    real_s = float(real) if real.isdigit() else time.time()
    scale = e.get("PROJECT_TIME_SCALE", "1").strip()
    if scale.isdigit() and int(scale) > 1:
        start = _started_at(e)
        if start is not None:
            return dt.datetime.fromtimestamp(start + (real_s - start) * int(scale), tz=_UTC)
        if not _warned_scale:
            _warned_scale = True
            import sys

            print("librarian: PROJECT_TIME_SCALE set but no started_at; using real time", file=sys.stderr)
    return dt.datetime.fromtimestamp(real_s, tz=_UTC)


def iso(d: dt.datetime) -> str:
    return d.astimezone(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso(env: Optional[dict] = None) -> str:
    return iso(now(env))


def today(env: Optional[dict] = None) -> str:
    return now(env).strftime("%Y-%m-%d")


def age_seconds(ts: Optional[str], ref: Optional[dt.datetime] = None) -> Optional[float]:
    d = parse_ts(ts)
    if d is None:
        return None
    return ((ref or now()) - d).total_seconds()


def age_days(ts: Optional[str], ref: Optional[dt.datetime] = None) -> Optional[float]:
    s = age_seconds(ts, ref)
    return None if s is None else s / 86400.0


def project_week(env: Optional[dict] = None) -> str:
    """The 1-based, zero-padded project week from started_at, as project.sh counts it."""
    e = os.environ if env is None else env
    start = _started_at(e)
    if start is None:
        return now(e).strftime("%G-W%V")
    return "%02d" % (int((now(e).timestamp() - start) // 604800) + 1)


# ── ULIDs ────────────────────────────────────────────────────────────────────

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ulid_lock = threading.Lock()
_ulid_last_ms = -1
_ulid_last_rand = 0


def ulid(when: Optional[dt.datetime] = None) -> str:
    """A 26-character ULID from the librarian clock, monotonic within a process.

    Pinned clocks (tests, ``PROJECT_NOW``) produce many ids in one
    millisecond; the random part is incremented in that case so ordering by
    id still follows creation order.
    """
    global _ulid_last_ms, _ulid_last_rand
    ms = int((when or now()).timestamp() * 1000)
    with _ulid_lock:
        if ms == _ulid_last_ms:
            _ulid_last_rand = (_ulid_last_rand + 1) % (1 << 80)
            rand = _ulid_last_rand
        else:
            rand = secrets.randbits(80)
            _ulid_last_ms = ms
            _ulid_last_rand = rand
    value = (ms << 80) | rand
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(out))


def is_ulid(s: str) -> bool:
    return len(s) == 26 and all(c in _CROCKFORD for c in s)


# ── store ────────────────────────────────────────────────────────────────────


def default_store_path(env: Optional[dict] = None) -> Optional[Path]:
    e = os.environ if env is None else env
    p = e.get("LIBRARIAN_STORE", "").strip()
    if p:
        return Path(p)
    ident = e.get("IDENTITY_DIR", "").strip()
    if ident:
        return Path(ident) / "librarian" / "store.sqlite"
    return None


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK (type IN ('skill','decision','retrospective','preference',
                                     'identity_core','identity_working','episode')),
  summary TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK (status IN ('probationary','active','superseded','archived','disputed')),
  confidence REAL NOT NULL,
  use_count INTEGER NOT NULL DEFAULT 0,
  success_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0,
  failures_since_success INTEGER NOT NULL DEFAULT 0,
  unknown_citations INTEGER NOT NULL DEFAULT 0,
  last_used TEXT,
  last_confirmed TEXT,
  outcome TEXT,
  provenance TEXT NOT NULL,
  project TEXT,
  valid_from TEXT,
  valid_to TEXT,
  known_from TEXT NOT NULL,
  known_to TEXT,
  created TEXT NOT NULL,
  review_flag TEXT,
  archived_reason TEXT,
  summary_tokens INTEGER NOT NULL,
  body_tokens INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS nodes_type_status ON nodes(type, status);
CREATE INDEX IF NOT EXISTS nodes_project ON nodes(project);
CREATE INDEX IF NOT EXISTS nodes_status_last_confirmed ON nodes(status, last_confirmed);

CREATE TABLE IF NOT EXISTS tags (
  node_id TEXT NOT NULL REFERENCES nodes(id),
  tag TEXT NOT NULL,
  PRIMARY KEY (node_id, tag)
);
CREATE INDEX IF NOT EXISTS tags_tag ON tags(tag);

CREATE TABLE IF NOT EXISTS tag_vocab (
  tag TEXT PRIMARY KEY,
  namespace TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  added TEXT NOT NULL,
  note TEXT
);

CREATE TABLE IF NOT EXISTS edges (
  id INTEGER PRIMARY KEY,
  from_id TEXT NOT NULL,
  to_id TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('derived_from','supersedes','contradicts','applies_to','caused',
                                     'informed','co_retrieved','part_of','failed_in')),
  weight REAL NOT NULL DEFAULT 1.0,
  provenance TEXT,
  created TEXT NOT NULL,
  UNIQUE (from_id, to_id, type)
);
CREATE INDEX IF NOT EXISTS edges_from ON edges(from_id, type);
CREATE INDEX IF NOT EXISTS edges_to ON edges(to_id, type);

CREATE TABLE IF NOT EXISTS requests (
  request_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('pack','search','fetch')),
  project TEXT,
  phase TEXT,
  task TEXT,
  tags TEXT NOT NULL DEFAULT '[]',
  budget INTEGER,
  used_tokens INTEGER,
  truncated INTEGER NOT NULL DEFAULT 0,
  coverage TEXT,
  llm_cut INTEGER NOT NULL DEFAULT 0,
  covered_by_pack INTEGER,
  ritual TEXT,
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS requests_project_ts ON requests(project, ts);

CREATE TABLE IF NOT EXISTS retrieval_log (
  id INTEGER PRIMARY KEY,
  request_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('pack','search','fetch','suggestion')),
  section TEXT,
  rank INTEGER,
  score REAL,
  episode_id TEXT,
  project TEXT,
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS rl_node ON retrieval_log(node_id);
CREATE INDEX IF NOT EXISTS rl_req ON retrieval_log(request_id);

CREATE TABLE IF NOT EXISTS citations (
  episode_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  source TEXT NOT NULL,
  request_id TEXT,
  helpful INTEGER,
  outcome_override TEXT,
  PRIMARY KEY (episode_id, node_id)
);

CREATE TABLE IF NOT EXISTS credit_log (
  id INTEGER PRIMARY KEY,
  episode_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  delta_conf REAL NOT NULL,
  confirmed INTEGER NOT NULL,
  promoted INTEGER NOT NULL,
  prev_last_confirmed TEXT,
  prev_status TEXT,
  ts TEXT NOT NULL,
  reversed_ts TEXT
);
CREATE INDEX IF NOT EXISTS credit_episode ON credit_log(episode_id);
CREATE INDEX IF NOT EXISTS credit_node ON credit_log(node_id);

CREATE TABLE IF NOT EXISTS progress_log (
  id INTEGER PRIMARY KEY,
  project TEXT,
  phase TEXT,
  status TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  tool_calls INTEGER NOT NULL DEFAULT 0,
  errors TEXT NOT NULL DEFAULT '[]',
  run_id TEXT,
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS progress_project_ts ON progress_log(project, ts);

CREATE TABLE IF NOT EXISTS suggestions (
  id TEXT PRIMARY KEY,
  trigger TEXT NOT NULL,
  memory_ids TEXT NOT NULL DEFAULT '[]',
  rationale TEXT,
  project TEXT,
  ts TEXT NOT NULL,
  response TEXT CHECK (response IN ('accept','defer','dismiss')),
  responded_ts TEXT,
  consumed_by TEXT,
  delivered INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trigger_state (
  project TEXT NOT NULL,
  trigger TEXT NOT NULL,
  last_fired TEXT,
  tool_calls_at_fire INTEGER,
  tool_calls_total INTEGER NOT NULL DEFAULT 0,
  threshold_bump INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (project, trigger)
);

CREATE TABLE IF NOT EXISTS checkin_queue (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  dedupe_key TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  created TEXT NOT NULL,
  decided TEXT,
  note TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS queue_dedupe ON checkin_queue(dedupe_key)
  WHERE dedupe_key IS NOT NULL AND status = 'pending';

CREATE TABLE IF NOT EXISTS identity_edits (
  id INTEGER PRIMARY KEY,
  node_id TEXT NOT NULL,
  occasion TEXT NOT NULL,
  project TEXT,
  occasion_key TEXT,
  trigger_id TEXT,
  superseded_id TEXT,
  ts TEXT NOT NULL,
  reverted_ts TEXT,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS probes (
  run_id TEXT NOT NULL,
  probe_id TEXT NOT NULL,
  prompt TEXT NOT NULL,
  answer TEXT,
  identity_hash TEXT NOT NULL,
  model TEXT,
  ts TEXT NOT NULL,
  PRIMARY KEY (run_id, probe_id)
);

CREATE TABLE IF NOT EXISTS projects (
  project TEXT PRIMARY KEY,
  opened TEXT NOT NULL,
  closed TEXT
);

CREATE TABLE IF NOT EXISTS maintenance (
  kind TEXT NOT NULL,
  key TEXT NOT NULL,
  ts TEXT NOT NULL,
  report TEXT,
  PRIMARY KEY (kind, key)
);

CREATE TABLE IF NOT EXISTS pending_capture (
  id TEXT PRIMARY KEY,
  signature TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  project TEXT,
  run_id TEXT,
  span TEXT,
  created TEXT NOT NULL,
  cleared TEXT,
  cleared_by TEXT
);

CREATE TABLE IF NOT EXISTS consolidation_log (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  step TEXT NOT NULL,
  report TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
  node_id TEXT PRIMARY KEY REFERENCES nodes(id),
  model TEXT NOT NULL,
  dim INTEGER NOT NULL,
  vector BLOB NOT NULL,
  created TEXT NOT NULL
);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
  node_id UNINDEXED, summary, tags, tokenize='porter unicode61'
);
"""


class Store:
    """A thin wrapper around one sqlite connection with write transactions."""

    def __init__(self, path: Path, conn: sqlite3.Connection):
        self.path = path
        self.conn = conn
        self._fts_mode: Optional[str] = None

    # ── lifecycle ──
    @classmethod
    def open(cls, path: Optional[Path] = None, create: bool = False) -> "Store":
        p = path or default_store_path()
        if p is None:
            raise NoStore("no store path: set IDENTITY_DIR or LIBRARIAN_STORE")
        if not p.exists() and not create:
            raise NoStore(f"no store at {p}")
        if create:
            p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p), timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        store = cls(p, conn)
        if create:
            store.init_schema()
        else:
            try:
                store.conn.execute("SELECT 1 FROM meta LIMIT 1").fetchone()
            except sqlite3.DatabaseError as exc:
                raise StoreError(f"store at {p} is not a librarian store: {exc}") from exc
        return store

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        # One statement at a time: executescript() commits implicitly and would
        # end the write transaction under us.
        with self.write():
            for stmt in SCHEMA.split(";"):
                if stmt.strip():
                    self.conn.execute(stmt)
            mode = "python"
            try:
                self.conn.execute("SAVEPOINT fts")
                self.conn.execute(FTS_SCHEMA)
                self.conn.execute("RELEASE fts")
                mode = "fts5"
            except sqlite3.OperationalError:
                self.conn.execute("ROLLBACK TO fts")
                self.conn.execute("RELEASE fts")
            if self.meta_get("fts_mode") is None:
                self.meta_set("fts_mode", mode)
            if self.meta_get("schema_version") is None:
                self.meta_set("schema_version", str(SCHEMA_VERSION))
            if self.meta_get("created") is None:
                self.meta_set("created", now_iso())

    # ── transactions ──
    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE`` with one retry; raises :class:`StoreBusy`."""
        if self.conn.in_transaction:
            # Nested use: join the outer transaction.
            yield self.conn
            return
        attempts = 0
        while True:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError as exc:
                attempts += 1
                if "locked" in str(exc).lower() and attempts < 2:
                    time.sleep(0.2)
                    continue
                raise StoreBusy(f"store busy: {exc}") from exc
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    # ── helpers ──
    def meta_get(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def meta_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    @property
    def fts_mode(self) -> str:
        if self._fts_mode is None:
            self._fts_mode = self.meta_get("fts_mode") or "python"
            if os.environ.get("LIBRARIAN_FTS", "") == "python":
                self._fts_mode = "python"
        return self._fts_mode

    def q(self, sql: str, params: tuple = ()) -> list:
        return self.conn.execute(sql, params).fetchall()

    def q1(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchone()

    def ex(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)


def row_dict(row: Any) -> dict:
    return {k: row[k] for k in row.keys()}
