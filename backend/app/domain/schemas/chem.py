from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MoleculeIdentifier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_smiles: str = Field(default="", description="Canonical SMILES string.")
    isomeric_smiles: str = Field(default="", description="Isomeric SMILES string when available.")
    iupac_name: str = Field(default="", description="IUPAC name when known.")
    formula: str = Field(default="", description="Molecular formula when known.")


class DescriptorSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    molecular_weight: float | None = Field(default=None, description="Exact or average molecular weight.")
    logp: float | None = Field(default=None, description="Estimated LogP.")
    tpsa: float | None = Field(default=None, description="Topological polar surface area.")
    qed: float | None = Field(default=None, description="QED drug-likeness score.")
    hbd: int | None = Field(default=None, description="Hydrogen bond donor count.")
    hba: int | None = Field(default=None, description="Hydrogen bond acceptor count.")


class MoleculeArtifactRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_id: str | None = Field(default=None, description="Artifact identifier when persisted.")
    parent_artifact_id: str | None = Field(default=None, description="Optional parent artifact lineage.")
    identifier: MoleculeIdentifier = Field(default_factory=MoleculeIdentifier)
    descriptors: DescriptorSnapshot | None = Field(default=None)