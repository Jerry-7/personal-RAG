import unittest

from app.services.routing_recommendations import build_routing_recommendations


def group(**overrides):
    value = {
        "tier": "standard",
        "route": "tool_agent",
        "planning_source": "not_applicable",
        "terminal_run_count": 10,
        "rated_run_count": 5,
        "negative_feedback_count": 3,
        "operational_success_rate": 100.0,
        "user_satisfaction_rate": 100.0,
        "tool_call_count": 10,
        "tool_failure_rate": 0.0,
        "tool_budget_utilization": 60.0,
        "negative_reason_counts": {},
    }
    value.update(overrides)
    return value


def analytics(*groups):
    return {
        "summary": {
            "terminal_run_count": sum(item["terminal_run_count"] for item in groups),
            "rated_run_count": sum(item["rated_run_count"] for item in groups),
        },
        "groups": list(groups),
    }


class RoutingRecommendationTests(unittest.TestCase):
    def test_insufficient_samples_produce_readiness_without_advice(self):
        report = build_routing_recommendations(analytics(group(
            terminal_run_count=9,
            rated_run_count=4,
        )))

        self.assertFalse(report["readiness"]["operational_ready"])
        self.assertFalse(report["readiness"]["feedback_ready"])
        self.assertEqual(report["items"], [])

    def test_low_satisfaction_recommends_tier_upgrade(self):
        report = build_routing_recommendations(analytics(group(
            user_satisfaction_rate=40.0,
            negative_reason_counts={"missing_evidence": 3},
        )))

        item = report["items"][0]
        self.assertEqual(item["action"], "upgrade_tier")
        self.assertIn("missing_evidence", item["reason_codes"])
        self.assertEqual(item["confidence"], "low")

    def test_expert_quality_problem_targets_dynamic_planning(self):
        report = build_routing_recommendations(analytics(group(
            tier="expert",
            route="supervisor",
            planning_source="model",
            user_satisfaction_rate=20.0,
            negative_reason_counts={"incorrect": 4},
            negative_feedback_count=4,
        )))

        self.assertEqual(report["items"][0]["action"], "review_planning")

    def test_slow_and_overcomplicated_feedback_get_specific_actions(self):
        report = build_routing_recommendations(analytics(
            group(
                user_satisfaction_rate=40.0,
                negative_reason_counts={"too_slow": 3},
            ),
            group(
                tier="expert",
                route="supervisor",
                user_satisfaction_rate=40.0,
                negative_reason_counts={"over_complicated": 3},
            ),
        ))

        self.assertEqual(
            {item["action"] for item in report["items"]},
            {"optimize_latency", "simplify_route"},
        )

    def test_reliability_has_priority_over_quality_tuning(self):
        report = build_routing_recommendations(analytics(group(
            operational_success_rate=70.0,
            user_satisfaction_rate=40.0,
            tool_failure_rate=30.0,
        )))

        item = report["items"][0]
        self.assertEqual(item["action"], "investigate_reliability")
        self.assertEqual(
            item["reason_codes"],
            ["low_operational_success", "high_tool_failure"],
        )

    def test_high_quality_low_utilization_recommends_lower_tier_trial(self):
        report = build_routing_recommendations(analytics(group(
            terminal_run_count=20,
            rated_run_count=10,
            operational_success_rate=100.0,
            user_satisfaction_rate=90.0,
            tool_budget_utilization=20.0,
        )))

        item = report["items"][0]
        self.assertEqual(item["action"], "downgrade_tier")
        self.assertEqual(item["confidence"], "medium")

    def test_active_policy_does_not_borrow_previous_policy_samples(self):
        previous = group(
            policy_version=0,
            terminal_run_count=20,
            rated_run_count=10,
            operational_success_rate=70.0,
        )
        current = group(
            policy_version=1,
            terminal_run_count=2,
            rated_run_count=1,
            operational_success_rate=50.0,
        )

        report = build_routing_recommendations(
            analytics(previous, current),
            policy_version=1,
        )

        self.assertEqual(report["policy_version"], 1)
        self.assertEqual(report["readiness"]["terminal_run_count"], 2)
        self.assertEqual(report["readiness"]["rated_run_count"], 1)
        self.assertFalse(report["readiness"]["operational_ready"])
        self.assertEqual(report["items"], [])
