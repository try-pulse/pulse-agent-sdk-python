"""Check release metadata and the contents of the wheel and sdist."""

from __future__ import annotations

import argparse
import os
import tarfile
import tomllib
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile

from packaging.utils import parse_sdist_filename, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def metadata(raw: bytes) -> Message:
    return BytesParser().parsebytes(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME")
                        if os.environ.get("GITHUB_REF_TYPE") == "tag" else None)
    args = parser.parse_args()

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    name, version = project["name"], project["version"]
    if args.tag is not None:
        require(args.tag == f"v{version}", f"Release tag must be v{version}")
    github_repo = os.environ.get("GITHUB_REPOSITORY")
    if args.tag is not None and github_repo:
        require(
            project["urls"]["Repository"] == f"https://github.com/{github_repo}",
            "Package repository URL does not match GITHUB_REPOSITORY",
        )
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    require(next((line for line in changelog if line.startswith("## ")), "") == f"## {version}",
            f"First changelog entry must be {version}")

    wheels = list(args.dist.glob("*.whl"))
    sources = list(args.dist.glob("*.tar.gz"))
    require(len(wheels) == len(sources) == 1, "Expected one wheel and one source distribution")
    wheel_name, wheel_version, _, tags = parse_wheel_filename(wheels[0].name)
    source_name, source_version = parse_sdist_filename(sources[0].name)
    require(wheel_name == source_name == name and str(wheel_version) == str(source_version) == version,
            "Distribution filenames do not match pyproject.toml")
    require({str(tag) for tag in tags} == {"py3-none-any"}, "Expected a pure-Python wheel")
    with ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        require({
            "pulse_agent_sdk/py.typed", "pulse_agent_sdk/_generated.py",
            "pulse_agent_sdk/_generated_api.py", "pulse_agent_sdk/__init__.py",
        } <= names, "Wheel is missing SDK modules or typing marker")
        wheel_metadata = metadata(wheel.read(next(path for path in names if path.endswith(".dist-info/METADATA"))))
    with tarfile.open(sources[0], "r:gz") as source:
        prefix = sources[0].name.removesuffix(".tar.gz")
        names = {path.removeprefix(f"{prefix}/") for path in source.getnames()}
        require({
            "pyproject.toml", "README.md", "LICENSE", "CHANGELOG.md", "SECURITY.md",
            "docs/quickstart.md", "examples/scout.py", "scripts/generate_types.py",
            "specs/SHA256SUMS", "fixtures/agent-session-created.json", "tests/test_protocol.py",
        } <= names, "Source distribution is missing tests, specs, example or documentation")
        package_info = source.extractfile(f"{prefix}/PKG-INFO")
        assert package_info is not None
        source_metadata = metadata(package_info.read())
    for distribution in (wheel_metadata, source_metadata):
        require(distribution["Name"] == name and distribution["Version"] == version, "Invalid package metadata")
        require(distribution["Requires-Python"] == project["requires-python"], "Invalid Requires-Python")
        require(distribution["License-Expression"] == project["license"], "Invalid license expression")
        require(distribution["License-File"] == "LICENSE", "Missing license file metadata")
        require(distribution["Description-Content-Type"] == "text/markdown", "Missing Markdown content type")
    for field in ("Requires-Dist", "Project-URL", "Classifier"):
        require(wheel_metadata.get_all(field) == source_metadata.get_all(field), f"Metadata differs for {field}")
    print(f"Release artifacts and metadata verified for {name} {version}.")


if __name__ == "__main__":
    main()
