"""Run after installing a wheel or sdist in a clean environment."""

from __future__ import annotations

from importlib.metadata import distribution
from importlib.resources import files
from pathlib import Path

import pulse_agent_sdk


def main() -> None:
    package = distribution("pulse-agent-sdk")
    installed_module = Path(str(package.locate_file("pulse_agent_sdk/__init__.py")))
    assert Path(pulse_agent_sdk.__file__).resolve() == installed_module.resolve()
    assert files("pulse_agent_sdk").joinpath("py.typed").is_file()
    assert package.metadata["License-Expression"] == "MIT"
    for name in pulse_agent_sdk.__all__:
        assert getattr(pulse_agent_sdk, name) is not None, name
    print(f"Installed artifact imports and public exports verified for {package.version}.")


if __name__ == "__main__":
    main()
