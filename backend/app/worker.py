from __future__ import annotations

import asyncio
import os
import re
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
from app.core.task_queue import (
    build_redis_settings,
    get_default_artifact_ttl_seconds,
    get_default_result_ttl_seconds,
    get_worker_job_timeout_seconds,
    get_worker_max_jobs,
    store_artifact,
    store_task_result,
)

TaskFn = Callable[..., dict[str, Any]]

_TASK_DISPATCH: dict[str, TaskFn] = {
    "rdkit.compute_lipinski": compute_lipinski,
    "rdkit.validate_smiles": validate_smiles,
    "rdkit.strip_salts_and_neutralize": strip_salts_and_neutralize,
    "rdkit.compute_descriptors": compute_descriptors,
    "rdkit.compute_similarity": compute_similarity,
    "rdkit.substructure_match": substructure_match,
    "rdkit.murcko_scaffold": murcko_scaffold,
    "babel.convert_format": convert_format,
    "babel.build_3d_conformer": build_3d_conformer,
    "babel.prepare_pdbqt": prepare_pdbqt,
    "babel.compute_mol_properties": compute_mol_properties,
    "babel.compute_partial_charges": compute_partial_charges,
    "babel.list_supported_formats": list_supported_formats,
    "babel.sdf_split": sdf_split,
    "babel.sdf_merge": sdf_merge,
}


def _sanitize_stem(name: str | None, fallback: str) -> str:
    stem = (name or "").strip()
    if stem.lower().endswith(".sdf"):
        stem = stem[:-4]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return stem or fallback


async def _execute_task(task_name: str, kwargs: dict[str, Any], task_id: str) -> dict[str, Any]:
    fn = _TASK_DISPATCH.get(task_name)
    if fn is None:
        return {"is_valid": False, "error": f"未知任务：{task_name}"}

    task_kwargs = dict(kwargs)
    filename_base = task_kwargs.pop("filename_base", None)
    result = await asyncio.to_thread(fn, **task_kwargs)

    if task_name == "babel.sdf_split" and result.get("is_valid"):
        zip_bytes = result.pop("zip_bytes", b"")
        download_id = task_id
        filename_stem = _sanitize_stem(filename_base, "split")
        await store_artifact(
            download_id,
            content=zip_bytes,
            filename=f"{filename_stem}_split.zip",
            media_type="application/zip",
            ttl_seconds=get_default_artifact_ttl_seconds(),
        )
        result["download_id"] = download_id

    if task_name == "babel.sdf_merge" and result.get("is_valid"):
        sdf_content = result.pop("sdf_content", "")
        download_id = task_id
        filename_stem = _sanitize_stem(filename_base, "merged_library")
        await store_artifact(
            download_id,
            content=sdf_content.encode("utf-8"),
            filename=f"{filename_stem}.sdf",
            media_type="chemical/x-mdl-sdfile",
            ttl_seconds=get_default_artifact_ttl_seconds(),
        )
        result["download_id"] = download_id

    return result


async def run_chem_task(ctx: dict[str, Any], task_name: str, kwargs: dict[str, Any], task_id: str) -> dict[str, Any]:
    try:
        result = await _execute_task(task_name, kwargs, task_id)
    except Exception as exc:
        result = {"is_valid": False, "error": f"任务执行失败：{exc}"}

    await store_task_result(task_id, result, ttl_seconds=get_default_result_ttl_seconds())
    return result


class WorkerSettings:
    functions = [run_chem_task]
    redis_settings = build_redis_settings()
    max_jobs = get_worker_max_jobs()
    job_timeout = get_worker_job_timeout_seconds()
    keep_result = 0
    queue_name = os.environ.get("CHEMAGENT_QUEUE_NAME", "arq:queue")
