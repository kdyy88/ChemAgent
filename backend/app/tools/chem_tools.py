"""
ChemAgent native tool functions.

All tools expose Annotated type hints + comprehensive docstrings so that
AG2's ``register_function`` auto-generates correct JSON Schemas for LLM
function-calling.

Architecture
------------
- Each tool returns a **slim JSON** string to the LLM (summary + result_id).
- Heavy artefacts (base64 images, large coordinate arrays) go into
  ``tool_result_store`` and are pushed to the frontend via WebSocket
  ``tool.result`` events — they never inflate the LLM context window.

Error Defence (three-layer)
---------------------------
- **Layer 1** — Silent programmatic retry (tenacity) for transient network
  errors (PubChem 502, Serper timeout, Redis hiccup).  The LLM never sees
  these — they are resolved in < 5 s.
- **Layer 2** — Fail-fast for logical errors (invalid SMILES, unknown
  compound).  Immediately returns ``retry_hint`` so ChemBrain's FSM can
  self-correct.
- **Layer 3** — Circuit-breaker interface reserved in ``core/tooling.py``
  (not yet wired).

Worker offloading
-----------------
Heavy RDKit computation (descriptors, scaffolds, similarity, substructure)
can be transparently offloaded to an ARQ worker when ``USE_WORKER=1``.
Async tools use ``await run_via_worker()`` directly; fallback uses
``await asyncio.to_thread(sync_fn)`` to keep the event loop free.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Annotated

import requests
from rdkit import Chem
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.chem.rdkit_ops import (
    compute_descriptors,
    compute_similarity,
    mol_to_png_b64,
    murcko_scaffold,
    substructure_match,
)
from app.core.tooling import ToolArtifact, ToolExecutionResult, tool_result_store


# ── Configuration ─────────────────────────────────────────────────────────────

USE_WORKER = os.getenv("USE_WORKER", "0") == "1"


# ── Tenacity retry decorator for transient network errors ─────────────────────

_TRANSIENT_EXCEPTIONS = (
    urllib.error.URLError,
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    OSError,
)

_retry_transient = retry(
    retry=retry_if_exception_type(_TRANSIENT_EXCEPTIONS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    reraise=True,
)


# ── Worker bridge ─────────────────────────────────────────────────────────────


async def _offload(task_name: str, kwargs: dict) -> dict:
    """Run a heavy chem task via ARQ worker or in-thread fallback.

    When ``USE_WORKER=1``, delegates to ``run_via_worker`` (async, Redis
    queue).  Otherwise falls back to ``asyncio.to_thread`` so the
    event-loop is never blocked by RDKit CPU work.
    """
    if USE_WORKER:
        from app.core.task_bridge import run_via_worker

        return await run_via_worker(task_name, kwargs)

    # Fallback: run the sync rdkit/babel function in a thread-pool thread
    from app.worker import _TASK_DISPATCH

    fn = _TASK_DISPATCH.get(task_name)
    if fn is None:
        return {"is_valid": False, "error": f"Unknown task: {task_name}"}
    return await asyncio.to_thread(fn, **kwargs)


# ── PubChem lookup helper ─────────────────────────────────────────────────────

_PUBCHEM_URL = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name"
    "/{name}/property/IsomericSMILES/JSON"
)


@_retry_transient
def _fetch_smiles_from_pubchem(name: str) -> str | None:
    """Fetch canonical SMILES from PubChem by compound name.

    Decorated with ``@_retry_transient`` — network errors (502, timeout)
    are retried up to 3× with exponential back-off.  A 404 (compound not
    found) is **not** a transient error and is returned immediately.
    """
    url = _PUBCHEM_URL.format(name=urllib.parse.quote(name.strip()))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "chem-agent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode())
        props = payload["PropertyTable"]["Properties"]
        entry = props[0]
        return entry.get("IsomericSMILES") or entry.get("SMILES")
    except urllib.error.HTTPError as exc:
        # 404 = compound not found → not transient, return None
        if exc.code == 404:
            return None
        raise  # 5xx etc → let tenacity retry
    except (KeyError, IndexError):
        return None


# ── Serper.dev constants ──────────────────────────────────────────────────────

_SERPER_URL = "https://google.serper.dev/search"
_SERPER_TIMEOUT = 15


# ── Helper: store result and return slim payload ──────────────────────────────


def _slim_response(result: ToolExecutionResult) -> str:
    """Store full result in tool_result_store, return slim JSON for LLM."""
    tool_result_store.put(result)
    slim: dict = {
        "success": result.status == "success",
        "result_id": result.result_id,
        "summary": result.summary,
    }
    if result.error_code:
        slim["error_code"] = result.error_code
    if result.retry_hint:
        slim["retry_hint"] = result.retry_hint
    return json.dumps(slim, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 1 — get_molecule_smiles
# ═══════════════════════════════════════════════════════════════════════════════


def get_molecule_smiles(
    name: Annotated[
        str,
        "化合物的英文名称（INN、IUPAC 或常用名），例如 'aspirin' 或 'apixaban'",
    ],
) -> str:
    """通过化合物英文名称从 PubChem 数据库检索精确的 SMILES 结构式。
    用于在进行分子分析、骨架提取或绘图之前，先获取化合物的标准 SMILES 表示。

    Args:
        name: 化合物英文名称
    """
    smiles = _fetch_smiles_from_pubchem(name)
    if smiles is None:
        result = ToolExecutionResult(
            status="error",
            summary=f"未能在 PubChem 中找到化合物 '{name}'。请检查名称拼写或尝试使用标准英文名。",
            data={"name": name},
            error_code="compound_not_found",
            retry_hint="检查化合物名称是否为标准英文名（INN/IUPAC），避免使用商品名或缩写。",
        )
        return _slim_response(result)

    result = ToolExecutionResult(
        status="success",
        summary=f"已找到 {name} 的 SMILES：{smiles}",
        data={"name": name, "smiles": smiles},
    )
    return _slim_response(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 2 — analyze_molecule  (async — heavy RDKit descriptors)
# ═══════════════════════════════════════════════════════════════════════════════


async def analyze_molecule(
    smiles: Annotated[str, "标准 SMILES 字符串，例如 'CC(=O)OC1=CC=CC=C1C(=O)O'"],
    name: Annotated[str, "化合物名称（可选，用于结果标注）"] = "",
) -> str:
    """验证 SMILES 化学合法性并计算完整分子描述符：Lipinski 五规则（MW/LogP/HBD/HBA）、
    TPSA、QED 药物相似性评分、SA 合成可及性评分、可旋转键数、芳香环数等 15+ 项
    理化性质，同时生成 2D 分子结构图。

    Args:
        smiles: SMILES 字符串
        name: 化合物名称（可选）
    """
    raw = await _offload("rdkit.compute_descriptors", {"smiles": smiles, "name": name})

    if not raw.get("is_valid"):
        result = ToolExecutionResult(
            status="error",
            summary=raw.get("error", "SMILES 解析失败。"),
            data={"smiles": smiles},
            error_code="invalid_smiles",
            retry_hint="请检查 SMILES 的环闭合、芳香性、括号匹配和原子价态，修正后重试。",
        )
        return _slim_response(result)

    d = raw["descriptors"]
    lip = raw["lipinski"]
    verdict = "通过" if lip["pass"] else f"存在 {lip['violations']} 条违规，未通过"

    result = ToolExecutionResult(
        status="success",
        summary=(
            f"分子分析完成。分子量 {d['molecular_weight']} Da，LogP {d['log_p']}，"
            f"QED {d['qed']}，SA Score {d['sa_score']}，{verdict} Lipinski 五规则。"
        ),
        data={},
        artifacts=[
            ToolArtifact(
                kind="json",
                mime_type="application/json",
                encoding="json",
                data=raw,
                title=name.strip() if name.strip() else smiles,
                description=f"分子描述符与 Lipinski 分析：{name or smiles}",
            ),
        ],
    )
    return _slim_response(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 3 — extract_murcko_scaffold  (async — RDKit scaffold + images)
# ═══════════════════════════════════════════════════════════════════════════════


async def extract_murcko_scaffold(
    smiles: Annotated[str, "标准 SMILES 字符串"],
) -> str:
    """提取分子的 Bemis-Murcko 骨架和通用碳骨架。骨架保留环系统和连接子，
    通用骨架进一步将所有原子简化为碳、所有键简化为单键。
    用于分析分子的核心药效团骨架、识别化学系列。

    Args:
        smiles: SMILES 字符串
    """
    raw = await _offload("rdkit.murcko_scaffold", {"smiles": smiles})

    if not raw.get("is_valid"):
        result = ToolExecutionResult(
            status="error",
            summary=raw.get("error", "骨架提取失败。"),
            data={"smiles": smiles},
            error_code="scaffold_error",
            retry_hint="请检查 SMILES 是否合法，确保分子含有环系统。",
        )
        return _slim_response(result)

    artifacts: list[ToolArtifact] = []
    if raw.get("molecule_image"):
        artifacts.append(
            ToolArtifact(
                kind="image",
                mime_type="image/png",
                encoding="base64",
                data=raw["molecule_image"],
                title="原分子结构",
                description="原始分子 2D 结构图",
            )
        )
    if raw.get("scaffold_image"):
        artifacts.append(
            ToolArtifact(
                kind="image",
                mime_type="image/png",
                encoding="base64",
                data=raw["scaffold_image"],
                title="Murcko 骨架",
                description="Bemis-Murcko 骨架 2D 结构图",
            )
        )

    result = ToolExecutionResult(
        status="success",
        summary=f"骨架提取完成。Murcko 骨架：{raw['scaffold_smiles']}",
        data={
            "scaffold_smiles": raw["scaffold_smiles"],
            "generic_scaffold_smiles": raw.get("generic_scaffold_smiles", ""),
        },
        artifacts=artifacts,
    )
    return _slim_response(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 4 — draw_molecule_structure  (async — batch PubChem + RDKit rendering)
# ═══════════════════════════════════════════════════════════════════════════════


async def draw_molecule_structure(
    chemical_names: Annotated[
        str,
        "一个或多个化合物英文名称，以英文逗号分隔，例如 'aspirin, caffeine, ibuprofen'",
    ],
) -> str:
    """通过 PubChem 查询化合物英文名称对应的 SMILES，然后使用 RDKit 生成
    每个化合物的 2D 分子结构图（PNG 图像）。支持批量输入多个化合物名称。

    Args:
        chemical_names: 化合物英文名称，多个名称用英文逗号分隔
    """
    names = [n.strip() for n in chemical_names.split(",") if n.strip()]
    if not names:
        result = ToolExecutionResult(
            status="error",
            summary="未提供任何化合物名称。",
            error_code="empty_input",
        )
        return _slim_response(result)

    artifacts: list[ToolArtifact] = []
    failed: list[dict] = []

    # PubChem lookups + RDKit rendering — run in thread to avoid blocking
    # the event loop (each compound involves network I/O + CPU rendering).
    def _render_all():
        _ok: list[ToolArtifact] = []
        _fail: list[dict] = []
        for compound_name in names:
            smiles = _fetch_smiles_from_pubchem(compound_name)
            if smiles is None:
                _fail.append({"name": compound_name, "reason": "PubChem 未找到该化合物"})
                continue

            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                _fail.append({"name": compound_name, "reason": f"RDKit 无法解析 SMILES：{smiles}"})
                continue

            try:
                png_b64 = mol_to_png_b64(mol, size=(400, 400))
            except Exception as exc:
                _fail.append({"name": compound_name, "reason": f"图像生成失败：{exc}"})
                continue

            _ok.append(
                ToolArtifact(
                    kind="image",
                    mime_type="image/png",
                    encoding="base64",
                    data=png_b64,
                    title=compound_name,
                    description=f"{compound_name} 的 2D 结构图（SMILES: {smiles}）",
                )
            )
        return _ok, _fail

    artifacts, failed = await asyncio.to_thread(_render_all)

    ok = len(artifacts)
    fail = len(failed)

    if ok == 0:
        result = ToolExecutionResult(
            status="error",
            summary=f"所有 {fail} 个化合物均解析失败。",
            data={"failed": failed},
            error_code="all_failed",
            retry_hint="请检查化合物名称是否为标准英文名（INN/IUPAC），避免商品名和缩写。",
        )
    elif fail == 0:
        result = ToolExecutionResult(
            status="success",
            summary=f"成功绘制 {ok} 个结构图。",
            data={},
            artifacts=artifacts,
        )
    else:
        result = ToolExecutionResult(
            status="success",
            summary=f"成功绘制 {ok} 个结构图，{fail} 个解析失败。",
            data={"failed": failed},
            artifacts=artifacts,
        )

    return _slim_response(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 5 — search_web  (sync — HTTP call, auto-threaded by AG2)
# ═══════════════════════════════════════════════════════════════════════════════


def search_web(
    query: Annotated[
        str,
        "搜索关键词，例如 'FDA approved lung cancer drugs 2025' 或 'EGFR inhibitor clinical trials'",
    ],
) -> str:
    """搜索互联网和医学文献，获取最新药物审批信息、临床试验结果、分子发现新闻等
    化学与药理学领域的前沿情报。返回相关结果的标题、URL 和摘要。

    Args:
        query: 搜索查询字符串
    """
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        result = ToolExecutionResult(
            status="error",
            summary="搜索服务未配置（缺少 SERPER_API_KEY）。",
            data={"query": query},
            error_code="missing_api_key",
        )
        return _slim_response(result)

    try:
        response = _serper_search(api_key, query)
    except requests.exceptions.Timeout:
        result = ToolExecutionResult(
            status="error",
            summary=f"搜索超时（{_SERPER_TIMEOUT}s）：{query}",
            data={"query": query},
            error_code="timeout",
            retry_hint="尝试缩短或精简搜索关键词后重试。",
        )
        return _slim_response(result)
    except requests.exceptions.RequestException as exc:
        result = ToolExecutionResult(
            status="error",
            summary=f"搜索请求失败：{exc}",
            data={"query": query},
            error_code="request_failed",
        )
        return _slim_response(result)

    data = response.json()

    results: list[dict] = []
    for item in data.get("organic", []):
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
        )

    if answer_box := data.get("answerBox"):
        answer_text = (
            answer_box.get("answer")
            or answer_box.get("snippet")
            or answer_box.get("snippetHighlighted", "")
        )
        if answer_text:
            results.insert(
                0,
                {
                    "title": answer_box.get("title", "Direct Answer"),
                    "url": answer_box.get("link", ""),
                    "snippet": answer_text,
                },
            )

    result = ToolExecutionResult(
        status="success",
        summary=f"找到 {len(results)} 条与 '{query}' 相关的结果。",
        data={"query": query, "results": results},
    )
    return _slim_response(result)


@_retry_transient
def _serper_search(api_key: str, query: str) -> requests.Response:
    """Perform the actual Serper HTTP call (tenacity-retried on transient errors)."""
    response = requests.post(
        _SERPER_URL,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "num": 8},
        timeout=_SERPER_TIMEOUT,
    )
    response.raise_for_status()
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 6 — compute_molecular_similarity  (async — RDKit fingerprints + images)
# ═══════════════════════════════════════════════════════════════════════════════


async def compute_molecular_similarity(
    smiles1: Annotated[str, "第一个分子的 SMILES 字符串"],
    smiles2: Annotated[str, "第二个分子的 SMILES 字符串"],
) -> str:
    """计算两个分子之间的 Tanimoto 相似度（基于 Morgan/ECFP4 指纹）。
    相似度范围 0~1，>0.85 为高度相似，0.7~0.85 中等，0.4~0.7 低度，<0.4 基本不相似。

    Args:
        smiles1: 第一个分子的 SMILES
        smiles2: 第二个分子的 SMILES
    """
    raw = await _offload(
        "rdkit.compute_similarity", {"smiles1": smiles1, "smiles2": smiles2}
    )

    if not raw.get("is_valid"):
        result = ToolExecutionResult(
            status="error",
            summary=raw.get("error", "相似度计算失败。"),
            data={"smiles1": smiles1, "smiles2": smiles2},
            error_code="similarity_error",
            retry_hint="请检查两个 SMILES 是否均合法。",
        )
        return _slim_response(result)

    artifacts: list[ToolArtifact] = []
    for key, label in [("molecule_1", "分子 1"), ("molecule_2", "分子 2")]:
        mol_data = raw[key]
        if mol_data.get("image"):
            artifacts.append(
                ToolArtifact(
                    kind="image",
                    mime_type="image/png",
                    encoding="base64",
                    data=mol_data["image"],
                    title=f"{label}（{mol_data['smiles']}）",
                    description=f"{label} 2D 结构图",
                )
            )

    result = ToolExecutionResult(
        status="success",
        summary=(
            f"Tanimoto 相似度：{raw['tanimoto']}（{raw['interpretation']}）。"
            f"分子 1：{raw['molecule_1']['formula']}，分子 2：{raw['molecule_2']['formula']}。"
        ),
        data={
            "tanimoto": raw["tanimoto"],
            "interpretation": raw["interpretation"],
            "fingerprint_type": raw["fingerprint_type"],
        },
        artifacts=artifacts,
    )
    return _slim_response(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 7 — check_substructure  (async — RDKit SMARTS matching + PAINS)
# ═══════════════════════════════════════════════════════════════════════════════


async def check_substructure(
    smiles: Annotated[str, "目标分子的 SMILES 字符串"],
    smarts_pattern: Annotated[
        str,
        "SMARTS 子结构模式，例如 'c1ccccc1'（苯环）或 '[OH]'（羟基）",
    ],
) -> str:
    """检查目标分子是否包含指定的 SMARTS 子结构模式，并执行 PAINS（泛靶点干扰化合物）
    筛查。返回匹配数量和 PAINS 告警信息。

    Args:
        smiles: 目标分子的 SMILES
        smarts_pattern: SMARTS 子结构模式
    """
    raw = await _offload(
        "rdkit.substructure_match",
        {"smiles": smiles, "smarts_pattern": smarts_pattern},
    )

    if not raw.get("is_valid"):
        result = ToolExecutionResult(
            status="error",
            summary=raw.get("error", "子结构匹配失败。"),
            data={"smiles": smiles, "smarts_pattern": smarts_pattern},
            error_code="substructure_error",
            retry_hint="请检查 SMILES 和 SMARTS 表达式是否合法。",
        )
        return _slim_response(result)

    pains_status = (
        "PAINS 清洁"
        if raw["pains_clean"]
        else f"发现 {len(raw['pains_alerts'])} 个 PAINS 告警"
    )

    artifacts: list[ToolArtifact] = []
    if raw.get("highlighted_image"):
        artifacts.append(
            ToolArtifact(
                kind="image",
                mime_type="image/png",
                encoding="base64",
                data=raw["highlighted_image"],
                title="子结构匹配结果",
                description=f"匹配 SMARTS '{smarts_pattern}' 的高亮结构图",
            )
        )

    result = ToolExecutionResult(
        status="success",
        summary=(
            f"子结构{'匹配成功' if raw['matched'] else '未匹配'}，"
            f"共 {raw['match_count']} 处匹配。{pains_status}。"
        ),
        data={
            "matched": raw["matched"],
            "match_count": raw["match_count"],
            "pains_clean": raw["pains_clean"],
            "pains_alerts": raw.get("pains_alerts", []),
        },
        artifacts=artifacts,
    )
    return _slim_response(result)
