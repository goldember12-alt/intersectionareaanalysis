# Directed Signal-Leg Initial QA Readout

## A. Methodology Boundary

This QA readout covers the no-crash, road-network-first signal-leg workflow only.

The workflow creates oriented roadway legs from anchor X to anchor Y. The orientation is a geometry-ordering device so an A-to-B leg can be distinguished from a B-to-A leg. It does not infer true vehicle travel direction, does not assign crashes, and does not use crash data for validation.

Crash direction may be useful later as an assignment or validation attribute after the roadway scaffold has been reviewed. It is not an evidence source in this pass.

Leg types have different interpretive strength:

- `signal_to_signal`: strongest current analytical leg type; supports between-signal bins.
- `signal_to_access`: useful for access spacing and access-context review; not equivalent to `signal_to_signal`.
- `signal_to_road_endpoint`: QA/support object for cases without another signal or access terminus on that side; not a downstream study claim by itself.

## B. Output Inventory

Current run: `signal_leg_orientation_pivot_final`

| Metric | Count | Percent |
| --- | ---: | ---: |
| Signal nodes | 2,006 |  |
| Directed signal legs | 4,012 | 100.00% |
| 50-foot leg-bin rows | 555,503 |  |
| `signal_to_signal` legs | 2,816 | 70.19% |
| `signal_to_access` legs | 106 | 2.64% |
| `signal_to_road_endpoint` legs | 1,090 | 27.17% |
| Orientation review rows | 1,979 | 49.33% |
| Short/problem leg rows | 1,408 | 35.09% |
| Rejected/unresolved signal-leg rows | 0 | 0.00% |
| True vehicle direction inferred rows | 0 | 0.00% |

The 1,979 orientation review rows should not be read as 1,979 failures. They are conservative QA flags from several different causes.

## C. Orientation Review Breakdown

Primary orientation review statuses:

| QA orientation status | Count | Interpretation |
| --- | ---: | --- |
| `review_geometry_fallback` | 1,159 | The workflow could not extract a clean roadway substring and used a direct anchor-to-anchor line. These need map review. |
| `support_only_endpoint_leg` | 571 | Endpoint support legs with usable roadway substrings. These are expected support/edge objects, not failures by default. |
| `review_short_leg` | 200 | Legs under 50 feet. These may be near-signal duplicates, tiny route fragments, or valid very short anchor spans. |
| `unresolved_zero_length_geometry` | 49 | Zero-length endpoint/fallback cases. These are real geometry failures or degenerate anchors. |

By leg type:

| Leg type | Review rows | Review percent within type | Main reason |
| --- | ---: | ---: | --- |
| `signal_to_signal` | 832 | 29.55% | Almost entirely geometry fallback; 2 short rows. |
| `signal_to_access` | 57 | 53.77% | Geometry fallback and short access termini. |
| `signal_to_road_endpoint` | 1,090 | 100.00% | All endpoint legs are review/support rows by design. |

By geometry status within orientation review:

| Geometry status | Count | Interpretation |
| --- | ---: | --- |
| `fallback_direct_anchor_line` | 1,377 | Higher priority QGIS review. These are not following a verified roadway substring. |
| `roadway_substring` | 602 | Mostly endpoint support or short rows. These are more likely to be harmless QA flags. |

Problem flags across all legs:

| Problem flag | Count | Interpretation |
| --- | ---: | --- |
| `geometry_fallback` | 1,159 | Direct anchor line fallback. |
| `short_under_50ft;geometry_fallback` | 169 | Short and fallback; high review priority. |
| `zero_length;geometry_fallback` | 49 | Degenerate geometry; high review priority. |
| `short_under_50ft` | 31 | Short but with roadway substring. |

The useful split is therefore:

- Mostly harmless/conservative review: 571 `support_only_endpoint_leg` rows.
- Real geometry review need: 1,377 fallback direct-line rows.
- Real degenerate geometry issue: 49 zero-length rows.
- Context-dependent: 200 short rows, especially the 169 that also used fallback geometry.

The detailed grouping table is:

- `work/output/directed_segments/review/current/orientation_review_reason_summary.csv`

## D. Leg Type QA

| Leg type | Count | Percent | Median length ft | Min ft | Max ft | Mean bins | Review count | Review % | Short/problem count | Short/problem % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `signal_to_signal` | 2,816 | 70.19% | 2,276.42 | 21.89 | 211,063.82 | 149.25 | 832 | 29.55% | 832 | 29.55% |
| `signal_to_access` | 106 | 2.64% | 680.34 | 0.03 | 438,440.08 | 111.78 | 57 | 53.77% | 57 | 53.77% |
| `signal_to_road_endpoint` | 1,090 | 27.17% | 1,241.69 | 0.00 | 402,122.53 | 113.17 | 1,090 | 100.00% | 519 | 47.61% |

The detailed leg-type table is:

- `work/output/directed_segments/review/current/leg_type_qa_summary.csv`

## E. Segment/Bin Sanity

Length distribution across all 4,012 legs:

| Statistic | Length ft |
| --- | ---: |
| Mean | 6,897.70 |
| 5th percentile | 33.73 |
| 25th percentile | 871.24 |
| Median | 1,981.43 |
| 75th percentile | 5,049.59 |
| 95th percentile | 26,620.95 |
| 99th percentile | 88,576.54 |
| Max | 438,440.08 |

Length bands:

| Length band | Count |
| --- | ---: |
| 0 ft | 49 |
| 0-50 ft | 200 |
| 50-250 ft | 93 |
| 250-1,000 ft | 836 |
| 1,000-5,280 ft | 1,859 |
| 5,280-26,400 ft | 772 |
| 26,400+ ft | 203 |

Bin-count distribution:

| Bin count band | Leg count |
| --- | ---: |
| 0 bins | 49 |
| 1 bin | 200 |
| 2-5 bins | 93 |
| 6-20 bins | 836 |
| 21-100 bins | 1,824 |
| 101-500 bins | 797 |
| 501+ bins | 213 |

The longest leg is a `signal_to_access` fallback line on `R-VA   US00221NB` with 438,440 ft and 8,769 bins. That is not plausible as a normal access-spacing leg and should be one of the first QGIS checks.

Example tables:

- `work/output/directed_segments/review/current/longest_leg_examples.csv`
- `work/output/directed_segments/review/current/shortest_leg_examples.csv`

## F. Road Endpoint Assessment

`signal_to_road_endpoint` legs account for 1,090 rows, or 27.17% of all legs.

Endpoint QA status:

| Status | Count | Read |
| --- | ---: | --- |
| `support_only_endpoint_leg` | 571 | Likely harmless dataset-edge/support rows where roadway substring extraction succeeded. |
| `review_geometry_fallback` | 291 | Need QGIS review; direct anchor line was used. |
| `review_short_leg` | 179 | Likely tiny endpoint fragments or near-endpoint signals. |
| `unresolved_zero_length_geometry` | 49 | Real degenerate geometry issue. |

Endpoint length distribution:

| Statistic | Length ft |
| --- | ---: |
| Median | 1,241.69 |
| 75th percentile | 4,269.56 |
| 95th percentile | 20,459.62 |
| Max | 402,122.53 |

The route/status count breakdown is dispersed rather than concentrated in one route; many routes contribute two endpoint rows because each route/carriageway group can have a lower-side and higher-side end. That pattern supports treating many endpoint rows as expected edge/support objects. However, endpoint rows with `fallback_direct_anchor_line`, zero length, or extremely long length are not harmless until mapped.

Review first:

- endpoint rows with `unresolved_zero_length_geometry`
- endpoint rows with `review_geometry_fallback`
- endpoint rows above the 95th percentile length

Example table:

- `work/output/directed_segments/review/current/road_endpoint_leg_examples.csv`

## G. Signal-To-Access Assessment

`signal_to_access` legs account for 106 rows, or 2.64% of all legs.

Access-leg QA status:

| Status | Count | Read |
| --- | ---: | --- |
| `oriented_geometry_only` | 49 | Best candidates for access-spacing review. |
| `review_geometry_fallback` | 38 | Need QGIS review; direct anchor line was used. |
| `review_short_leg` | 19 | Very short access termini; may be valid near-signal access or duplicate/fragment behavior. |

Access-leg length distribution:

| Statistic | Length ft |
| --- | ---: |
| Median | 680.34 |
| 75th percentile | 1,719.19 |
| 95th percentile | 4,996.10 |
| Max | 438,440.08 |

Most signal-to-access legs are short enough to be plausible access-spacing objects, but the maximum is an obvious outlier caused by fallback geometry or route/measure behavior. These legs should not be interpreted as equivalent to `signal_to_signal` legs. They are access-context scaffolds only.

Review first:

- longest signal-to-access rows
- signal-to-access rows with `fallback_direct_anchor_line`
- very short signal-to-access rows under 50 feet

Example table:

- `work/output/directed_segments/review/current/signal_to_access_leg_examples.csv`

## H. Manual Review Sample

The manual review sample has 85 rows:

| Review group | Rows |
| --- | ---: |
| `signal_to_signal_no_obvious_qa_problem` | 15 |
| `signal_to_signal_orientation_review` | 15 |
| `signal_to_road_endpoint` | 15 |
| `signal_to_access` | 10 |
| `short_or_problem` | 10 |
| `longest_legs` | 10 |
| `shortest_nonzero_legs` | 10 |

Sample file:

- `work/output/directed_segments/review/current/manual_orientation_review_sample.csv`

Manual reviewers should fill:

- `notes`
- `manual_review_status`

Suggested QGIS order:

1. Open `directed_signal_legs.geojson`.
2. Add `orientation_review.geojson`.
3. Add `access_anchors_used.geojson`.
4. Filter to the manual sample IDs.
5. Review fallback rows before endpoint support-only rows.
6. Confirm whether very long legs are true route gaps, route-measure artifacts, or geometry extraction failures.

## I. Recommendations

The foundation is ready for manual QGIS review, but it is not ready for crash assignment.

The 1,979 orientation review rows are mixed:

- 571 are conservative endpoint support rows and may be mostly harmless.
- 1,377 use fallback direct-line geometry and need spatial review before analytical use.
- 49 are zero-length and should be treated as actual geometry failures.
- 200 are under 50 feet and need review for route fragments, near-signal access, or duplicate anchor behavior.

Inspect these patterns first:

1. `signal_to_signal` rows with `fallback_direct_anchor_line`, because they affect the strongest leg type.
2. longest legs and rows with very high bin counts, especially `signal_to_access` and endpoint rows.
3. zero-length endpoint rows.
4. short rows under 50 feet.
5. endpoint support rows only after the higher-risk groups are understood.

The next code step should be QA refinement, not crash/access assignment. A practical next refinement is to reduce direct-line fallbacks by improving roadway substring extraction across multipart or fragmented route rows, while keeping the no-crash and no-true-vehicle-direction boundary intact.

