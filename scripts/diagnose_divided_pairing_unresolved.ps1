param(
    [string]$OutputRoot = "work/output/roadway_graph"
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$tables = Join-Path $OutputRoot "tables/current"
$review = Join-Path $OutputRoot "review/current"
$geojson = Join-Path $OutputRoot "review/geojson/current"

New-Item -ItemType Directory -Force -Path $review | Out-Null
New-Item -ItemType Directory -Force -Path $geojson | Out-Null

$feetPerMeter = 3.280839895
$sideDistanceToleranceFt = 8.0
$highSideDistanceFt = 16.0
$maxSameLegBearingDiffDeg = 35.0

function Get-RouteStem([string]$value) {
    $text = ($value | ForEach-Object { "$_" }).Trim()
    if (-not $text) { return "" }
    $text = [regex]::Replace($text, "\s+", " ")
    $text = [regex]::Replace($text, "(?:\b|[-_ ])(NB|SB|EB|WB|NORTHBOUND|SOUTHBOUND|EASTBOUND|WESTBOUND)$", "", "IgnoreCase")
    $text = [regex]::Replace($text, "([A-Z]+-\d+)([NSEW])$", '$1', "IgnoreCase")
    $text = [regex]::Replace($text, "([A-Z]+-\d+)(NB|SB|EB|WB)$", '$1', "IgnoreCase")
    return $text.Trim()
}

function Get-WktCoords([string]$wkt) {
    if (-not $wkt) { return @() }
    $open = $wkt.IndexOf("(")
    $close = $wkt.LastIndexOf(")")
    if ($open -lt 0 -or $close -le $open) { return @() }
    $body = $wkt.Substring($open + 1, $close - $open - 1).Trim("() ")
    $coords = @()
    foreach ($part in $body -split ",") {
        $nums = @($part.Trim() -split "\s+" | Where-Object { $_ -ne "" })
        if ($nums.Count -ge 2) {
            $coords += [pscustomobject]@{ X = [double]$nums[0]; Y = [double]$nums[1] }
        }
    }
    return $coords
}

function Get-Bearing($start, $end) {
    if ($null -eq $start -or $null -eq $end) { return $null }
    $dx = [double]$end.X - [double]$start.X
    $dy = [double]$end.Y - [double]$start.Y
    if ($dx -eq 0 -and $dy -eq 0) { return $null }
    return ([math]::Atan2($dx, $dy) * 180.0 / [math]::PI + 360.0) % 360.0
}

function Get-AngularDiff([double]$a, [double]$b) {
    $diff = [math]::Abs($a - $b) % 360.0
    return [math]::Min($diff, 360.0 - $diff)
}

function Get-LineMidpoint($coords) {
    if ($coords.Count -eq 0) { return $null }
    if ($coords.Count -eq 1) { return $coords[0] }
    $lengths = @()
    $total = 0.0
    for ($i = 0; $i -lt $coords.Count - 1; $i++) {
        $dx = [double]$coords[$i + 1].X - [double]$coords[$i].X
        $dy = [double]$coords[$i + 1].Y - [double]$coords[$i].Y
        $seg = [math]::Sqrt($dx * $dx + $dy * $dy)
        $lengths += $seg
        $total += $seg
    }
    if ($total -eq 0) { return $coords[0] }
    $target = $total / 2.0
    $walk = 0.0
    for ($i = 0; $i -lt $lengths.Count; $i++) {
        $seg = [double]$lengths[$i]
        if (($walk + $seg) -ge $target) {
            $ratio = if ($seg -eq 0) { 0 } else { ($target - $walk) / $seg }
            return [pscustomobject]@{
                X = [double]$coords[$i].X + ([double]$coords[$i + 1].X - [double]$coords[$i].X) * $ratio
                Y = [double]$coords[$i].Y + ([double]$coords[$i + 1].Y - [double]$coords[$i].Y) * $ratio
            }
        }
        $walk += $seg
    }
    return $coords[$coords.Count - 1]
}

function Get-SideOfReference($referenceStart, $referenceEnd, $point) {
    $vx = [double]$referenceEnd.X - [double]$referenceStart.X
    $vy = [double]$referenceEnd.Y - [double]$referenceStart.Y
    $wx = [double]$point.X - [double]$referenceStart.X
    $wy = [double]$point.Y - [double]$referenceStart.Y
    $length = [math]::Sqrt($vx * $vx + $vy * $vy)
    if ($length -eq 0) {
        return [pscustomobject]@{ Side = "ambiguous"; DistanceFt = 0.0 }
    }
    $signed = $vx * $wy - $vy * $wx
    $distanceFt = [math]::Abs($signed) / $length * $feetPerMeter
    if ($distanceFt -le $sideDistanceToleranceFt) {
        return [pscustomobject]@{ Side = "center"; DistanceFt = $distanceFt }
    }
    $side = if ($signed -gt 0) { "left" } else { "right" }
    return [pscustomobject]@{ Side = $side; DistanceFt = $distanceFt }
}

function Get-LineSignature($coords) {
    if ($coords.Count -lt 2) { return "" }
    $a = $coords[0]
    $b = $coords[$coords.Count - 1]
    return "{0:n2},{1:n2}|{2:n2},{3:n2}" -f $a.X, $a.Y, $b.X, $b.Y
}

function Evaluate-Pair($a, $b) {
    if ($null -eq $a.start_xy -or $null -eq $a.end_xy -or $null -eq $b.start_xy -or $null -eq $b.end_xy -or $null -eq $a.segment_bearing -or $null -eq $b.segment_bearing) {
        return [pscustomobject]@{ Status = "unresolved"; Reason = "invalid_or_empty_geometry"; Score = 0.0 }
    }
    $bearingDiff = Get-AngularDiff ([double]$a.segment_bearing) ([double]$b.segment_bearing)
    if ($bearingDiff -gt $maxSameLegBearingDiffDeg) {
        return [pscustomobject]@{ Status = "unresolved"; Reason = "not_same_leg_bearing"; BearingDiff = $bearingDiff; Score = 0.0 }
    }
    if ($a.base_graph_edge_id -eq $b.base_graph_edge_id) {
        return [pscustomobject]@{ Status = "unresolved"; Reason = "same_base_graph_edge"; BearingDiff = $bearingDiff; Score = 0.0 }
    }
    if ($a.road_component_id -eq $b.road_component_id) {
        return [pscustomobject]@{ Status = "unresolved"; Reason = "same_road_component"; BearingDiff = $bearingDiff; Score = 0.0 }
    }
    if ($a.line_signature -eq $b.line_signature) {
        return [pscustomobject]@{ Status = "unresolved"; Reason = "same_physical_geometry_signature"; BearingDiff = $bearingDiff; Score = 0.0 }
    }

    $referenceStart = [pscustomobject]@{ X = ($a.start_xy.X + $b.start_xy.X) / 2.0; Y = ($a.start_xy.Y + $b.start_xy.Y) / 2.0 }
    $referenceEnd = [pscustomobject]@{ X = ($a.end_xy.X + $b.end_xy.X) / 2.0; Y = ($a.end_xy.Y + $b.end_xy.Y) / 2.0 }
    $referenceBearing = Get-Bearing $referenceStart $referenceEnd
    if ($null -eq $referenceBearing) {
        return [pscustomobject]@{ Status = "unresolved"; Reason = "zero_length_reference_vector"; BearingDiff = $bearingDiff; Score = 0.0 }
    }
    if ($null -eq $a.midpoint_xy -or $null -eq $b.midpoint_xy) {
        return [pscustomobject]@{ Status = "unresolved"; Reason = "invalid_midpoint_geometry"; BearingDiff = $bearingDiff; Score = 0.0 }
    }
    $sideA = Get-SideOfReference $referenceStart $referenceEnd $a.midpoint_xy
    $sideB = Get-SideOfReference $referenceStart $referenceEnd $b.midpoint_xy
    $score = [math]::Min([double]$sideA.DistanceFt, [double]$sideB.DistanceFt)
    $sides = @($sideA.Side, $sideB.Side)
    if (-not ($sides -contains "left" -and $sides -contains "right")) {
        $reason = if ($sides -contains "center") { "side_assignment_near_centerline" } else { "candidate_geometries_do_not_bracket_reference" }
        return [pscustomobject]@{
            Status = "ambiguous"; Reason = $reason; BearingDiff = $bearingDiff; Score = $score
            DistanceA = $sideA.DistanceFt; DistanceB = $sideB.DistanceFt; ReferenceBearing = $referenceBearing
        }
    }
    $confidence = if ($score -ge $highSideDistanceFt -and $bearingDiff -le 20.0) { "high" } elseif ($score -gt $sideDistanceToleranceFt) { "medium" } else { "low" }
    return [pscustomobject]@{
        Status = "paired"; Reason = ""; BearingDiff = $bearingDiff; Score = $score
        DistanceA = $sideA.DistanceFt; DistanceB = $sideB.DistanceFt; ReferenceBearing = $referenceBearing
        Confidence = $confidence
    }
}

function Get-LengthBand([double]$lengthFt) {
    if ($lengthFt -lt 100) { return "000_lt_100" }
    if ($lengthFt -lt 250) { return "100_249" }
    if ($lengthFt -lt 500) { return "250_499" }
    if ($lengthFt -lt 1000) { return "500_999" }
    if ($lengthFt -lt 2500) { return "1000_2499" }
    return "2500_plus"
}

function Write-Csv($rows, [string]$path) {
    @($rows) | Export-Csv -Path $path -NoTypeInformation -Encoding UTF8
}

$enriched = Import-Csv (Join-Path $tables "signal_oriented_roadway_segments_divided_pairing_enriched.csv")
$edges = Import-Csv (Join-Path $tables "roadway_graph_edges.csv")
$pairs = Import-Csv (Join-Path $tables "divided_carriageway_pair_candidates.csv")

$edgeById = @{}
foreach ($edge in $edges) {
    $edgeById[$edge.graph_edge_id] = $edge
}

$divided = @()
foreach ($row in $enriched) {
    if ($row.roadway_directionality_type -ne "divided") { continue }
    $coords = Get-WktCoords $row.geometry
    $edge = $edgeById[$row.base_graph_edge_id]
    $start = if ($coords.Count -ge 2) { $coords[0] } else { $null }
    $end = if ($coords.Count -ge 2) { $coords[$coords.Count - 1] } else { $null }
    $row | Add-Member -NotePropertyName route_pair_stem -NotePropertyValue (Get-RouteStem $row.route_common) -Force
    $row | Add-Member -NotePropertyName coords -NotePropertyValue $coords -Force
    $row | Add-Member -NotePropertyName start_xy -NotePropertyValue $start -Force
    $row | Add-Member -NotePropertyName end_xy -NotePropertyValue $end -Force
    $row | Add-Member -NotePropertyName midpoint_xy -NotePropertyValue (Get-LineMidpoint $coords) -Force
    $row | Add-Member -NotePropertyName segment_bearing -NotePropertyValue (Get-Bearing $start $end) -Force
    $row | Add-Member -NotePropertyName line_signature -NotePropertyValue (Get-LineSignature $coords) -Force
    $row | Add-Member -NotePropertyName length_band -NotePropertyValue (Get-LengthBand ([double]$row.length_ft)) -Force
    $row | Add-Member -NotePropertyName facility_text -NotePropertyValue $(if ($edge) { $edge.facility_text } else { "" }) -Force
    $row | Add-Member -NotePropertyName median_text -NotePropertyValue $(if ($edge) { $edge.median_text } else { "" }) -Force
    $row | Add-Member -NotePropertyName rte_category -NotePropertyValue $(if ($edge) { $edge.rte_category } else { "" }) -Force
    $row | Add-Member -NotePropertyName rte_type_name -NotePropertyValue $(if ($edge) { $edge.rte_type_name } else { "" }) -Force
    $row | Add-Member -NotePropertyName rte_ramp_code -NotePropertyValue $(if ($edge) { $edge.rte_ramp_code } else { "" }) -Force
    $divided += $row
}

$groupBySignalRoute = @{}
$groupBySignal = @{}
foreach ($row in $divided) {
    $key = "$($row.reference_signal_id)||$($row.route_pair_stem)"
    if (-not $groupBySignalRoute.ContainsKey($key)) { $groupBySignalRoute[$key] = @() }
    $groupBySignalRoute[$key] += $row
    $sigKey = "$($row.reference_signal_id)"
    if (-not $groupBySignal.ContainsKey($sigKey)) { $groupBySignal[$sigKey] = @() }
    $groupBySignal[$sigKey] += $row
}

$diagnosed = @()
foreach ($row in ($divided | Where-Object { $_.divided_pairing_status -eq "unpaired" })) {
    $key = "$($row.reference_signal_id)||$($row.route_pair_stem)"
    $sameGroup = @($groupBySignalRoute[$key] | Where-Object { $_.oriented_segment_id -ne $row.oriented_segment_id })
    $sameSignalDifferentStem = @($groupBySignal[$row.reference_signal_id] | Where-Object { $_.oriented_segment_id -ne $row.oriented_segment_id -and $_.route_pair_stem -ne $row.route_pair_stem })

    $bestPaired = $null
    $bestAmbiguous = $null
    $reasonCounts = @{}
    foreach ($candidate in $sameGroup) {
        $eval = Evaluate-Pair $row $candidate
        if (-not $reasonCounts.ContainsKey($eval.Reason)) { $reasonCounts[$eval.Reason] = 0 }
        $reasonCounts[$eval.Reason] += 1
        if ($eval.Status -eq "paired") {
            if ($null -eq $bestPaired -or $eval.Score -gt $bestPaired.Score) {
                $bestPaired = [pscustomobject]@{ Candidate = $candidate; Eval = $eval; Score = $eval.Score }
            }
        } elseif ($eval.Status -eq "ambiguous") {
            if ($null -eq $bestAmbiguous -or $eval.Score -gt $bestAmbiguous.Score) {
                $bestAmbiguous = [pscustomobject]@{ Candidate = $candidate; Eval = $eval; Score = $eval.Score }
            }
        }
    }

    $bestDifferentStem = $null
    foreach ($candidate in $sameSignalDifferentStem) {
        $eval = Evaluate-Pair $row $candidate
        if ($eval.Status -in @("paired", "ambiguous")) {
            if ($null -eq $bestDifferentStem -or $eval.Score -gt $bestDifferentStem.Score) {
                $bestDifferentStem = [pscustomobject]@{ Candidate = $candidate; Eval = $eval; Score = $eval.Score }
            }
        }
    }

    $routeText = "$($row.route_name) $($row.route_common)"
    $possibleAux = $routeText -match "(?i)\b(ramp|frontage|service|collector|distributor|connector|cd road|flyover|spur)\b" -or "$($row.rte_ramp_code)" -ne ""
    $questionableDivided = "$($row.facility_text)" -match "(?i)one-way divided" -or "$($row.median_text)" -match "(?i)no median"
    $shortFragment = ([double]$row.length_ft -lt 100.0)

    $reason = "unknown_unresolved"
    $methodClass = "unknown"
    $possiblePairId = ""
    $pairScore = ""
    $candidateStatus = ""
    $candidateRoute = ""
    $candidateFamily = ""
    $candidatePairingStatus = ""
    $diagnosticNote = ""

    if ($null -ne $bestPaired) {
        $possiblePairId = $bestPaired.Candidate.oriented_segment_id
        $pairScore = [math]::Round([double]$bestPaired.Score, 3)
        $candidateStatus = "paired_candidate_found_in_same_reference_signal_route_stem"
        $candidateRoute = $bestPaired.Candidate.route_common
        $candidateFamily = $bestPaired.Candidate.segment_family_id
        $candidatePairingStatus = $bestPaired.Candidate.divided_pairing_status
        if ($bestPaired.Candidate.segment_family_id -ne $row.segment_family_id) {
            $reason = "opposite_carriageway_exists_but_not_same_segment_family"
        } else {
            $reason = "opposite_carriageway_exists_but_anchor_mismatch"
        }
        $methodClass = "possible_pairing_logic_improvement"
        $diagnosticNote = "A same-reference/same-route-stem candidate passes the geometric pair test, but the row remained unpaired, usually because the one-to-one greedy pass assigned the candidate elsewhere or the local anchor geometry is fragmented."
    } elseif ($null -ne $bestAmbiguous) {
        $possiblePairId = $bestAmbiguous.Candidate.oriented_segment_id
        $pairScore = [math]::Round([double]$bestAmbiguous.Score, 3)
        $candidateStatus = "ambiguous_candidate_found_in_same_reference_signal_route_stem"
        $candidateRoute = $bestAmbiguous.Candidate.route_common
        $candidateFamily = $bestAmbiguous.Candidate.segment_family_id
        $candidatePairingStatus = $bestAmbiguous.Candidate.divided_pairing_status
        $reason = "opposite_carriageway_exists_but_side_score_ambiguous"
        $methodClass = "possible_pairing_logic_improvement"
        $diagnosticNote = "A nearby candidate has similar bearing and distinct component geometry but does not clearly bracket the reference axis."
    } elseif ($null -ne $bestDifferentStem) {
        $possiblePairId = $bestDifferentStem.Candidate.oriented_segment_id
        $pairScore = [math]::Round([double]$bestDifferentStem.Score, 3)
        $candidateStatus = "candidate_found_same_reference_signal_different_route_stem"
        $candidateRoute = $bestDifferentStem.Candidate.route_common
        $candidateFamily = $bestDifferentStem.Candidate.segment_family_id
        $candidatePairingStatus = $bestDifferentStem.Candidate.divided_pairing_status
        $reason = "pair_search_threshold_too_strict"
        $methodClass = "possible_pairing_logic_improvement"
        $diagnosticNote = "A same-reference signal candidate appears only if the route-stem grouping is relaxed."
    } elseif ($row.opposite_anchor_type -eq "road_endpoint_dead_end") {
        $reason = "endpoint_or_one_sided_graph_edge"
        $methodClass = "acceptable_methodological_exclusion"
        $diagnosticNote = "The segment terminates at a source graph endpoint, so a reciprocal TRUE signal-centered carriageway should not be forced."
    } elseif ($row.missing_reciprocal_reason -eq "opposite_signal_not_true_reference_but_valid_boundary") {
        $reason = "opposite_carriageway_not_in_crash_ready_subset"
        $methodClass = "acceptable_methodological_exclusion"
        $diagnosticNote = "The opposite signal boundary is valid but is not a TRUE Step 5 reference signal under the current scope."
    } elseif ($row.missing_reciprocal_reason -eq "opposite_anchor_is_non_signal_or_endpoint_boundary") {
        $reason = "source_travelway_missing_opposite_carriageway"
        $methodClass = "source_or_scope_limitation"
        $diagnosticNote = "The row ends at a non-signal/endpoint boundary and no clear same-scope opposite carriageway was found."
    } elseif ($possibleAux) {
        $reason = "ramp_or_frontage_or_auxiliary_road_possible"
        $methodClass = "acceptable_methodological_exclusion"
        $diagnosticNote = "Route text or route metadata suggests an auxiliary facility where same-route carriageway pairing may be inappropriate."
    } elseif ($shortFragment) {
        $reason = "geometry_too_short_or_fragmented"
        $methodClass = "source_or_scope_limitation"
        $diagnosticNote = "The segment is shorter than 100 ft and may be too fragmented for reliable bracketing."
    } elseif ($questionableDivided) {
        $reason = "divided_classification_questionable"
        $methodClass = "source_or_scope_limitation"
        $diagnosticNote = "The source facility/median attributes do not look like a normal two-way divided carriageway pair."
    }

    $row | Add-Member -NotePropertyName unpaired_reason -NotePropertyValue $reason -Force
    $row | Add-Member -NotePropertyName methodological_class -NotePropertyValue $methodClass -Force
    $row | Add-Member -NotePropertyName possible_pair_candidate_id -NotePropertyValue $possiblePairId -Force
    $row | Add-Member -NotePropertyName pair_distance_or_side_score -NotePropertyValue $pairScore -Force
    $row | Add-Member -NotePropertyName possible_pair_candidate_status -NotePropertyValue $candidateStatus -Force
    $row | Add-Member -NotePropertyName possible_pair_candidate_route_common -NotePropertyValue $candidateRoute -Force
    $row | Add-Member -NotePropertyName possible_pair_candidate_segment_family_id -NotePropertyValue $candidateFamily -Force
    $row | Add-Member -NotePropertyName possible_pair_candidate_current_pairing_status -NotePropertyValue $candidatePairingStatus -Force
    $row | Add-Member -NotePropertyName same_reference_route_stem_candidate_count -NotePropertyValue $sameGroup.Count -Force
    $row | Add-Member -NotePropertyName same_reference_different_route_stem_candidate_count -NotePropertyValue $sameSignalDifferentStem.Count -Force
    $row | Add-Member -NotePropertyName diagnostic_note -NotePropertyValue $diagnosticNote -Force
    $diagnosed += $row
}

$totalUnpaired = @($diagnosed).Count
$reasonSummary = $diagnosed |
    Group-Object unpaired_reason, methodological_class |
    ForEach-Object {
        $parts = $_.Name -split ", "
        [pscustomobject]@{
            unpaired_reason = $parts[0]
            methodological_class = $parts[1]
            unpaired_rows = $_.Count
            percent_of_unpaired = [math]::Round(100.0 * $_.Count / $totalUnpaired, 2)
            diagnostic_basis = (@($_.Group | Select-Object -ExpandProperty diagnostic_note -Unique) -join " | ")
        }
    } | Sort-Object unpaired_rows -Descending

Write-Csv $reasonSummary (Join-Path $review "divided_pairing_unresolved_reason_summary.csv")

$byAnchor = $diagnosed |
    Group-Object opposite_anchor_type, unpaired_reason |
    ForEach-Object {
        $parts = $_.Name -split ", "
        [pscustomobject]@{
            opposite_anchor_type = $parts[0]
            unpaired_reason = $parts[1]
            unpaired_rows = $_.Count
        }
    } | Sort-Object opposite_anchor_type, unpaired_rows -Descending
Write-Csv $byAnchor (Join-Path $review "divided_pairing_unresolved_by_anchor_type.csv")

$pairedRouteCounts = @{}
foreach ($row in ($divided | Where-Object { $_.divided_pairing_status -eq "paired" })) {
    $key = "$($row.route_common)||$($row.route_pair_stem)"
    if (-not $pairedRouteCounts.ContainsKey($key)) { $pairedRouteCounts[$key] = 0 }
    $pairedRouteCounts[$key] += 1
}
$byRoute = $diagnosed |
    Group-Object route_common, route_pair_stem |
    ForEach-Object {
        $parts = $_.Name -split ", "
        $routeCommon = $parts[0]
        $stem = if ($parts.Count -gt 1) { $parts[1] } else { "" }
        $key = "$routeCommon||$stem"
        $topReason = $_.Group | Group-Object unpaired_reason | Sort-Object Count -Descending | Select-Object -First 1
        $pairedRows = if ($pairedRouteCounts.ContainsKey($key)) { $pairedRouteCounts[$key] } else { 0 }
        [pscustomobject]@{
            route_common = $routeCommon
            route_pair_stem = $stem
            unpaired_rows = $_.Count
            paired_rows = $pairedRows
            divided_rows = $_.Count + $pairedRows
            unpaired_percent_on_route = [math]::Round(100.0 * $_.Count / ($_.Count + $pairedRows), 2)
            top_unpaired_reason = $topReason.Name
            top_unpaired_reason_rows = $topReason.Count
            facility_text_values = (@($_.Group | Select-Object -ExpandProperty facility_text -Unique) -join " | ")
            median_text_values = (@($_.Group | Select-Object -ExpandProperty median_text -Unique) -join " | ")
            rte_category_values = (@($_.Group | Select-Object -ExpandProperty rte_category -Unique) -join " | ")
        }
    } | Sort-Object unpaired_rows -Descending
Write-Csv $byRoute (Join-Path $review "divided_pairing_unresolved_by_route.csv")

$allLength = $divided |
    Group-Object length_band, divided_pairing_status |
    ForEach-Object {
        $parts = $_.Name -split ", "
        [pscustomobject]@{
            length_band = $parts[0]
            divided_pairing_status = $parts[1]
            rows = $_.Count
            average_length_ft = [math]::Round((($_.Group | ForEach-Object { [double]$_.length_ft }) | Measure-Object -Average).Average, 2)
            median_length_ft_note = "PowerShell summary reports average; see diagnosis doc for interpretation."
        }
    } | Sort-Object length_band, divided_pairing_status
Write-Csv $allLength (Join-Path $review "divided_pairing_unresolved_by_length_band.csv")

$byRefStatus = $diagnosed |
    Group-Object reference_signal_step5_status, opposite_anchor_step5_status, missing_reciprocal_reason, unpaired_reason |
    ForEach-Object {
        $parts = $_.Name -split ", "
        [pscustomobject]@{
            reference_signal_step5_status = $parts[0]
            opposite_anchor_step5_status = if ($parts.Count -gt 1) { $parts[1] } else { "" }
            missing_reciprocal_reason = if ($parts.Count -gt 2) { $parts[2] } else { "" }
            unpaired_reason = if ($parts.Count -gt 3) { $parts[3] } else { "" }
            unpaired_rows = $_.Count
        }
    } | Sort-Object unpaired_rows -Descending
Write-Csv $byRefStatus (Join-Path $review "divided_pairing_unresolved_by_reference_signal_status.csv")

$logicRows = @(
    [pscustomobject]@{
        possible_improvement = "review_same_reference_same_route_candidate_conflicts"
        affected_unpaired_rows = @($diagnosed | Where-Object { $_.possible_pair_candidate_status -eq "paired_candidate_found_in_same_reference_signal_route_stem" }).Count
        evidence = "Rows have a same-reference/same-route-stem candidate that passes the diagnostic geometric pair test but remained unpaired."
        risk = "A broader or non-greedy matcher could recover rows, but may create many-to-one or wrong-anchor pairings without manual review."
        recommendation = "Review QGIS sample before changing one-to-one assignment."
    },
    [pscustomobject]@{
        possible_improvement = "review_ambiguous_side_score_candidates"
        affected_unpaired_rows = @($diagnosed | Where-Object { $_.unpaired_reason -eq "opposite_carriageway_exists_but_side_score_ambiguous" }).Count
        evidence = "Rows have candidates with similar bearing and distinct component geometry, but the side/bracketing score is near-center or non-bracketing."
        risk = "Relaxing side thresholds can pair adjacent lanes, ramps, or geometry fragments as false opposites."
        recommendation = "Use road centerline/reference-axis support or manual review before relaxing side thresholds."
    },
    [pscustomobject]@{
        possible_improvement = "relax_route_stem_grouping_with_same_reference_signal"
        affected_unpaired_rows = @($diagnosed | Where-Object { $_.unpaired_reason -eq "pair_search_threshold_too_strict" }).Count
        evidence = "Rows have candidates only when same-reference signal search is allowed across different route stems."
        risk = "Route-stem relaxation can cross-pair ramp, frontage, service, or cross-street geometry."
        recommendation = "Only test as a bounded same-reference + similar-bearing + centerline-axis rule."
    },
    [pscustomobject]@{
        possible_improvement = "source_travelway_opposite_geometry_review"
        affected_unpaired_rows = @($diagnosed | Where-Object { $_.unpaired_reason -eq "source_travelway_missing_opposite_carriageway" }).Count
        evidence = "Rows end at non-signal/endpoint boundaries and lack a clear opposite candidate in the crash-ready pairing group."
        risk = "Code cannot recover a carriageway that is absent or fragmented in source geometry."
        recommendation = "Inspect Travelway/source graph before expanding pairing logic."
    },
    [pscustomobject]@{
        possible_improvement = "endpoint_methodological_exclusion_documentation"
        affected_unpaired_rows = @($diagnosed | Where-Object { $_.unpaired_reason -eq "endpoint_or_one_sided_graph_edge" }).Count
        evidence = "Rows terminate at graph endpoints/dead ends."
        risk = "Forcing reciprocal pairs at endpoints would invent unsupported directionality."
        recommendation = "Keep unresolved unless manual/source-data review finds a missing carriageway."
    }
)
Write-Csv $logicRows (Join-Path $review "divided_pairing_unresolved_possible_logic_improvements.csv")

$sampleSpecs = @(
    @{ Group = "acceptable_endpoint_or_one_sided"; Reason = "endpoint_or_one_sided_graph_edge"; Limit = 10 },
    @{ Group = "likely_missing_travelway_opposite"; Reason = "source_travelway_missing_opposite_carriageway"; Limit = 10 },
    @{ Group = "likely_pairable_but_not_grouped"; Reason = "pair_search_threshold_too_strict"; Limit = 10 },
    @{ Group = "ambiguous_side_score"; Reason = "opposite_carriageway_exists_but_side_score_ambiguous"; Limit = 10 },
    @{ Group = "possible_divided_false_positive"; Reason = "divided_classification_questionable"; Limit = 10 }
)
$sample = @()
foreach ($spec in $sampleSpecs) {
    $rows = @($diagnosed | Where-Object { $_.unpaired_reason -eq $spec.Reason } | Sort-Object route_common, reference_signal_id | Select-Object -First $spec.Limit)
    foreach ($row in $rows) {
        $sample += [pscustomobject]@{
            review_group = $spec.Group
            oriented_segment_id = $row.oriented_segment_id
            segment_family_id = $row.segment_family_id
            reference_signal_id = $row.reference_signal_id
            from_anchor_id = $row.from_anchor_id
            to_anchor_id = $row.to_anchor_id
            opposite_anchor_type = $row.opposite_anchor_type
            route_name = $row.route_name
            route_common = $row.route_common
            route_id = $row.route_id
            road_component_id = $row.road_component_id
            facility_text = $row.facility_text
            median_text = $row.median_text
            length_ft = $row.length_ft
            unpaired_reason = $row.unpaired_reason
            possible_pair_candidate_id = $row.possible_pair_candidate_id
            possible_pair_candidate_route_common = $row.possible_pair_candidate_route_common
            pair_distance_or_side_score = $row.pair_distance_or_side_score
            manual_review_status = ""
            notes = ""
            geometry = $row.geometry
        }
    }
}
Write-Csv $sample (Join-Path $review "divided_pairing_unresolved_manual_review_sample.csv")

$features = @()
foreach ($row in $sample) {
    $coords = Get-WktCoords $row.geometry
    $coordText = (($coords | ForEach-Object { "[{0},{1}]" -f ([double]$_.X), ([double]$_.Y) }) -join ",")
    $props = [ordered]@{}
    foreach ($prop in @("review_group","oriented_segment_id","segment_family_id","reference_signal_id","from_anchor_id","to_anchor_id","opposite_anchor_type","route_name","route_common","route_id","road_component_id","facility_text","median_text","length_ft","unpaired_reason","possible_pair_candidate_id","possible_pair_candidate_route_common","pair_distance_or_side_score","manual_review_status","notes")) {
        $props[$prop] = "$($row.$prop)"
    }
    $propsJson = $props | ConvertTo-Json -Compress
    $features += "{""type"":""Feature"",""properties"":$propsJson,""geometry"":{""type"":""LineString"",""coordinates"":[$coordText]}}"
}
$geojsonText = "{""type"":""FeatureCollection"",""features"":[$($features -join ',')]}"
Set-Content -Path (Join-Path $geojson "divided_pairing_unresolved_manual_review_sample.geojson") -Value $geojsonText -Encoding UTF8

Write-Host "Wrote divided pairing unresolved diagnosis outputs under $review and $geojson"
