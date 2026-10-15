"""Static checks for the Streamlit playground (Milestone 4, plan §14).

The playground is an optional extra, so these tests must pass with neither
streamlit installed nor a browser available: they byte-compile the app and
verify import hygiene through the AST. Nothing here imports streamlit.
"""

from __future__ import annotations

import ast
import py_compile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = REPO_ROOT / "playground" / "app.py"
SRC_ROOT = REPO_ROOT / "src" / "suvix"


def _module_imports(path: Path) -> list[str]:
    """Imported module names in a file (``import x`` and ``from x import y``)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


def _is_public_suvix_import(module: str) -> bool:
    """Only the top-level package and the public adapter surface are public."""
    return (
        module == "suvix"
        or module == "suvix.adapters"
        or module.startswith("suvix.adapters.")
    )


def test_app_compiles(tmp_path: Path) -> None:
    """playground/app.py must byte-compile (py_compile; bytecode goes to tmp)."""
    assert APP_PATH.is_file(), f"missing playground app: {APP_PATH}"
    py_compile.compile(str(APP_PATH), cfile=str(tmp_path / "app.pyc"), doraise=True)


def test_app_imports_streamlit_and_only_public_suvix_api() -> None:
    """The app may use streamlit plus the public suvix API only.

    Allowed suvix imports: the top-level ``suvix`` package and the public
    adapter surface (``suvix.adapters.*``). Private internals such as
    ``suvix.extraction`` or ``suvix.validation`` are forbidden here.
    """
    modules = _module_imports(APP_PATH)
    assert any(m == "streamlit" or m.startswith("streamlit.") for m in modules), (
        "playground/app.py must import streamlit"
    )
    private = [
        module
        for module in modules
        if module.startswith("suvix") and not _is_public_suvix_import(module)
    ]
    assert not private, f"playground/app.py imports private suvix internals: {private}"


def test_core_library_never_imports_streamlit() -> None:
    """No file under src/suvix/ may import streamlit (the library stays UI-free)."""
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        for module in _module_imports(path):
            if module == "streamlit" or module.startswith("streamlit."):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {module}")
    assert not offenders, (
        "core library must never import streamlit:\n" + "\n".join(offenders)
    )
