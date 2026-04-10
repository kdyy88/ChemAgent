from __future__ import annotations

import json

import pytest

from app.agents.sub_agents.protocol import build_subagent_report_xml, parse_subagent_report_xml
from app.agents.sub_agents.runtime_tools import tool_task_complete


def test_subagent_report_xml_round_trip() -> None:
    xml_report = build_subagent_report_xml(
        status="completed",
        summary="Optimized 3D conformer batch.",
        artifact_ids=["art_1", "art_2"],
        metrics={"count": 2, "engine": "mmff94"},
        advisory_active_smiles="CCO",
    )

    payload = parse_subagent_report_xml(xml_report)

    assert payload.summary == "Optimized 3D conformer batch."
    assert payload.produced_artifact_ids == ["art_1", "art_2"]
    assert payload.metrics == {"count": 2, "engine": "mmff94"}
    assert payload.advisory_active_smiles == "CCO"
    assert payload.xml_report.startswith("<subagent_report>")


def test_subagent_report_xml_rejects_invalid_root_tag() -> None:
    with pytest.raises(ValueError, match="root tag must be <subagent_report>"):
        parse_subagent_report_xml("<report><summary>x</summary></report>")


def test_tool_task_complete_generates_canonical_xml_when_omitted() -> None:
    raw = tool_task_complete.invoke(
        {
            "summary": "Descriptor batch complete.",
            "produced_artifact_ids": ["art_desc_1"],
            "metrics": {"count": 1},
            "advisory_active_smiles": "CCN",
        }
    )
    payload = json.loads(raw)

    assert payload["status"] == "completed"
    assert payload["summary"] == "Descriptor batch complete."
    assert payload["xml_report"].startswith("<subagent_report>")
    assert "art_desc_1" in payload["xml_report"]


def test_tool_task_complete_validates_user_supplied_xml() -> None:
    xml_report = """
    <subagent_report>
      <status>completed</status>
      <summary>Safe artifact-only report.</summary>
      <generated_artifacts><artifact_id>art_safe_1</artifact_id></generated_artifacts>
      <metrics><metric key="count">1</metric></metrics>
      <advisory_active_smiles>CCC</advisory_active_smiles>
    </subagent_report>
    """.strip()

    raw = tool_task_complete.invoke({"xml_report": xml_report})
    payload = json.loads(raw)

    assert payload["summary"] == "Safe artifact-only report."
    assert payload["produced_artifact_ids"] == ["art_safe_1"]
    assert payload["metrics"] == {"count": 1}
    assert payload["advisory_active_smiles"] == "CCC"