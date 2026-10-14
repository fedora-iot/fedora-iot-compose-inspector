import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import Mock, patch

from ai_analysis import analyze_log_source, format_issue_report, parse_ai_json
from utils import prioritize_items


with patch.dict(os.environ, {
    "AI_MODEL_CONFIG": "/tmp/fedora-iot-inspector-test-missing-models.json",
    "MY_GITHUB_TOKEN": "",
}), patch("github.Github.get_user", side_effect=RuntimeError("No network in tests")):
    with contextlib.redirect_stdout(io.StringIO()):
        import check_fedora_iot as inspector


class ReviewFixTests(unittest.TestCase):
    def test_ai_json_requires_an_object(self):
        for response in ("[]", "[{}]", "null", '"text"'):
            with self.subTest(response=response), self.assertRaises(ValueError):
                parse_ai_json(response)

        model = Mock()
        model.invoke.return_value.content = "[{}]"
        result = analyze_log_source(model, "runroot.log (aarch64)", "error", [])
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["source"], "runroot.log (aarch64)")

    def test_final_ai_response_wrong_shape_uses_fallback(self):
        logs = {"pungi.global.log": "Error: failed"}
        with patch.object(inspector, "collect_failure_logs", return_value=logs), \
             patch.object(inspector, "ai_models", {"log_analysis": Mock(), "synthesis": Mock()}), \
             patch.object(inspector, "run_staged_log_analysis", return_value=[{"source": "pungi.global.log"}]), \
             patch.object(inspector, "synthesize_log_analyses", return_value="[]"), \
             patch.object(inspector, "find_related_open_issues", return_value=([], None)), \
             contextlib.redirect_stdout(io.StringIO()):
            result = inspector.diagnose_failure("https://example.test/", "Fedora-IoT-45")
        self.assertIn("*AI Diagnosis:*", result)

    def test_final_ai_response_handles_invalid_evidence_field(self):
        logs = {"pungi.global.log": "Error: failed"}
        with patch.object(inspector, "collect_failure_logs", return_value=logs), \
             patch.object(inspector, "ai_models", {"log_analysis": Mock(), "synthesis": Mock()}), \
             patch.object(inspector, "run_staged_log_analysis", return_value=[{"source": "pungi.global.log"}]), \
             patch.object(inspector, "synthesize_log_analyses", return_value='{"evidence": {"bad": true}}'), \
             patch.object(inspector, "find_related_open_issues", return_value=([], None)), \
             contextlib.redirect_stdout(io.StringIO()):
            result = inspector.diagnose_failure("https://example.test/", "Fedora-IoT-45")
        self.assertIn("no evidence excerpt was returned", result)

    def test_issue_report_uses_one_architecture_field(self):
        result = {
            "affected_arches": ["aarch64", "aarch64"],
            "issue_report": {
                "bug_description": "Image creation failed",
                "os_version": "Fedora IoT 45",
            },
        }
        report = format_issue_report(result, "https://example.test/", "Fedora-IoT-45")
        self.assertIn("*Describe the bug:* Image creation failed", report)
        self.assertIn("*OS version:* Fedora IoT 45", report)
        self.assertIn("*Affected architectures:* aarch64", report)
        self.assertEqual(report.count("aarch64"), 1)

    def test_requested_sources_are_not_repeated(self):
        self.assertEqual(
            prioritize_items(["pungi", "pungi", "runroot-a", "runroot-b", "pungi"],
                             ["runroot-b", "runroot-b", "missing", "runroot-a"]),
            ["runroot-b", "runroot-a", "pungi"],
        )

    def test_only_failed_deliverables_select_architectures(self):
        deliverables = {
            "attempted": {"ostree-container": [["IoT", "x86_64", None], ["IoT", "aarch64", None]]},
            "failed": {"ostree-container": [["IoT", "aarch64", None]]},
        }
        logs = {"deliverables.json": json.dumps(deliverables)}
        self.assertEqual(inspector.affected_arches_from_logs(logs), ["aarch64"])
        logs.update({
            "pungi.global.log": "Error: failed",
            "runroot.log (x86_64)": "unrelated",
            "runroot.log (aarch64)": "failure",
            "koji_task_123": "failure",
        })
        self.assertEqual(inspector.log_analysis_order(logs), [
            "deliverables.json", "pungi.global.log", "runroot.log (aarch64)",
            "koji_task_123", "runroot.log (x86_64)",
        ])
        deliverables["failed"] = {}
        self.assertEqual(inspector.affected_arches_from_logs(
            {"deliverables.json": json.dumps(deliverables)}), [])
        self.assertEqual(inspector.affected_arches_from_logs(
            {"deliverables.json": "not JSON"}), [])

    def test_evidence_must_match_its_claimed_source(self):
        logs = {
            "pungi.global.log": "Error: unrelated failure",
            "runroot.log (aarch64)": "start\r\nError: disk full\r\nend",
        }
        self.assertEqual(inspector.verified_log_snapshot(
            logs, {"source": "runroot.log (aarch64)", "excerpt": ""}), (None, None))
        self.assertEqual(inspector.verified_log_snapshot(
            logs, {"source": "missing.log", "excerpt": "Error: disk full"}), (None, None))
        self.assertEqual(inspector.verified_log_snapshot(
            logs, {"source": "runroot.log (aarch64)", "excerpt": "Error: unrelated failure"}),
            (None, None))
        source, snapshot = inspector.verified_log_snapshot(
            logs, {"source": "runroot.log (aarch64)", "excerpt": "Error: disk full"})
        self.assertEqual(source, "runroot.log (aarch64)")
        self.assertIn("Error: disk full", snapshot)

    def test_malformed_quay_tag_keeps_requested_tag_in_error(self):
        response = Mock()
        response.json.return_value = {"tags": ["unexpected payload"]}
        output = io.StringIO()
        with patch.object(inspector.requests, "get", return_value=response), \
             contextlib.redirect_stdout(output):
            result = inspector.check_quay_container("fedora/fedora-iot", "45")
        self.assertFalse(result["exists"])
        self.assertIn("error", result)
        self.assertIn("fedora/fedora-iot:45", output.getvalue())
        quay_report = inspector.format_quay_slack_blocks(
            "2026-10-13", [{"version": "45", "containers": {"fedora/fedora-iot": result}}])
        quay_text = "".join(block["text"]["text"] for block in quay_report)
        self.assertIn("check unavailable", quay_text)
        self.assertNotIn("tag not found", quay_text)

    def test_compose_and_quay_reports_are_separate_and_within_slack_limit(self):
        reports = [{
            "version": "45",
            "status": "DOOMED",
            "compose_url": "https://example.test/compose/",
            "diagnosis": "A" + "Z" * 7000 + "B",
            "containers": {
                "fedora/fedora-iot": {
                    "exists": True,
                    "manifest_digest": "sha256:abc",
                    "last_modified": "Mon, 12 Oct 2026 00:00:00 GMT",
                    "updated_after_compose": True,
                }
            },
        }]
        compose = inspector.format_slack_blocks("2026-10-13", reports)
        quay = inspector.format_quay_slack_blocks("2026-10-13", reports)
        for blocks in (compose, quay):
            self.assertTrue(all(1 <= len(block["text"]["text"]) <= 3000 for block in blocks))
            self.assertIn("View full GitHub Actions run log", blocks[-1]["text"]["text"])
        compose_text = "".join(block["text"]["text"] for block in compose)
        quay_text = "".join(block["text"]["text"] for block in quay)
        self.assertEqual(compose_text.count("Z"), 7000)
        self.assertIn("AI Analysis", compose_text)
        self.assertNotIn("sha256:abc", compose_text)
        self.assertIn("sha256:abc", quay_text)
        self.assertNotIn("AI Analysis", quay_text)

    def test_main_attempts_both_reports_after_saving_artifact(self):
        report = {"version": "45", "status": "FINISHED", "containers": {}}
        with patch.dict(os.environ, {"OVERRIDE_DATE": "20261013"}), \
             patch.object(sys, "argv", ["check_fedora_iot.py"]), \
             patch.object(inspector, "get_all_compose_links", return_value=["compose"]), \
             patch.object(inspector, "detect_active_versions", return_value=["45"]), \
             patch.object(inspector, "inspect_version", return_value=report), \
             patch.object(inspector, "save_daily_report") as save, \
             patch.object(inspector, "send_slack_notification", side_effect=[False, True]) as send, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as exit_result:
                inspector.main()
        self.assertEqual(exit_result.exception.code, 1)
        save.assert_called_once()
        self.assertEqual(send.call_count, 2)

    def test_slack_webhook_failure_is_reported(self):
        response = Mock()
        response.raise_for_status.side_effect = inspector.requests.exceptions.HTTPError("Bad request")
        blocks = inspector.slack_section_blocks(["Compose report"])
        with patch.object(inspector, "SLACK_WEBHOOK_URL", "https://example.test/webhook"), \
             patch.dict(os.environ, {"DISABLE_SLACK": "false"}), \
             patch.object(inspector.requests, "post", return_value=response), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(inspector.send_slack_notification(blocks))


if __name__ == "__main__":
    unittest.main()
