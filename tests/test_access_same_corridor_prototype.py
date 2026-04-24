import json
import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

from src.active.context_enrichment_access_same_corridor_prototype import (
    _reviewed_family_candidate_decision,
)
from src.active.context_enrichment import _same_corridor_candidate_decision


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE_ROOT = REPO_ROOT / "work" / "output" / "context_enrichment_access_same_corridor_prototype"
CONTEXT_ROOT = REPO_ROOT / "work" / "output" / "context_enrichment"
GUARDRAIL_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "access_same_corridor_pre_promotion_guardrails"


def _read_csv(relative_path: str) -> pd.DataFrame:
    return pd.read_csv(REPO_ROOT / relative_path)


def _read_fixture_csv(filename: str) -> pd.DataFrame:
    return pd.read_csv(GUARDRAIL_FIXTURE_ROOT / filename)


class SameCorridorPrototypeDecisionTests(unittest.TestCase):
    def test_include_family_candidate_is_supported(self):
        decision = _reviewed_family_candidate_decision(
            [
                {
                    "StudyRoad_RowID": 1,
                    "approved_pair": True,
                    "within_threshold": True,
                    "distance_ft": 0.1,
                },
                {
                    "StudyRoad_RowID": 2,
                    "approved_pair": False,
                    "within_threshold": False,
                    "distance_ft": 12.0,
                },
            ]
        )
        self.assertEqual(decision["status"], "candidate_supported")
        self.assertEqual(decision["winner"]["StudyRoad_RowID"], 1)

    def test_refuses_when_approved_route_absent(self):
        decision = _reviewed_family_candidate_decision(
            [
                {
                    "StudyRoad_RowID": 1,
                    "approved_pair": False,
                    "within_threshold": False,
                    "distance_ft": 0.1,
                }
            ]
        )
        self.assertEqual(decision["status"], "approved_study_route_not_present")

    def test_refuses_multiple_rows_within_threshold(self):
        decision = _reviewed_family_candidate_decision(
            [
                {
                    "StudyRoad_RowID": 1,
                    "approved_pair": True,
                    "within_threshold": True,
                    "distance_ft": 0.1,
                },
                {
                    "StudyRoad_RowID": 2,
                    "approved_pair": True,
                    "within_threshold": True,
                    "distance_ft": 0.2,
                },
            ]
        )
        self.assertEqual(decision["status"], "ambiguous_local_geometry")

    def test_refuses_when_nearest_row_is_not_approved(self):
        decision = _reviewed_family_candidate_decision(
            [
                {
                    "StudyRoad_RowID": 1,
                    "approved_pair": False,
                    "within_threshold": False,
                    "distance_ft": 0.1,
                },
                {
                    "StudyRoad_RowID": 2,
                    "approved_pair": True,
                    "within_threshold": True,
                    "distance_ft": 0.5,
                },
            ]
        )
        self.assertEqual(decision["status"], "nearest_row_not_approved_pair")

    def test_refuses_missing_projection_or_flow(self):
        decision = _reviewed_family_candidate_decision(
            [
                {
                    "StudyRoad_RowID": 1,
                    "approved_pair": True,
                    "within_threshold": True,
                    "distance_ft": 0.1,
                }
            ],
            signal_projection_supported=False,
        )
        self.assertEqual(decision["status"], "missing_flow_or_projection")

    def test_production_decision_helper_matches_reviewed_family_refusal_modes(self):
        decision = _same_corridor_candidate_decision(
            [
                {
                    "StudyRoad_RowID": 1,
                    "approved_pair": False,
                    "within_threshold": False,
                    "distance_ft": 0.1,
                },
                {
                    "StudyRoad_RowID": 2,
                    "approved_pair": True,
                    "within_threshold": True,
                    "distance_ft": 0.5,
                },
            ]
        )
        self.assertEqual(decision["status"], "nearest_row_not_approved_pair")


class SameCorridorPrototypeOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assignments = _read_fixture_csv("same_corridor_prototype_assignments.csv")
        cls.family_table = _read_fixture_csv("reviewed_same_corridor_family_table.csv")
        cls.signal_impact = _read_fixture_csv("signal_approach_impact_summary.csv")
        cls.approach_impact = _read_fixture_csv("approach_row_impact_summary.csv")
        cls.broad_diagnostic = _read_fixture_csv("all_route_conflict_local_geometry_diagnostic.csv")

    def test_guardrail_fixture_manifest_hashes_match(self):
        manifest_path = GUARDRAIL_FIXTURE_ROOT / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for filename, expected in manifest["files"].items():
            payload = (GUARDRAIL_FIXTURE_ROOT / filename).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), expected["sha256"], filename)
            self.assertEqual(len(payload), expected["bytes"], filename)

    def test_reviewed_family_regression_counts(self):
        recovered = self.assignments[self.assignments["Prototype_Recovered"].astype(bool)]
        self.assertEqual(int((self.assignments["Access_AssignmentStatus"] == "route_conflict").sum()), 288)
        self.assertEqual(int((self.assignments["Prototype_Evaluated"].astype(bool)).sum()), 66)
        self.assertEqual(len(recovered), 55)
        self.assertEqual(recovered["Access_PointID"].nunique(), 52)
        self.assertEqual(
            self.assignments["Prototype_EffectiveAssignmentStatus"].value_counts().to_dict(),
            {"route_conflict": 233, "matched": 110, "near_signal": 16, "measure_conflict": 3},
        )

    def test_reviewed_family_eligibility_statuses(self):
        included = self.assignments[self.assignments["Prototype_ReviewDecision"] == "include"]
        excluded = self.assignments[self.assignments["Prototype_AssignmentStatus"] == "family_excluded"]
        unreviewed = self.assignments[self.assignments["Prototype_AssignmentStatus"] == "no_reviewed_family"]

        self.assertEqual(len(included), 66)
        self.assertEqual(int(included["Prototype_Recovered"].astype(bool).sum()), 55)
        self.assertEqual(len(excluded), 83)
        self.assertEqual(int(excluded["Prototype_Recovered"].astype(bool).sum()), 0)
        self.assertEqual(len(unreviewed), 139)
        self.assertEqual(int(unreviewed["Prototype_Recovered"].astype(bool).sum()), 0)

    def test_opposite_direction_exclusions_remain_unmatched(self):
        excluded_keys = {
            "us00058_alt_opposite_direction",
            "us00019_opposite_direction",
            "us00250_opposite_direction",
        }
        reviewed = self.family_table[self.family_table["FamilyKey"].isin(excluded_keys)]
        self.assertEqual(set(reviewed["ReviewDecision"]), {"exclude"})

        affected = self.assignments[
            self.assignments["Prototype_FamilyKeysAvailable"].fillna("").apply(
                lambda value: any(key in value for key in excluded_keys)
            )
        ]
        self.assertFalse(affected.empty)
        self.assertEqual(int(affected["Prototype_Recovered"].astype(bool).sum()), 0)
        self.assertTrue((affected["Prototype_EffectiveAssignmentStatus"] == "route_conflict").all())

    def test_geometry_threshold_behavior(self):
        recovered = self.assignments[self.assignments["Prototype_Recovered"].astype(bool)]
        self.assertLessEqual(float(recovered["Prototype_ToRowDistanceFt"].max()), 5.0)

        offset_families = {"richmond_hwy__us00001nb", "w_broad_st_pr__us00250eb"}
        offset = self.assignments[
            self.assignments["Prototype_FamilyKeysAvailable"].fillna("").apply(
                lambda value: any(key in value for key in offset_families)
            )
        ]
        self.assertFalse(offset.empty)
        self.assertEqual(int(offset["Prototype_Recovered"].astype(bool).sum()), 0)

    def test_broad_diagnostic_guard_is_not_production(self):
        recovered = self.broad_diagnostic[
            self.broad_diagnostic["Status"].isin(["recovered_matched", "recovered_near_signal"])
        ]
        self.assertEqual(len(recovered), 110)
        self.assertGreater(len(recovered), int(self.assignments["Prototype_Recovered"].astype(bool).sum()))

        broad_only_routes = set(recovered["Access_Route_Normalized"]) - set(
            self.assignments.loc[self.assignments["Prototype_Recovered"].astype(bool), "Access_Route_Normalized"]
        )
        self.assertIn("R-VA US00058WBALT001", broad_only_routes)
        production_recovered_routes = set(
            self.assignments.loc[self.assignments["Prototype_Recovered"].astype(bool), "Access_Route_Normalized"]
        )
        self.assertNotIn("R-VA US00058WBALT001", production_recovered_routes)

    def test_signal_and_approach_impact_regression(self):
        signal_changed = self.signal_impact[self.signal_impact["SignalAccessCountDelta"] > 0]
        row_changed = self.approach_impact[self.approach_impact["ApproachRowAccessCountDelta"] > 0]

        self.assertEqual(len(signal_changed), 18)
        self.assertEqual(len(row_changed), 18)
        self.assertEqual(int(signal_changed["SignalAccessCountDelta"].max()), 9)
        self.assertEqual(int(row_changed["ApproachRowAccessCountDelta"].max()), 9)

    def test_map_review_geojsons_cover_review_targets(self):
        recovered_path = GUARDRAIL_FIXTURE_ROOT / "recovered_same_corridor_assignments.geojson"
        refused_path = GUARDRAIL_FIXTURE_ROOT / "refused_same_corridor_candidates.geojson"
        self.assertTrue(recovered_path.exists())
        self.assertTrue(refused_path.exists())

        recovered_geo = json.loads(recovered_path.read_text(encoding="utf-8"))
        refused_geo = json.loads(refused_path.read_text(encoding="utf-8"))
        self.assertEqual(len(recovered_geo["features"]), 55)
        self.assertEqual(len(refused_geo["features"]), 11)

        recovered_families = {
            feature["properties"]["Prototype_FamilyKey"] for feature in recovered_geo["features"]
        }
        expected_recovered_families = set(
            self.family_table.loc[self.family_table["ReviewDecision"] == "include", "FamilyKey"]
        )
        self.assertEqual(recovered_families, expected_recovered_families)


class ContextEnrichmentOutputTests(unittest.TestCase):
    def test_promoted_production_counts_match_prototype_guardrails(self):
        access = _read_csv("work/output/context_enrichment/tables/current/access_assignment_points.csv")
        self.assertEqual(
            access["Access_AssignmentStatus"].value_counts().to_dict(),
            {"route_conflict": 233, "matched": 110, "near_signal": 16, "measure_conflict": 3},
        )

        recovered = access[access["Access_SameCorridorReviewStatus"].eq("recovered")]
        self.assertEqual(len(recovered), 55)
        self.assertEqual(recovered["Access_PointID"].nunique(), 52)
        self.assertEqual(int(recovered["Access_ToRowDistanceFt"].max() <= 5.0), 1)
        self.assertEqual(
            recovered["Access_SignalRelativePosition"].value_counts().to_dict(),
            {"downstream": 28, "upstream": 19, "near_signal": 8},
        )

        refused = access[access["Access_SameCorridorReviewStatus"].eq("approved_study_route_not_present")]
        self.assertEqual(len(refused), 11)
        self.assertTrue(refused["Access_AssignmentStatus"].eq("route_conflict").all())

    def test_promoted_production_keeps_excluded_opposite_direction_unmatched(self):
        access = _read_csv("work/output/context_enrichment/tables/current/access_assignment_points.csv")
        excluded_keys = {
            "us00058_alt_opposite_direction",
            "us00019_opposite_direction",
            "us00250_opposite_direction",
        }
        excluded = access[
            access["Access_SameCorridorFamilyKey"].fillna("").apply(
                lambda value: any(key in value for key in excluded_keys)
            )
        ]
        self.assertFalse(excluded.empty)
        self.assertTrue(excluded["Access_SameCorridorReviewStatus"].eq("family_excluded").all())
        self.assertTrue(excluded["Access_AssignmentStatus"].eq("route_conflict").all())

    def test_current_history_idempotence_for_context_enrichment(self):
        current_path = CONTEXT_ROOT / "runs" / "current" / "context_enrichment_run_summary.json"
        history_dir = CONTEXT_ROOT / "runs" / "history"
        before_history = set(history_dir.glob("context_enrichment_run_summary*.json"))

        subprocess.run(
            [sys.executable, "-m", "src.active.context_enrichment"],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        after_history = set(history_dir.glob("context_enrichment_run_summary*.json"))
        self.assertTrue(current_path.exists())
        self.assertGreater(len(after_history), len(before_history))
        summary = json.loads(current_path.read_text(encoding="utf-8"))
        for output_path in summary["output_files"].values():
            self.assertTrue(Path(output_path).exists(), output_path)

    def test_crash_context_access_counts_match_approach_and_signal_summaries(self):
        approach = _read_csv("work/output/context_enrichment/tables/current/approach_row_context_enriched.csv")
        signal = _read_csv("work/output/context_enrichment/tables/current/signal_study_area_context_enriched.csv")
        crashes = _read_csv("work/output/context_enrichment/tables/current/classified_crash_context_enriched.csv")

        approach_counts = approach[
            [
                "StudyAreaID",
                "StudyRoad_RowID",
                "Access_Count_Total",
                "Access_Count_Upstream",
                "Access_Count_Downstream",
                "Access_Count_NearSignal",
                "Access_Count_Unresolved",
            ]
        ].drop_duplicates()
        crash_approach = crashes.merge(
            approach_counts,
            on=["StudyAreaID", "StudyRoad_RowID"],
            suffixes=("", "_ApproachExpected"),
            how="left",
            validate="many_to_one",
        )
        for column in (
            "Access_Count_Total",
            "Access_Count_Upstream",
            "Access_Count_Downstream",
            "Access_Count_NearSignal",
            "Access_Count_Unresolved",
        ):
            self.assertTrue((crash_approach[column] == crash_approach[f"{column}_ApproachExpected"]).all(), column)

        signal_counts = signal[
            [
                "StudyAreaID",
                "Access_Count_Total",
                "Access_Count_Upstream",
                "Access_Count_Downstream",
                "Access_Count_NearSignal",
                "Access_Count_Unresolved",
            ]
        ].drop_duplicates()
        crash_signal = crashes.merge(
            signal_counts,
            on="StudyAreaID",
            suffixes=("", "_SignalExpected"),
            how="left",
            validate="many_to_one",
        )
        for column in (
            "Access_Count_Total",
            "Access_Count_Upstream",
            "Access_Count_Downstream",
            "Access_Count_NearSignal",
            "Access_Count_Unresolved",
        ):
            signal_column = f"Signal_{column}"
            self.assertTrue((crash_signal[signal_column] == crash_signal[f"{column}_SignalExpected"]).all(), signal_column)


if __name__ == "__main__":
    unittest.main()
