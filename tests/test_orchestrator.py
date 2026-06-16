import tempfile
import unittest
from pathlib import Path

from series_cloud_archiver.config import ScanConfig
from series_cloud_archiver.orchestrator import evaluate, list_status, plan_cleanup, status_detail


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")


class OrchestratorTest(unittest.TestCase):
    def test_evaluate_stores_all_rows_even_when_output_is_limited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "TV"
            for name in ["A.Show.S01.Complete", "B.Show.S01.Complete"]:
                show = root / name
                for index in range(1, 3):
                    touch(show / f"{name}.S01E{index:02d}.mkv")
            db_path = str(tmp_path / "state.sqlite3")

            report = evaluate(
                ScanConfig(
                    media_roots=[str(root)],
                    include_qb=False,
                    min_seed_days=0,
                    min_age_days=0,
                    max_depth=2,
                    top=1,
                ),
                db_path,
            )

            self.assertEqual(len(report.candidates), 1)
            self.assertEqual(len(list_status(db_path, limit=10)), 2)

    def test_cleanup_plan_is_blocked_without_required_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "TV"
            show = root / "A.Show.S01.Complete"
            for index in range(1, 3):
                touch(show / f"A.Show.S01E{index:02d}.mkv")
            db_path = str(tmp_path / "state.sqlite3")

            evaluate(
                ScanConfig(
                    media_roots=[str(root)],
                    include_qb=False,
                    min_seed_days=0,
                    min_age_days=0,
                    max_depth=2,
                    top=0,
                ),
                db_path,
            )
            plan = plan_cleanup(db_path, "A.Show")

            self.assertTrue(plan["found"])
            self.assertEqual(plan["status"], "blocked")
            self.assertEqual(plan["deletion_targets"], [])
            self.assertIn("missing_mv3_strm_evidence", plan["blockers"])
            self.assertIn("manual_approval_required", plan["blockers"])

            detail = status_detail(db_path, "A.Show")
            self.assertTrue(detail["found"])
            self.assertTrue(any(event["event_type"] == "cleanup_plan_created" for event in detail["audit"]))


if __name__ == "__main__":
    unittest.main()
