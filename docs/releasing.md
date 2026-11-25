# Releasing the Python SDK

## Prepare 0.1.2 for approval

The reviewed baseline is 0.1.2rc2. This preparation ends with verified stable archives and a Cyborg result tied to the wheel digest. Publication requires the maintainer's explicit approval.

1. Review the release diff, preserve concurrent changes, set the project version to `0.1.2`, and summarize the user-visible changes since 0.1.1 in the first changelog entry. Check current release instructions and version examples for stale references.
2. Run `make check` on Python 3.11–3.14 with mocked endpoints. Build the stable wheel and sdist into `dist/stable-0.1.2/`. Validate filenames, embedded version, contents, strict Twine metadata, and `scripts/check_release.py --tag v0.1.2 --dist dist/stable-0.1.2`. This tag argument validates metadata locally.
3. Install both exact archives in separate clean environments, run the installed-package smoke and offline Scout, then record relative wheel and sdist filenames and SHA-256 digests in `dist/stable-0.1.2/SHA256SUMS`. Make the manifest available only after these final bytes pass. Retain the artifacts through approval.
4. Cyborg verifies the wheel in an isolated environment and records its digest with the complete Pulse integration result. A rebuilt wheel with a different digest needs its own downstream run. Record which checks ran locally and which ran in hosted CI.
5. Following explicit release approval and authorization for the required Git operations, compare the artifacts produced by the release workflow with the approved digests before allowing the protected PyPI job to proceed. If they differ, verify the new artifacts and obtain approval for those bytes. Confirm the published files match before Cyborg adopts the public pin.

## Tagged release workflow

1. Update the version in `pyproject.toml` and add a matching first entry in `CHANGELOG.md`. Run CI on the release commit and use an exact `v<version>` tag.
2. Run the **Release SDK** workflow against that tag with **Publish** off. It checks the tag, runs the full Python matrix, builds both distributions, validates metadata, and installs and exercises each artifact.
3. Before the first upload, configure GitHub's `pypi` environment to accept version tags and enable private vulnerability reporting. Set up a pending [PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) for project `pulse-agent-sdk`, owner `try-pulse`, repository `pulse-agent-sdk-python`, workflow `release.yml`, environment `pypi`.
4. Dispatch the workflow on the matching tag with **Publish** on. Only the final job has OIDC permission. It publishes that run's verified wheel and sdist with PyPI attestations. Confirm the published files and use the matching changelog entry for the GitHub release notes.

For local validation, use a fresh output directory.

```bash
python -m pip install '.[release]'
python -m build --outdir dist/release-check
python -m twine check --strict dist/release-check/*
python scripts/check_release.py --tag v0.1.2 --dist dist/release-check
```
