import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.agent.routing import ComplexityRouter, RoutingPolicy
from app.db.database import Base
from app.db.models import RoutingPolicyConclusion, RoutingPolicyVersion
from app.schemas.routing_policy import RoutingPolicySimulation
from app.services.routing_policy import (
    RoutingPolicyConflict,
    create_routing_policy,
    get_active_routing_policy,
    list_routing_policies,
    rollback_routing_policy,
)
from app.services.routing_policy_conclusion import (
    RoutingPolicyConclusionConflict,
    conclude_routing_policy_experiment,
)
from app.services.routing_policy_evaluation import (
    build_policy_experiment,
    simulate_routing_policy,
)


def observed_policy(version, **overrides):
    metrics = {
        "terminal_run_count": 10,
        "rated_run_count": 5,
        "operational_success_rate": 95.0,
        "average_duration_ms": 1000,
        "tool_failure_rate": 5.0,
        "tool_budget_utilization": 50.0,
        "user_satisfaction_rate": 90.0,
    }
    metrics.update(overrides)
    return {"version": version, "metrics": metrics}


class RoutingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_default_policy_is_implicit_and_visible(self):
        policy = get_active_routing_policy(self.db)
        report = list_routing_policies(self.db)

        self.assertEqual(policy, RoutingPolicy())
        self.assertEqual(report["current"]["version"], 0)
        self.assertEqual(report["current"]["source"], "default")
        self.assertEqual(report["versions"], [])

    def test_create_policy_is_append_only_and_checks_active_version(self):
        first = create_routing_policy(
            self.db,
            standard_min_score=3,
            expert_min_score=5,
            expected_active_version=0,
            note="conservative trial",
        )
        self.assertEqual(first.version, 1)
        self.assertEqual(first.based_on_version, 0)
        self.assertEqual(get_active_routing_policy(self.db), RoutingPolicy(1, 3, 5))

        with self.assertRaises(RoutingPolicyConflict):
            create_routing_policy(
                self.db,
                standard_min_score=2,
                expert_min_score=4,
                expected_active_version=0,
            )

    def test_rollback_creates_a_new_auditable_version(self):
        first = create_routing_policy(
            self.db,
            standard_min_score=3,
            expert_min_score=5,
            expected_active_version=0,
        )
        second = create_routing_policy(
            self.db,
            standard_min_score=2,
            expert_min_score=3,
            expected_active_version=first.version,
        )
        rollback = rollback_routing_policy(
            self.db,
            target_version=first.version,
            expected_active_version=second.version,
            note="restore stable thresholds",
        )

        self.assertEqual(rollback.version, 3)
        self.assertEqual(rollback.source, "rollback")
        self.assertEqual(rollback.based_on_version, 1)
        self.assertEqual((rollback.standard_min_score, rollback.expert_min_score), (3, 5))
        self.assertEqual(
            [item["version"] for item in list_routing_policies(self.db)["versions"]],
            [3, 2, 1],
        )

    def test_policy_thresholds_change_auto_route_not_manual_override(self):
        router = ComplexityRouter(RoutingPolicy(7, 3, 5))
        question = "请分析这个方案"

        self.assertEqual(ComplexityRouter().route(question).tier, "standard")
        automatic = router.route(question)
        manual = router.route(question, tier_preference="expert")

        self.assertEqual(automatic.tier, "fast")
        self.assertEqual(automatic.policy_version, 7)
        self.assertEqual(manual.tier, "expert")
        self.assertEqual(manual.policy_version, 7)

    def test_simulation_excludes_manual_and_non_terminal_runs(self):
        def run(**values):
            defaults = {
                "status": "completed",
                "route_tier_preference": "auto",
                "route_tier": "standard",
                "route_score": 2,
                "mode": "auto",
                "route_policy_version": 0,
            }
            defaults.update(values)
            return SimpleNamespace(**defaults)

        runs = [
            run(route_tier="standard", route_score=2),
            run(route_tier="expert", route_score=4),
            run(route_tier="standard", route_score=2, mode="web"),
            run(route_tier="expert", route_score=1, route_tier_preference="expert"),
            run(route_tier="standard", route_score=0),
            run(status="running", route_tier="standard", route_score=2),
        ]

        result = simulate_routing_policy(
            runs,
            standard_min_score=3,
            expert_min_score=5,
        )

        self.assertEqual(result["eligibility"], {
            "sample_limit": 6,
            "terminal_run_count": 5,
            "eligible_auto_run_count": 3,
            "excluded_manual_override_count": 1,
            "excluded_baseline_mismatch_count": 1,
            "excluded_non_terminal_count": 1,
        })
        self.assertEqual(result["projected_tier_counts"], {
            "fast": 1,
            "standard": 2,
            "expert": 0,
        })
        self.assertEqual(result["changed_run_count"], 2)
        self.assertEqual(result["upgrade_run_count"], 0)
        self.assertEqual(result["downgrade_run_count"], 2)
        self.assertTrue(result["is_counterfactual"])
        self.assertIsNone(result["quality_prediction"])

    def test_simulation_threshold_order_is_validated(self):
        with self.assertRaises(ValidationError):
            RoutingPolicySimulation(
                standard_min_score=5,
                expert_min_score=3,
            )

    def test_experiment_collects_runs_then_feedback(self):
        policy = {"version": 2, "source": "manual", "based_on_version": 1}
        collecting = build_policy_experiment(
            policy,
            [observed_policy(2, terminal_run_count=4, rated_run_count=1)],
        )
        awaiting_feedback = build_policy_experiment(
            policy,
            [observed_policy(2, rated_run_count=2)],
        )

        self.assertEqual(collecting["status"], "collecting")
        self.assertEqual(collecting["recommendation"], "collect_runs")
        self.assertEqual(awaiting_feedback["status"], "awaiting_feedback")
        self.assertEqual(awaiting_feedback["recommendation"], "collect_feedback")

    def test_experiment_flags_severe_operational_regression_early(self):
        result = build_policy_experiment(
            {"version": 2, "source": "manual", "based_on_version": 1},
            [
                observed_policy(1, operational_success_rate=95.0),
                observed_policy(
                    2,
                    rated_run_count=0,
                    operational_success_rate=65.0,
                ),
            ],
        )

        self.assertEqual(result["status"], "operational_alert")
        self.assertEqual(result["recommendation"], "rollback")
        self.assertEqual(result["comparison"]["operational_success_rate_delta"], -30.0)

    def test_ready_experiment_keeps_stable_policy_and_rejects_low_quality(self):
        policy = {"version": 2, "source": "manual", "based_on_version": 1}
        baseline = observed_policy(1)
        stable = build_policy_experiment(policy, [baseline, observed_policy(2)])
        low_quality = build_policy_experiment(
            policy,
            [baseline, observed_policy(2, user_satisfaction_rate=40.0)],
        )

        self.assertEqual(stable["status"], "ready")
        self.assertEqual(stable["recommendation"], "keep")
        self.assertEqual(low_quality["recommendation"], "rollback")
        self.assertIn("quality_regression", low_quality["reason_codes"])

    def test_experiment_cannot_be_concluded_before_it_is_ready(self):
        policy = create_routing_policy(
            self.db,
            standard_min_score=3,
            expert_min_score=5,
            expected_active_version=0,
        )

        with self.assertRaisesRegex(RoutingPolicyConclusionConflict, "not ready"):
            conclude_routing_policy_experiment(
                self.db,
                policy_version=policy.version,
                expected_active_version=policy.version,
                decision="keep",
                experiment={
                    "current_policy_version": policy.version,
                    "baseline_policy_version": 0,
                    "status": "collecting",
                    "recommendation": "collect_runs",
                },
            )

        self.assertEqual(self.db.query(RoutingPolicyConclusion).count(), 0)

    def test_keep_conclusion_preserves_policy_and_evidence(self):
        policy = create_routing_policy(
            self.db,
            standard_min_score=3,
            expert_min_score=5,
            expected_active_version=0,
        )
        experiment = {
            "current_policy_version": policy.version,
            "baseline_policy_version": 0,
            "status": "ready",
            "recommendation": "keep",
            "reason_codes": ["stable"],
        }

        conclusion, resulting_policy = conclude_routing_policy_experiment(
            self.db,
            policy_version=policy.version,
            expected_active_version=policy.version,
            decision="keep",
            experiment=experiment,
        )

        self.assertIsNone(resulting_policy)
        self.assertEqual(conclusion.policy_version, policy.version)
        self.assertIn('\"reason_codes\": [\"stable\"]', conclusion.evidence_json)
        self.assertEqual(get_active_routing_policy(self.db).version, policy.version)
        with self.assertRaisesRegex(RoutingPolicyConclusionConflict, "already"):
            conclude_routing_policy_experiment(
                self.db,
                policy_version=policy.version,
                expected_active_version=policy.version,
                decision="keep",
                experiment=experiment,
            )

    def test_alert_conclusion_rolls_back_and_records_one_transaction(self):
        policy = create_routing_policy(
            self.db,
            standard_min_score=3,
            expert_min_score=5,
            expected_active_version=0,
        )

        conclusion, rollback = conclude_routing_policy_experiment(
            self.db,
            policy_version=policy.version,
            expected_active_version=policy.version,
            decision="rollback",
            experiment={
                "current_policy_version": policy.version,
                "baseline_policy_version": 0,
                "status": "operational_alert",
                "recommendation": "rollback",
                "reason_codes": ["success_rate_regression"],
            },
        )

        self.assertIsNotNone(rollback)
        assert rollback is not None
        self.assertEqual(rollback.version, 2)
        self.assertEqual(rollback.source, "rollback")
        self.assertEqual(rollback.based_on_version, 0)
        self.assertEqual(conclusion.resulting_policy_version, rollback.version)
        self.assertEqual(get_active_routing_policy(self.db).version, rollback.version)
        original = self.db.get(RoutingPolicyVersion, policy.version)
        assert original is not None
        self.assertFalse(original.is_active)

    def test_guarded_recommendation_override_requires_note(self):
        policy = create_routing_policy(
            self.db,
            standard_min_score=3,
            expert_min_score=5,
            expected_active_version=0,
        )
        experiment = {
            "current_policy_version": policy.version,
            "baseline_policy_version": 0,
            "status": "ready",
            "recommendation": "rollback",
        }

        with self.assertRaisesRegex(RoutingPolicyConclusionConflict, "note"):
            conclude_routing_policy_experiment(
                self.db,
                policy_version=policy.version,
                expected_active_version=policy.version,
                decision="keep",
                experiment=experiment,
            )

        conclusion, _ = conclude_routing_policy_experiment(
            self.db,
            policy_version=policy.version,
            expected_active_version=policy.version,
            decision="keep",
            experiment=experiment,
            note="Reviewed the failed samples manually",
        )
        self.assertEqual(conclusion.note, "Reviewed the failed samples manually")


class RoutingPolicyMigrationTests(unittest.TestCase):
    def test_migration_is_idempotent_and_backfills_legacy_runs(self):
        engine = create_engine("sqlite:///:memory:")
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "20260815_08_routing_policy_versions.py"
        )
        spec = importlib.util.spec_from_file_location("routing_policy_migration", migration_path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE agent_runs (id VARCHAR(36) PRIMARY KEY)"
            ))
            connection.execute(text("INSERT INTO agent_runs VALUES ('legacy-run')"))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            migration.upgrade()

            self.assertTrue(inspect(connection).has_table("routing_policy_versions"))
            self.assertIn(
                "route_policy_version",
                {column["name"] for column in inspect(connection).get_columns("agent_runs")},
            )
            self.assertEqual(connection.execute(text(
                "SELECT route_policy_version FROM agent_runs WHERE id = 'legacy-run'"
            )).scalar_one(), 0)
        engine.dispose()

    def test_conclusion_migration_is_idempotent(self):
        engine = create_engine("sqlite:///:memory:")
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "20260815_09_routing_policy_conclusions.py"
        )
        spec = importlib.util.spec_from_file_location(
            "routing_policy_conclusion_migration",
            migration_path,
        )
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE routing_policy_versions (version INTEGER PRIMARY KEY)"
            ))
            connection.execute(text(
                "INSERT INTO routing_policy_versions (version) VALUES (1)"
            ))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            migration.upgrade()

            inspector = inspect(connection)
            self.assertTrue(inspector.has_table("routing_policy_conclusions"))
            self.assertEqual(
                {
                    "id",
                    "policy_version",
                    "baseline_version",
                    "decision",
                    "resulting_policy_version",
                    "evidence_json",
                    "note",
                    "created_at",
                },
                {
                    column["name"]
                    for column in inspector.get_columns("routing_policy_conclusions")
                },
            )
        engine.dispose()
