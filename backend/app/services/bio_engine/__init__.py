"""Bio-informatics engine — reserved for future large-molecule / sequence analysis.

Expected interface (to be implemented):
  - sequence_alignment(seq_a, seq_b) -> AlignmentResult
  - structure_prediction_stub(sequence) -> PDB-format str  (AlphaFold / ESMFold proxy)
  - blast_local(query_seq, db_path) -> list[BlastHit]

Do not add production code here until the interface is settled.
"""
