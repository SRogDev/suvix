"""Foundation tests: the package must be importable and versioned."""

import suvix


def test_package_imports_and_exposes_version() -> None:
    assert isinstance(suvix.__version__, str)
    assert suvix.__version__
