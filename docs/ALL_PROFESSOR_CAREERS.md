# Whole-release career exploration

The career page starts with a searchable directory of all 3,937 professors in the public release. Each row opens that professor's lifetime hypergraph, including a singleton graph when no supported colleague can be found. The directory supports institution, subject and connection-status filters, with 50 rows per page and direct page selection. Opening a row clears the graph's subject filter so the selected professor is compared with the entire release.

The three default columns summarize doctoral, postdoc, and current-institution groups. An optional checkbox adds explicitly verified first-assistant groups to both the directory and graph. A supported interval without a matching peer is distinguished from a stage with insufficient evidence. Incomplete computation is never displayed as zero connections. Total peers count distinct other researchers across the enabled stages, rather than summing stage totals. These are individual-centred groups; summing their counts would not measure unique hyperedges in a global graph.

Current-institution groups use the same canonical school and recorded broad subject (mathematics, physics, chemistry, or biology), with employment observed in the release year. Different, missing, or inferred department strings do not split current colleagues. Historical doctoral and first-assistant groups still require department evidence, and postdoc groups compare institutions. Each researcher can belong to all applicable stage groups at once.

## Current coverage

With the UI defaults (doctoral, postdoc and current stages; estimated doctoral windows enabled, five-year backward offset, inferred departments included), the release produces:

| Coverage | Professors |
| --- | ---: |
| All directory entries | 3,937 |
| At least one supported group | 3,309 |
| Eligible interval, but no matching peer | 24 |
| No eligible interval in the enabled stages | 604 |

| Stage | Eligible interval | At least one group |
| --- | ---: | ---: |
| Doctoral | 800 | 446 |
| Postdoc | 2,392 | 2,183 |
| Verified first assistant professor (optional) | 1 | 0 |
| Current institution | 3,241 | 3,240 |

The current stage has 232 school/subject units: 231 groups with at least two members and one singleton. The 95 otherwise eligible current records without country metadata remain included, with country left missing. Older employment observations are not promoted to the release year.

Stage counts overlap and must not be added. A missing connection does not establish the absence of a real relationship. These figures describe the current evidence and settings, not complete or independently verified biographies. In particular, paper-derived departments remain inferred; their observation dates are retained. The first-assistant stage is not inferred from career order. Matching and interval semantics are documented in [HYPERGRAPH_METHOD.md](HYPERGRAPH_METHOD.md).

## Computation and privacy

`createLifetimeIndex` prepares eligible profiles and indexes candidate intervals by stage and institution unit once. The directory's module worker queries every ID and returns only compact per-stage counts in batches of 250. The detailed evidence and embedding are generated for the selected professor. A whole-release index-and-summary pass takes approximately 0.3 seconds in the local Node runtime; browser scheduling and rendering add overhead.

The directory applies the current estimation settings across all subjects. Changing evidence settings starts a new worker request; old responses are ignored. A failed batch computation preserves completed summaries and access to individual graphs. Both workers receive an explicit allowlist of anonymous fields. Names stay in the password-unlocked UI and are never included in worker messages. Unlocking or relocking preserves the selected researcher and evidence settings while clearing search text.

## Institution evidence checks

Explicit shorthand aliases support matching without conflating distinct campuses or hospitals. Merger rules continue to apply only to the specified succession cases. The aliases also consolidate the previously split Dankook institution keys in statistics; observed researcher counts and move totals are unchanged.

A department is attached to a historical degree or career only when its source institution matches the public institution through conservative normalization and explicit aliases. This excludes 69 unsafe inferred PhD-department joins and the corresponding doctoral career departments. The two verified PhD departments remain available. Exclusion reasons are retained in runtime metadata. The original public records, supplemental metadata file and encrypted identities are unchanged.

## Validation

Checks cover full-release ID retention, isolated researchers, stage counts, evidence-preserving index parity with the previous implementation, source-institution mismatches, aliases, and anonymous worker projections. Sampled detailed graphs agree with their directory summaries. TypeScript, lint, the complete JavaScript suite and the production build are checked before deployment. The simultaneous-membership update also tests shared doctoral/current peers with different postdocs, optional first-assistant/current edges with identical members, visible edge context, and deterministic collision-free layout.

The current-school/subject regression checks all ten Gyeongsang National University physics researchers from either side of the former six/four department-text split, with inferred departments both enabled and disabled. Whole-release checks retain specific current schools with missing country without filling that country, preserve explicit campuses and dated merger rules, and exclude stale or unsupported current observations. Detailed layout workers consume the prepared lifetime groups so narrowing the graph's node set cannot reinterpret membership or change group IDs.
