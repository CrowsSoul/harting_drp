# -*- coding: utf-8 -*-
"""Offline exact-release capabilities and read-only solver detection tests."""

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nxdrp.checkers.performance.solver_environment import (  # noqa: E402
    capability_for,
    detect_solver_environment,
    load_capabilities,
    validate_capability_mode,
)


class TestSolverCapabilities(unittest.TestCase):
    def test_catalog_is_exact_and_unverified(self):
        catalog = load_capabilities()
        self.assertEqual(catalog["release_matching"], "exact")
        self.assertEqual(list(catalog["releases"]), ["NX 2606.3002"])
        for release in catalog["releases"].values():
            self.assertEqual(release["status"], "unverified")
            self.assertFalse(release["verified"])
            for capability in release["items"].values():
                self.assertEqual(capability["status"], "unverified")
                self.assertFalse(capability["verified"])
                self.assertTrue(capability["native_result_mapping"])
                self.assertTrue(
                    all(key is None for key in capability["native_result_mapping"].values())
                )

    def test_perf01_names_and_mode(self):
        capability = capability_for("NX 2606.3002", "PERF-01")
        self.assertEqual(capability["mode"], "thermal_with_joule")
        self.assertEqual(capability["template_names"]["fem"], "FemThermalFlowMetric.fem")
        self.assertEqual(capability["template_names"]["sim"], "SimThermalFlowMetric.sim")
        self.assertEqual(capability["solver_name"], "NX THERMAL")
        self.assertEqual(capability["analysis_name"], "thermal_with_joule")
        self.assertEqual(capability["solution_name"], "Steady State Solid Thermal")
        self.assertIn("voltage_drop_v", capability["native_result_mapping"])

    def test_perf02_names_and_mode(self):
        capability = capability_for("NX 2606.3002", "PERF-02")
        self.assertEqual(capability["mode"], "SOL401")
        self.assertEqual(capability["solution_card"], "SOL 401")
        self.assertEqual(capability["template_names"]["fem"], "FemNxNastranMetric.fem")
        self.assertEqual(capability["template_names"]["sim"], "SimNxNastranMetric.sim")
        self.assertEqual(capability["solver_name"], "NX NASTRAN")
        self.assertEqual(capability["analysis_name"], "Structural")
        self.assertEqual(capability["solution_name"], "SOL 401 Multi-Step Nonlinear")
        self.assertEqual(capability["solution_mode"], "nonlinear_contact")

    def test_unknown_release_has_no_nearest_fallback(self):
        for release in ("NX 2606", "NX2606", "NX 2606.3003", "NX 2506.3002"):
            result = capability_for(release, "PERF-01")
            self.assertEqual(result["status"], "not_done")
            self.assertFalse(result["execution_ready"])
            self.assertEqual(result["errors"][0]["code"], "unsupported_release")
            self.assertIn("action", result["errors"][0])

    def test_unknown_item_and_verified_requirement_fail_closed(self):
        unknown = capability_for("NX 2606.3002", "PERF-99")
        self.assertEqual(unknown["status"], "not_done")
        self.assertEqual(unknown["errors"][0]["code"], "unsupported_item")

        unverified = capability_for("NX 2606.3002", "PERF-01", require_verified=True)
        self.assertEqual(unverified["status"], "not_done")
        self.assertEqual(unverified["errors"][0]["code"], "capability_unverified")

    def test_unknown_mode_and_output_key_are_structured_errors(self):
        capability = capability_for("NX 2606.3002", "PERF-01")
        bad_mode = validate_capability_mode(capability, "SOL401")
        self.assertEqual(bad_mode["status"], "not_done")
        self.assertEqual(bad_mode["errors"][0]["code"], "unsupported_mode")

        bad_output = validate_capability_mode(
            capability, "thermal_with_joule", ["temperature"]
        )
        self.assertEqual(bad_output["status"], "not_done")
        self.assertEqual(bad_output["errors"][0]["code"], "unknown_output_key")
        self.assertIn("known_output_keys", bad_output["errors"][0])

    def test_execution_reports_unverified_native_keys(self):
        capability = capability_for("NX 2606.3002", "PERF-01")
        result = validate_capability_mode(
            capability,
            "thermal_with_joule",
            ["maximum_temperature_c", "voltage_drop_v"],
            for_execution=True,
        )
        self.assertEqual(result["status"], "not_done")
        self.assertFalse(result["execution_ready"])
        codes = {entry["code"] for entry in result["not_done"]}
        self.assertIn("capability_unverified", codes)
        self.assertIn("native_output_key_unverified", codes)
        native = [entry for entry in result["not_done"] if entry["code"] == "native_output_key_unverified"]
        self.assertEqual(len(native), 2)
        self.assertTrue(all(entry["native_key"] is None for entry in native))


class TestSolverEnvironment(unittest.TestCase):
    @staticmethod
    def _file(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"offline detection fixture")

    def test_detection_is_read_only_and_does_not_authorize(self):
        with tempfile.TemporaryDirectory() as root:
            run_journal = os.path.join(root, "NXBIN", "run_journal.exe")
            analysis = os.path.join(root, "NXNASTRAN", "bin", "analysis.exe")
            floefd = os.path.join(root, "FloEFD", "bin", "efdsolver.exe")
            for path in (run_journal, analysis, floefd):
                self._file(path)
            env = {
                "UGII_BASE_DIR": root,
                "NXDRP_NX_RELEASE": "NX 2606.3002",
            }
            with mock.patch("subprocess.run", side_effect=AssertionError("must not execute")):
                summary = detect_solver_environment(environ=env)
            self.assertEqual(summary["nx_release"], "NX 2606.3002")
            self.assertEqual(summary["run_journal"]["path"], os.path.abspath(run_journal))
            self.assertEqual(summary["nastran"]["path"], os.path.abspath(analysis))
            self.assertEqual(summary["floefd"]["path"], os.path.abspath(floefd))
            for name in ("run_journal", "nastran", "floefd"):
                self.assertTrue(summary[name]["exists"])
                self.assertFalse(summary[name]["authorized"])
                self.assertFalse(summary[name]["license_verified"])
                self.assertEqual(summary[name]["license_mode"], "unverified")
            self.assertTrue(summary["read_only"])
            self.assertFalse(summary["solver_run_performed"])
            self.assertEqual(summary["detection_status"], "complete")
            self.assertFalse(summary["authorized"])

    def test_explicit_missing_paths_do_not_become_authorized(self):
        with tempfile.TemporaryDirectory() as root:
            missing = os.path.join(root, "missing", "analysis.exe")
            summary = detect_solver_environment(
                nx_release="NX 2606.3002",
                nastran_analysis=missing,
                environ={},
            )
            self.assertEqual(summary["nastran"]["path"], os.path.abspath(missing))
            self.assertFalse(summary["nastran"]["exists"])
            self.assertFalse(summary["nastran"]["authorized"])
            self.assertEqual(summary["status"], "unverified")
            self.assertEqual(summary["detection_status"], "partial")
            self.assertIn("license_unverified", {entry["code"] for entry in summary["not_done"]})

    def test_release_is_not_guessed_from_install_path(self):
        with tempfile.TemporaryDirectory() as root:
            summary = detect_solver_environment(ugii_base_dir=root, environ={})
            self.assertIsNone(summary["nx_release"])
            self.assertEqual(summary["nx_release_source"], "not_detected")
            self.assertIn("nx_release_not_detected", {entry["code"] for entry in summary["not_done"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
