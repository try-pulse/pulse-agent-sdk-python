# Releasing the Python SDK

**Pushing a new protected `v*` tag starts publication to PyPI.** Run the rehearsal on the release branch before creating a tag.

1. Set the version in `pyproject.toml` and add a matching first entry to `CHANGELOG.md`. Push the release branch and open its PR.
2. In **Actions → Release SDK → Run workflow**, select the **release branch** and leave **Publish** off. The dry run exercises the supported Python matrix, builds the wheel and sdist, checks their metadata, and installs each archive. Download `sdk-distributions` from this run.
3. Compute the SHA-256 of both downloaded archives. Run Cyborg's full Pulse integration suite against this exact wheel and record its digest and result. Add the two approved digests to `.github/release-digests/v<VERSION>.json` in the PR. Use the keys and format in the [manifest example](../.github/release-digests/v0.1.2.json). If either archive changes, verify the replacement before approval.
4. Once the release is approved and the PR has merged, push a new tag `v<VERSION>` at the reviewed merge commit. The [release workflow](../.github/workflows/release.yml) checks the commit is on `main`, runs CI again and compares the rebuilt archives with the tagged manifest. Matching files are uploaded via PyPI Trusted Publishing with attestations. A mismatch stops the upload.
5. Confirm both public files match the approved hashes and smoke-test a clean install from PyPI. Create GitHub release notes against the existing tag using the version's changelog entry and `gh release create --verify-tag`. Release notes for an already-published version can be added independently.

For a retry of a failed upload, inspect PyPI first. Use the manual publish option only for the same approved tag and digests after confirming the version's upload state.

## Local package check

Set `VERSION` to the proposed version and use a fresh output directory. The tag argument below checks package metadata locally.

```sh
python -m pip install '.[release]'
out=$(mktemp -d)
python -m build --outdir "$out"
python -m twine check --strict "$out"/*
python scripts/check_release.py --tag "v${VERSION:?set VERSION}" --dist "$out"
```
