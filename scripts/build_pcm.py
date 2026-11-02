#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.parse
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Union

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "kappyphm/PhucNT_LIB"
DEFAULT_BRANCH = "main"
SCHEMA_URL = "https://go.kicad.org/pcm/schemas/v1"

IDENTIFIER_RE = re.compile(r"^[a-zA-Z][-a-zA-Z0-9.]{0,98}[a-zA-Z0-9]$")
VERSION_RE = re.compile(r"^\d{1,4}(\.\d{1,4}(\.\d{1,6})?)?$")
KICAD_VERSION_RE = re.compile(r"^\d{1,2}(\.\d{1,2}(\.\d{1,2})?)?$")
TAG_RE = re.compile(r"^v(\d{1,4}(?:\.\d{1,4}(?:\.\d{1,6})?)?)$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RESOURCE_KEY_RE = re.compile(r"^[a-zA-Z][-a-zA-Z0-9 ]{0,48}[a-zA-Z0-9]$")
CONTACT_KEY_RE = re.compile(r"^[a-z][-a-z0-9 ]{0,48}[a-z0-9]$")
TAG_KEY_RE = re.compile(r"^[a-z][-a-z0-9]{0,48}[a-z0-9]$")
SYMBOL_FOOTPRINT_RE = re.compile(r'\(property\s+"Footprint"\s+"([^"]*)"')
FOOTPRINT_NAME_RE = re.compile(r'\(footprint\s+"([^"]+)"')
MODEL_PATH_RE = re.compile(r'\(model\s+"([^"]+)"')
LICENSE_VALUES = {
    "public-domain",
    "Apache",
    "Apache-1.0",
    "Apache-2.0",
    "Artistic",
    "Artistic-1.0",
    "Artistic-2.0",
    "BSD",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "BSD-4-Clause",
    "ISC",
    "CC-BY",
    "CC-BY-1.0",
    "CC-BY-2.0",
    "CC-BY-2.5",
    "CC-BY-3.0",
    "CC-BY-4.0",
    "CC-BY-SA",
    "CC-BY-SA-1.0",
    "CC-BY-SA-2.0",
    "CC-BY-SA-2.5",
    "CC-BY-SA-3.0",
    "CC-BY-SA-4.0",
    "CC-BY-ND",
    "CC-BY-ND-1.0",
    "CC-BY-ND-2.0",
    "CC-BY-ND-2.5",
    "CC-BY-ND-3.0",
    "CC-BY-ND-4.0",
    "CC-BY-NC",
    "CC-BY-NC-1.0",
    "CC-BY-NC-2.0",
    "CC-BY-NC-2.5",
    "CC-BY-NC-3.0",
    "CC-BY-NC-4.0",
    "CC-BY-NC-SA",
    "CC-BY-NC-SA-1.0",
    "CC-BY-NC-SA-2.0",
    "CC-BY-NC-SA-2.5",
    "CC-BY-NC-SA-3.0",
    "CC-BY-NC-SA-4.0",
    "CC-BY-NC-ND",
    "CC-BY-NC-ND-1.0",
    "CC-BY-NC-ND-2.0",
    "CC-BY-NC-ND-2.5",
    "CC-BY-NC-ND-3.0",
    "CC-BY-NC-ND-4.0",
    "CC0-1.0",
    "CDDL-1.0",
    "CPL",
    "EFL",
    "EFL-1.0",
    "EFL-2.0",
    "MIT",
    "GPL",
    "GPL-1.0",
    "GPL-2.0",
    "GPL-3.0",
    "LGPL",
    "LGPL-2.1",
    "LGPL-3.0",
    "GNU-LGPL-2.0",
    "GFDL",
    "GFDL-1.0",
    "GFDL-1.1",
    "GFDL-1.2",
    "GFDL-1.3",
    "GFDL-NIV",
    "LPPL",
    "LPPL-1.0",
    "LPPL-1.1",
    "LPPL-1.2",
    "LPPL-1.3",
    "MPL-1.1",
    "Perl",
    "Python-2.0",
    "QPL-1.0",
    "W3C",
    "Zlib",
    "Zope",
    "Zope-1.0",
    "Zope-1.1",
    "Zope-2.0",
    "Zope-2.1",
    "CERN-OHL",
    "WTFPL",
    "Unlicense",
    "open-source",
    "unrestricted",
}
STATUS_VALUES = {"stable", "testing", "development", "deprecated"}
PLATFORM_VALUES = {"windows", "macos", "linux"}


class BuildError(Exception):
    pass


@dataclass(frozen=True)
class SourceSet:
    symbol_file: Path
    footprint_lib: Path
    models_dir: Path
    footprint_nickname: str


@dataclass(frozen=True)
class BuildResult:
    zip_path: Path
    zip_sha256: str
    zip_size: int
    install_size: int
    packages_path: Union[Path, None]
    repository_path: Union[Path, None]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BuildError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BuildError(f"invalid JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise BuildError(f"cannot read {path}: {exc}") from exc


def _json_bytes(data: Any) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _write_json(path: Path, data: Any) -> bytes:
    content = _json_bytes(data)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    except OSError as exc:
        raise BuildError(f"cannot write {path}: {exc}") from exc
    return content


def _is_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _validate_contact(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise BuildError(f"{label} must be an object")
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise BuildError(f"{label}.name must be a non-empty string")
    contact = value.get("contact")
    if not isinstance(contact, dict):
        raise BuildError(f"{label}.contact must be an object")
    for key, item in contact.items():
        if not isinstance(key, str) or not CONTACT_KEY_RE.fullmatch(key):
            raise BuildError(f"{label}.contact has invalid key: {key!r}")
        if not isinstance(item, str) or len(item) > 500:
            raise BuildError(f"{label}.contact.{key} must be a string of at most 500 characters")


def _validate_version_entry(entry: Any) -> None:
    if not isinstance(entry, dict):
        raise BuildError("metadata versions entries must be objects")
    version = entry.get("version")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise BuildError(f"invalid version: {version!r}")
    status = entry.get("status")
    if status not in STATUS_VALUES:
        raise BuildError(f"invalid version status: {status!r}")
    kicad_version = entry.get("kicad_version")
    if not isinstance(kicad_version, str) or not KICAD_VERSION_RE.fullmatch(kicad_version):
        raise BuildError(f"invalid kicad_version: {kicad_version!r}")
    epoch = entry.get("version_epoch")
    if epoch is not None and (not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0):
        raise BuildError("version_epoch must be a non-negative integer")
    platforms = entry.get("platforms")
    if platforms is not None:
        if not isinstance(platforms, list) or not platforms:
            raise BuildError("platforms must be a non-empty array")
        for platform in platforms:
            if platform not in PLATFORM_VALUES:
                raise BuildError(f"invalid platform: {platform!r}")
    keep_on_update = entry.get("keep_on_update")
    if keep_on_update is not None:
        if not isinstance(keep_on_update, list) or not all(isinstance(item, str) for item in keep_on_update):
            raise BuildError("keep_on_update must be an array of strings")
    for key in entry:
        if key.startswith("download_"):
            raise BuildError(f"metadata.json versions must not contain {key}; use packages.json for download fields")


def validate_metadata(meta: Any) -> None:
    if not isinstance(meta, dict):
        raise BuildError("metadata.json must contain an object")
    schema = meta.get("$schema")
    if schema is not None and not _is_url(schema):
        raise BuildError("metadata $schema must be an HTTP(S) URL")

    identifier = meta.get("identifier")
    if not isinstance(identifier, str) or not IDENTIFIER_RE.fullmatch(identifier):
        raise BuildError(f"invalid identifier: {identifier!r}")

    name = meta.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise BuildError("name must be a non-empty string of at most 200 characters")
    description = meta.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 500:
        raise BuildError("description must be a non-empty string of at most 500 characters")
    description_full = meta.get("description_full")
    if not isinstance(description_full, str) or not description_full.strip() or len(description_full) > 5000:
        raise BuildError("description_full must be a non-empty string of at most 5000 characters")

    if meta.get("type") not in {"plugin", "library", "fab", "colortheme"}:
        raise BuildError(f"invalid package type: {meta.get('type')!r}")
    if meta.get("license") not in LICENSE_VALUES:
        raise BuildError(f"invalid license: {meta.get('license')!r}")
    _validate_contact(meta.get("author"), "author")
    if "maintainer" in meta:
        _validate_contact(meta["maintainer"], "maintainer")

    resources = meta.get("resources")
    if not isinstance(resources, dict) or not resources:
        raise BuildError("resources must be a non-empty object")
    for key, value in resources.items():
        if not isinstance(key, str) or not RESOURCE_KEY_RE.fullmatch(key):
            raise BuildError(f"invalid resource key: {key!r}")
        if not _is_url(value):
            raise BuildError(f"resource {key} must be an HTTP(S) URL")
        if len(value) > 500:
            raise BuildError(f"resource {key} must be at most 500 characters")

    tags = meta.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or not tags:
            raise BuildError("tags must be a non-empty array")
        for tag in tags:
            if not isinstance(tag, str) or not TAG_KEY_RE.fullmatch(tag):
                raise BuildError(f"invalid tag: {tag!r}")
        if len(set(tags)) != len(tags):
            raise BuildError("tags must be unique")

    versions = meta.get("versions")
    if not isinstance(versions, list) or len(versions) != 1:
        raise BuildError("metadata.json must contain exactly one version entry")
    _validate_version_entry(versions[0])


def _sanitize_identifier(identifier: str) -> str:
    return identifier.replace(".", "_")


def _safe_arcname(arcname: str) -> None:
    if not arcname or arcname.startswith("/") or "\\" in arcname:
        raise BuildError(f"unsafe archive path: {arcname!r}")
    parts = Path(arcname).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise BuildError(f"unsafe archive path: {arcname!r}")


def validate_sources(root: Path, meta: dict[str, Any]) -> SourceSet:
    symbols_dir = root / "symbols"
    footprints_dir = root / "footprints"
    models_root = root / "3dmodels"
    for directory in (symbols_dir, footprints_dir, models_root):
        if not directory.is_dir():
            raise BuildError(f"missing directory: {directory}")

    symbol_files = sorted(path for path in symbols_dir.iterdir() if path.is_file() and path.suffix == ".kicad_sym")
    if len(symbol_files) != 1:
        raise BuildError(f"expected exactly one .kicad_sym file in {symbols_dir}, found {len(symbol_files)}")
    symbol_file = symbol_files[0]

    footprint_libs = sorted(path for path in footprints_dir.iterdir() if path.is_dir() and path.name.endswith(".pretty"))
    if len(footprint_libs) != 1:
        raise BuildError(f"expected exactly one .pretty directory in {footprints_dir}, found {len(footprint_libs)}")
    footprint_lib = footprint_libs[0]

    model_dirs = sorted(path for path in models_root.iterdir() if path.is_dir() and path.name.endswith(".3dshapes"))
    if len(model_dirs) != 1:
        raise BuildError(f"expected exactly one .3dshapes directory in {models_root}, found {len(model_dirs)}")
    models_dir = model_dirs[0]
    if not any(path.is_file() for path in models_dir.rglob("*")):
        raise BuildError(f"no 3D model files found in {models_dir}")

    nickname = f"PCM_{footprint_lib.stem}"
    symbol_text = symbol_file.read_text(encoding="utf-8")
    if "(kicad_symbol_lib" not in symbol_text:
        raise BuildError(f"{symbol_file} is not a KiCad symbol library")
    for reference in SYMBOL_FOOTPRINT_RE.findall(symbol_text):
        if not reference:
            continue
        if ":" not in reference:
            raise BuildError(f"symbol footprint reference has no library nickname: {reference!r}")
        prefix, footprint_name = reference.split(":", 1)
        if prefix != nickname:
            raise BuildError(f"symbol footprint reference {reference!r} must use prefix {nickname!r}")
        if not footprint_name or "/" in footprint_name or "\\" in footprint_name:
            raise BuildError(f"invalid footprint name in symbol reference: {reference!r}")
        if not (footprint_lib / f"{footprint_name}.kicad_mod").is_file():
            raise BuildError(f"symbol references missing footprint: {footprint_name}.kicad_mod")

    footprint_files = sorted(footprint_lib.glob("*.kicad_mod"))
    if not footprint_files:
        raise BuildError(f"no .kicad_mod files found in {footprint_lib}")
    model_prefix = (
        f"${{KICAD9_3RD_PARTY}}/3dmodels/"
        f"{_sanitize_identifier(str(meta['identifier']))}/{models_dir.name}/"
    )
    for footprint_file in footprint_files:
        footprint_text = footprint_file.read_text(encoding="utf-8")
        name_match = FOOTPRINT_NAME_RE.search(footprint_text)
        if not name_match:
            raise BuildError(f"cannot read footprint name from {footprint_file}")
        if name_match.group(1) != footprint_file.stem:
            raise BuildError(
                f"footprint name {name_match.group(1)!r} does not match filename {footprint_file.name!r}"
            )
        for model_path in MODEL_PATH_RE.findall(footprint_text):
            if not model_path.startswith(model_prefix):
                raise BuildError(f"3D model path must start with {model_prefix!r}: {model_path!r}")
            relative_model = model_path[len(model_prefix):]
            if not relative_model or not (models_dir / relative_model).is_file():
                raise BuildError(f"missing 3D model: {model_path}")

    return SourceSet(
        symbol_file=symbol_file,
        footprint_lib=footprint_lib,
        models_dir=models_dir,
        footprint_nickname=nickname,
    )


def _normalize_tag(tag: str) -> tuple[str, str]:
    value = tag.strip()
    if not value:
        raise BuildError("tag must not be empty")
    if value.startswith("v"):
        match = TAG_RE.fullmatch(value)
        if not match:
            raise BuildError(f"invalid tag: {tag!r}")
        return value, match.group(1)
    if not VERSION_RE.fullmatch(value):
        raise BuildError(f"invalid tag: {tag!r}")
    return f"v{value}", value


def _check_package(root: Path, tag: Union[str, None]) -> tuple[dict[str, Any], SourceSet, dict[str, Any]]:
    meta = _read_json(root / "metadata.json")
    validate_metadata(meta)
    source = validate_sources(root, meta)
    version_entry = meta["versions"][0]
    if tag is not None:
        _, tag_version = _normalize_tag(tag)
        if tag_version != version_entry["version"]:
            raise BuildError(
                f"tag version {tag_version!r} does not match metadata version {version_entry['version']!r}"
            )
    return meta, source, version_entry


def _parse_timestamp(value: Union[str, datetime, None]) -> datetime:
    if value is None:
        moment = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise BuildError(f"invalid timestamp: {value!r}") from exc
    else:
        raise BuildError("timestamp must be an ISO 8601 string or datetime")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc).replace(microsecond=0)
    if moment.year < 1980:
        raise BuildError("timestamp must be 1980-01-01 or later")
    return moment


def _collect_entries(meta: dict[str, Any], source: SourceSet) -> dict[str, Union[bytes, Path]]:
    entries: dict[str, Union[bytes, Path]] = {}

    def add(arcname: str, value: Union[bytes, Path]) -> None:
        _safe_arcname(arcname)
        if arcname in entries:
            raise BuildError(f"duplicate archive path: {arcname}")
        entries[arcname] = value

    add("metadata.json", _json_bytes(meta))
    add(f"symbols/{source.symbol_file.name}", source.symbol_file)
    for path in sorted(source.footprint_lib.rglob("*")):
        if path.is_file():
            relative = path.relative_to(source.footprint_lib).as_posix()
            add(f"footprints/{source.footprint_lib.name}/{relative}", path)
    for path in sorted(source.models_dir.rglob("*")):
        if path.is_file():
            relative = path.relative_to(source.models_dir).as_posix()
            add(f"3dmodels/{source.models_dir.name}/{relative}", path)
    return entries


def _write_zip(zip_path: Path, entries: dict[str, Union[bytes, Path]], moment: datetime) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=zip_path.name + ".", suffix=".tmp", dir=zip_path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for arcname in sorted(entries):
                item = entries[arcname]
                info = zipfile.ZipInfo(arcname, date_time=moment.timetuple()[:6])
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                if isinstance(item, bytes):
                    archive.writestr(info, item)
                else:
                    archive.writestr(info, item.read_bytes())
        os.replace(temp_path, zip_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _verify_zip(zip_path: Path, meta: dict[str, Any], entries: dict[str, Union[bytes, Path]]) -> None:
    expected = set(entries)
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            names = set(archive.namelist())
            if names != expected:
                missing = sorted(expected - names)
                extra = sorted(names - expected)
                raise BuildError(f"archive content mismatch; missing={missing}, extra={extra}")
            bad = archive.testzip()
            if bad is not None:
                raise BuildError(f"archive integrity check failed at {bad}")
            archived_metadata = archive.read("metadata.json")
    except zipfile.BadZipFile as exc:
        raise BuildError(f"invalid zip archive {zip_path}: {exc}") from exc
    if archived_metadata != _json_bytes(meta):
        raise BuildError("archived metadata.json does not match source metadata")
    parsed = json.loads(archived_metadata)
    for entry in parsed.get("versions", []):
        for key in entry:
            if key.startswith("download_"):
                raise BuildError(f"archived metadata must not contain {key}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_key(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, str):
        return (0, 0, 0)
    match = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    if not match:
        return (0, 0, 0)
    return tuple(int(part or 0) for part in match.groups())


def _load_packages(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"$schema": SCHEMA_URL, "packages": []}
    data = _read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("packages"), list):
        raise BuildError(f"{path} must contain an object with a packages array")
    return data


def _update_packages(
    data: dict[str, Any],
    meta: dict[str, Any],
    version_entry: dict[str, Any],
    download_url: str,
    download_sha256: str,
    download_size: int,
    install_size: int,
) -> None:
    packages = data["packages"]
    package_meta = {key: value for key, value in meta.items() if key not in {"$schema", "versions"}}
    version = version_entry["version"]

    package = None
    for item in packages:
        if not isinstance(item, dict):
            raise BuildError("packages.json contains a non-object package entry")
        if item.get("identifier") == meta["identifier"]:
            package = item
            break
    if package is None:
        package = {}
        packages.append(package)

    existing_versions = package.get("versions", [])
    if not isinstance(existing_versions, list):
        raise BuildError("package versions must be an array")

    package.pop("versions", None)
    package.update(package_meta)

    new_version = dict(version_entry)
    new_version.update(
        {
            "download_url": download_url,
            "download_sha256": download_sha256,
            "download_size": download_size,
            "install_size": install_size,
        }
    )
    kept = [
        item
        for item in existing_versions
        if isinstance(item, dict) and item.get("version") != version
    ]
    kept.append(new_version)
    package["versions"] = sorted(kept, key=lambda item: _version_key(item.get("version")), reverse=True)
    data["$schema"] = SCHEMA_URL
    data["packages"] = packages


def _write_repository(
    path: Path,
    packages_bytes: bytes,
    repo: str,
    branch: str,
    moment: datetime,
    meta: dict[str, Any],
) -> None:
    data = {
        "$schema": SCHEMA_URL,
        "name": f"{meta['name']} Repository",
        "packages": {
            "url": f"https://raw.githubusercontent.com/{repo}/{branch}/dist/packages.json",
            "sha256": hashlib.sha256(packages_bytes).hexdigest(),
            "update_timestamp": int(moment.timestamp()),
            "update_time_utc": moment.strftime("%Y-%m-%d %H:%M:%S"),
        },
    }
    if "maintainer" in meta:
        data["maintainer"] = meta["maintainer"]
    _write_json(path, data)


def _validate_repo(repo: str) -> None:
    if not REPO_RE.fullmatch(repo):
        raise BuildError(f"invalid repository: {repo!r}")


def _validate_branch(branch: str) -> None:
    if not branch or any(character in branch for character in " \t\r\n"):
        raise BuildError(f"invalid branch: {branch!r}")


def check_package(root: Path = ROOT, tag: Union[str, None] = None) -> dict[str, Any]:
    meta, source, version_entry = _check_package(Path(root).resolve(), tag)
    return {
        "identifier": meta["identifier"],
        "version": version_entry["version"],
        "symbol_file": source.symbol_file,
        "footprint_lib": source.footprint_lib,
        "models_dir": source.models_dir,
        "footprint_nickname": source.footprint_nickname,
    }


def build_package(
    root: Path = ROOT,
    output_dir: Union[Path, None] = None,
    repo: str = DEFAULT_REPO,
    branch: str = DEFAULT_BRANCH,
    tag: Union[str, None] = None,
    timestamp: Union[str, datetime, None] = None,
    write_index: bool = True,
) -> BuildResult:
    root = Path(root).resolve()
    _validate_repo(repo)
    _validate_branch(branch)
    meta, source, version_entry = _check_package(root, tag)
    version = version_entry["version"]
    normalized_tag, _ = _normalize_tag(tag or f"v{version}")
    moment = _parse_timestamp(timestamp)

    if output_dir is None:
        output_path = root / "dist"
    else:
        output_path = Path(output_dir)
        if not output_path.is_absolute():
            output_path = root / output_path
    output_path.mkdir(parents=True, exist_ok=True)

    entries = _collect_entries(meta, source)
    zip_name = f"{meta['identifier']}_v{version}_pcm.zip"
    zip_path = output_path / zip_name
    _write_zip(zip_path, entries, moment)
    _verify_zip(zip_path, meta, entries)

    zip_sha256 = _sha256_file(zip_path)
    zip_size = zip_path.stat().st_size
    install_size = sum(
        len(value) if isinstance(value, bytes) else value.stat().st_size for value in entries.values()
    )
    download_url = f"https://github.com/{repo}/releases/download/{normalized_tag}/{zip_name}"

    packages_path: Union[Path, None] = None
    repository_path: Union[Path, None] = None
    if write_index:
        packages_path = output_path / "packages.json"
        repository_path = output_path / "repository.json"
        data = _load_packages(packages_path)
        _update_packages(data, meta, version_entry, download_url, zip_sha256, zip_size, install_size)
        packages_bytes = _write_json(packages_path, data)
        _write_repository(repository_path, packages_bytes, repo, branch, moment, meta)

    return BuildResult(
        zip_path=zip_path,
        zip_sha256=zip_sha256,
        zip_size=zip_size,
        install_size=install_size,
        packages_path=packages_path,
        repository_path=repository_path,
    )


def _parse_args(argv: Union[list[str], None] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the PhucNT KiCad PCM package and repository indexes.")
    parser.add_argument("--root", default=str(ROOT), help="library source root (default: repository root)")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO),
        help="GitHub repository in owner/name form",
    )
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="branch that hosts dist/packages.json")
    parser.add_argument("--tag", default=None, help="release tag; defaults to v<metadata version>")
    parser.add_argument("--output-dir", default=None, help="output directory; defaults to <root>/dist")
    parser.add_argument("--timestamp", default=None, help="ISO 8601 build timestamp for reproducible output")
    parser.add_argument("--no-index", action="store_true", help="build the archive without updating JSON indexes")
    parser.add_argument("--check-only", action="store_true", help="validate the source tree without writing output")
    return parser.parse_args(argv)


def main(argv: Union[list[str], None] = None) -> int:
    args = _parse_args(argv)
    try:
        if args.check_only:
            info = check_package(Path(args.root), args.tag)
            print(
                f"OK: {info['identifier']} {info['version']} "
                f"({info['footprint_nickname']}, {info['symbol_file'].name})"
            )
            return 0
        result = build_package(
            root=Path(args.root),
            output_dir=Path(args.output_dir) if args.output_dir else None,
            repo=args.repo,
            branch=args.branch,
            tag=args.tag,
            timestamp=args.timestamp,
            write_index=not args.no_index,
        )
        print(f"Archive: {result.zip_path}")
        print(f"SHA-256: {result.zip_sha256}")
        print(f"Download size: {result.zip_size} bytes")
        print(f"Install size: {result.install_size} bytes")
        if result.packages_path is not None:
            print(f"Packages: {result.packages_path}")
        if result.repository_path is not None:
            print(f"Repository: {result.repository_path}")
        return 0
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
