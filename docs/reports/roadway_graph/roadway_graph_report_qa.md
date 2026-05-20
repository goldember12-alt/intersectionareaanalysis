# Roadway-Graph Report QA

**Status: CURRENT DRAFT QA.** This QA covers the generated descriptive report draft and figure package, including the stakeholder-safe aggregate AADT-normalized prototype exhibits.

- QA checks passed: 59 of 59
- No new rates were computed for this report update. Existing stakeholder-safe aggregate summaries were copied from the suppression review output.
- Unit-level rates remain QA-only and are not exposed as stakeholder-facing findings.
- Figure and report outputs use accepted descriptive tables, copied stakeholder SVGs under `docs/reports/roadway_graph/figures/`, and aggregate rate summaries with denominator, sparse-cell, and review notes.

| check_name                                     | passed | observed                                             | expected            |
| ---------------------------------------------- | ------ | ---------------------------------------------------- | ------------------- |
| crash_direction_fields_read_or_used            | True   | False                                                | False               |
| no_over_2500ft_rows_used                       | True   | 0_250ft,250_500ft,500_1000ft,1000_1500ft,1500_2500ft | 0-2500ft bands only |
| total_assigned_crashes                         | True   | 13216                                                | 13216               |
| upstream_crashes                               | True   | 6543                                                 | 6543                |
| downstream_crashes                             | True   | 6673                                                 | 6673                |
| high_priority_0_1000ft_crashes                 | True   | 9170                                                 | 9170                |
| sensitivity_1000_2500ft_crashes                | True   | 4046                                                 | 4046                |
| stable_speed_bins                              | True   | 84857                                                | 84857               |
| stable_aadt_bins                               | True   | 106210                                               | 106210              |
| crash_area_type_urban                          | True   | 11915                                                | 11915               |
| crash_area_type_rural                          | True   | 1301                                                 | 1301                |
| no_crash_rates_computed                        | True   | False                                                | False               |
| no_aadt_normalized_comparisons_computed        | True   | False                                                | False               |
| no_models_regressions_predictions_fit          | True   | False                                                | False               |
| no_forbidden_interpretation_language_in_report | True   |                                                      |                     |
| all_figure_files_referenced_exist              | True   | copied stakeholder figure package checked            | required            |
| all_figure_source_tables_exist                 | True   | copied figure data and source tables checked         | required            |
| figure_captions_include_limitations            | True   | copied report captions checked                       | required            |
| no_new_rates_computed_for_report_update        | True   | copied existing suppression-review aggregate outputs | required            |
| only_stakeholder_safe_aggregate_rates_used     | True   | window and direction aggregate summaries only        | required            |
| unit_level_rates_not_stakeholder_facing        | True   | unit-level rate outputs referenced only as QA/suppression material | required |
| no_fixed_band_or_raw_bin_rates_created         | True   | no new fixed-band or raw-bin rate files              | required            |
| no_models_regressions_fit_for_rate_update      | True   | none                                                 | none                |
| no_prohibited_interpretive_claims_introduced   | True   | negated caveat language only                         | required            |
| rate_figures_reference_existing_outputs        | True   | suppression-review stakeholder-safe CSVs             | required            |
| rate_captions_include_required_caveats         | True   | both rate exhibits include aggregate-only and AADT caveats | required       |
| crash_direction_fields_not_read_for_rate_update | True  | existing suppression-review QA confirms guarded usecols only | required       |
| context_relationship_no_crash_direction_fields_read_or_used | True | guarded usecols and source tables only | required |
| context_relationship_no_over_2500ft_rows_entered | True | accepted 0-2500 ft cross-tabs and window units only | required |
| context_relationship_no_new_rate_methodology | True | existing aggregate prototype formula retained | required |
| context_relationship_no_direction_factor_applied | True | DIRECTION_FACTOR not applied | required |
| context_relationship_no_raw_bin_level_rates_computed | True | rates aggregate by analysis_window and context band only | required |
| context_relationship_no_signal_level_unit_rate_rankings | True | no reference_signal_id rate outputs | required |
| context_relationship_no_suppressed_unit_rates_exposed | True | unit rows used only to aggregate display-rule cells | required |
| context_relationship_no_models_or_regressions_fit | True | groupby summaries and figures only | required |
| context_relationship_no_causal_policy_downstream_distance_claims | True | descriptive caveats only | required |
| context_relationship_rate_figures_show_rates_with_review_notes | True | display_ready=28; review_cell=6 | required |
| context_relationship_all_figures_svg | True | 8 | 8 |
| context_relationship_all_source_tables_exist | True | 8 | 8 |
| context_relationship_stakeholder_figures_referenced_in_index | True | EX15-EX21 checked; summary demoted to technical QA | required |
| context_relationship_rate_captions_include_caveats | True | EX19-EX21 captions include required caveats | required |
| context_relationship_window_labels_human_readable | True | 0-1,000 ft; 1,000-2,500 ft | required |
| context_relationship_access_labels_numeric | True | Access points per 1,000 ft | required |
| context_relationship_access_density_local_count_grain_used | True | count figures use reference signal + signal-relative direction + distance-band grain | required |
| context_relationship_access_density_local_rate_grain_used | True | rate figure uses reference signal + signal-relative direction + analysis-window grain | required |
| context_relationship_raw_bin_access_density_not_used_for_stakeholder_figures | True | raw 50-ft access-density band retained only as QA context | required |
| context_relationship_broad_group_access_density_not_used_for_stakeholder_figures | True | whole displayed-group density retained only in grain comparison QA | required |
| context_relationship_access_middle_categories_supported_when_present | True | local data now place crashes in middle categories where supported | required |
| context_relationship_aadt_labels_include_vehicles_per_day | True | AADT labels include vehicles/day | required |
| context_relationship_rate_display_status_not_stakeholder_facing | True | rate SVG uses rate_cell_note rather than rate_display_status | required |
| context_relationship_rate_display_summary_demoted | True | context_relationship_summary_table.svg is technical QA only and omitted from stakeholder index/report | required |
| context_relationship_access_density_categories_present_or_explained | True | see access_density_category_coverage_qa.csv | required |
| context_relationship_exact_interval_support | True | scipy.stats.chi2 | preferred |
| manual_review_copied_work_figures_untouched | True | no files under work/output/roadway_graph/report/current were written | required |
| manual_review_no_crash_direction_fields_read_or_used | True | guarded generation used signal_relative_direction only | required |
| manual_review_no_over_2500ft_rows_used | True | 0 rows over 2,500 ft in copied figure generation | required |
| manual_review_no_rate_methodology_changed | True | copied figure refinement only | required |
| manual_review_removed_figures_not_referenced | True | EX03, EX04, EX05, EX06, and EX11 removed from stakeholder report/index references | required |
| manual_review_aggregate_rate_figures_remain | True | 11_aggregate_rate_by_direction.svg and 10_aggregate_rate_by_window.svg remain in copied package | required |
| manual_review_new_speed_aadt_companions_exist | True | EX08B and EX09B exist | required |
| manual_review_upstream_downstream_archived | True | ex03 archived after EX02 stacked direction figure was created | required |
| manual_review_signal_review_figures_archived | True | ex05 and ex06 archived | required |
| manual_review_context_completeness_archived | True | ex11 archived | required |
| manual_review_roadway_representation_legend_repositioned | True | EX12 regenerated with legend above chart area | required |

