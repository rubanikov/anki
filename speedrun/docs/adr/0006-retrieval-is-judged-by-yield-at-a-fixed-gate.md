# Retrieval is judged by yield at a fixed gate, against an ungated control

The requirement to beat keyword or vector search cannot be met by comparing our
pipeline against vector search, because our pipeline *is* vector search plus a
gate — a system measured against its own component. Instead the Generation gate
is held constant and only the retriever varies across four arms (BM25, embedding,
hybrid, and hybrid with the gate disabled), over a fixed query set of the 31
content categories at three generation requests each. The declared primary metric
is Yield: usable items per hundred attempts.

## Consequences

- The comparison can genuinely lose. BM25 may beat embeddings on textbook prose,
  which is dense with exact technical terms — and if it does, that is the
  finding we report.
- The ungated control arm, not the retrieval margin, carries the project's
  actual claim: it measures how often an ungated pipeline would have shipped an
  item whose answer is in no real source. That is the number that belongs in the
  traceability table.
- The gate has to log every rejection with a reason rather than silently
  dropping candidates, otherwise yield cannot be decomposed.
- The query set and the primary metric are fixed and written down before the
  first run, so the metric cannot be chosen after seeing which arm won.
