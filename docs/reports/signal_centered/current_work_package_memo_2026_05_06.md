---
title: ""
mainfont: "Arial"
sansfont: "Arial"
monofont: "Consolas"
fontsize: 11pt
header-includes:
  - \renewcommand{\familydefault}{\sfdefault}
  - \usepackage{fontspec}
  - \setmonofont[Scale=0.90]{Consolas}
  - \usepackage{booktabs}
  - \usepackage{array}
  - \usepackage{tabularx}
  - \usepackage{longtable}
  - \usepackage{xurl}
  - \usepackage{fvextra}
  - \usepackage{ragged2e}
  - \usepackage{needspace}
  - \DefineVerbatimEnvironment{Highlighting}{Verbatim}{breaklines,breakanywhere,commandchars=\\\{\}}
  - \DefineVerbatimEnvironment{verbatim}{Verbatim}{breaklines,breakanywhere}
  - \AtBeginDocument{\RaggedRight}
  - \setlength{\parindent}{0pt}
  - \setlength{\parskip}{6pt plus 1pt minus 1pt}
  - \linespread{1.04}
  - \setlength{\emergencystretch}{3em}
  - \setlength{\oddsidemargin}{-0.18in}
  - \setlength{\evensidemargin}{-0.18in}
  - \setlength{\topmargin}{-0.35in}
  - \setlength{\headheight}{12pt}
  - \setlength{\headsep}{0.2in}
  - \setlength{\textwidth}{6.85in}
  - \setlength{\textheight}{9.2in}
  - \renewcommand{\arraystretch}{1.12}
  - \setlength{\LTpre}{0.45em}
  - \setlength{\LTpost}{0.75em}
  - \usepackage{titlesec}
  - \titleformat{\section}{\Large\bfseries\sffamily}{\thesection}{0.6em}{}
  - \titleformat{\subsection}{\large\bfseries\sffamily}{\thesubsection}{0.6em}{}
  - \titleformat{\subsubsection}{\normalsize\bfseries\sffamily}{\thesubsubsection}{0.6em}{}
  - \titlespacing*{\section}{0pt}{1.05em}{0.45em}
  - \titlespacing*{\subsection}{0pt}{0.9em}{0.35em}
  - \titlespacing*{\subsubsection}{0pt}{0.75em}{0.25em}
---

\begin{center}
{\LARGE\bfseries Current Work\par}
\vspace{0.08in}
{\large\bfseries Divided-Road Signal-Centered Analysis\par}
\vspace{0.08in}
{\normalsize\textbf{Date:} May 6, 2026\par}
\end{center}
\vspace{0.08in}
\hrule
\vspace{0.18in}

## 1. Executive Summary

This project aims to develop an analysis workflow for downstream functional area guidance at signalized intersections in Virginia. A downstream functional area (DFA) is defined as the area after a signal where vehicles are leaving the intersection and where driveways, entrances, nearby roads, speed, traffic volume, and roadway design can affect traffic operations and safety.

The current workflow focuses on divided-road roadways, which are roads where opposing traffic directions are separated by a median or barrier. It organizes current signal, roadway, crash, access, traffic volume, speed, and related context records into reviewable summaries, but we do not yet estimate crash-rates, run statistical models, or recommend DFA design distances.

## 2. Bounded Research Question

The current bounded research question is:

> Can we build signal-centered evidence for divided-road intersections so crashes and access points can be described as upstream, downstream, near the signal, or unresolved?

This question is intentionally narrower than the full DFA research goal because we first need a trustworthy way to organize crash and access evidence around each signalized intersection before we can evaluate or establish guidance.

In practical terms, the workflow must be able to start from a signal, define the nearby divided-road study area, attach relevant crash and access records, and classify those records based on their position relative to the signal. A downstream record is one located after vehicles pass through the signal. An upstream record is one located before vehicles reach the signal. A near-signal record is close enough to the signal that a clean upstream or downstream label may not be appropriate. An unresolved record is retained when the available geometry or record context is not strong enough to support a confident label.

The answer to this specific research question is yes, with a few caveats. We can produce signal-level, crash-level, access-level, and distance-band tables. We also keep unresolved cases visible instead of forcing labels where the evidence is weak. Weak evidence means the workflow can see that a crash or access point is near the signal study area, but available location, route, distance, or roadway-direction information is not strong enough (is absent or some information is incongruous with others) to say confidently which side of the signal it belongs on.

This matters because DFA guidance cannot be evaluated until we can first say where crashes and access points sit in relation to a signal. Current work solves that first organizing problem for divided-road roadways.

## 3. Current Product

Our current product is a divided-road, signal-centered descriptive analysis package.

A “signal-centered package” means signalized intersections are our main object of study. We start with a signal, build a study area around it, attach nearby roadway information, then summarize nearby crashes and access points in relation to that signal. Roadway information includes divided-road geometry, travel direction, speed, traffic volume, median context, and roadway/facility-type fields (currently all divided roadways).

An access point means a driveway, entrance, or similar point where traffic can enter or leave the road. Access points matter because the DFA is primarily concerned with conflicts occurring after vehicles pass through a signal.

For our analysis, a distance-band means a distance range measured downstream from the signal. For example, a 0 to 250 foot band includes downstream records that fall within the first 250 feet after the signal. Current distance-bands are descriptive baseline bins, not proposed design values. Package 001 uses fixed 50-foot downstream bins, and Package 002 adds coarse fixed bins (0-250 feet, 250-500 feet, 500-1000 feet, 1000+ feet) and assigned-speed travel-time bins.

This baseline differs from the level-road AASHTO-based approach because the current package first needs simple, transparent bins that show where crashes and access points fall before we compare patterns under VDOT guidance, other state guidance, literature-derived assumptions, AASHTO concepts, or observed crash/access distributions. The level-road assumption was also extremely strong, but road grade may be worth investigating in the future.

Our current product helps answer the following questions:

- Which signalized intersections are included in the current divided-road slice, and what study area was built around each one?
- Which crashes are classified as upstream, downstream, or unresolved?
- Which access points are classified as downstream, upstream, near the signal, or unresolved?
- Which signals have both downstream crashes and downstream access points?
- How do downstream crashes and access points fall into distance-bands?
- Which signals should be reviewed on a map before they are used as examples or future modeling candidates?

## 4. Work Completed to Produce the Current Package

We produced the current package through a sequence of preparation, classification, enrichment, packaging, and review steps:

1. Organized the project around signalized intersections.
2. Prepared required road, signal, and crash inputs for analysis. We read raw source layers, copy records into artifact folders, then normalize those copies into cleaned working files that later analysis steps can use. Currently, normalization means using a consistent coordinate system, removing records without usable geometry, filtering crashes to the current 2022–2024 study window, and recording source and row-count information in manifests.
3. Built divided-road study slices around signalized intersections.
4. Enriched signals with nearest-road context. We attach information from the closest candidate road segment so each signal record includes roadway context (route name, roadway geometry, divided-road status, median/facility fields, and nearby speed context), not just signal location.
5. Ran a directionality experiment. “Directionality” means the inferred travel direction on a divided-road carriageway, where a carriageway is one side of a divided-road roadway that carries traffic in one direction.
6. Ran an upstream and downstream crash classification prototype. We classify crashes in relation to each signal where we have strong enough evidence. “Strong enough evidence” means the crash falls within the signal’s study area, matches one same-route signal, is close to the roadway row used for that signal, and that roadway row has a trusted travel direction based on consistent crash direction evidence. If any of those pieces are missing or too ambiguous, the crash is left unresolved rather than forced into upstream or downstream.
7. Ran a high-confidence descriptive analysis. We filtered the already classified crash records to the most conservative subset. To be included, a crash had to be in the approach-shaped study area, receive an upstream or downstream classification, attach to the selected signal’s roadway row with high attachment confidence, and use the strongest travel-direction evidence. “High attachment confidence” means the crash point was within 25 meters of the selected roadway row. The “strongest travel-direction evidence” means all qualifying nearby crashes unanimously agreed on one travel direction. Crashes could still be classified outside this subset if they had medium attachment confidence (more than 25 meters but no more than 50 meters from the selected roadway row) or if direction was supported by 90% of crashes rather than strict unanimity, but would not be included in this high-confidence analysis.
8. Added context enrichment, which means attaching traffic volume, speed, access point, median, roadway type, and crash area fields to the signal-centered analysis outputs.
9. Organized the final enriched signal-centered outputs into three descriptive packages. These packages turn signal, crash, access, roadway, speed, traffic volume, and distance-band information into stable tables for review.
10. Created a manual map-review packet for the highest-priority Package 003 locations. This packet identifies 18 signals where downstream crash evidence and downstream access evidence both appear, and provides map layers to visually investigate these cases.

\Needspace{10\baselineskip}

## 5. What is a Signal Study Area?

The main object analyzed in the current package is the signal study area.

We define a signal study area as one signalized intersection plus a limited nearby roadway area, determined by same route divided-road rows near the signal, clipped to a speed-based approach length, buffered laterally by 18 meters, and joined with a 20 meter buffer around the signal itself. We use it as a unit to summarize crashes, access points, traffic volume, speed, and roadway context.

The current package also creates several supporting record types, where "record" just means one row in a table:

\begingroup
\small
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{1.35in}>{\raggedright\arraybackslash}p{2.7in}>{\raggedright\arraybackslash}p{2.6in}@{}}
\toprule
Record type & Meaning & Current role \\
\midrule
Signal study area & One signalized intersection and its bounded nearby roadway area & Main reporting object \\
Approach row & A signal-related road approach or carriageway segment & Supports travel-direction interpretation and roadway context \\
Crash record & One crash record associated with a signal study area where possible & Used for upstream, downstream, and unresolved crash summaries \\
Access point record & One driveway, entrance, or similar point associated with a study area where possible & Used for downstream access summaries and unresolved access reporting \\
Signal-band row & One signal study area summarized within one downstream distance-band & Used to compare downstream crash and access counts by distance \\
\bottomrule
\end{longtable}
\endgroup

## 6. Evidence Sources and Current Interpretive Limits

We employ several evidence types to build the current signal-centered package. Each evidence type has a specific role. Some fields support direct classification, while others provide only descriptive context.

\begingroup
\small
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{1.45in}>{\raggedright\arraybackslash}p{2.0in}>{\raggedright\arraybackslash}p{3.2in}@{}}
\toprule
Evidence type & Current role & Current interpretive limit \\
\midrule
Signals & Provide location and identifiers for each signalized intersection & A signal location alone does not show the nearby road geometry, travel direction, traffic volume, speed, median type, or access context \\
Roads & Provide nearby roadway geometry, route names, roadway type, median context, and carriageway structure & Road data helps describe the physical roadway, but complicated intersections can still require manual review \\
Crashes & Provide crash locations and available route or direction information & A crash record alone does not reliably show whether the crash is upstream, downstream, near the signal, or unresolved \\
Access points & Provide driveway, entrance, and similar point locations near the roadway & An access point alone does not show whether it should be treated as upstream, downstream, near-signal, or unresolved \\
Traffic volume & Provides AADT (annual average daily traffic) & AADT helps describe how much traffic uses the road, but it is not yet being used to calculate crash-rates \\
Speed & Provides assigned speed for speed-based distance-bands & Speed supports exploratory distance tabulation, but the resulting bands should not be treated as recommended DFA distances \\
Median and roadway type fields & Provide information about the divided-road setting & These fields help describe the roadway, but they do not fully resolve complex geometry or classification questions \\
Crash area context & Provides rural or urban context recorded on the crash record & Crash-record area context is not the same as a roadway-level rural, suburban, or urban policy classification \\
Review queues and map layers & Identify signals and records that need human review & Identify review needs but still need manual validation \\
\bottomrule
\end{longtable}
\endgroup

We do not currently have a trusted roadway-level rural, suburban, and urban source. Crash-record area context is useful descriptive information, but should not be used as the final geographic class for policy or modeling.

\Needspace{10\baselineskip}

## 7. How Current Outputs Are Packaged

The current workflow organizes outputs into three descriptive packages. These packages are staged handoffs that present the same signal-centered evidence in different, easier to review and analyze forms, not independent analyses with competing conclusions.

Package 001 establishes baseline descriptive tables. Package 002 expands the same baseline records into additional downstream distance-band views. Package 003 turns descriptive outputs into summary findings and review queues, including the first manual map-review packet.

\begingroup
\small
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{0.9in}>{\raggedright\arraybackslash}p{3.0in}>{\raggedright\arraybackslash}p{2.75in}@{}}
\toprule
Package & Main purpose & How to interpret it \\
\midrule
Package 001 & Establishes the baseline signal, crash, access, traffic volume, speed, roadway, and fixed-band summaries & Most basic starting point for describing the current divided-road slice \\
Package 002 & Reorganizes baseline records into additional distance-band groupings & Compares where downstream crashes and access points fall by distance (fixed and speed determined) \\
Package 003 & Summarizes findings and identifies locations needing review & A review-planning package \\
\bottomrule
\end{longtable}
\endgroup

### 7.1 Package 001: Baseline Descriptive Package

Package 001 is the baseline for the current descriptive package. It creates tables for the signal study areas, crash records, access point records, and fixed downstream distance-bands.

\begingroup
\small
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{2.6in}>{\raggedleft\arraybackslash}p{0.6in}>{\raggedright\arraybackslash}p{3.5in}@{}}
\toprule
Table & Rows & What it contains \\
\midrule
\texttt{signal\_\allowbreak context\_\allowbreak analysis.csv} & 163 & One row per signal study area \\
\texttt{signal\_\allowbreak band\_\allowbreak context\_\allowbreak analysis.csv} & 2,381 & One row per signal study area and fixed 50-foot downstream band \\
\texttt{crash\_\allowbreak band\_\allowbreak assignment.csv} & 2,571 & Crash records associated with signal study areas and downstream bands where possible \\
\texttt{access\_\allowbreak band\_\allowbreak assignment.csv} & 362 & Access point records associated with signal study areas and downstream bands where possible \\
\bottomrule
\end{longtable}
\endgroup

### 7.2 Package 002: Expanded Distance-Band Package

Package 002 keeps the same baseline crash and access records but summarizes them through additional basic distance-band families. This lets us compare patterns using more than one distance framework without changing underlying records.

\begingroup
\small
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{1.55in}>{\raggedright\arraybackslash}p{3.0in}>{\raggedright\arraybackslash}p{2.1in}@{}}
\toprule
Band family & Meaning & Current use \\
\midrule
Fixed 50-foot bands & Detailed 50-foot downstream bins & Fine-grained descriptive review \\
Coarse fixed bands & 0–250 feet, 250–500 feet, 500–1,000 feet, and overflow (within study area) & Easier comparison across signals \\
Speed-based time bands & 0–3 seconds, 3–6 seconds, 6–10 seconds, and overflow (within study area) using assigned speed & Speed-based distance view \\
\bottomrule
\end{longtable}
\endgroup

Package 002 generated these expanded tables:

\begingroup
\small
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{2.85in}>{\raggedleft\arraybackslash}p{0.6in}>{\raggedright\arraybackslash}p{3.25in}@{}}
\toprule
Table & Rows & What it contains \\
\midrule
\texttt{signal\_\allowbreak band\_\allowbreak context\_\allowbreak analysis\_\allowbreak expanded.csv} & 3,685 & Signal study areas summarized across each implemented band family \\
\texttt{crash\_\allowbreak band\_\allowbreak assignment\_\allowbreak expanded.csv} & 7,713 & Crash records repeated across the implemented band families \\
\texttt{access\_\allowbreak band\_\allowbreak assignment\_\allowbreak expanded.csv} & 1,086 & Access point records repeated across the implemented band families \\
\bottomrule
\end{longtable}
\endgroup

Speed-based bands help organize records by distance and assigned speed, but are not recommended DFA design distances (no current distance band should be interpreted as such).

### 7.3 Package 003: Findings and Review Queue Package

Package 003 uses Package 001 and Package 002 outputs to identify useful summaries, unresolved case patterns, and locations that need manual review. Its purpose is to help decide which signals are strong enough to discuss as examples after manual review.

\begingroup
\small
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{2.85in}>{\raggedleft\arraybackslash}p{0.6in}>{\raggedright\arraybackslash}p{3.25in}@{}}
\toprule
Table & Rows & What it contains \\
\midrule
\texttt{signal\_\allowbreak descriptive\_\allowbreak findings\_\allowbreak summary.csv} & 163 & One row per signal with summary flags and counts \\
\texttt{band\_\allowbreak family\_\allowbreak crash\_\allowbreak access\_\allowbreak summary.csv} & 55 & Summary of crash and access counts by band family and band \\
\texttt{signal\_\allowbreak outlier\_\allowbreak review\_\allowbreak queue.csv} & 71 & Signals flagged for manual review using review triggers \\
\texttt{unresolved\_\allowbreak case\_\allowbreak summary.csv} & 34 & Summary of unresolved case patterns \\
\bottomrule
\end{longtable}
\endgroup

Package 003 also created the first manual map-review packet, called Batch A. Batch A includes 18 signals from the Package 003 review queue where both high-confidence downstream crash evidence and downstream access evidence appear at review-trigger levels. This means there were 6 or more high-confidence downstream crashes and 2 or more downstream access points. A signal could include high-confidence crash and access evidence and not make it into Batch A if it did not meet these thresholds. This was the case for three additional signals. The packet includes map layers for signals, study areas, approach rows, downstream high-confidence crashes, downstream access points, unresolved crashes, and unresolved or conflict access points.

Package 003 is a review-planning product. It identifies promising and questionable locations, but still needs manual review.

\Needspace{12\baselineskip}

## 8. What Current Counts Show

The above packages contain enough classified evidence to support descriptive review, but also enough unresolved evidence to inspire some caution.

\subsection*{8.1 Signal and crash classification counts}

\begingroup
\small
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{2.45in}>{\raggedleft\arraybackslash}p{0.65in}>{\raggedright\arraybackslash}p{3.55in}@{}}
\toprule
Measure & Count & What it shows \\
\midrule
Signal study areas & 163 & Current divided-road signal universe \\
Approach rows & 178 & Roadway approaches or carriageway rows used to support context and direction interpretation \\
Classified crash-context rows & 2,571 & Crash context records included in the signal-centered classification table \\
Downstream crashes & 426 & Crash records currently classified downstream of a signal \\
Upstream crashes & 742 & Crash records currently classified upstream of a signal \\
Unresolved crash records & 1,403 & Crash records retained but not confidently assigned upstream or downstream \\
High-confidence downstream crashes & 389 & More conservative downstream crash subset \\
\bottomrule
\end{longtable}
\endgroup

\subsection*{8.2 Access, context, and review counts}

\begingroup
\small
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{2.45in}>{\raggedleft\arraybackslash}p{0.65in}>{\raggedright\arraybackslash}p{3.55in}@{}}
\toprule
Measure & Count & What it shows \\
\midrule
Candidate access points in study areas & 362 & Access records considered within current signal study areas \\
Downstream access points & 70 & Access points currently assigned downstream of a signal \\
Upstream access points & 59 & Access points currently assigned upstream of a signal \\
Near-signal access points & 20 & Access points close enough to the signal that upstream or downstream is not assigned \\
Unresolved access positions & 213 & Access records retained but not confidently assigned to a signal-relative position \\
Signals with matched AADT & 158 & Signal study areas with at least one matched traffic-volume row* \\
Signals with assigned speed & 163 & Signal study areas with speed available or assigned for descriptive use \\
Signals with high-confidence downstream crashes & 112 & Signals with at least one conservative downstream crash record \\
Signals with downstream access points & 28 & Signals with at least one downstream access point \\
Signals with both downstream crashes and downstream access & 21 & Signals where both evidence types appear, including three below the Batch A both-evidence trigger rule \\
Package 003 review queue signals & 71 & Signals flagged for table or map-review \\
Batch A manual review signals & 18 & First high-priority map-review subset from Package 003 \\
\bottomrule
\end{longtable}
\endgroup

\begingroup
\small
\noindent * “matched” means an AADT row has (1) route support, (2) measure support, and (3) geometry support. Route support means the AADT route matches the study road route. Measure support means the AADT record has positive overlap with the route milepoint range used for the signal study area, such as US 220 NB from milepoint 12.40 to milepoint 12.85. Geometry support means the AADT geometry is within 3 feet of the study road geometry.
\par
\endgroup


## 9. Current Boundary of Claims

The current package is a descriptive review product. It organizes signal-centered crash, access, roadway, traffic volume, speed, and distance-band information for the current divided-road slice. It should not yet be used as final evidence for crash-rate analysis, regression modeling, statewide generalization, spreadsheet calculator logic, or recommended DFA design distances.

The main reason is that the current work has not yet defined exposure denominators, model-ready variables, validated policy distance-bands, unresolved-case handling rules, or a trusted roadway-level rural/suburban/urban classification. It also does not support causal claims that access points caused downstream crashes.

“Exposure denominators” means the “amount of traffic or opportunity” used to turn crash counts into crash-rates. For example, 10 crashes at a very high-volume signal and 10 crashes at a low-volume signal do not mean the same thing. A denominator could involve AADT, number of years, segment length, number of approaches, number of access points, or some combination.

“Model-ready variables” means the final columns we would use in a statistical model. For example: downstream crash count, downstream access density, AADT, speed, distance-band, median type, roadway type, rural/suburban/urban class, and rules for which signals are included or excluded.

“Validated policy distance-bands” means distance ranges that are defensible for guidance. The current speed bands help describe where records fall, but we do not have bands validated against VDOT guidance, other DOT literature sources, or observed crash/access patterns enough to say “this is a recommended DFA distance.”

“Unresolved-case handling rules” means a documented decision for what to do with crashes or access points that cannot be confidently classified. For example: exclude them, keep them in a separate unresolved category, test sensitivity with/without them, or require manual review before using them.

“Trusted roadway-level rural/suburban/urban classification” means a reliable source for classifying the road setting itself, not just the crash record. The current crash area context may say rural or urban for a crash, but that is not the same thing as a defensible classification of the entire signalized roadway environment.

“Causal claims” means saying that access points caused crashes. The current workflow can show that downstream crashes and downstream access points coexist near a signal. It cannot yet prove that the access points caused those crashes.

Taken together, the current package converts a complex spatial problem into reviewable signal-centered summaries. It does not answer the final policy question, but it gives the project a structured way to decide which locations, classifications, and distance definitions are credible enough to build on.

## 10. Immediate Methodological Gaps to Resolve

The current package is useful as a descriptive review product, but several methodological gaps need to be resolved before the work can support stronger comparison, modeling, or guidance claims.

### 10.1 Classification and Unresolved Records

Many crash and access records remain unresolved. In the current package, 1,403 of 2,571 crash-context rows are unresolved. For access points, 213 of 362 positions are unresolved.

This does not make the current package unusable, but it does mean unresolved records need to remain visible and must be handled consistently before any model-ready table is created. The next step is to decide whether unresolved records should be excluded, reviewed manually, retained as a separate category, or tested through sensitivity checks.

### 10.2 Access Assignment

Access assignment remains conservative; access points are assigned only when route, measure, and geometry evidence support the match. This protects the workflow from overstating downstream access evidence, but it also leaves many access records unresolved.

This matters because downstream access is central to the DFA question. Before access counts are used in stronger claims, we need clearer rules for when access assignments are accepted, manually reviewed, or left unresolved.

### 10.3 Distance Band Definitions

The current distance-bands are descriptive baseline bins. Package 001 uses fixed 50-foot bands. Package 002 adds coarse fixed bands and speed-based time bands. These bands help organize where downstream crashes and access points fall, but they are not recommended DFA design distances.

The next step is to add additional sourced distance-band families so the same data can be examined under explicit assumptions from VDOT guidance, other state guidance, literature sources, AASHTO-based concepts, and simple observed crash/access patterns.

### 10.4 Geographic Context

The current workflow includes crash-record area context, but it does not yet have a trusted roadway-level rural, suburban, and urban classification.

This matters because future guidance may need to vary by roadway setting. Before that can happen, the project needs to select and document a defensible geographic source, such as Census urban area, VDOT classification, locality, district, MPO area, functional classification, or another roadway-level source.

### 10.5 Reproducible Package Generation

The current descriptive packages exist and are documented, but package generation should be promoted into a cleaner reproducible code path. Future reviewers should be able to easily regenerate Packages 001, 002, and 003 from available repository code in the GitHub.

\Needspace{12\baselineskip}

## 11. Recommended Next Deliverables

The next phase should focus on turning the current descriptive package into a reviewed, reproducible, and defensible handoff. We should validate the strongest current examples, make the package easier to regenerate, and define remaining decisions needed before comparison or modeling work begins.

\begingroup
\small
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{0.45in}>{\raggedright\arraybackslash}p{1.65in}>{\raggedright\arraybackslash}p{2.85in}>{\raggedright\arraybackslash}p{1.55in}@{}}
\toprule
Priority & Deliverable & Purpose & Proposed output \\
\midrule
1 & Complete Batch A review & Review the 18 highest-priority review-queue signals with both downstream crash and access evidence at trigger levels & Completed review table \\
2 & Write Package 003 findings memo & Separate strong examples from questionable or interpretation-limited cases & Reviewed findings memo \\
3 & Reproducibly generate Packages 001--003 & Make the current descriptive package easier to regenerate and audit & Runnable command or module \\
4 & Define unresolved-case rules & Decide how unresolved records enter future tables & Handling note \\
5 & Define sourced distance bands & Add band families tied to VDOT, AASHTO, other DOT/literature sources, and observed patterns for comparison against the baseline bins & Band memo \\
6 & Select roadway-level geography source & Support future rural/suburban/urban interpretation & Source decision memo \\
7 & Define model-ready table contract & Specify fields and inclusion rules before modeling begins & Modeling contract \\
8 & Create Package 004 & Apply sourced band definitions to the descriptive package & Package 004 outputs \\
\bottomrule
\end{longtable}
\endgroup


\begingroup
\small
\noindent *Note: Earlier work used a fixed AASHTO stopping-distance table and a speed-based buffer to approximate decision stopping distance. The current Package 001--003 bands are simpler descriptive baseline bins, not that earlier AASHTO-based approximation.
\par
\endgroup



\begingroup
\small
\noindent **Note: A model-ready table contract would define what the future modeling dataset should look like before any model is run. It would specify the unit of analysis, included/excluded signals, outcome variables, exposure or denominator fields, explanatory variables, unresolved-case handling rules, distance-band fields, geographic-context fields, and interpretation limits.
\par
\endgroup


### 11.1 Immediate Review Deliverable

The most important immediate next step is to complete the Package 003 Batch A manual review and write up findings.

This would help determine which locations are strong examples, which are questionable, and which should not be used until classification or geometry concerns are resolved. We have so few (18) that manual review is fully reasonable but may take a bit of time. We also need a clear review structure so review is consistent from signal study area to signal study area.

### 11.2 Reproducible Packaging Deliverable

The most important packaging step is to promote the Package 001–003 generation process into a cleaner reproducible path.

### 11.3 Methodology Deliverables Before Modeling

Before creating a model-ready table, we should define unresolved-case handling rules, sourced downstream distance-band families, and a trusted roadway-level geographic source.

These decisions should come before regression, crash-rate analysis, spreadsheet calculator logic, or recommended DFA design distances. They determine what the eventual comparison table means and how strongly its results can be interpreted.

## 12. Exact Questions For Review

1. Should I stay focused on only divided-roads for now or try moving to a different roadway type?

2. Should I manually review only Batch A or try to go through the larger 71-signal queue*?

3. What should I record during manual review?

4. What sources should I use to define the next distance-bands? What's the best way to look for patterns in our crash/access data?

5. What should we do with unresolved crashes and access points? Should unresolved records stay in a separate category, be excluded from future tables, be manually reviewed, or be tested in some kind of sensitivity check?

6. What should we use for rural/suburban/urban context? The current crash area field is not enough for roadway-level classification. Should I look at Census urban area, VDOT classification, locality, district, MPO area, functional class, or another source?

7. Goals for next meeting?


\begingroup
\small
\noindent *Note: Package 003 flagged 71 signal study areas because each one met at least one review trigger: a high downstream crash count (6 or more high-confidence downstream crashes), a high downstream access count (2 or more downstream access points), both evidence types present with at least one of those count triggers, many unresolved crashes, many unresolved access points, or a meaningful difference between fixed distance-bands and speed-based time bands. There were 21 signals with any high-confidence downstream crash evidence and any downstream access evidence, but only 18 entered Batch A under the both-evidence review-trigger rule.
\par
\endgroup


\newpage

# Appendix A. Repo and Output Map

## A.1 Key Documentation Files

\begingroup
\scriptsize
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{3.15in}>{\raggedright\arraybackslash}p{3.45in}@{}}
\toprule
File & Purpose \\
\midrule
\texttt{docs/\allowbreak methodology/\allowbreak overview\_\allowbreak methodology.md} & Core active methodology for signal-centered downstream functional area analysis \\
\texttt{docs/\allowbreak methodology/\allowbreak proposal\_\allowbreak alignment\_\allowbreak growth\_\allowbreak plan.md} & Connection between the current repo and the larger VTRC proposal \\
\texttt{docs/\allowbreak workflow/\allowbreak active\_\allowbreak workflow.md} & Current workflow commands, active modules, and output contracts \\
\texttt{docs/\allowbreak workflow/\allowbreak enrichment\_\allowbreak plan.md} & Context enrichment scope and validation expectations \\
\texttt{docs/\allowbreak workflow/\allowbreak proposal\_\allowbreak facing\_\allowbreak descriptive\_\allowbreak analysis\_\allowbreak package\_\allowbreak 001.md} & Baseline descriptive package documentation \\
\texttt{docs/\allowbreak workflow/\allowbreak proposal\_\allowbreak facing\_\allowbreak descriptive\_\allowbreak analysis\_\allowbreak package\_\allowbreak 002.md} & Expanded distance-band package documentation \\
\texttt{docs/\allowbreak workflow/\allowbreak proposal\_\allowbreak facing\_\allowbreak descriptive\_\allowbreak findings\_\allowbreak package\_\allowbreak 003.md} & First findings and review queue package documentation \\
\texttt{docs/\allowbreak workflow/\allowbreak package\_\allowbreak 003\_\allowbreak signal\_\allowbreak outlier\_\allowbreak map\_\allowbreak review\_\allowbreak batch\_\allowbreak A\_\allowbreak guide.md} & Batch A map-review guide \\
\bottomrule
\end{longtable}
\endgroup

## A.2 Key Output Locations

\begingroup
\scriptsize
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{3.15in}>{\raggedright\arraybackslash}p{3.45in}@{}}
\toprule
Output location & Purpose \\
\midrule
\texttt{work/\allowbreak output/\allowbreak proposal\_\allowbreak descriptive/\allowbreak tables/\allowbreak current/} & Package 001 current tables \\
\texttt{work/\allowbreak output/\allowbreak proposal\_\allowbreak descriptive/\allowbreak package\_\allowbreak 002/\allowbreak tables/\allowbreak current/} & Package 002 expanded band tables \\
\texttt{work/\allowbreak output/\allowbreak proposal\_\allowbreak descriptive/\allowbreak package\_\allowbreak 003/\allowbreak tables/\allowbreak current/} & Package 003 findings and review queue tables \\
\texttt{work/\allowbreak output/\allowbreak proposal\_\allowbreak descriptive/\allowbreak package\_\allowbreak 003/\allowbreak review/\allowbreak current/} & Batch A review packet and GeoJSON layers \\
\texttt{work/\allowbreak output/\allowbreak context\_\allowbreak enrichment/\allowbreak tables/\allowbreak current/} & Enriched signal, approach, crash, and access tables used by Package 001 \\
\texttt{work/\allowbreak output/\allowbreak upstream\_\allowbreak downstream\_\allowbreak prototype/\allowbreak review/\allowbreak geojson/\allowbreak current/} & Map support layers from the upstream and downstream prototype \\
\bottomrule
\end{longtable}
\endgroup

## A.3 Key Runnable Workflow Elements

The repository bootstrap command identifies the active Python interpreter:

```text
.\scripts\bootstrap.cmd
```

The standard active slice uses the bootstrap reported interpreter:

```text
<bootstrap-reported-python> -m src stage-inputs
<bootstrap-reported-python> -m src normalize-stage
<bootstrap-reported-python> -m src build-study-slice
<bootstrap-reported-python> -m src enrich-study-signals-nearest-road
<bootstrap-reported-python> -m src check-parity
```

The current direct entry analytical modules are:

- `src.active.directionality_experiment`
- `src.active.upstream_downstream_prototype`
- `src.active.high_confidence_upstream_downstream_analysis`
- `src.active.context_enrichment`
- `src.active.context_enrichment_access_same_corridor_prototype`

Each module should be run with the bootstrap reported Python interpreter, using the pattern `<bootstrap-reported-python> -m <module-name>`.

The proposal facing packages currently exist as generated outputs and documented contracts. The next packaging task is to promote their generation into a clean reproducible command or module.

# Appendix B. Suggested Figures for Future Version

This memo could become a more forward-facing project documentation piece with a small set of figures. The most useful figures would explain the full workflow, the signal study area concept, the package structure, and the manual review process. Two figures already exist for the directionality experiment and upstream/downstream classification, so the remaining need is a higher-level figure set that helps a reader understand how the pieces fit together without reading pages of repo code.

\begingroup
\small
\begin{longtable}{@{}>{\raggedright\arraybackslash}p{1.85in}>{\raggedright\arraybackslash}p{1.85in}>{\raggedright\arraybackslash}p{2.95in}@{}}
\toprule
Figure & Suggested location & Purpose \\
\midrule
Workflow overview diagram & After Section 4 & Show how raw inputs become signal study areas, classifications, enriched outputs, packages, and review queues \\
Signal study area concept sketch & After Section 5 & Explain the signal, divided-road approaches, upstream/downstream areas, access points, and distance-bands \\
Package progression diagram & After Section 7 & Show how Package 001, Package 002, and Package 003 build on each other \\
Classified vs. unresolved counts chart & After Section 8 & Show why the current package is useful but still conservative \\
Batch A review map example & After Section 12 or in a later reviewed findings memo & Show one signal with downstream crashes, downstream access points, unresolved records, and study area geometry \\
\bottomrule
\end{longtable}
\endgroup

The first two figures should be prioritized. The workflow overview explains what the project has built. The signal study area sketch explains the spatial logic behind the current analysis. The Batch A review map should wait until at least one signal has been manually reviewed, so the figure does not imply validation before review is complete.


