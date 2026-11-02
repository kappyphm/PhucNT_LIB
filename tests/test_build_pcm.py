import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_pcm


def make_fixture(root: Path, symbol_footprint: str = "PCM_Test_lib:FP", model_name: str = "model.step") -> None:
    (root / "symbols").mkdir(parents=True)
    (root / "footprints" / "Test_lib.pretty").mkdir(parents=True)
    (root / "3dmodels" / "Test_lib.3dshapes").mkdir(parents=True)

    (root / "symbols" / "Test_lib.kicad_sym").write_text(
        "(kicad_symbol_lib (version 20231120) (generator kicad_symbol_editor)\n"
        '  (symbol "Test"\n'
        f'    (property "Footprint" "{symbol_footprint}"\n'
        "      (at 0 0 0)\n"
        "    )\n"
        "  )\n"
        ")\n",
        encoding="utf-8",
    )
    (root / "footprints" / "Test_lib.pretty" / "FP.kicad_mod").write_text(
        '(footprint "FP" (version 20240108) (generator kicad_pcb)\n'
        '  (model "${KICAD9_3RD_PARTY}/3dmodels/com_github_kappyphm_phucnt-lib/Test_lib.3dshapes/'
        f'{model_name}"\n'
        "    (offset (xyz 0 0 0))\n"
        "  )\n"
        ")\n",
        encoding="utf-8",
    )
    (root / "3dmodels" / "Test_lib.3dshapes" / "model.step").write_text(
        "solid test\nendsolid test\n",
        encoding="ascii",
    )

    metadata = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))
    (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


class BuildPcmTests(unittest.TestCase):
    def test_check_actual_library(self) -> None:
        info = build_pcm.check_package(ROOT, "v1.0.0")
        self.assertEqual(info["identifier"], "com.github.kappyphm.phucnt-lib")
        self.assertEqual(info["version"], "1.0.0")
        self.assertEqual(info["footprint_nickname"], "PCM_PhucNT_lib")

    def test_actual_package_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "dist"
            moment = "2026-01-02T03:04:05Z"
            result = build_pcm.build_package(
                root=ROOT,
                output_dir=output,
                repo="kappyphm/PhucNT_LIB",
                branch="main",
                tag="v1.0.0",
                timestamp=moment,
            )

            self.assertEqual(result.zip_path.name, "com.github.kappyphm.phucnt-lib_v1.0.0_pcm.zip")
            self.assertTrue(result.zip_path.is_file())
            self.assertEqual(result.zip_sha256, hashlib.sha256(result.zip_path.read_bytes()).hexdigest())

            with zipfile.ZipFile(result.zip_path) as archive:
                names = set(archive.namelist())
                self.assertEqual(len(names), 12)
                self.assertIn("metadata.json", names)
                self.assertIn("symbols/PhucNT_lib.kicad_sym", names)
                self.assertIn("footprints/PhucNT_lib.pretty/BMP388_Breakout_Module_FP.kicad_mod", names)
                self.assertIn("3dmodels/PhucNT_Lib.3dshapes/BMP388_breakout.STEP", names)
                self.assertFalse(any(name.startswith(("dist/", "resources/", "libtest/")) for name in names))
                self.assertIsNone(archive.testzip())
                archived_metadata = json.loads(archive.read("metadata.json"))
                self.assertEqual(archived_metadata["versions"][0]["version"], "1.0.0")
                self.assertFalse(any(key.startswith("download_") for key in archived_metadata["versions"][0]))
                self.assertEqual(result.install_size, sum(item.file_size for item in archive.infolist()))

            packages_bytes = (output / "packages.json").read_bytes()
            packages = json.loads(packages_bytes)
            package = packages["packages"][0]
            version = package["versions"][0]
            self.assertEqual(package["identifier"], "com.github.kappyphm.phucnt-lib")
            self.assertEqual(version["version"], "1.0.0")
            self.assertEqual(version["download_sha256"], result.zip_sha256)
            self.assertEqual(version["download_size"], result.zip_size)
            self.assertEqual(version["install_size"], result.install_size)
            self.assertEqual(
                version["download_url"],
                "https://github.com/kappyphm/PhucNT_LIB/releases/download/v1.0.0/"
                "com.github.kappyphm.phucnt-lib_v1.0.0_pcm.zip",
            )

            repository = json.loads((output / "repository.json").read_text(encoding="utf-8"))
            self.assertEqual(
                repository["packages"]["url"],
                "https://raw.githubusercontent.com/kappyphm/PhucNT_LIB/main/dist/packages.json",
            )
            self.assertEqual(repository["packages"]["sha256"], hashlib.sha256(packages_bytes).hexdigest())
            expected_timestamp = int(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp())
            self.assertEqual(repository["packages"]["update_timestamp"], expected_timestamp)

    def test_build_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            moment = "2026-01-02T03:04:05Z"
            left = build_pcm.build_package(
                root=ROOT,
                output_dir=Path(first),
                tag="v1.0.0",
                timestamp=moment,
                write_index=False,
            )
            right = build_pcm.build_package(
                root=ROOT,
                output_dir=Path(second),
                tag="v1.0.0",
                timestamp=moment,
                write_index=False,
            )
            self.assertEqual(left.zip_sha256, right.zip_sha256)

    def test_fixture_no_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            output = Path(temp) / "out"
            make_fixture(root)
            result = build_pcm.build_package(
                root=root,
                output_dir=output,
                tag="v1.0.0",
                timestamp="2026-01-02T03:04:05Z",
                write_index=False,
            )
            self.assertTrue(result.zip_path.is_file())
            self.assertFalse((output / "packages.json").exists())
            self.assertFalse((output / "repository.json").exists())

    def test_fixture_preserves_version_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            output = Path(temp) / "out"
            make_fixture(root)
            build_pcm.build_package(
                root=root,
                output_dir=output,
                tag="v1.0.0",
                timestamp="2026-01-02T03:04:05Z",
            )
            metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
            metadata["versions"][0]["version"] = "1.0.1"
            (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            build_pcm.build_package(
                root=root,
                output_dir=output,
                tag="v1.0.1",
                timestamp="2026-01-03T03:04:05Z",
            )
            packages = json.loads((output / "packages.json").read_text(encoding="utf-8"))
            versions = [item["version"] for item in packages["packages"][0]["versions"]]
            self.assertEqual(versions, ["1.0.1", "1.0.0"])

    def test_rejects_stale_symbol_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_fixture(root, symbol_footprint="phucnt_fp:FP")
            with self.assertRaises(build_pcm.BuildError):
                build_pcm.check_package(root, "v1.0.0")

    def test_rejects_missing_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_fixture(root, model_name="missing.step")
            with self.assertRaises(build_pcm.BuildError):
                build_pcm.check_package(root, "v1.0.0")

    def test_rejects_download_fields_in_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_fixture(root)
            metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
            metadata["versions"][0]["download_url"] = "https://example.com/package.zip"
            (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(build_pcm.BuildError):
                build_pcm.check_package(root, "v1.0.0")

    def test_rejects_tag_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_fixture(root)
            with self.assertRaises(build_pcm.BuildError):
                build_pcm.check_package(root, "v9.9.9")


if __name__ == "__main__":
    unittest.main()
