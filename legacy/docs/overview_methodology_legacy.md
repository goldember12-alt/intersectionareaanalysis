\# Crash-Based Evaluation of Downstream Functional Area Requirements



\## Purpose



To supplement the literature review and best-practice survey, a Virginia-specific crash-screening analysis was conducted using observed roadway, access, and crash data. This task built on the observation that other agencies had already developed downstream functional area guidance from established safety principles and had translated those principles into practical distance tables and design criteria.



The literature review informed this analysis by identifying the principal variables, calculation approaches, and downstream distance frameworks used in state and national guidance. These findings were then used to determine which Virginia intersection attributes should be compiled and how downstream baseline zones should be defined for comparison.



This approach moved beyond purely calculation-based criteria by evaluating how downstream functional areas performed under actual Virginia roadway conditions. Guidance and distance tables from other states were used as an initial baseline, after which crash experience was examined within each comparison group to determine the typical level of crashes that could still occur even when intersections generally met similar design conditions.



Intersections with crash occurrence notably higher than that of comparable sites were then reviewed in greater detail to identify downstream design features that differed from the comparison guidance and to assess how roadway context, access density, and other external features affected downstream safety performance. Findings from this process were used to support the development of a Virginia-specific downstream functional distance table and to summarize the minimum downstream conditions that should be preserved in future guidance for signalized intersections.



This approach was particularly appropriate for Virginia because it reflected actual roadway design and operating conditions observed across the Commonwealth, thereby providing a more practical basis for analysis than relying solely on calculation-based design criteria derived from standard assumptions, such as stopping sight distance.



\## Analytical Workflow



The analysis was conducted using the following steps:



1\. A merged Virginia intersection dataset was compiled using roadway geometry, traffic signals, crash records, access-point data, AADT, speed limits, and other relevant roadway attributes needed to support reliable downstream classification.



2\. Additional context variables, including roadway environment classifications such as rural, suburban, and urban, were assigned so that each intersection could be evaluated within its proper operating setting.



3\. Downstream functional-distance tables identified from other states and related guidance were used as the initial baseline for defining expected downstream zones at Virginia intersections. Existing standards were treated as starting points rather than final Virginia recommendations.



4\. Each intersection was then segmented into downstream zones based on those baseline distances, and the roadway and access features within each zone were summarized. Observed Virginia crash experience was then compared against the initial zone definitions.



5\. Crash occurrence within the filtered baseline zones was measured to determine the typical level of crash experience associated with intersections that satisfied those initial comparison distances.



6\. Intersections with crash occurrence notably higher than that of comparable sites were then reviewed in greater detail to identify downstream design features that differed from the comparison guidance.



7\. For these outlier intersections, additional analysis was conducted to determine how access density, roadway context, and other external features appeared to influence the downstream functional area beyond what was captured by the initial baseline distances alone.



8\. Results from the baseline screening and outlier review were then synthesized to develop a Virginia-specific downstream functional distance table that was sensitive to roadway context and key design features, rather than relying only on generalized values from other states.



Within that workflow, downstream directionality should be understood as a network-referenced analytical requirement rather than a purely geometric labeling exercise. Geometry-derived segment support can help prepare later downstream labeling by identifying segment endpoints, signal proximity, and other local context, but those support fields are not the same thing as trustworthy final downstream directionality when the underlying GIS lineage does not yet carry the necessary directional keys.



The current migration direction therefore treats Oracle-backed linkage as the expected trustworthy path for final downstream directionality when base GIS layers alone are insufficient. A likely bridge path runs through traffic-volume or AADT-adjacent data that may carry the GIS-side link identity needed to relate portable segment lineage to Oracle `rns.eyroadxx` and its `tmslinkid` field. For that reason, comparing any newly added traffic-volume layer against the AADT source already used by the repository is part of the methodology-preserving migration path, not a separate side exercise. That comparison is intended to determine whether the bridge key already exists in current AADT lineage, is joinable to it, or belongs at another justified boundary before later Oracle-backed direction enrichment is attached.

