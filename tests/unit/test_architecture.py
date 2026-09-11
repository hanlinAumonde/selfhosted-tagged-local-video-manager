"""
Guards on which direction dependencies are allowed to point.

These assert structure, not behaviour. They exist because a reversed import is invisible
in review and in green tests — it only shows up later, as a service that cannot be reused
and a test suite that has to build a GraphQL schema to exercise a file walk.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[2] / "src"

# Presentation modules: they define the strawberry types the schema is built from.
#: Modules that define Beanie documents, one per feature that owns a collection.
DOCUMENT_MODULES = {
    "src.features.catalog.video",
    "src.features.catalog.video_tag",
    "src.features.browsing.dir_metadata",
    "src.features.migration.migration_task",
}


def _is_document_module(name: str) -> bool:
    return name in DOCUMENT_MODULES


PRESENTATION_MODULES = {
    "src.schema.types.video_type",
    "src.schema.types.fileBrowse_type",
    "src.schema.types.search_type",
    "src.schema.types.migration_type",
    "src.schema.types.scalars",
}


def _imported_modules(path: Path) -> set[str]:
    """Every module name a file imports, whether via ``import x`` or ``from x import y``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _service_modules() -> list[Path]:
    """Every module under features/, minus the ones that are a delivery surface."""
    return sorted(
        p for p in (SRC / "features").rglob("*.py")
        if "__pycache__" not in p.parts and not p.name.endswith("_router.py")
    )


def _relative(path: Path) -> str:
    return path.relative_to(SRC.parent).as_posix()


class TestServicesDoNotDependOnGraphQL:
    """GraphQL is one delivery channel among several — there is also a REST router, and
    background tasks with no request at all. A service that builds strawberry types can
    only ever be called from a resolver, and drags schema construction into every test
    that touches it."""

    def test_no_service_imports_strawberry(self):
        offenders = [
            _relative(path)
            for path in _service_modules()
            if "strawberry" in _imported_modules(path)
        ]

        assert offenders == [], f"services importing strawberry: {offenders}"

    def test_no_service_imports_a_presentation_type_module(self):
        offenders = {
            _relative(path): sorted(_imported_modules(path) & PRESENTATION_MODULES)
            for path in _service_modules()
            if _imported_modules(path) & PRESENTATION_MODULES
        }

        assert offenders == {}, f"services importing GraphQL types: {offenders}"


class TestResolversDoNotQueryTheDatabase:
    """A resolver's job is validate → delegate → map. Query logic that lives here cannot
    be reused by the REST router or a background task, and can only be exercised by going
    through GraphQL."""

    def test_no_resolver_imports_a_document_model(self):
        offenders = {}
        for path in sorted((SRC / "resolvers").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            leaked = sorted(
                name for name in _imported_modules(path)
                if name.startswith("src.features") and _is_document_module(name)
            )
            if leaked:
                offenders[_relative(path)] = leaked

        assert offenders == {}, f"resolvers importing ODM documents: {offenders}"


#: Features whose job is to run background work over what the other features own. They
#: read the catalogue and the directory tree; nothing reads them back.
JOB_FEATURES = {"migration"}


def _owning_feature(path: Path) -> str:
    """Which feature package a file under features/ belongs to."""
    return path.relative_to(SRC / "features").parts[0]


class TestJobFeaturesAreLeaves:
    """A feature that runs background work depends on the features it acts upon —
    migration moves catalog records and updates browsing's directory metadata. The reverse
    must not happen.

    It is tempting when a reader needs one fact a job knows ("is this file spoken for?"),
    and importing the job's helper is the shortest way to get it. The cost only shows up
    later: the two features can no longer be read, tested or reused apart, and the next
    kind of job has nowhere to publish the same fact from. Such a fact belongs behind an
    abstraction in platform/ that both sides can reach — ``PathLockRegistry`` is the one
    that exists for this question."""

    def test_no_feature_imports_a_job_feature(self):
        offenders = {}
        for path in sorted((SRC / "features").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            owner = _owning_feature(path)
            if owner in JOB_FEATURES:
                continue
            leaked = sorted(
                name for name in _imported_modules(path)
                if _feature_of(name) in JOB_FEATURES
            )
            if leaked:
                offenders[_relative(path)] = leaked

        assert offenders == {}, f"features importing a job feature: {offenders}"


def _feature_of(module_name: str) -> str | None:
    """Which feature package a module name belongs to, or None if it names no feature."""
    parts = module_name.split(".")
    if len(parts) >= 3 and parts[0] == "src" and parts[1] == "features":
        return parts[2]
    return None


class TestPlatformStaysGeneric:
    """The platform packages are the reusable core: they may be imported by features, and
    must never import one."""

    def test_platform_does_not_import_a_feature(self):
        offenders = {}
        for path in (SRC / "platform").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            leaked = sorted(
                name for name in _imported_modules(path) if name.startswith("src.features")
            )
            if leaked:
                offenders[_relative(path)] = leaked

        assert offenders == {}, f"platform modules importing features: {offenders}"
