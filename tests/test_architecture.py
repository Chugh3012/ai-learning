import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _imports(path: Path) -> set[str]:
    mods: set[str] = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            mods.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module)
    return mods


def _py(*parts: str) -> list[Path]:
    return [p for p in ROOT.joinpath(*parts).rglob("*.py") if "__pycache__" not in str(p)]


class TestArchitectureBoundaries(unittest.TestCase):
    """The eval-gate guards output quality; these guard the ARCHITECTURE so a future change (or a
    builder-agent PR) that erodes a boundary fails RED instead of merging green."""

    def test_reelforge_is_a_standalone_engine(self):
        # The video engine must never depend on the app — its only seam is a Storyboard.
        for f in _py("reelforge"):
            bad = [m for m in _imports(f) if m == "prism" or m.startswith("prism.")]
            self.assertEqual(bad, [], f"{f} imports {bad}; reelforge must stay standalone")

    def test_domain_does_not_depend_on_outer_layers(self):
        for f in _py("prism", "domain"):
            bad = [m for m in _imports(f) if m.startswith(("prism.services", "prism.repositories"))]
            self.assertEqual(bad, [], f"{f} imports {bad}; domain must not depend on outer layers")

    def test_sqlite_is_confined_to_repositories(self):
        # The store seam: only repositories/ may know the backend is SQLite. Everything else
        # depends on KnowledgeBase's methods, so swapping the store later stays a repository change.
        for layer in ("services", "cli", "domain", "lib"):
            for f in _py("prism", layer):
                self.assertNotIn("sqlite3", _imports(f),
                                 f"{f} imports sqlite3 outside repositories/ — the store seam leaked")

    def test_consumers_never_provision(self):
        # Consumers (reel, builder) READ lenses; they never create them or mint ids.
        for f in [ROOT / "prism" / "cli" / "reel.py", *_py("builder")]:
            src = f.read_text(encoding="utf-8")
            for forbidden in ("provision_feed", "upsert_entity", "delete_entity", "_mint("):
                self.assertNotIn(forbidden, src,
                                 f"{f.name} references {forbidden}; consumers must not provision")


if __name__ == "__main__":
    unittest.main()
