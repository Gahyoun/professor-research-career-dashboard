# Researcher constellation core

`hypergraph.ts` has no external dependencies and works in a module Web Worker. It copies only pseudonymous ID and subject into graph nodes. Never pass private decrypted identities to this worker.

## Data semantics

- Spatial hyperedges are sets of at least two researchers with the same verified canonical institution, falling back to conservative typographic normalization. No guessed aliases. Numeric-only unresolved institution codes, unknown institutions, and unknown countries are excluded.
- Educational units require the recorded degree department as well as school, for both domestic and foreign institutions; current appointment department and broad subject are never substitutes. Institutions are distinguished using normalized country codes. Only the person-focused postdoc groups below use institution-only matching.
- Inferred departments are excluded by default (`includeInferredDepartments: false`). When explicitly enabled, graph edges and trajectory evidence mark them as inferred. Inferring a department from a contemporaneous paper affiliation does not establish the actual degree department.
- Annual temporal hyperedges contain all researchers whose doctoral windows include that calendar year. Endpoints are inclusive, so one shared endpoint year is one shared annual observation. This does not establish day-level co-presence or acquaintance.
- Valid explicitly non-estimated doctoral career intervals take priority. Otherwise, `phd_year - estimatedYears` through `phd_year` is an estimate. The default of five produces six inclusive calendar-year bins. Missing PhD years are excluded. Existing estimated career windows are recomputed from the configurable estimate; they are not treated as observed dates.
- Identical annual membership sets merge into one edge with the complete list of years, including non-contiguous years. Duplication does not multiply edge weight. Different evidence types remain separate even if their membership is identical.
- Duplicate IDs keep their first record. Missing IDs are rejected. Explicit disconnected actual doctoral intervals retain gaps.
- Optional bachelor time cohorts use the user-specified interval `phd_year - 10` through `phd_year - 8`, inclusive. These are always estimates, never actual undergraduate dates. The offsets are configurable. `includeEstimated: false` excludes these intervals as well as estimated doctoral intervals.
- Joint `cohort` hyperedges require both the same eligible country-aware educational unit and a shared degree year. They are tagged `degree: 'bachelor' | 'phd'`. Identical joint membership sets merge within a degree and unit while retaining the years. Joint cohorts are a composite relationship and should not be described as independent evidence in addition to their temporal/spatial ingredients.

## Weight and overlap correction

For hyperedge `e` with cardinality `k`, layer strength `s`, and same-type neighbor edges `f`:

```
sizeAdjustment(e) = 1 / (k - 1)
overlapAdjustment(e) = 1 / (1 + sum_f Jaccard(e, f))
weight(e) = s * k * sizeAdjustment(e) * overlapAdjustment(e)
```

The `k` factor compensates for the `1/k` already in the normalized hypergraph operator. Consequently each distinct pair within an edge receives affinity `s * overlapAdjustment / (k - 1)`, keeping total off-diagonal evidence per member from growing linearly with group size. Applying `1/(k-1)` to `W` without this factor would normalize group size twice.

Jaccard overlap correction is a transparent project heuristic for redundant neighboring annual groups, not a theorem or estimated causal association. It is computed within each kind and degree; temporal, spatial, and joint cohort relations remain distinguishable. Edges intersect only via incident researchers, so no researcher pair matrix is materialized. Joint cohort base strength is the geometric mean of spatial and temporal strengths.

## Sparse spectral embedding

Let `H` be binary researcher-by-hyperedge incidence, `W` edge weights, `De` edge cardinalities, and `Dv` summed incident weights. The operator is

```
A = Dv^(-1/2) H W De^(-1) H^T Dv^(-1/2)
L = I - A
```

The source for this normalized hypergraph Laplacian and spectral embedding is Zhou, Huang, and Schölkopf, *Learning with Hypergraphs: Clustering, Classification, and Embedding*, NeurIPS 2006, sections 5–6:

https://proceedings.neurips.cc/paper_files/paper/2006/file/dff8e9c2ac33381546d96deea9922999-Paper.pdf

Each connected component is embedded independently. Deterministic multistart block power iteration approximates two nontrivial low-energy eigenvectors, excluding the stationary degree vector with double orthogonalization. The default uses 100 iterations and three seeded starts. Lazy diffusion preserves eigenvectors while stabilizing rank-deficient components. Candidate selection minimizes the two-axis Laplacian trace; diagnostics report a node-count-weighted component average. Singleton/one-edge components use an isotropic arrangement because there is no preferred internal direction; their diagnostic energy reflects available nontrivial dimensions.

`objective` and `candidateObjectives` refer to spectral coordinates **before** display spreading and collision removal. They should never be labeled a global optimum of the final visible layout. Multistart, finite iteration, non-linear display scaling, and geometric overlap adjustment make the final result a practical approximation.

Disconnected components use radial placement, with large components near the center and isolated researchers distributed around them. Incidence-identical researchers spread isotropically; their internal position is not meaningful evidence. Spatial hashing removes visible node overlaps. Remaining collisions search outwards in a spiral, with a permuted fallback grid for extreme crowding so no artificial rows form. Requested minimum distance is reduced only when the viewport makes the packing request infeasible, and both requested and effective values are reported.

The final chronological display uses doctoral completion year (or the estimated bachelor endpoint in bachelor institution mode) as a global vertical anchor, with bounded spectral and deterministic jitter within approximately nearby year lanes. `chronologicalStrength` defaults to `0.35`; higher values reduce spectral jitter, while zero disables chronological anchoring. Collision removal may move very close cohorts slightly, so precise dates must be read from the evidence. The date axis is a display constraint, not an additional inferred date and not an unconstrained spectral optimum.

## Person-focused lifetime hyperedges

`lifetime.ts` constructs one group per selected person's stage, eligible unit, and interval. Doctoral groups combine overlapping doctoral peers and independently observed/verified faculty at the same school and department. Postdoc groups permit doctoral, postdoc, and verified faculty peers at the same institution without a department requirement. First-assistant groups require an explicit assistant-professor rank and a reviewed first-appointment flag, then match observed/verified faculty at the same school and department. Current groups require same-school/department observations in the release year; an older roster is not extended to the present.

Faculty employment comes from `faculty_appointments` with semester-roster, official-profile, or verified-CV evidence. A generic `faculty` career stage, career sequence, publication affiliation, or non-estimated flag alone is not employment confirmation. Doctoral windows retain their observed/estimated distinction. The current record uses separate `current_position` evidence. Unknown units, conflicting countries, unverified employment, or missing department evidence do not create an edge. Publication-derived departments remain explicitly inferred and require opt-in.

The temporal semantics are **selected-interval union**: every member overlaps the selected person's interval, but members need not all overlap one another in the same year. Member-level role, overlap years, and source kinds accompany every group. For example, an observed professor and overlapping doctoral peers in one department can form one school-years hyperedge. Single-member intervals are shown as available periods, with an explanation that no peer is supported; they are not rendered as hyperedges.

`trajectoryGraph.ts` uses the same lifetime group IDs and membership as the evidence panel. Orange, teal, purple, and blue encode doctoral, postdoc, first-assistant, and current groups respectively; researcher-node colors encode subjects separately. Smooth convex envelopes indicate selected groups, while highlighted nodes and the member list determine actual membership. An unrelated node can geometrically fall inside an envelope. Names remain outside the worker and are overlaid only by the unlocked UI, together with current institution.

University succession changes current display units and exempts specified post-merger institution transitions from job-change counts. Historic degree and career names remain intact. See [institution successions](INSTITUTION_SUCCESSIONS.md).

## Generic trajectory observations

`buildResearcherTrajectory` keeps eligible doctoral, postdoc, and faculty intervals. `findTrajectoryPeers` compares sets of `(institution unit, inclusive calendar year)` observations. A shared unit-year counts once even if career records duplicate or overlap; stage is shown in evidence rather than multiplied into the score.

```
score = shared distinct unit-years / union distinct unit-years
```

Each peer carries matching institution, country, department, both career stages, shared year interval, and estimated/inferred flags. Unknown units or invalid dates are excluded, and coverage diagnostics identify why. Actual doctoral intervals can use degree metadata only when they refer to the same recorded/canonical doctoral institution. Current faculty department is never imported into degree history. Country-less postdoc/faculty intervals remain excluded. This generic helper is separate from the person-focused lifetime groups. The institutional statistics page uses actual same-semester roster observations from its own aggregation module, not these reconstructed career intervals or a hypergraph score.

## Complexity and validation

Building incidence and each diffusion pass cost `O(total incidence)`. Overlap counting costs `O(sum_v incident_edge_count(v)^2)`, small for bounded doctoral windows. No all-pairs researcher similarity matrix is built. Collision handling uses spatial hashing. Trajectory lookup is linear in the number of recorded unit-year observations for one selected researcher.

Validation uses strict TypeScript compilation and Node tests covering inclusive endpoints, observed-vs-estimated precedence, non-contiguous intervals, missing values, domestic/foreign department rules, inference opt-in, canonical aliases, duplicate IDs, absence of private fields, cardinality and overlap weighting, layer toggles, trajectory evidence/Jaccard, bachelor estimation, joint degree cohorts, chronological ordering, deterministic disconnected layouts, finite outputs, weight sensitivity, and 3,937-node behavior. Lifetime regressions additionally check shared doctoral/faculty groups, postdoc exceptions, first-assistant evidence, stale current observations, source conflicts, and graph/panel group agreement. University-succession regressions cover effective years, exact aliases, pre-merger moves, immutability, and preservation of history.

Actual-data checks use the current release and supplemental metadata, including one selected researcher with school-years, postdoc, first-assistant, and current records. Performance is environment-dependent; an end-to-end lifetime/group build for the 3,937-record release took approximately 0.18 seconds on the bundled Node runtime. A verified first-assistant interval with no supported colleague correctly produces no hyperedge.
