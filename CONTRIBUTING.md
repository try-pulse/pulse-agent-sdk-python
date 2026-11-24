# Contributing

Use Python 3.11–3.14 and a virtual environment.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
make -j3 check
```

Use `make test` for the fast mocked suite. Tests and the Scout example run without Pulse credentials. The [README](README.md#development) lists equivalent commands for Windows and other environments without Make.

Open a pull request with a focused change and the checks you ran. Add a mocked regression test for protocol changes and preserve the public Python API where possible. Review [contract sources](specs/SOURCES.md) before updating a spec and regenerate the wire types with `python scripts/generate_types.py`. Keep changes to generated files tied to the generator or pinned spec.

Maintainers use the [release runbook](docs/releasing.md). Report vulnerabilities privately using the instructions in [SECURITY.md](SECURITY.md).
