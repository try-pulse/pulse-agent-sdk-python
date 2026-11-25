# Publish an approved SDK release

Include the SHA-256 digests of the approved wheel and sdist in a release PR, using the versioned JSON file in this directory as the template. Merge the reviewed PR, then push the protected version tag at its merged commit.

For 0.1.2, replace `MERGED_RELEASE_SHA` with the commit GitHub shows for the merged release PR.

```sh
git fetch origin main
git tag v0.1.2 MERGED_RELEASE_SHA
git push origin refs/tags/v0.1.2
```

The tag push starts **Release SDK**. It checks that the tagged commit is on main, runs the Python matrix, builds and tests both distributions, and checks their digests before uploading them to PyPI. A missing manifest or checksum mismatch stops publication. The manual workflow remains available for a dry run or to retry a tagged release with the approved digests.
