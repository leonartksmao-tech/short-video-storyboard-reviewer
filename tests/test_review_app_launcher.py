import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "serve_c451_review.sh"
HANDOFF_SCRIPT = ROOT / "scripts" / "build_c451_handoff_package.sh"
APP = ROOT / "短视频审片.app"
APP_EXECUTABLE = APP / "Contents" / "MacOS" / "短视频审片"
INFO_PLIST = APP / "Contents" / "Info.plist"
PKG_INFO = APP / "Contents" / "PkgInfo"


class ReviewAppLauncherTests(unittest.TestCase):
    def test_launcher_script_supports_local_and_lan_review_server(self):
        self.assertTrue(SCRIPT.exists())
        self.assertTrue(os.access(SCRIPT, os.X_OK))

        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("python3 -m http.server", source)
        self.assertIn("--bind 0.0.0.0", source)
        self.assertIn("c451_tool_output/storyboard_preview.html", source)
        self.assertIn("ipconfig getifaddr", source)
        self.assertIn("pbcopy", source)
        self.assertIn('open "$LOCAL_URL"', source)
        self.assertIn("server_is_healthy", source)
        self.assertIn('wait "$SERVER_PID"', source)
        self.assertIn("SHORT_VIDEO_REVIEW_PORT", source)
        self.assertIn("SHORT_VIDEO_REVIEW_DRY_RUN", source)

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "work"
            (project / "c451_tool_output").mkdir(parents=True)
            (project / "c451_tool_output" / "storyboard_preview.html").write_text(
                "<!doctype html><title>review</title>",
                encoding="utf-8",
            )

            result = subprocess.run(
                [str(SCRIPT)],
                cwd=ROOT,
                env={
                    **os.environ,
                    "SHORT_VIDEO_REVIEW_DRY_RUN": "1",
                    "SHORT_VIDEO_REVIEW_PORT": "9876",
                    "SHORT_VIDEO_REVIEW_PROJECT_DIR": str(project),
                },
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn(f"PROJECT_DIR={project}", result.stdout)
            self.assertIn("LOCAL_URL=http://127.0.0.1:9876/c451_tool_output/storyboard_preview.html", result.stdout)
            self.assertIn("LAN_URL=http://", result.stdout)

    def test_mac_app_bundle_points_to_launcher(self):
        self.assertTrue(INFO_PLIST.exists())
        self.assertEqual(PKG_INFO.read_text(encoding="utf-8").strip(), "APPL????")
        self.assertTrue(APP_EXECUTABLE.exists())
        self.assertTrue(os.access(APP_EXECUTABLE, os.X_OK))

        with INFO_PLIST.open("rb") as file:
            info = plistlib.load(file)
        self.assertEqual(info["CFBundleName"], "短视频审片")
        self.assertEqual(info["CFBundleExecutable"], "短视频审片")
        self.assertEqual(info["CFBundlePackageType"], "APPL")

        executable_source = APP_EXECUTABLE.read_text(encoding="utf-8")
        self.assertIn("scripts/serve_c451_review.sh", executable_source)
        self.assertIn("exec", executable_source)

    def test_builds_standalone_handoff_package(self):
        self.assertTrue(HANDOFF_SCRIPT.exists())
        self.assertTrue(os.access(HANDOFF_SCRIPT, os.X_OK))

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            project = temp / "work"
            (project / "c451_tool_output").mkdir(parents=True)
            (project / "c451_tool_output" / "storyboard_preview.html").write_text(
                "<!doctype html><title>review</title>",
                encoding="utf-8",
            )
            (project / "storyboard").mkdir()
            (project / "storyboard" / "01.jpg").write_bytes(b"fake image")

            output = temp / "out"
            result = subprocess.run(
                [str(HANDOFF_SCRIPT)],
                cwd=ROOT,
                env={
                    **os.environ,
                    "SHORT_VIDEO_HANDOFF_PROJECT_DIR": str(project),
                    "SHORT_VIDEO_HANDOFF_OUTPUT_DIR": str(output),
                    "SHORT_VIDEO_HANDOFF_PACKAGE_NAME": "测试交接包",
                },
                text=True,
                capture_output=True,
                check=True,
            )

            package = output / "测试交接包"
            zip_path = output / "测试交接包.zip"
            app_executable = package / "短视频审片.app" / "Contents" / "MacOS" / "短视频审片"
            embedded_preview = (
                package
                / "短视频审片.app"
                / "Contents"
                / "Resources"
                / "public"
                / "c451_tool_output"
                / "storyboard_preview.html"
            )

            self.assertIn(f"PACKAGE_DIR={package}", result.stdout)
            self.assertIn(f"ZIP_PATH={zip_path}", result.stdout)
            self.assertTrue(zip_path.exists())
            self.assertTrue(embedded_preview.exists())
            self.assertTrue(app_executable.exists())
            self.assertTrue(os.access(app_executable, os.X_OK))

            executable_source = app_executable.read_text(encoding="utf-8")
            self.assertIn("Contents/Resources/public", executable_source)
            self.assertNotIn("scripts/serve_c451_review.sh", executable_source)

            dry_run = subprocess.run(
                [str(app_executable)],
                env={**os.environ, "SHORT_VIDEO_REVIEW_DRY_RUN": "1", "SHORT_VIDEO_REVIEW_PORT": "9876"},
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn(
                "LOCAL_URL=http://127.0.0.1:9876/c451_tool_output/storyboard_preview.html",
                dry_run.stdout,
            )
            self.assertIn(f"SERVER_ROOT={embedded_preview.parents[1].resolve()}", dry_run.stdout)
            self.assertNotIn(str(ROOT / "0527_work"), dry_run.stdout)


if __name__ == "__main__":
    unittest.main()
