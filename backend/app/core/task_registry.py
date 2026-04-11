"""
task_registry — shared task-name → callable mapping.

Imported by:
  app/core/task_bridge.py  (direct fallback when Redis is unavailable)
  app/worker.py            (ARQ worker dispatch table)

Adding a new chem operation:
  1. Add the function import here.
  2. Add the "module.function_name": TaskSpec(...) entry to TASK_DISPATCH.
  No other file needs to change.

For tasks that produce downloadable artifacts (e.g. ZIP, SDF), add an
ArtifactSpec so worker.py knows how to persist the binary content without
any hardcoded task-name checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.chem.babel_ops import (
    build_3d_conformer,
    compute_mol_properties,
    compute_partial_charges,
    convert_format,
    list_supported_formats,
    prepare_pdbqt,
    sdf_merge,
    sdf_split,
)
from app.chem.rdkit_ops import (
    compute_descriptors,
    compute_lipinski,
    compute_similarity,
    murcko_scaffold,
    strip_salts_and_neutralize,
    substructure_match,
    validate_smiles,
)

TaskFn = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ArtifactSpec:
    """Describes how to extract and persist a binary artifact from a task result.

    Attributes:
        content_key:       Key to pop from the result dict (holds raw bytes or str).
        filename_template: Filename template; ``{stem}`` is replaced with the
                           sanitised ``filename_base`` kwarg (or ``fallback``).
        fallback_stem:     Default stem when no ``filename_base`` is provided.
        media_type:        MIME type used when storing the artifact.
        encode_utf8:       If True, encode a str result as UTF-8 bytes before storing.
    """

    content_key: str
    filename_template: str
    fallback_stem: str
    media_type: str
    encode_utf8: bool = False


@dataclass(frozen=True)
class TaskSpec:
    """Bundles a callable with optional artifact persistence metadata."""

    fn: TaskFn
    artifact: ArtifactSpec | None = None


TASK_DISPATCH: dict[str, TaskSpec] = {
    # ── RDKit ──────────────────────────────────────────────────────────────
    "rdkit.compute_lipinski":           TaskSpec(compute_lipinski),
    "rdkit.validate_smiles":            TaskSpec(validate_smiles),
    "rdkit.strip_salts_and_neutralize": TaskSpec(strip_salts_and_neutralize),
    "rdkit.compute_descriptors":        TaskSpec(compute_descriptors),
    "rdkit.compute_similarity":         TaskSpec(compute_similarity),
    "rdkit.substructure_match":         TaskSpec(substructure_match),
    "rdkit.murcko_scaffold":            TaskSpec(murcko_scaffold),
    # ── Open Babel ─────────────────────────────────────────────────────────
    "babel.convert_format":             TaskSpec(convert_format),
    "babel.build_3d_conformer":         TaskSpec(build_3d_conformer),
    "babel.prepare_pdbqt":              TaskSpec(prepare_pdbqt),
    "babel.compute_mol_properties":     TaskSpec(compute_mol_properties),
    "babel.compute_partial_charges":    TaskSpec(compute_partial_charges),
    "babel.list_supported_formats":     TaskSpec(list_supported_formats),
    "babel.sdf_split": TaskSpec(
        sdf_split,
        artifact=ArtifactSpec(
            content_key="zip_bytes",
            filename_template="{stem}_split.zip",
            fallback_stem="split",
            media_type="application/zip",
        ),
    ),
    "babel.sdf_merge": TaskSpec(
        sdf_merge,
        artifact=ArtifactSpec(
            content_key="sdf_content",
            filename_template="{stem}.sdf",
            fallback_stem="merged_library",
            media_type="chemical/x-mdl-sdfile",
            encode_utf8=True,
        ),
    ),
}

