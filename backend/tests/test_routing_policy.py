import importlib.util
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.agent.routing import ComplexityRouter, RoutingPolicy
from app.db.database import Base
from app.services.routing_policy import (
    RoutingPolicyConflict,
    create_routing_policy,
    get_active_routing_policy,
    list_routing_policies,
    rollback_routing_policy,
)


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
