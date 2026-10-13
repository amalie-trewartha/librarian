import os
import sqlite3
import threading
import time
import unittest

from helpers import StoreCase, T0
from librarian import db


class ClockTest(StoreCase):
    def test_librarian_now_pin_wins(self):
        os.environ["PROJECT_NOW"] = "1800000000"
        self.assertEqual(db.now_iso(), T0)

    def test_project_now_epoch(self):
        os.environ.pop("LIBRARIAN_NOW")
        os.environ["PROJECT_NOW"] = "1800000000"
        self.assertEqual(db.now_iso(), "2027-01-15T08:00:00Z")

    def test_scaled_project_clock(self):
        os.environ.pop("LIBRARIAN_NOW")
        os.environ["PROJECT_STARTED_AT"] = "1000"
        os.environ["PROJECT_REAL_NOW"] = "1100"
        os.environ["PROJECT_TIME_SCALE"] = "48"
        self.assertEqual(int(db.now().timestamp()), 1000 + 100 * 48)

    def test_scaled_clock_reads_started_at_file(self):
        os.environ.pop("LIBRARIAN_NOW")
        (self.ident / "project-pristine").mkdir()
        (self.ident / "project-pristine" / "started_at").write_text("2000\n")
        os.environ["PROJECT_REAL_NOW"] = "2010"
        os.environ["PROJECT_TIME_SCALE"] = "10"
        self.assertEqual(int(db.now().timestamp()), 2100)

    def test_parse_ts_variants(self):
        self.assertEqual(db.iso(db.parse_ts("2026-05-16T13:26:06.846-0700")), "2026-05-16T20:26:06Z")
        self.assertEqual(db.iso(db.parse_ts("2026-10-02")), "2026-10-02T00:00:00Z")
        self.assertIsNone(db.parse_ts("garbage"))
        self.assertAlmostEqual(db.age_days("2026-09-30T00:00:00Z"), 1.0)


class UlidTest(StoreCase):
    def test_ulid_shape_and_monotonic_under_pinned_clock(self):
        ids = [db.ulid() for _ in range(50)]
        self.assertTrue(all(db.is_ulid(i) for i in ids))
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 50)

    def test_ulid_time_prefix_follows_clock(self):
        a = db.ulid()
        self.at("2026-10-02T00:00:00Z")
        b = db.ulid()
        self.assertLess(a[:10], b[:10])


class StoreTest(StoreCase):
    def test_schema_and_fts_mode(self):
        self.assertIn(self.store.fts_mode, ("fts5", "python"))
        self.assertEqual(self.store.meta_get("schema_version"), str(db.SCHEMA_VERSION))
        tables = {r[0] for r in self.store.q("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for t in ("nodes", "tags", "edges", "requests", "retrieval_log", "citations", "credit_log", "checkin_queue", "maintenance", "pending_capture", "embeddings"):
            self.assertIn(t, tables)

    def test_init_is_idempotent(self):
        again = db.Store.open(self.store.path, create=True)
        self.assertEqual(again.meta_get("fts_mode"), self.store.fts_mode)
        again.close()

    def test_missing_store_raises(self):
        with self.assertRaises(db.NoStore):
            db.Store.open(self.ident / "nope.sqlite")

    def test_default_path_from_identity(self):
        self.assertEqual(db.default_store_path(), self.ident / "librarian" / "store.sqlite")
        os.environ["LIBRARIAN_STORE"] = "/x/y.sqlite"
        self.assertEqual(str(db.default_store_path()), "/x/y.sqlite")

    def test_write_retries_then_raises_busy(self):
        other = sqlite3.connect(str(self.store.path), isolation_level=None, timeout=0.1)
        other.execute("BEGIN IMMEDIATE")
        self.store.conn.execute("PRAGMA busy_timeout=50")
        t0 = time.time()
        with self.assertRaises(db.StoreBusy):
            with self.store.write():
                pass
        self.assertGreater(time.time() - t0, 0.15)  # one retry happened
        other.execute("ROLLBACK")
        other.close()
        with self.store.write():
            self.store.meta_set("x", "1")
        self.assertEqual(self.store.meta_get("x"), "1")

    def test_concurrent_writers_serialize(self):
        errors = []

        def worker(n):
            try:
                s = db.Store.open(self.store.path)
                for i in range(5):
                    with s.write():
                        s.meta_set(f"w{n}-{i}", "1")
                s.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.store.q1("SELECT COUNT(*) FROM meta WHERE key LIKE 'w%'")[0], 20)

    def test_python_fts_fallback_forced(self):
        os.environ["LIBRARIAN_FTS"] = "python"
        s = db.Store.open(self.store.path)
        self.assertEqual(s.fts_mode, "python")
        s.close()


if __name__ == "__main__":
    unittest.main()
