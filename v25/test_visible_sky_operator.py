"""Public zero-argument and advanced-config visible-sky workflow tests."""
from __future__ import annotations

import argparse
from contextlib import chdir
from contextlib import redirect_stdout
import io
from pathlib import Path
import shutil
import sqlite3
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from visible_sky_auto_workflow import AutomaticWorkflowResult
from visible_sky_acquisition import AcquisitionResult
from visible_sky_operator import (
    OperatorConfig,
    build_parser,
    delegate_arguments,
    discover_automatic_workflow_configs,
    main,
)


class VisibleSkyOperatorTests(unittest.TestCase):
    def _config(self, root: Path, extra: str = "") -> Path:
        archive = root / "archive"
        archive.mkdir()
        manifest = archive / "manifest.sqlite"
        manifest.write_bytes(b"sqlite fixture")
        config = root / "camera.toml"
        config.write_text(textwrap.dedent(f"""\
            schema = "wide-field-solver-visible-sky-operator-v1"
            source_id = "example"
            camera_id = "camera-a"
            installation_id = "example-camera-2026a"
            orientation = "detector_native_top_left_xy_right_y_down"
            download_manifest = "archive/manifest.sqlite"
            archive_root = "archive"
            review_root = "review"
            calibration_root = "calibrations"
            {extra}
        """), encoding="utf-8")
        return config

    @staticmethod
    def _managed_archive(root: Path) -> Path:
        archive = root / "raw_allsky_samples"
        archive.mkdir()
        manifest = archive / "manifest.sqlite"
        with sqlite3.connect(manifest) as connection:
            connection.execute(
                """
                CREATE TABLE downloads (
                    remote_url TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    observed_utc TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    observed_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    download_status TEXT NOT NULL,
                    validation_status TEXT NOT NULL
                )
                """
            )
            rows = []
            for date_index in range(10):
                for frame_index in range(10):
                    rows.append((
                        f"fixture://eligible/{date_index}/{frame_index}",
                        "eligible-source",
                        "eligible-camera",
                        f"2026-10-{date_index + 1:02d}T{frame_index:02d}:00:00Z",
                        f"eligible-{date_index}-{frame_index}.fits",
                        100,
                        f"{date_index * 10 + frame_index:064x}",
                        "downloaded",
                        "verified",
                    ))
            rows.append((
                "fixture://insufficient/0",
                "insufficient-source",
                "insufficient-camera",
                "2026-10-01T00:00:00Z",
                "insufficient.fits",
                100,
                "f" * 64,
                "downloaded",
                "verified",
            ))
            connection.executemany(
                "INSERT INTO downloads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return manifest

    @staticmethod
    def _managed_archive_rows(manifest: Path) -> None:
        rows = []
        for date_index in range(10):
            for frame_index in range(10):
                rows.append((
                    f"fixture://acquired/{date_index}/{frame_index}",
                    "eligible-source",
                    "eligible-camera",
                    f"2026-10-{date_index + 1:02d}T{frame_index:02d}:30:00Z",
                    f"acquired-{date_index}-{frame_index}.fits",
                    100,
                    f"{1000 + date_index * 10 + frame_index:064x}",
                    "downloaded",
                    "verified",
                ))
        with sqlite3.connect(manifest) as connection:
            connection.executemany(
                "INSERT INTO downloads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def test_zero_argument_discovery_selects_only_eligible_managed_cameras(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._managed_archive(root)
            configs = discover_automatic_workflow_configs(root)

        self.assertEqual(len(configs), 1)
        config = configs[0]
        self.assertEqual(config.source_id, "eligible-source")
        self.assertEqual(config.camera_id, "eligible-camera")
        self.assertEqual(
            config.installation_id,
            "eligible-source-eligible-camera-automatic",
        )
        self.assertEqual(config.download_manifest, manifest.resolve())
        self.assertEqual(config.archive_root, manifest.parent.resolve())
        self.assertEqual(config.review_root, root / "calibration-review")
        self.assertEqual(config.calibration_root, root / "camera-calibrations")

    def test_no_arguments_runs_automatic_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._managed_archive(root)
            result = AutomaticWorkflowResult(
                "activated",
                0,
                root / "calibration-review/run",
                root / "calibration-review/run/automatic_run.json",
                root / "camera-calibrations/mask.json",
            )
            with patch(
                "visible_sky_operator.REPOSITORY_ROOT", root
            ), patch(
                "visible_sky_operator.run_automatic_workflow", return_value=result
            ), redirect_stdout(io.StringIO()) as stdout:
                status = main([])

        self.assertEqual(status, 0)
        self.assertEqual(len(stdout.getvalue().splitlines()), 1)
        self.assertTrue(stdout.getvalue().startswith("ACTIVATED "))

    def test_no_arguments_acquires_before_checking_calibration_thresholds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._managed_archive(root)
            with sqlite3.connect(manifest) as connection:
                connection.execute(
                    "DELETE FROM downloads WHERE source_id='eligible-source' "
                    "AND observed_utc >= '2026-10-02'"
                )
            result = AutomaticWorkflowResult(
                "activated", 0, root / "run", root / "run/receipt.json",
                root / "calibrations/mask.json",
            )

            def acquire_before_discovery(_root, _calibrated):
                self._managed_archive_rows(manifest)
                return AcquisitionResult(10, 0)

            with patch(
                "visible_sky_operator.REPOSITORY_ROOT", root
            ), patch(
                "visible_sky_operator.acquire_managed_calibration_inputs",
                side_effect=acquire_before_discovery,
            ), patch(
                "visible_sky_operator.run_automatic_workflow", return_value=result
            ), redirect_stdout(io.StringIO()) as stdout:
                status = main([])

        self.assertEqual(status, 0)
        self.assertTrue(stdout.getvalue().startswith("ACTIVATED "))

    def test_registered_camera_is_up_to_date_when_archive_grows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._managed_archive(root)
            with sqlite3.connect(manifest) as connection:
                connection.execute(
                    "UPDATE downloads SET source_id='mmto', camera_id='mmto-skycam' "
                    "WHERE source_id='eligible-source'"
                )
            bundled = Path(__file__).resolve().parent / "data/sky_masks"
            shutil.copytree(bundled, root / "v25/data/sky_masks")

            with patch(
                "visible_sky_operator.REPOSITORY_ROOT", root
            ), patch(
                "visible_sky_operator.run_automatic_workflow",
                side_effect=AssertionError("registered camera was recalibrated"),
            ), redirect_stdout(io.StringIO()) as stdout:
                status = main([])

        self.assertEqual(status, 0)
        self.assertEqual(
            stdout.getvalue().strip(),
            "UP TO DATE no uncalibrated managed camera has enough data",
        )

    def test_relative_paths_resolve_from_config_not_working_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = self._config(root)
            with chdir(Path("/tmp")):
                config = OperatorConfig.load(config_path)

        self.assertEqual(config.download_manifest, root / "archive/manifest.sqlite")
        self.assertEqual(config.archive_root, root / "archive")
        self.assertEqual(config.review_root, root / "review")
        self.assertEqual(config.calibration_root, root / "calibrations")

    def test_unknown_missing_empty_and_unsafe_values_fail_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = {
                "unknown": lambda text: text + 'unexpected = "value"\n',
                "empty": lambda text: text.replace(
                    'camera_id = "camera-a"', 'camera_id = ""'
                ),
                "unsafe": lambda text: text.replace(
                    'installation_id = "example-camera-2026a"',
                    'installation_id = "../escape"',
                ),
            }
            for name, change in cases.items():
                with self.subTest(name=name):
                    case_root = root / name
                    case_root.mkdir()
                    config_path = self._config(case_root)
                    config_path.write_text(
                        change(config_path.read_text(encoding="utf-8")),
                        encoding="utf-8",
                    )
                    output = case_root / "must-not-exist"
                    with self.assertRaises(ValueError):
                        main([
                            "propose", "--config", str(config_path),
                            "--output", str(output),
                        ])
                    self.assertFalse(output.exists())

            missing_root = root / "missing"
            missing_root.mkdir()
            config_path = self._config(missing_root)
            text = config_path.read_text(encoding="utf-8")
            config_path.write_text(
                text.replace('camera_id = "camera-a"\n', ""), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                OperatorConfig.load(config_path)

    def test_each_stage_delegates_only_its_builder_operation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = OperatorConfig.load(self._config(root))
            proposal = root / "proposal/selection.json"
            edited = root / "edited.png"
            output = root / "revision"

            propose = delegate_arguments(
                "propose", config, argparse.Namespace(output=None)
            )
            self.assertEqual(propose, [
                "propose",
                "--download-manifest", str(root / "archive/manifest.sqlite"),
                "--archive-root", str(root / "archive"),
                "--source", "example",
                "--camera", "camera-a",
                "--installation-id", "example-camera-2026a",
                "--orientation", "detector_native_top_left_xy_right_y_down",
                "--output", str(root / "review/example-camera-2026a"),
            ])
            revise = delegate_arguments(
                "revise",
                config,
                argparse.Namespace(
                    parent_selection=proposal,
                    edited_mask=edited,
                    output=output,
                ),
            )
            self.assertEqual(revise, [
                "revise",
                "--parent-selection", str(proposal),
                "--edited-mask", str(edited),
                "--output", str(output),
            ])
            approve = delegate_arguments(
                "approve",
                config,
                argparse.Namespace(
                    proposal=proposal,
                    reviewed_draft_sha256="a" * 64,
                    mask_id="example-mask-v1",
                    approved_by="Peter",
                    safety_margin_pixels=5,
                ),
            )
            self.assertEqual(approve, [
                "approve",
                "--proposal", str(proposal),
                "--reviewed-draft-sha256", "a" * 64,
                "--mask-id", "example-mask-v1",
                "--approved-by", "Peter",
                "--safety-margin-pixels", "5",
                "--calibration-root", str(root / "calibrations"),
            ])
            activate = delegate_arguments(
                "activate", config, argparse.Namespace()
            )
            self.assertEqual(activate, [
                "activate",
                "--calibration-registry", str(root / "calibrations/registry.jsonl"),
                "--source", "example",
                "--camera", "camera-a",
                "--installation-id", "example-camera-2026a",
            ])
            for delegated, forbidden in (
                (propose, "approve"),
                (approve, "activate"),
                (activate, "approve"),
            ):
                self.assertNotIn(forbidden, delegated)

    def test_main_calls_builder_once_and_launcher_selects_v25(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = self._config(root)
            with patch("visible_sky_operator.builder_main", return_value=0) as builder:
                status = main(["propose", "--config", str(config_path)])
            self.assertEqual(status, 0)
            builder.assert_called_once()
            self.assertEqual(builder.call_args.args[0][0], "propose")

        launcher = Path(__file__).resolve().parent.parent / "go_visible_sky_v25.sh"
        source = launcher.read_text(encoding="utf-8")
        self.assertIn('--project "$repo/v25"', source)
        self.assertIn('"$repo/v25/visible_sky_operator.py"', source)
        self.assertNotIn("v24", source)

    def test_auto_requires_only_config(self):
        parser = build_parser()
        args = parser.parse_args(["auto", "--config", "/tmp/camera.toml"])
        self.assertEqual(args.command, "auto")
        self.assertFalse(args.replace_active)
        for forbidden in (
            "--proposal",
            "--reviewed-draft-sha256",
            "--mask-id",
            "--approved-by",
            "--output",
        ):
            with self.subTest(forbidden=forbidden), self.assertRaises(SystemExit):
                parser.parse_args(["auto", "--config", "/tmp/camera.toml", forbidden, "x"])

        discovered = parser.parse_args(["auto"])
        self.assertIsNone(discovered.config)

    def test_auto_delegates_one_workflow_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = self._config(root)
            result = AutomaticWorkflowResult(
                "activated",
                0,
                root / "review/example-camera-2026a/auto-run",
                root / "review/example-camera-2026a/auto-run/automatic_run.json",
                root / "calibrations/example-camera-2026a/mask.json",
            )
            with patch(
                "visible_sky_operator.run_automatic_workflow", return_value=result
            ) as workflow, redirect_stdout(io.StringIO()) as stdout:
                status = main(["auto", "--config", str(config_path)])
            self.assertEqual(status, 0)
            workflow.assert_called_once()
            supplied = workflow.call_args.args[0]
            self.assertEqual(supplied.download_manifest, root / "archive/manifest.sqlite")
            self.assertEqual(supplied.review_root, root / "review")
            self.assertEqual(supplied.calibration_root, root / "calibrations")
            self.assertFalse(workflow.call_args.kwargs["replace_active"])
            self.assertEqual(stdout.getvalue().count("ACTIVATED"), 1)

    def test_auto_replace_active_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = self._config(root)
            result = AutomaticWorkflowResult(
                "rejected", 1, root / "run", root / "run/automatic_run.json", None
            )
            with patch(
                "visible_sky_operator.run_automatic_workflow", return_value=result
            ) as workflow, redirect_stdout(io.StringIO()):
                main(["auto", "--config", str(config_path), "--replace-active"])
            self.assertTrue(workflow.call_args.kwargs["replace_active"])

    def test_auto_maps_result_status_to_exact_exit_code(self):
        cases = (
            ("activated", 0, "ACTIVATED "),
            ("rejected", 1, "NOT ACTIVATED "),
            ("operational_failure", 3, "NOT ACTIVATED "),
        )
        for status_name, exit_code, prefix in cases:
            with self.subTest(status=status_name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config_path = self._config(root)
                result = AutomaticWorkflowResult(
                    status_name, exit_code, root / "run", root / "run/automatic_run.json", None
                )
                with patch(
                    "visible_sky_operator.run_automatic_workflow", return_value=result
                ), redirect_stdout(io.StringIO()) as stdout:
                    observed = main(["auto", "--config", str(config_path)])
                self.assertEqual(observed, exit_code)
                lines = stdout.getvalue().splitlines()
                self.assertEqual(len(lines), 1)
                self.assertTrue(lines[0].startswith(prefix))

    def test_auto_configuration_error_is_one_clean_exit_two_line(self):
        with redirect_stdout(io.StringIO()) as stdout:
            status = main(["auto", "--config", "/does/not/exist/camera.toml"])

        self.assertEqual(status, 2)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("NOT ACTIVATED status=configuration_error "))

    def test_manual_subcommands_are_unchanged(self):
        parser = build_parser()
        self.assertEqual(
            set(parser._subparsers._group_actions[0].choices),
            {"auto", "propose", "revise", "approve", "activate"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = OperatorConfig.load(self._config(root))
            self.assertEqual(
                delegate_arguments("activate", config, argparse.Namespace())[0],
                "activate",
            )


if __name__ == "__main__":
    unittest.main()
