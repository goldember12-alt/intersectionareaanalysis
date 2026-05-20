\begin{titlepage}
\centering
\vspace*{1.35in}

{\Large\bfseries Cross-City Urban Heat Hotspot Screening\par}
\vspace{0.25in}
{\large Same-City Learning, Held-Out-City Transfer, and Spatial Alignment\par}

\vspace{0.85in}
Max Clements and Nicholas Machado\par
\vspace{0.18in}
University of Virginia\par
\vspace{0.18in}
STAT 5630 Statistical Machine Learning\par
\vspace{0.18in}
Instructor: Lingxiao Wang\par
\vspace{0.18in}
May 3, 2026\par

\vfill

\end{titlepage}

\newpage

## 1. Background Information

Extreme urban heat presents an increasing public health, infrastructure, and planning problem as land surface temperatures (LST) continue to rise. Complicating things, land surface temperature is not distributed evenly within cities. Pavement, roofs, vegetation, water proximity, terrain, and land cover can create large temperature contrasts across nearby neighborhoods. A citywide average therefore hides the local places where heat-mitigation investment, additional monitoring, or planning attention may be most useful. Determining these local critical areas, or hotspots, motivates a modeling question: can publicly available spatial variables rank local grid cells when direct thermal measurement is unavailable, incomplete, or reserved for evaluation?

To investigate this question, this report constructs a dataset for 30 cities with 30 m grid cell resolution and tests whether six public nonthermal predictors can identify the grid cells with the highest LSTs. The central finding is simple but highlights a critical understanding for future research: validation design changes scientific conclusion dramatically. Random forest performs strongly when tested on held-out cells from cities represented during training, but performance in cities withheld entirely from training is much weaker, and the gain over simple imperviousness and land-cover baselines is only modest. However, poor 30 m cell matching does not always mean model predictions are spatially random in cities withheld from training. We illustrate this fact with a supplemental spatial analysis.

Our analysis distinguishes three evaluation questions. Same-city evaluation asks whether held-out cells can be ranked inside cities represented during model development. Heldout-city transfer asks whether a model can rank hotspot cells in cities that were fully withheld from training, preprocessing, and tuning. Broader spatial alignment asks whether high predicted risk falls in the same broad areas of an unseen city as observed hotspot concentration, even when the exact cells do not match.

Remote sensing makes the hotspot label possible because satellites can observe spatial temperature patterns that ground stations alone cannot. Thermal infrared sensors measure emitted radiation from the land surface and can be converted into LST. LST is surface temperature, not two-meter air temperature: a roof, road, tree canopy, irrigated field, or bare-soil patch can heat differently from the surrounding air. NASA land surface temperature documentation emphasizes this distinction, and ECOSTRESS documentation describes a thermal mission that measures surface temperature at fine spatial detail from the International Space Station. For this reason, the hotspot label should be interpreted as a measure of relative LST intensity, not direct human heat exposure.

Urban thermal remote sensing has long been used to map surface-temperature variation within cities. Voogt and Oke (2003) review this literature and note that many urban thermal studies historically emphasized qualitative maps of thermal patterns and simple correlations with surface descriptors. Later Landsat-based work gave more quantitative evidence for specific predictors. Weng, Lu, and Schubring (2004) studied the relationship between land surface temperature and vegetation abundance in Indianapolis, while Yuan and Bauer (2007) compared NDVI and impervious surface as indicators of surface urban heat-island effects in the Twin Cities. Stewart and Oke (2012) also show why urban thermal behavior depends on local surface form, land cover, and urban structure rather than climate alone. Together, this work motivates a feature set based on vegetation, imperviousness, land cover, terrain, water proximity, and climate context, while heat vulnerability also depends on people, resources, and exposure conditions beyond surface temperature itself (Harlan et al., 2006).

AppEEARS, NASA’s tool for requesting and subsetting Earth observation products, supports the reproducible remote sensing part of our workflow by subsetting MODIS/Terra NDVI and ECOSTRESS LST to the same-city study regions and May-August 2023 window used for modeling. As a result, the dataset relies on area requests and preprocessing rules rather than manually selected images.

The distinction between same-city ranking and held-out-city transfer is central to our validation design because spatial models can appear stronger when evaluation data remain close to the training data. Ordinary row or cell splits can be too easy for spatial data because nearby cells and cells from the same city can appear in both training and testing. Roberts et al. (2017) argue that ignoring spatial, temporal, or hierarchical structure in cross-validation can underestimate predictive error, and Meyer et al. (2018) show that target-oriented validation can reveal weaker performance when models must predict beyond familiar locations. We apply the same principle at the city scale while also reporting the same-city question that planners often face inside a mapped city.

The stated urban-heat literature motivates our feature set, while the spatial-validation literature motivates our evaluation design. Prior LST studies show that vegetation, imperviousness, land cover, and urban form can explain local thermal variation, but those relationships are often estimated within a single familiar city. The harder question is whether those relationships hold in cities the model has never seen.

Because our primary goal is exploring validation design, the model comparison is deliberately modest. Logistic regression provides a linear reference model, while random forest provides a nonlinear comparison that can capture threshold effects and interactions without adding a more complex deep-learning or spatial-statistical architecture. Hotspots make up roughly one tenth of eligible cells, so the held-out-city transfer evaluation emphasizes precision-recall metrics rather than overall accuracy. A model can appear accurate by blanketly predicting the majority non-hotspot class, but that does not answer the more important ranking question.

This report proceeds in four steps. First, we construct a standardized 30-city grid cell dataset from public geospatial and remote sensing sources. Second, we define a city-relative hotspot label based on the hottest 10% of valid May-August ECOSTRESS LST cells within each city. Third, we compare logistic regression and random forest under same-city evaluation and held-out-city transfer. Finally, we use city-level and spatial summaries to show where performance is stronger, where it weakens, and when broader spatial alignment remains visible despite errors at the 30 m cell scale.

Therefore, our main contributions are the standardized dataset, a comparison between same-city and held-out-city evaluation, a comparison between simple baselines, logistic regression, and random forest, and a supplemental spatial analysis of held-out random forest predictions. The completed dataset contains 71,394,894 rows and 17 columns, with one row representing one analytic 30 m grid cell in one selected U.S. city. Cities are balanced across three broad climate groups: 10 hot arid, 10 hot humid, and 10 mild cool cities. Figure 1 shows the selected city locations, and Table 2 summarizes the final audited dataset by climate group. The public geospatial and remote sensing sources used to construct our dataset are summarized in Table 1. Our modeling specification excludes thermal variables, using ECOSTRESS LST to define the outcome rather than predict it. Because we constructed the final dataset from public source layers rather than downloading a preexisting dataset, source products are cited in References, and reproducibility notes at the end of the report link to a GitHub repository for this project.

## 2. Research Questions

Our primary research question has two parts:

Can basic environmental and built-environment features identify local heat hotspots across a multi-city dataset? How does performance change when evaluation moves from held-out cells within familiar cities to cities withheld entirely from model development?

Three secondary questions organize the results. First, do nonthermal geospatial predictors rank the locally hottest urban grid cells above cooler cells? Second, does a nonlinear random forest improve hotspot ranking compared with logistic regression and simple baselines, and does that comparison change across evaluation designs? Third, do prediction maps show evidence of broader spatial alignment with observed hotspot concentration at resolutions coarser than 30m?

Our analysis applies to eligible 30 m grid cells in the 30 selected U.S. urban-area study regions. The outcome variable, `hotspot_10pct`, is a binary label identifying the hottest 10% of valid eligible cells within its own city, based on median May-August ECOSTRESS LST after filtering. This top-decile definition creates a common ranking task across cities with different absolute temperature distributions. It also matches a practical prioritization question: if a city could inspect or target only the highest-risk decile of cells, how many true local surface-temperature hotspots would it recover? Because the label is based on LST, our analysis supports local LST hotspot modeling rather than national heat-exposure assessment, air-temperature risk mapping, or vulnerability analysis.

## 3. Dataset Construction

Our dataset construction workflow begins with city selection and defining the study-region. We use 30 U.S. cities, balanced across three broad climate groups: hot arid, hot humid, and mild cool. Cities were selected to provide geographic and climate variation while remaining feasible for a standardized acquisition and modeling pipeline, so the set is purposive rather than nationally representative. That choice limits interpretation: our results are evidence from a deliberately varied city panel, not national estimates for all U.S. urban areas.

For each selected city, the study region begins with the 2020 Census urban area containing the city-center coordinate for that city. We then apply a 2 km buffer around that urban-area polygon. The 2 km distance is a pragmatic fixed rule that captures near-urban land-cover and water-adjacency transitions without redefining each city manually; buffer sensitivity is left for future work and may have a larger impact in hot arid cities. The unbuffered core area remains available for core-city filters but is not the focus of our analysis.

We then overlay each city with a city-specific 30 m resolution grid built in a local UTM coordinate reference system, which makes distances and cell areas meaningful within each city. This grid provides the common unit for all features and labels: every final row is one grid cell, and every raster or vector source is converted into a value for that same cell.

Not every source variable had native 30 m resolution. NLCD aligns closely with the grid, while MODIS/Terra NDVI is coarser, ECOSTRESS has its own thermal-pixel and overpass structure, and vector quantities such as distance to water are summarized to cell centroids or geometry. The common grid gives every city the same modeling unit rather than requiring native 30 m measurement for every variable.

The source layers are then prepared against this grid. NLCD 2021 land cover supplies a categorical surface class for each cell, and NLCD 2021 imperviousness supplies a continuous percent-impervious value. USGS 3DEP elevation is aligned to the grid to provide terrain context. NHDPlus HR hydrography is handled as vector information: water features are clipped to the city study area and converted to a distance from each grid cell to the nearest selected water feature. MODIS/Terra NDVI and ECOSTRESS LST are acquired through AppEEARS using the city area of interest and summarized for May-August 2023. We use median May-August NDVI as the vegetation predictor and median May-August ECOSTRESS LST as the basis for the hotspot label.

The May-August seasonal summary is a compromise between heat relevance and data robustness. It focuses the target and vegetation feature on the summer, when surface heat is most relevant to the urban heat problem, while aggregating over multiple observations. ECOSTRESS also has irregular overpass timing because it is mounted on the International Space Station, so the analysis records n_valid_ecostress_passes as an observation count variable. Cells are retained for labeling only when at least three valid ECOSTRESS observations contribute to the May-August LST summary. This filter reduces the chance that a cell is labeled from an unstable or nearly missing ECOSTRESS summary, but pass count alone does not make all cities observationally identical. Overpass time, clouds, seasonality within May-August, and weather conditions can still vary across cities and remain part of the remote sensing limitation.

Our final assembly step merges the per-city feature tables into a single modeling-ready dataset. Open-water cells are removed when NLCD land cover identifies class 11 (open water cells), so the hotspot label is not driven by water surfaces that are outside the intended land-focused analysis. After this open-water filter and the ECOSTRESS quality filter, hotspot_10pct is recomputed within each city. Eligible cells in a city are ranked by median May-August LST, the hottest decile is labeled 1, and the remaining eligible cells are labeled 0.

The final dataset contains the city identifier and name, broad climate group, cell identifier, centroid longitude and latitude, six primary predictors, ECOSTRESS-derived LST and pass count, the hotspot_10pct label, and three neighborhood-context variables reserved for supplemental modeling. The primary six predictor specification does not use those neighborhood variables for logistic vs. random forest comparisons. They are excluded here to keep the first comparison focused on basic public predictors. In particular, latitude and longitude are excluded for held-out-city transfer because we focus on modeling surface relationships that can translate across cities, and location identity definitionally cannot.

The completed audit summarized in Table 2, broken down by climate group, shows 30 cities, 71,394,894 rows, and 7,139,588 hotspot-positive cells. Because hotspot_10pct is recomputed within cities, overall prevalence is approximately 10% by construction, though not exactly 10% in all cases because rare ties can occur in LST. Each climate group has nearly the same hotspot prevalence despite large differences in total row count by construction. Missingness is low for the primary predictors: imperviousness, land cover, distance to water, and climate group have no missing values in the final table; elevation is missing for only 3,426 cells, and median May-August NDVI is missing for 99,625 cells, about 0.14% of the dataset. The row-count distribution is uneven across cities because study-area extents differ substantially.

The dataset contains many rows, but nearby rows are not fully independent. Adjacent cells can share source summaries, sensor conditions, and spatial context, so the effective number of independent observations is smaller than the raw row count.

Figure 2 summarizes the full dataset construction workflow. The resulting table is designed for model evaluation rather than city-by-city description. Each row represents a standardized 30 m grid cell, each predictor is aligned to that common unit, and the city-relative hotspot label supports comparison between same-city prediction and held-out-city transfer.

## 4. Model and Method

Using this constructed dataset, the central machine learning task is to estimate whether each grid cell belongs in the hottest 10% of a given city’s eligible cells. The response variable is hotspot_10pct, and the primary model uses only these six nonthermal predictors: impervious_pct, land_cover_class, elevation_m, dist_to_water_m, ndvi_median_may_aug, and climate_group. Climate group is included as a broad, preassigned city-level descriptor rather than a city identifier; it does not identify individual held-out cities but may capture coarse regional thermal context and help interpret differences across city groups. Capturing more specific variation in climatology for all cities by including a better climate feature presents a strong opportunity for future work.

Several columns are intentionally excluded from the predictive feature set. The target itself, hotspot_10pct, is our response variable. The thermal variables lst_median_may_aug and n_valid_ecostress_passes are excluded because LST defines the label and ECOSTRESS pass count is an observation count variable used in dataset construction rather than a stable urban-form predictor. Cell identifiers, city identifiers, city names, and centroid coordinates are excluded so the first model comparison focuses on portable surface relationships rather than location identity. Location-aware and spatial-context predictors are logical extensions for future work.

Our two validation designs answer different scientific questions. The first is same-city held-out evaluation: cities are represented during model development, and models are evaluated on held-out cells from those same cities. The same-city analysis holds out approximately 30% of cells within each city using a 70/30 train/test split. It reports class-1 hotspot precision, recall, and F1 for logistic regression and random forest using thresholded class predictions. See Appendix B and the project GitHub for notes about the same-city modeling code. Because the model has already seen cells from each city during training, these results represent an expectedly easier local-ranking task and serve as a benchmark for the held-out-city transfer analysis.

The second design evaluates transfer on unseen cities, illustrated schematically in Figure 3. The 30 cities are partitioned into five outer folds, with six cities held out in each fold and the remaining 24 cities used for training. Partitioning was performed randomly. To see specific fold splits, see Appendix Table A1. Every city is held out exactly once. For each outer fold, preprocessing, imputation, scaling, categorical encoding, and hyperparameter tuning are fit using training-city rows only. Inner cross-validation also holds out groups of training cities rather than randomly splitting individual cells. The final held-out prediction table represents a city-level generalization test.

We compare logistic regression and random forest across these two validation designs and include single feature or simple rule-based baselines for held-out city analysis. This baseline comparison shows whether a learned model improves beyond basic ranking rules. We include a no-skill reference, a global-mean baseline, a baseline using only land cover, a baseline using only imperviousness, and a baseline using only climate. Reference performance metrics are reported in Table 3 and are discussed in more detail in section 5.2.

The logistic regression model serves as a linear comparison for our primary six-feature analysis. Missing-value imputation, numeric scaling, one-hot encoding of categorical features, and the classifier are fit together inside each training fold. The classifier uses the saga solver to support regularized L1, L2, and elastic-net logistic models over the same feature specification. Logistic regression models hotspot log-odds as an additive function of the predictors. This provides a reference point for asking whether nonlinear structure adds value.

The random forest model serves as a nonlinear comparison. It uses the same training-only preprocessing rule. Numeric predictors are imputed, categorical predictors are encoded inside the training fold, and the forest is tuned over tree count, tree depth, feature subsampling, and minimum leaf size. A random forest averages predictions from many decision trees, allowing threshold effects and interactions among variables such as land cover, vegetation, imperviousness, and climate group. The model is therefore a natural test of whether nonlinear relationships improve performance.

Our two validation settings use related but not identical metrics, so the report compares patterns rather than treating all numbers as one leaderboard. Same-city held-out results are summarized with thresholded hotspot precision, recall, and F1. Held-out-city performance is primarily evaluated with average precision (AP) and recall at the top 10% predicted risk. Because hotspots make up roughly 10% of each city’s eligible cells, an AP score near 0.10 corresponds to the no-skill reference, where true hotspots are not meaningfully ranked above non-hotspots.

Two AP metrics are reported for held-out-city performance: pooled AP and mean city AP. Pooled AP combines rows from all held-out cities before scoring, so it emphasizes aggregate row-level ranking. Mean city AP first computes AP separately for each held-out city and then averages across cities, which gives each city equal interpretive weight. The two can disagree when a model performs better in some cities than others. Recall at top 10% predicted risk asks what fraction of true hotspots would be recovered if a city inspected only the cells the model ranked in the highest risk decile. Because the hotspot label is also defined as the hottest 10% of cells within each city, this recall metric has a direct screening interpretation: it measures hotspot recovery when the model selects the same share of cells as the label. The fixed hotspot share in the held-out samples means these scores should still be read as ranking metrics for the benchmark sample, not as calibrated probabilities for the full city population.

The held-out-city transfer benchmark uses sampled rows rather than every eligible grid cell so that each city receives equal weight. Our primary model comparison samples 5,000 rows per city: 500 hotspot cells and 4,500 non hotspot cells, using random state 42. In each outer fold, the models train on 120,000 sampled rows from 24 cities and test on 30,000 sampled rows from six held-out cities. This 5,000-row setting is the primary logistic regression versus random forest comparison because both models use the same sample cap and fold structure. We report a larger 20,000-row logistic regression run for context and to test whether increased sample size materially changes results. This design preserves the grouped city-held-out validation structure while preventing larger cities from dominating. Scoring every eligible cell would answer a separate citywide deployment question: whether the model can prioritize the right locations across the full study area, not just within a balanced benchmark sample. The larger logistic run provides a check on whether additional rows alone reduce the transfer challenge.

Our final spatial analysis asks a different question from the sampled model comparison. Instead of questioning whether the model recovers the exact hottest 30 m cells, it asks whether predicted risk falls in the same broader parts of a held-out city as observed hotspot concentration. Each outer-fold random forest model is trained and tuned only on training cities using 5,000 sampled rows, then used to score every eligible row in the held-out cities. Observed hotspot and predicted risk maps are reconstructed on each city’s 30 m grid and smoothed at 150 m, 300 m, and 600 m. These radii act as neighborhood-scale checks: 150 m captures fine local structure, 300 m is the medium scale we emphasize, and 600 m tests broader gradients. For each scale, we summarize Spearman correlation between smoothed maps, overlap between observed and predicted top smoothed regions, observed hotspot mass captured by the predicted top region, centroid distance, and median nearest-region distance. These all-row spatial summaries do not replace AP or recall at top 10%, but do test whether the transfer model retains broader spatial signal even when exact cell recovery is weak.

## 5. Results and Discussion

### 5.1 Same-City Screening

Same-city results show how much signal the six predictors contain when local examples are available. Figure 4 summarizes our same-city results and shows random forest clearly outperforms logistic regression on class-1 hotspot precision, recall, and F1. Averaged across the 30 cities, random forest reaches mean hotspot precision 0.7310, recall 0.3433, and F1 0.4480, compared with logistic regression means of 0.3887, 0.0727, and 0.1083. This result shows that the six nonthermal predictors rank hotspot cells well when local examples from the same city are available, and that nonlinear or interaction-like structure helps in that setting. The combination of high precision and lower recall also suggests that the same-city random forest identifies a selective subset of predicted hotspots more successfully than it recovers all hotspot cells. In practical terms, the model is better at flagging a smaller set of highly likely hotspot cells than at producing a complete map of every hotspot cell within the city.

### 5.2 Held-Out-City Transfer

Held-out-city transfer results give a weaker and much closer model comparison. The models rank hotspots above the no-skill reference in unseen cities, but gains over imperviousness and land-cover baselines are small and concentrated mainly in selected hot arid cities. As shown in Table 3, the random forest 5k model reaches pooled AP of 0.1486, above the 0.1000 no-skill reference and above the 0.1353 baseline using land cover alone. The logistic SAGA 5k model reaches 0.1421.

In our matched 5000-row comparison, random forest improves from 0.1421 to 0.1486 on pooled AP. It also improves recall at the top 10% predicted risk from 0.1647 to 0.1961. At the same time, logistic regression remains slightly stronger on mean city AP, with 0.1803 compared with 0.1781 for random forest. This small city-weighted edge suggests that random forest’s pooled gains are not uniform across held-out cities; they depend partly on selected cities where nonlinear splits transfer more successfully. The larger 20,000-row logistic run reaches pooled AP of 0.1457 and recall at the top 10% of 0.1709, which suggests that more sampled rows improve performance marginally but do not remove the transfer challenge. Table 3 shows that despite the modest improvement, runtime for the 20,000-row run increased over 300%.

These transfer results are best interpreted as a prioritization test, not as evidence that the model can classify every 30 m cell correctly in a new city. In the sampled comparison, random forest recovers about 19.6% of true hotspots when only the top 10% of predicted-risk cells are inspected. That is nearly double the 10% no-skill reference, but only modestly above the 18.6% recall from the impervious-only baseline. In practical terms, the model provides some useful ranking signal in unseen cities, but much of that signal is already captured by simple built-environment variables.

The validation design changes the model comparison. Random forest shows a clear advantage when each city contributes training examples, while transfer to held-out cities is weaker, closer between models, and more varied across places. Figure 4 is therefore a validation contrast rather than a single metric scale. The same-city panel shows how well the models exploit local training examples, while the held-out-city panel shows how much of that signal transfers to new urban contexts.

### 5.3 Transfer Heterogeneity and Signal Shift

Transfer performance varies substantially across cities, and same-city success does not reliably predict where transfer will work best. Figure 5 compares same-city random forest performance with held-out-city transfer performance. The correlation between same-city random forest hotspot F1 and held-out-city random forest AP is only 0.08. The correlation between same-city random forest hotspot recall and held-out-city random forest recall at the top 10% of predicted risk is only 0.03. In practical terms, cities that are easy to model when local examples are available are not necessarily easy to model when the city is withheld entirely from training.

This weak relationship shows that same-city screening and held-out-city transfer are measuring different forms of model success. Same-city performance reflects how well the model can learn local spatial relationships once it has seen examples from that city. Transfer performance reflects whether relationships learned from other cities apply to a new urban context. Reno illustrates this distinction: it has strong same-city random forest performance, but that local success does not carry over with the same strength under transfer. One plausible interpretation is that the six predictors capture strong within-city heat structure in Reno, but that the local feature relationships are too city-specific to transfer when Reno is withheld from training. Nashville points in the other direction because it performs comparatively well when held out and remains visible in the same-city view. Its relative success under held-out-city validation may reflect stronger alignment between hotspots and urban structure captured by the six predictors. These examples suggest that transfer depends less on whether a city has a strong learnable structure in general and more on whether that structure is captured by relationships shared across cities.

Figure 5 also shows visible separation between hot arid and hot humid cities. This pattern is useful for interpretation, but should not be treated as causal evidence. Climate group classification is entangled with geography, urban form, fold composition, coastal exposure, vegetation patterns, sensor timing, and other local conditions not fully captured by the six-predictor model. The visual separation therefore only identifies where transfer behavior differs, not necessarily why it differs.

Appendix Figure A1 provides a complementary view by plotting the gap between same-city performance and retained held-out-city performance for each city and model. The AP gap and recall at the top 10% gap move together closely, with a Pearson correlation of 0.95 and a Spearman correlation of 0.94 across the plotted city-model points. This high correlation is expected because both metrics measure related forms of validation loss: when a model loses its ability to rank hotspots above cooler cells in transfer, both average precision and top-decile recall usually decline. Reno random forest is the clearest outlier. Its large gap reflects unusually strong local learning that does not transfer with the same strength, rather than simply poor held-out performance.

Several other cities show the same kind of signal shift. El Paso random forest, Las Vegas logistic regression, San Jose random forest, and Los Angeles random forest appear in the high-gap region, meaning the model extracts strong local signal when the city is represented during fitting but loses much of that advantage when transferring from other cities. By contrast, Portland logistic regression and Detroit logistic regression fall slightly below zero on both gap metrics. Those points are not errors; they indicate cases where retained transfer scores are slightly higher than repeated same-city split scores.

The broader interpretation is that transfer works best when the six predictors capture the local structure that actually organizes surface heat in a city. Nashville is a useful example. Its random forest gap is moderate rather than extreme in Appendix Figure A1, and Appendix Figure A2 shows strong broad spatial alignment between predicted risk and observed hotspots. This suggests that Nashville’s hotspot geography may be organized in ways reasonably captured by imperviousness, vegetation, land cover, elevation, water proximity, and climate group. San Francisco points in the opposite direction. Its random forest shows a much larger same-city advantage, while Appendix Figure A2 shows weak spatial alignment. That pattern suggests that coastal exposure, microclimate, sensor timing, or other local features outside the model may be more important there.

City-to-city heterogeneity is the main caution against overreading the pooled result. Appendix Tables A2–A4 show that random forest gains are not uniform: it improves performance in folds 0, 3, and 4, but underperforms in folds 1 and 2, and logistic regression wins most city-level AP comparisons. Random forest gains are concentrated more in hot arid cities, while hot humid and mild cool cities more often favor logistic regression or show weaker random forest gains. One plausible interpretation is that hot arid cities provide sharper surface contrasts that align more directly with imperviousness, vegetation, and land-cover thresholds, while hot humid and mild cool cities may depend more on local canopy structure, coastal exposure, weather, sensor timing, or other factors outside the six-predictor feature set. Under those conditions, random forest’s flexibility can become less transferable: it may learn splits that fit some training cities well without providing a stable rule for every held-out city. Together, these results suggest that the better model varies by city and climate group rather than following a simple random forest versus logistic regression rule.

### 5.4 Broad Spatial Placement

Figure 6 provides Denver as an example held-out city from a random forest fold in which Denver was excluded from training. These maps compare predicted hotspot cells, observed hotspot cells, and categorical error types. Errors are not randomly scattered: missed hotspots and false positives appear in easy to identify spatial bands and clusters. This motivates our all-city spatial analysis. A single city map cannot establish overall performance, but it shows why exact 30 m cell recovery and broader spatial placement are different evaluation questions.

All-city spatial analysis sharpens the interpretation of held-out-city transfer. At the 300 m smoothing scale, random forest prediction maps show mean Spearman correlation of 0.2713, mean top-region overlap of 0.1353, and mean observed hotspot mass captured of 0.2114. These averages are modest, but the cross-city spread in Figure 7 is more informative than the mean alone, as top-region overlap and captured mass varied heavily by city. Nashville presents a clearly strongly-aligned case: it has the highest Spearman correlation, observed mass capture, and top-region overlap in the medium-scale analysis. Appendix Figure A2 shows the pattern behind those scores. In Nashville, predicted high-risk areas follow much of the same broad geography as observed hotspots. For this feature set, Nashville appears to be a city where imperviousness, vegetation, land cover, elevation, water proximity, and climate group align unusually well with observed hotspot geography.

San Francisco provides the clearest weak-alignment contrast. Its prediction map is not visually incoherent; the random forest still projects a structured pattern reflecting underlying urban structure. However, that predicted pattern visually does not match the observed hotspot map at all. Numerically, San Francisco has a medium-scale Spearman correlation of 0.05, observed hotspot mass captured of 0.04, and top-region overlap of 0.02. This suggests that the six-predictor specification can produce a coherent urban-structure map while still missing the processes that determine hotspots in a particular unseen city. Those missing processes could include coastal effects, microclimate, spatial context, sensor timing, or local land-surface details not represented by the six predictors. For San Francisco in particular, observed hotspots appear concentrated in the southern portion of the study region, which may reflect coastal cooling and marine-layer effects in the city core combined with warmer inland or industrial surfaces toward the edge of the urban area.

The broader interpretation is that held-out-city performance depends on whether the chosen feature set matches each city’s actual hotspot geography. Where hotspots follow gradients in imperviousness, vegetation, land cover, and related urban form, the model can place risk in roughly the same broad areas as observed hotspots. Where hotspots are driven by unmeasured local factors or spatial details outside the six predictors, both exact 30 m recovery and broader alignment weaken. The random forest is therefore not simply guessing random cells, but its learned urban-structure pattern transfers only when that pattern corresponds to the held-out city’s observed hotspot structure.

### 5.5 Predictive Interpretation

Appendix Figure A3 provides predictive interpretation summaries: random forest permutation importance emphasizes NDVI and imperviousness, while logistic coefficients are more sensitive to categorical encoding and the omitted land-cover reference level. These summaries are predictive rather than causal because predictors are correlated with broader urban form, land management, local climate, and sensor-observation conditions.

These results support our central interpretation. Public nonthermal geospatial predictors can rank hotspot cells above cooler cells, but the apparent strength of that ranking depends strongly on the validation design. Same-city performance is comparatively strong, 30 m performance in unseen cities is weaker and heterogeneous, and the spatial analysis shows why: spatial predictions are most informative when the feature pattern and underlying urban form match the held-out city’s observed hotspot geography.

## 6. Limitations and Future Work

Several limitations shape how our results should be interpreted. The held-out-city evaluation provides the strongest protection against leakage: entire cities are withheld from training, and preprocessing, imputation, encoding, scaling, and tuning are fit using training cities only. This design gives the clearest test of transfer to unseen cities. However, it does not remove all spatial dependence. Cells within a held-out city can still be spatially clustered, share remote sensing conditions, and produce spatially structured errors.

The sampled transfer benchmark is designed for balanced model comparison rather than full citywide cell-level scoring. The primary AP and recall comparison uses 5,000 sampled rows per city, which preserves equal city weight and a fixed hotspot share but does not represent every detail of each city’s full spatial distribution. Although the spatial analysis scores every eligible held-out row for the random forest maps, the main 30 m retrieval metrics are still based on the sampled benchmark. A useful next step is therefore a full-row held-out-city AP and recall analysis to test whether the sampled ranking patterns hold when every eligible cell in each held-out city is evaluated.

The outcome also limits what the results can claim. The hotspot label is based on ECOSTRESS land surface temperature, not two-meter air temperature or direct human heat exposure. Although the ECOSTRESS valid-pass filter reduces reliance on sparse observations, remaining variation in overpass timing, cloud conditions, and weather during available observations can still affect the May-August LST summary. The city-relative hotspot definition also means that a positive cell is locally hot within its own city, not necessarily equally hot in absolute LST or equally severe for public health risk across cities. The 30 m grid provides a common analytic unit, but not every source variable is natively observed at 30 m. These choices make the dataset suitable for local surface-temperature hotspot modeling, but not for direct claims about national heat exposure, air-temperature risk, or social vulnerability.

External validity is limited by city selection. The 30 cities were chosen to provide a deliberately varied multi-city panel, not a representative sample of all U.S. urban areas. The results should therefore be interpreted as evidence about transfer across this selected city set rather than as national estimates across all climates, coastal settings, urban forms, and topographies.

Future work should extend both sides of the validation contrast. On the same-city side, the single 70/30 split should be replaced with repeated validation within each city. Those folds should keep preprocessing inside each fold and should compare random stratified splits with spatially separated blocks. This would show whether strong same-city performance is stable within a city or sensitive to one split before it is compared with the stricter held-out-city transfer result.

On the transfer side, future models should test richer spatial and climate features without collapsing into memorization of location identity. Raw latitude, longitude, city identifiers, and city names were intentionally excluded here because they can encode place identity rather than portable surface relationships. A future location-aware model should add spatial features deliberately, such as distance to coast, distance to urban core, neighborhood vegetation and imperviousness, surrounding land-cover composition, and spatial or hierarchical model structures. The goal should be to separate portable surface relationships from city-specific spatial effects rather than simply giving the model more ways to recognize place.

Finally, future work should broaden the outcome and spatial evaluation. The all-row spatial analysis in this report uses full eligible held-out rows for random forest maps only; future work should compare spatial alignment metrics across model families, cities, and smoothing scales, with uncertainty summaries where appropriate. The LST hotspot label should also be compared with air temperature, exposure, and vulnerability outcomes where those data are available, because surface-temperature hotspots are only one component of heat risk.

## 7. Conclusion

This project contributes a reproducible 30-city grid dataset and a validation framework for urban heat hotspot modeling. Same-city learning overstates what should be expected in unseen cities: the same public predictors look strong when each city contributes training examples, but performance is much more modest when entire cities are held out. Simple public predictors carry some hotspot ranking information, yet random forest is not a universal solution; its nonlinear gains are selective, with clearer advantages in some hot arid cities than in the full city panel. Additional spatial analysis shows why: random forest can project coherent urban-structure patterns, but those patterns help only when they align with the held-out city’s observed hotspot geography. The main contribution is therefore not a single best model, but an evaluation framework demonstrating that validation design changes the scientific conclusion. Future urban heat modeling should treat local screening, city-to-city transfer, and broader spatial placement as related but distinct tasks.

\newpage

## References

Harlan, S. L., Brazel, A. J., Prashad, L., Stefanov, W. L., & Larsen, L. (2006). Neighborhood microclimates and vulnerability to heat stress. *Social Science & Medicine, 63*(11), 2847-2863. https://doi.org/10.1016/j.socscimed.2006.07.030

Meyer, H., Reudenbach, C., Hengl, T., Katurji, M., & Nauss, T. (2018). Improving performance of spatio-temporal machine learning models using forward feature selection and target-oriented validation. *Environmental Modelling & Software, 101*, 1-9. https://doi.org/10.1016/j.envsoft.2017.12.001

NASA Earthdata. (n.d.). *AppEEARS*. https://www.earthdata.nasa.gov/data/tools/appeears

NASA Earthdata. (n.d.). *ECOSTRESS Swath Land Surface Temperature and Emissivity Instantaneous L2 Global 70 m V002*. https://www.earthdata.nasa.gov/data/catalog/lpcloud-eco-l2-lste-002

NASA Science. (n.d.). *Land Surface Temperature*. https://science.nasa.gov/earth/earth-observatory/global-maps/land surface-temperature/

Roberts, D. R., Bahn, V., Ciuti, S., Boyce, M. S., Elith, J., Guillera-Arroita, G., Hauenstein, S., Lahoz-Monfort, J. J., Schroeder, B., Thuiller, W., Warton, D. I., Wintle, B. A., Hartig, F., & Dormann, C. F. (2017). Cross-validation strategies for data with temporal, spatial, hierarchical, or phylogenetic structure. *Ecography, 40*(8), 913-929. https://doi.org/10.1111/ecog.02881

Stewart, I. D., & Oke, T. R. (2012). Local climate zones for urban temperature studies. *Bulletin of the American Meteorological Society, 93*(12), 1879-1900. https://doi.org/10.1175/BAMS-D-11-00019.1

Voogt, J. A., & Oke, T. R. (2003). Thermal remote sensing of urban climates. *Remote Sensing of Environment, 86*(3), 370-384. https://doi.org/10.1016/S0034-4257(03)00079-8

Weng, Q., Lu, D., & Schubring, J. (2004). Estimation of land surface temperature-vegetation abundance relationship for urban heat island studies. *Remote Sensing of Environment, 89*(4), 467-483. https://doi.org/10.1016/j.rse.2003.11.005

Yuan, F., & Bauer, M. E. (2007). Comparison of impervious surface area and normalized difference vegetation index as indicators of surface urban heat island effects in Landsat imagery. *Remote Sensing of Environment, 106*(3), 375-386. https://doi.org/10.1016/j.rse.2006.09.003

\newpage

## Tables and Figures

Tables and figures are organized here rather than interleaved with the main text. Appendix tables and figures provide additional city, fold, model-specification, and heterogeneity details. Detailed heterogeneity tables are kept in the appendix so the main tables section preserves the core source, dataset, and model results.

### Table 1. Data Sources and Constructed Variables

\begingroup
\footnotesize
\setlength{\tabcolsep}{4.5pt}
\renewcommand{\arraystretch}{1.14}

\begin{tabular}{L{0.18\textwidth}L{0.28\textwidth}L{0.26\textwidth}L{0.18\textwidth}}
\toprule
Source & Product/layer & Constructed variable(s) & Role \\
\midrule
U.S. Census urban areas & 2020 TIGERweb urban-area polygon & Study-area and core-city geometry; 30 m city grid & Study region and grid target \\
NLCD & 2021 land-cover raster & \texttt{land\_cover\_class} & Predictor; open-water filter \\
NLCD & 2021 impervious percentage raster & \texttt{impervious\_pct} & Built-intensity predictor \\
USGS 3DEP & 1 arc-second DEM & \texttt{elevation\_m} & Terrain predictor \\
NHDPlus HR & High-resolution hydrography & \texttt{dist\_to\_water\_m} & Water-proximity predictor \\
MODIS/Terra via AppEEARS & MOD13A1.061 NDVI, May-Aug. 2023 & \texttt{ndvi\_median\_may\_aug} & Vegetation predictor \\
ECOSTRESS via AppEEARS & ECO\_L2T\_LSTE.002 LST, May-Aug. 2023 & \texttt{lst\_median\_may\_aug}; \texttt{n\_valid\_ecostress\_passes}; \texttt{hotspot\_10pct} & Basis for the hotspot label and observation count filter \\
\bottomrule
\end{tabular}

\endgroup

All constructed variables in Table 1 are ultimately summarized to the common 30 m analytic grid. The table lists each source's main role; Section 3 describes the spatial alignment logic and row filters in prose.

### Table 2. Final Dataset Summary by Climate Group

\begingroup
\footnotesize
\setlength{\tabcolsep}{5.2pt}
\renewcommand{\arraystretch}{1.12}

| Climate group | City count | Total rows | Hotspot count | Hotspot prevalence | Min rows | Median rows | Max rows | Median valid passes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Hot arid | 10 | 12,814,143 | 1,281,427 | 0.1000 | 382,964 | 1,100,156 | 3,199,440 | 30.0 |
| Hot humid | 10 | 27,098,157 | 2,709,866 | 0.1000 | 700,063 | 1,788,622 | 7,081,699 | 21.5 |
| Mild cool | 10 | 31,482,594 | 3,148,295 | 0.1000 | 817,627 | 2,889,018 | 6,722,963 | 33.0 |

\endgroup

\newpage

### Table 3. Main Held-Out-City Model Metrics

Rows labeled 5k sampled use the same class stratified per city sample and can be compared directly. With 10% positives, AP values near 0.1000 indicate little useful ranking beyond the no-skill reference.

\begingroup
\small

| Model | Rows/city | Pooled AP | Mean city AP | Recall@top10 | Runtime (min) |
| --- | --- | ---: | ---: | ---: | ---: |
| No-skill reference | 5k sampled | 0.1000 | 0.1000 | 0.1000 | n/a |
| Global mean | 5k sampled | 0.0982 | 0.0997 | 0.0971 | n/a |
| Climate only | 5k sampled | 0.0982 | 0.0997 | 0.0975 | n/a |
| Impervious only | 5k sampled | 0.1351 | 0.1519 | 0.1858 | n/a |
| Land cover only | 5k sampled | 0.1353 | 0.1479 | 0.1672 | n/a |
| Logistic 5k | 5k sampled | 0.1421 | 0.1803 | 0.1647 | 35.6 |
| Logistic 20k | 20k sampled | 0.1457 | 0.1796 | 0.1709 | 156.6 |
| RF 5k | 5k sampled | 0.1486 | 0.1781 | 0.1961 | 97.2 |

\endgroup

Notes: `RF` = random forest. The impervious-only baseline is the strongest simple baseline on recall, and the baseline using land cover alone is the strongest simple baseline on pooled AP. The 5k logistic model is the matched linear comparison for the 5k random forest; the 20k logistic row provides larger-sample logistic context. Runtime is shown only for fitted model runs; the simple baselines are deterministic scoring rules and are marked `n/a` rather than compared with tuned model-fitting time. Small deviations around 0.1000 for near-constant baselines reflect tie handling.

### Figure 1. Study City Locations

![Study City Locations](figures/study_city_points.png){width=\linewidth}

The 30 study cities span western, southern, and northern U.S. regions and are colored by broad climate group. Appendix Table A1 lists full city names, climate groups, row counts, and fold assignments.

### Figure 2. Dataset Construction Workflow

![Dataset Construction Workflow](figures/workflow_overview.png){width=\linewidth}

Figure 2 summarizes the reproducible data construction path from study region definition through feature assembly, final dataset generation, audit, fold creation, and model evaluation. MODIS/Terra NDVI and ECOSTRESS LST enter through AppEEARS and are summarized to the common city grid.

### Figure 3. Held-Out-City Evaluation Design

![Held-Out-City Evaluation Design](figures/evaluation_design.png){width=\linewidth}

Each outer fold holds out six complete cities and trains on the remaining 24 cities. All preprocessing and tuning are fit using training-city rows only, so held-out cities remain unseen until final scoring.

\newpage

### Figure 4. Validation Contrast: Same-City and Held-Out-City Results

![Same-City and Held-Out-City Results Side by Side](figures/within_city_vs_transfer_results.png){width=\linewidth}

Figure 4 contrasts same-city held-out evaluation with held-out-city transfer. Random forest has a large same-city advantage, while 30 m transfer performance in unseen cities is closer between models and only modestly above simple baselines. The panels use different metrics, so the figure shows how the conclusion changes across validation designs rather than a direct point-for-point comparison. The right-panel AP values are average precision scores, not ROC AUC or a trapezoidal area measure. Because the hotspot label is a top decile outcome, the relevant no-skill reference is the approximately 0.10 positive prevalence rather than 0.50.

### Figure 5. Same-City Success Does Not Reliably Predict Transfer Success

![City-Level Signal Shifts Across Evaluation Designs](figures/city_signal_transfer_relationship_labeled.png){width=\linewidth}

Each point is one city. The weak city-level correlations show that stronger same-city random forest performance does not reliably predict stronger held-out-city transfer. The left panel compares same-city RF hotspot F1 with held-out-city AP; the right panel compares same-city RF hotspot recall with held-out-city recall at top 10%.

\newpage

### Figure 6. Held-Out Denver Map Example

![Held-Out Denver Map Example](figures/heldout_denver_map_focus.png){width=\linewidth}

Figure 6 shows held-out Denver from a random forest fold in which Denver was excluded from training. The panels show predicted top-decile cells, observed hotspot cells, and error categories. This map motivates the spatial alignment analysis, but it is a diagnostic example rather than evidence of performance across all cities.

### Figure 7. Medium Scale All City Spatial Alignment Summary

![Medium Scale All City Spatial Alignment Summary](figures/spatial_alignment_medium_summary.png){width=\linewidth}

Figure 7 summarizes broad spatial alignment for random forest predictions at 300 m smoothing. Each point is labeled by city. The x-axis is Spearman correlation between smoothed predicted and observed maps, and the y-axis is observed hotspot mass captured inside predicted top regions. Larger points have greater overlap between predicted and observed top smoothed regions. Nashville is the clearest strong alignment city; San Francisco provides a weak alignment contrast where the predicted map is structured but poorly matched to the observed hotspot map.

\newpage

## Appendix

### Appendix Table A1. City and Fold Composition

\begingroup
\scriptsize
\setlength{\tabcolsep}{3.2pt}
\renewcommand{\arraystretch}{1.06}

\resizebox{\linewidth}{!}{%
\begin{tabular}{rl@{\hspace{10pt}}lrrrr}
\hline
City ID & City & Climate group & Final rows & Hotspot count & Hotspot prev. & Outer fold \\
\hline
1 & Phoenix & Hot arid & 3,199,440 & 319,949 & 0.1000 & 2 \\
2 & Tucson & Hot arid & 1,779,906 & 177,991 & 0.1000 & 0 \\
3 & Las Vegas & Hot arid & 1,718,669 & 171,867 & 0.1000 & 3 \\
4 & Albuquerque & Hot arid & 1,336,755 & 133,676 & 0.1000 & 4 \\
5 & El Paso & Hot arid & 738,527 & 73,853 & 0.1000 & 4 \\
6 & Denver & Hot arid & 1,859,393 & 185,943 & 0.1000 & 1 \\
7 & Salt Lake City & Hot arid & 863,557 & 86,356 & 0.1000 & 1 \\
8 & Fresno & Hot arid & 459,104 & 45,912 & 0.1000 & 1 \\
9 & Bakersfield & Hot arid & 382,964 & 38,297 & 0.1000 & 0 \\
10 & Reno & Hot arid & 475,828 & 47,583 & 0.1000 & 2 \\
11 & Houston & Hot humid & 5,054,661 & 505,468 & 0.1000 & 2 \\
12 & Columbia & Hot humid & 1,055,916 & 105,626 & 0.1000 & 2 \\
13 & Richmond & Hot humid & 1,481,846 & 148,185 & 0.1000 & 0 \\
14 & New Orleans & Hot humid & 700,063 & 70,008 & 0.1000 & 3 \\
15 & Tampa & Hot humid & 2,847,118 & 284,712 & 0.1000 & 0 \\
16 & Miami & Hot humid & 3,635,068 & 363,510 & 0.1000 & 3 \\
17 & Jacksonville & Hot humid & 1,664,542 & 166,458 & 0.1000 & 2 \\
18 & Atlanta & Hot humid & 7,081,699 & 708,171 & 0.1000 & 0 \\
19 & Charlotte & Hot humid & 1,896,996 & 189,703 & 0.1000 & 3 \\
20 & Nashville & Hot humid & 1,680,248 & 168,025 & 0.1000 & 4 \\
21 & Seattle & Mild cool & 2,831,875 & 283,189 & 0.1000 & 2 \\
22 & Portland & Mild cool & 1,496,116 & 149,618 & 0.1000 & 1 \\
23 & San Francisco & Mild cool & 1,466,276 & 146,628 & 0.1000 & 3 \\
24 & San Jose & Mild cool & 817,627 & 81,764 & 0.1000 & 0 \\
25 & Los Angeles & Mild cool & 4,736,063 & 473,607 & 0.1000 & 4 \\
26 & San Diego & Mild cool & 1,948,679 & 194,869 & 0.1000 & 4 \\
27 & Chicago & Mild cool & 6,722,963 & 672,306 & 0.1000 & 1 \\
28 & Minneapolis & Mild cool & 2,946,162 & 294,619 & 0.1000 & 1 \\
29 & Detroit & Mild cool & 3,702,849 & 370,291 & 0.1000 & 4 \\
30 & Boston & Mild cool & 4,813,984 & 481,404 & 0.1000 & 3 \\
\hline
\end{tabular}
}

\endgroup

\newpage

### Appendix Table A2. RF Minus Logistic Performance by Climate Group

Positive deltas mean the random forest performed better than the matched logistic model within that climate group. The table provides climate-group detail for the heterogeneity discussion; Table 3 remains the main model-comparison summary.

\begingroup
\small

| Climate group | Cities | RF AP wins | Logit AP wins | Mean AP delta | RF recall wins | Logit recall wins | Mean recall delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Hot arid | 10 | 5 | 5 | +0.0336 | 6 | 4 | +0.0762 |
| Hot humid | 10 | 2 | 8 | -0.0123 | 2 | 8 | -0.0164 |
| Mild cool | 10 | 2 | 8 | -0.0281 | 1 | 9 | -0.0280 |

\endgroup

### Appendix Table A3. Fold-Level RF Minus Logistic Comparison

R@10 denotes recall among the top 10% highest-risk held-out cells.

\begingroup
\scriptsize

| Fold | Train rows | Test rows | Pos. | Test prev. | Logit AP | RF AP | RF - Logit AP | Logit R@10 | RF R@10 | RF - Logit R@10 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 120,000 | 30,000 | 3,000 | 0.1000 | 0.1610 | 0.1773 | +0.0163 | 0.2170 | 0.2217 | +0.0047 |
| 1 | 120,000 | 30,000 | 3,000 | 0.1000 | 0.2006 | 0.1598 | -0.0408 | 0.2563 | 0.2087 | -0.0477 |
| 2 | 120,000 | 30,000 | 3,000 | 0.1000 | 0.1436 | 0.1301 | -0.0135 | 0.1777 | 0.1443 | -0.0333 |
| 3 | 120,000 | 30,000 | 3,000 | 0.1000 | 0.1267 | 0.1606 | +0.0340 | 0.1463 | 0.2133 | +0.0670 |
| 4 | 120,000 | 30,000 | 3,000 | 0.1000 | 0.1471 | 0.1493 | +0.0022 | 0.1640 | 0.2020 | +0.0380 |

\endgroup

### Appendix Table A4. City-Level Paired RF Minus Logistic Summary

\begingroup
\small

| Metric | Mean delta | Median delta | SD delta | Min delta | Max delta | RF wins | Logistic wins | Ties |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| City AP | -0.0023 | -0.0136 | 0.0602 | -0.0743 | 0.1945 | 9 | 21 | 0 |
| City R@10 | +0.0106 | -0.0150 | 0.0901 | -0.0700 | 0.3420 | 9 | 21 | 0 |

\endgroup

### Appendix Figure A1. Supplemental Same-City Versus Held-Out-City Gap

![Supplemental Same-City Versus Held-Out-City Gap](figures/within_vs_cross_gap.png){width=\linewidth}

Appendix Figure A1 compares same-city minus held-out-city gaps for AP and recall at top 10% predicted risk. The gaps move together strongly, with Pearson correlation 0.95 across the plotted city model points. Reno random forest is the largest gap case; Portland and Detroit logistic regression fall slightly below zero because their retained held-out-city scores are slightly higher than their repeated same-city split scores.

### Appendix Figure A2. Strong and Weak Spatial Alignment Examples

![Strong and Weak Spatial Alignment Examples](figures/selected_spatial_alignment_map_contrast.png){width=\linewidth}

Appendix Figure A2 contrasts a strong and weak 300 m spatial alignment case. Nashville shows predicted high risk regions following much of the observed hotspot geography, while San Francisco shows a coherent predicted pattern that diverges from observed hotspots. The contrast supports the interpretation that poor exact transfer does not always mean spatially incoherent prediction.

### Appendix Figure A3. Supplemental Feature Importance Summary

![Supplemental Feature Importance Summary](figures/feature_importance_ranked_summary.png){width=\linewidth}

Permutation importance and coefficient summaries are included for predictive interpretation only. They are not causal estimates of how changing an urban feature would change LST. NLCD land-cover categories are encoded as categorical levels, so logistic coefficient signs depend on the omitted reference category.

### Appendix B. Supplemental Same-City Modeling Code

The same-city modeling code is maintained in the project repository rather than reproduced in full here. The reference file is `appendix_within_city_code.md`, located under `docs/report/archive/`.

The appendix code builds sklearn pipelines that keep preprocessing inside the model workflow. Imputation, scaling for logistic regression, one-hot encoding, logistic regression, and random forest are fit within the training portion of the split rather than applied to the full dataset in advance. This is the main methodological point: preprocessing must be estimated only from training data to avoid leakage.

\newpage

### Data and Code Availability / Reproducibility Note

The workflow used for this report is maintained in the project repository: <https://github.com/goldember12-alt/urban-heat-mapping-dataset>. The code constructs the 30-city analytic grid, aligns public geospatial and remote sensing inputs, defines the city-relative hotspot label, runs the same-city and held-out-city evaluations, and exports the report tables and figures.

The repository provides the maintained analysis workflow, not a complete bundle of every raw download or generated artifact. Public source products are listed in Table 1 and cited in the References, but full regeneration may require external data acquisition, AppEEARS requests, local storage, and recomputation of generated outputs.

The main held-out-city analysis uses fixed outer city folds, class-stratified sampled rows, and preprocessing and tuning fit only on training cities. The supplemental spatial analysis follows the same held-out-city training rule, then scores every eligible row in the held-out cities for the random forest map summaries.
