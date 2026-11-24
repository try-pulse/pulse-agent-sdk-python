# Releasing the Python SDK

1. Update the version in `pyproject.toml` and add a matching first entry in `CHANGELOG.md`. Run CI on the release commit and use an exact `v<version>` tag.
2. Run the **Release SDK** workflow against that tag with **Publish** off. It checks the tag, runs the full Python matrix, builds both distributions, validates metadata, and installs and exercises each artifact.
3. Before the first upload, configure GitHub's `pypi` environment to accept version tags and enable private vulnerability reporting. Set up a pending [PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) for project `pulse-agent-sdk`, owner `try-pulse`, repository `pulse-agent-sdk-python`, workflow `release.yml`, environment `pypi`.
4. Dispatch the workflow on the matching tag with **Publish** on. Only the final job has OIDC permission. It publishes that run's verified wheel and sdist with PyPI attestations. Confirm the published files and use the matching changelog entry for the GitHub release notes.

For local validation, use a fresh output directory.

```bash
python -m pip install '.[release]'
python -m build --outdir dist/release-check
python -m twine check --strict dist/release-check/*
python scripts/check_release.py --tag v0.1.1 --dist dist/release-check
```
