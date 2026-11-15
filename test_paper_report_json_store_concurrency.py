"""Concurrency regression tests for report-history storage."""
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from paper_report_history import build_report_snapshot
from paper_report_json_store import load_report_history, save_report_history


def _process_append(path, first, candidate, queue):
    try:
        save_report_history(path, [first, candidate])
        queue.put("saved")
    except ValueError as exc:
        if "preserve all existing entries" in str(exc):
            queue.put("conflict")
        else:
            queue.put(f"error: {exc}")


class PaperReportJsonStoreConcurrencyTests(unittest.TestCase):
    def test_concurrent_conflicting_appends_cannot_silently_lose_an_update(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            first = build_report_snapshot(
                {"equity_usdt": "1000"},
                "2026-11-15T10:00:00Z",
                "concurrent-001",
            )
            second = build_report_snapshot(
                {"equity_usdt": "1010"},
                "2026-11-15T10:01:00Z",
                "concurrent-002",
            )
            third = build_report_snapshot(
                {"equity_usdt": "1020"},
                "2026-11-15T10:02:00Z",
                "concurrent-003",
            )
            save_report_history(path, [first])

            def append(candidate):
                try:
                    save_report_history(path, [first, candidate])
                    return "saved"
                except ValueError as exc:
                    if "preserve all existing entries" in str(exc):
                        return "conflict"
                    raise

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(append, (second, third)))

            self.assertCountEqual(results, ["saved", "conflict"])
            final_history = load_report_history(path)
            self.assertEqual(len(final_history), 2)
            self.assertEqual(final_history[0], first)
            self.assertIn(final_history[1], (second, third))


    def test_concurrent_appends_from_separate_processes_are_serialized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "history.json")
            first = build_report_snapshot(
                {"equity_usdt": "1000"},
                "2026-11-15T10:00:00Z",
                "process-001",
            )
            second = build_report_snapshot(
                {"equity_usdt": "1010"},
                "2026-11-15T10:01:00Z",
                "process-002",
            )
            third = build_report_snapshot(
                {"equity_usdt": "1020"},
                "2026-11-15T10:02:00Z",
                "process-003",
            )
            save_report_history(path, [first])
            context = multiprocessing.get_context("spawn")
            queue = context.Queue()
            processes = [
                context.Process(target=_process_append, args=(path, first, item, queue))
                for item in (second, third)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(15)
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join()
                    self.fail("concurrent writer process did not finish")
                self.assertEqual(process.exitcode, 0)
            results = [queue.get(timeout=2) for _ in processes]
            queue.close()
            self.assertCountEqual(results, ["saved", "conflict"])
            final_history = load_report_history(path)
            self.assertEqual(len(final_history), 2)
            self.assertEqual(final_history[0], first)
            self.assertIn(final_history[1], (second, third))


if __name__ == "__main__":
    unittest.main()
