/**
 * Custom TextMate grammars for chemistry formats not included in Shiki's bundle.
 * Loaded on-demand by code-block.tsx via getSingletonHighlighter().loadLanguage().
 */
import type { LanguageRegistration } from "shiki"

export const CHEM_LANG_IDS = ["fasta", "smiles", "sdf", "mol"] as const
export type ChemLangId = (typeof CHEM_LANG_IDS)[number]

// ── FASTA ──────────────────────────────────────────────────────────────────────
const fasta: LanguageRegistration = {
  name: "fasta",
  scopeName: "source.fasta",
  fileTypes: ["fa", "fasta", "fna", "faa", "ffn", "frn"],
  repository: {},
  patterns: [
    // Comment lines starting with ;
    { name: "comment.line.semicolon.fasta", match: "^;.*$" },
    // Header / identifier line
    { name: "entity.name.tag.header.fasta", match: "^>.*$" },
    // DNA / RNA bases
    {
      name: "string.unquoted.dna.fasta",
      match: "^[ACGTUNacgtun*-]+$",
    },
    // Amino acid sequences (include all 20 + ambiguous + gap)
    {
      name: "string.unquoted.aa.fasta",
      match: "^[ACDEFGHIKLMNPQRSTVWYXacdefghiklmnpqrstvwyx*-]+$",
    },
  ],
}

// ── SMILES ─────────────────────────────────────────────────────────────────────
const smiles: LanguageRegistration = {
  name: "smiles",
  scopeName: "source.smiles",
  fileTypes: ["smi", "smiles"],
  repository: {},
  patterns: [
    // Atom in brackets [CH4], [NH3+], [2H], [Fe+2], etc.
    {
      name: "entity.name.type.bracket-atom.smiles",
      match: "\\[[^\\]]*\\]",
    },
    // Two-letter halogens must come before single-letter atoms
    {
      name: "support.class.atom.halogen.smiles",
      match: "(?:Cl|Br)",
    },
    // Organic subset atoms (uppercase = aliphatic, lowercase = aromatic)
    {
      name: "support.class.atom.smiles",
      match: "[BCNOPSFIbcnops]",
    },
    // Ring closure digits (including %nn)
    {
      name: "constant.numeric.ring.smiles",
      match: "%\\d{2}|\\d",
    },
    // Bonds
    {
      name: "keyword.operator.bond.smiles",
      match: "[=#:$/\\\\]",
    },
    // Charges, chirality, dots, parentheses
    {
      name: "keyword.other.smiles",
      match: "[+\\-@\\.\\(\\)]",
    },
  ],
}

// ── SDF / MOL ──────────────────────────────────────────────────────────────────
const sdCommon: Omit<LanguageRegistration, "name"> = {
  scopeName: "source.sdf",
  fileTypes: ["sdf", "mol", "sd"],
  repository: {},
  patterns: [
    // Record separator
    {
      name: "keyword.control.separator.sdf",
      match: "^\\${4}$",
    },
    // Data field header  > <FIELD_NAME>
    {
      name: "entity.name.tag.field.sdf",
      match: "^>\\s+<[^>]+>.*$",
    },
    // Counts line (3rd line of molblock): aaabbblllfffcccsssxxxrrrpppiiimmmvvvvvv
    {
      name: "comment.line.counts.sdf",
      match: "^\\s*\\d+\\s+\\d+\\s+\\d+.*(?:V2000|V3000).*$",
    },
    // V3000 keywords
    {
      name: "keyword.other.v3000.sdf",
      match: "\\b(?:BEGIN|END|CTAB|ATOM|BOND|COLLECTION)\\b",
    },
    // Numbers (coordinates, bond types)
    {
      name: "constant.numeric.sdf",
      match: "-?\\d+\\.\\d+|-?\\d+",
    },
    // Element symbols (2 chars)
    {
      name: "support.class.element.sdf",
      match:
        "\\b(?:He|Li|Be|Ne|Na|Mg|Al|Si|Cl|Ar|Ca|Sc|Ti|Cr|Mn|Fe|Co|Ni|Cu|Zn|Ga|Ge|As|Se|Br|Kr|Rb|Sr|Zr|Nb|Mo|Tc|Ru|Rh|Pd|Ag|Cd|In|Sn|Sb|Te|Xe|Cs|Ba|La|Ce|Pr|Nd|Pm|Sm|Eu|Gd|Tb|Dy|Ho|Er|Tm|Yb|Lu|Hf|Ta|Re|Os|Ir|Pt|Au|Hg|Tl|Pb|Bi|Po|At|Rn|Fr|Ra|Ac|Th|Pa|Np|Pu|Am|Cm|Bk|Cf|Es|Fm|Md|No|Lr)\\b",
    },
    // Element symbols (1 char)
    {
      name: "support.class.element.sdf",
      match: "\\b(?:H|B|C|N|O|F|P|S|K|V|I)\\b",
    },
  ],
}

const sdf: LanguageRegistration = { name: "sdf", ...sdCommon }
const mol: LanguageRegistration = { name: "mol", ...sdCommon }

export const CHEM_LANGS: Record<ChemLangId, LanguageRegistration> = {
  fasta,
  smiles,
  sdf,
  mol,
}
