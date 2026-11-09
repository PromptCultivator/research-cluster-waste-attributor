# Handoff Report — Spec Miner 2: Attribution, Recommendations, Guardrails, Simulator, Calibration

## 1. Observation

Authoritative specification sources investigated:
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/ORIGINAL_REQUEST.md`

Direct observations and citations from `docs/SPEC.md`:

1. **Waste Attribution & Conservation Partition (Section 6.1, lines 146-157)**:
   - "For each job, partition `reserved_core_s` and `reserved_mem_mb_s` with this precedence, applied once, so that no second of reservation lands in two classes:
     1. Class 3, failed and retried work: if `state in {FAILED, TIMEOUT, OUT_OF_MEMORY, NODE_FAIL, PREEMPTED}` or (`CANCELLED` and `run_s > 0`), the job's entire reservation in both dimensions is class 3. Sub-labels: `oom`, `timeout`, `early_failure` (run_s ≤ 60), `other_failure`, `cancelled_after_start`, `node_fail`. Retry chains: a later job by the same user with the same `command_hash` (or `job_name` when no hash) submitted within `retry_window` (default 24 h) after a failed job is marked `retry_of`; the chain's total cost is reported, and the retried job itself is attributed normally.
     2. Class 4, redundant recomputation: if `state = COMPLETED` and another `COMPLETED` job with the same `(command_hash, input_hash)` ended earlier within `recompute_window` (default 30 days), the later job's entire reservation in both dimensions is class 4 (`confidence = declared_inputs`). When `input_hash` is missing and only `command_hash` matches, the job is listed under `possible_recompute` with `confidence = command_only` and is NOT counted in class 4 totals.
     3. Class 2, idle reserved CPU (core dimension): `idle_core_s = max(0, reserved_core_s − cpu_time_used_s)`; `used_core_s = reserved_core_s − idle_core_s`. If `cpu_time_used_s` is null, the job's core reservation is labeled `unattributed_missing_cpu_time` and counted in coverage, not in class 2.
     4. Class 1, memory over-request (memory dimension): `over_mem_mb_s = max(0, req_mem_mb − max_rss_mb) × run_s`; `used_mem_mb_s = reserved_mem_mb_s − over_mem_mb_s`. Null `max_rss_mb` → `unattributed_missing_rss`."
   - "G1 test: for every job and each dimension, `reserved = used + class1_or_2 + class3 + class4 + unattributed` exactly, in integer seconds and MB-seconds. Totals in the report are sums of these per-job values; a test recomputes the totals from the per-job table." (lines 156-157).
   - "Rows with `state in {RUNNING, PENDING}` are excluded from attribution and counted in the report's data-quality section. Rows with `run_s = 0` are kept (early failures) and attributed to class 3 with zero consumption." (lines 130-131).
   - "SWF has no declared inputs, so recomputation attribution is reported as 'not available' for SWF traces, never estimated." (lines 110-111).

2. **Ranked Reclaim List (Section 6.2, lines 159-162 & Section 5.4, lines 132-135)**:
   - "For each group: reserved and used core-hours and GB-hours; waste per class; share of cluster total; recommended action (section 7); confidence; evidence (five job ids with the largest waste). Sorted by reclaimable core-hours plus a configurable memory weight (`mem_weight_core_hours_per_gb_hour`, default from the cluster spec's core-to-memory ratio). Also roll-ups by user, account, partition." (lines 160-162).
   - "A group key is configurable in the policy; default `(user, command_hash or job_name)`. Secondary roll-ups by `account` and `partition`. Groups below `min_samples` (default 5) receive no recommendation." (lines 133-135).

3. **Recommendations with Guardrails (Section 7, lines 159-171 & Section 3, lines 41-42)**:
   - "Memory: recommended `req_mem_mb = ceil(p99(max_rss_mb over the group's COMPLETED jobs) × safety_factor)` with `safety_factor` default 1.2; never below `max(max_rss_mb)` observed in the group across all states; if any job in the group has `state = OUT_OF_MEMORY` in the window, the recommendation direction is `increase` to `ceil(max observed × 1.5)` and the group is excluded from reclaimable memory totals." (lines 161-162).
   - "CPU: recommended `cpus = clamp(ceil(p99(cpu_time_used_s / run_s) × safety_factor), 1, alloc_cpus)`; groups whose jobs have `run_s < 120` get no CPU recommendation (utilization is unreliable on short jobs)." (lines 163-164).
   - "Timeouts: recommend `time_limit = ceil(p99(run_s of COMPLETED jobs) × 1.5)` for groups with timeouts." (line 165).
   - "Early failures: no resource recommendation; the report lists the group with its failure share and sample exit codes." (line 166).
   - "Recomputation: recommend a result cache keyed by `(command_hash, input_hash)` for groups where class 4 exceeds a threshold; report the hit rate the cache would have had." (lines 167-168).
   - "G2 tests: for randomly generated groups (Hypothesis), the memory recommendation is never below the observed maximum times the safety factor; OOM groups never receive a decrease; groups below `min_samples` receive nothing." (lines 170-171).
   - "Phase 3 acceptance: Hypothesis finds no guardrail violation in 10,000 generated groups." (line 256).

4. **Scheduler Simulator & Calibration (Section 8, lines 169-179 & Section 3, lines 41-43)**:
   - "Model: a cluster of `N` identical nodes with `cores_per_node` and `mem_mb_per_node` (from `clusters/<name>.yaml`, or inferred from the trace as the maximum allocation seen, with the inference reported). Jobs arrive at `submit_time`, request `(cpus, mem_mb, nodes)`, and run for `run_s`. Scheduling: FCFS with EASY backfill (a later job may start early if it does not delay the first queued job's reservation), using the trace's `requested time` when present and `run_s × 1.2` otherwise. Deterministic: ties broken by `(submit_time, job_id)`; no randomness." (lines 170-172).
   - "Scenarios, each a full replay: `baseline` (original requests); `mem_rightsized`; `cpu_rightsized` under two runtime models, `none` (runtime unchanged) and `proportional` (runtime scales by `old_cpus / new_cpus` when the job's measured utilization exceeded the new allocation); `cache_dedup` (class 4 jobs removed); `all`. Each scenario reports median and p95 wait, makespan, core and memory utilization, and jobs completed per simulated day." (lines 173-175).
   - "Calibration (`rcwa calibrate`): run `baseline` on a real trace and compare simulated wait per job with the trace's recorded wait. Report median absolute error and the Spearman correlation. The README states the calibration error next to every scenario result, because a scenario delta is only as trustworthy as the baseline fit." (lines 176-177).
   - "G4 tests: every job appears once in every scenario's schedule; `sim_start ≥ submit_time`; per-timestep capacity checks on a sampled set of timestamps; a brute-force checker on small traces." (lines 178-179).
   - "Performance target: 1,000,000 jobs through `baseline` in under 15 minutes on a laptop in pure Python with a heap-based event loop and a per-node free-capacity index. If the target is missed, report the profile and stop." (line 180).

5. **ADRs and Core Architectural Decisions (Section 12, lines 220-227)**:
   - ADR 001: Conservation partition: precedence failed -> duplicate -> idle CPU / over-requested memory, each second attributed once. Optimizes exact, auditable totals; costs visibility into idle CPU inside failed jobs (listed as a sub-label, not a class).
   - ADR 003: Percentile rightsizing with guardrails: p99 * 1.2, minimum samples, OOM groups only increase. Optimizes safety of recommendations; costs reclaimable capacity left unclaimed (quantified as gap between p99 and p50 sizing).
   - ADR 004: EASY backfill simulator: FCFS plus EASY backfill on identical nodes, calibrated against real waits. Optimizes checkable baseline; ignores topology, preemption, fair share, GPUs; calibration error is stated bound on scenario deltas.

---

## 2. Logic Chain

### 2.1 Domain 1: Waste Attribution & Conservation Partition (G1)
1. **Mathematical Conservation Invariant (G1)**:
   For every job $j$, the total reservation is defined as:
   - $R_{\text{core}}(j) = \text{alloc\_cpus}(j) \times \text{run\_s}(j) \in \mathbb{Z}_{\ge 0}$ (integer seconds)
   - $R_{\text{mem}}(j) = \text{req\_mem\_mb}(j) \times \text{run\_s}(j) \in \mathbb{Z}_{\ge 0}$ (integer MB-seconds)
   The conservation equations must hold exactly:
   $$\begin{aligned}
   R_{\text{core}}(j) &= U_{\text{core}}(j) + W_{\text{class2}}(j) + W_{\text{class3,core}}(j) + W_{\text{class4,core}}(j) + U_{\text{unattrib,core}}(j) \\
   R_{\text{mem}}(j) &= U_{\text{mem}}(j) + W_{\text{class1}}(j) + W_{\text{class3,mem}}(j) + W_{\text{class4,mem}}(j) + U_{\text{unattrib,mem}}(j)
   \end{aligned}$$
   Where all terms are non-negative integers ($\ge 0$).

2. **Precedence Logic**:
   - **Step 1: Exclusions**:
     If $\text{state} \in \{\text{RUNNING}, \text{PENDING}\}$, job is omitted from attribution table and recorded in the report's data quality section.
     If $\text{run\_s} = 0$, job is preserved (early failure) and attributed to Class 3 with zero consumption ($R_{\text{core}} = 0, R_{\text{mem}} = 0$).
   - **Step 2: Class 3 (Precedence 1 - Failed & Retried Work)**:
     Condition: $\text{state} \in \{\text{FAILED}, \text{TIMEOUT}, \text{OUT\_OF\_MEMORY}, \text{NODE\_FAIL}, \text{PREEMPTED}\} \lor (\text{state} = \text{CANCELLED} \land \text{run\_s} > 0)$.
     Action:
     $W_{\text{class3,core}} = R_{\text{core}}$, $W_{\text{class3,mem}} = R_{\text{mem}}$.
     $U_{\text{core}} = 0, U_{\text{mem}} = 0, W_{\text{class1}} = 0, W_{\text{class2}} = 0, W_{\text{class4,core}} = 0, W_{\text{class4,mem}} = 0, U_{\text{unattrib,core}} = 0, U_{\text{unattrib,mem}} = 0$.
     Sub-labels assignment:
     - If $\text{state} = \text{OUT\_OF\_MEMORY} \to \text{"oom"}$
     - Else if $\text{state} = \text{TIMEOUT} \to \text{"timeout"}$
     - Else if $\text{state} = \text{NODE\_FAIL} \to \text{"node\_fail"}$
     - Else if $\text{state} = \text{CANCELLED} \land \text{run\_s} > 0 \to \text{"cancelled\_after\_start"}$
     - Else if $\text{run\_s} \le 60 \to \text{"early\_failure"}$
     - Else $\to \text{"other\_failure"}$
     Retry chain identification:
     For a failed job $A$, search forward for subsequent job $B$ by same `user` with matching `command_hash` (or matching `job_name` if `command_hash` is null) submitted within $\text{retry\_window}$ (default 24h = 86,400 s):
     $0 \le \text{submit\_time}(B) - \text{end\_time}(A) \le 86,400$.
     $B$ is labeled `retry_of = A.job_id`. The retry chain cost aggregates the reservation of all failed predecessors.
   - **Step 3: Class 4 (Precedence 2 - Redundant Recomputation)**:
     Condition: $\text{state} = \text{COMPLETED} \land \text{input\_hash is not null} \land \exists$ prior job $P$ with $\text{state} = \text{COMPLETED} \land \text{command\_hash}(j) = \text{command\_hash}(P) \land \text{input\_hash}(j) = \text{input\_hash}(P) \land 0 < \text{end\_time}(j) - \text{end\_time}(P) \le \text{recompute\_window}$ (default 30 days = 2,592,000 s).
     Action:
     $W_{\text{class4,core}} = R_{\text{core}}$, $W_{\text{class4,mem}} = R_{\text{mem}}$, $\text{confidence} = \text{"declared\_inputs"}$.
     All other terms are 0.
     Partial match fallback:
     If `input_hash` is null/missing, but `command_hash` matches prior completed job within window:
     Mark `possible_recompute = True`, $\text{confidence} = \text{"command\_only"}$.
     Do NOT attribute to Class 4 totals; fall through to Step 4 and Step 5.
   - **Step 4: Class 2 (Precedence 3 - Idle Reserved CPU)**:
     Evaluated on core dimension:
     If $\text{cpu\_time\_used\_s}$ is NULL:
     $U_{\text{unattrib,core}} = R_{\text{core}}$, $U_{\text{core}} = 0$, $W_{\text{class2}} = 0$, label $\text{"unattributed\_missing\_cpu\_time"}$.
     If $\text{cpu\_time\_used\_s}$ is not NULL:
     $W_{\text{class2}} = \max(0, R_{\text{core}} - \text{round}(\text{cpu\_time\_used\_s}))$.
     $U_{\text{core}} = R_{\text{core}} - W_{\text{class2}} = \min(R_{\text{core}}, \text{round}(\text{cpu\_time\_used\_s}))$.
     $U_{\text{unattrib,core}} = 0$.
   - **Step 5: Class 1 (Precedence 4 - Memory Over-Request)**:
     Evaluated on memory dimension:
     If $\text{max\_rss\_mb}$ is NULL:
     $U_{\text{unattrib,mem}} = R_{\text{mem}}$, $U_{\text{mem}} = 0$, $W_{\text{class1}} = 0$, label $\text{"unattributed\_missing\_rss"}$.
     If $\text{max\_rss\_mb}$ is not NULL:
     $W_{\text{class1}} = \max(0, \text{req\_mem\_mb} - \text{max\_rss\_mb}) \times \text{run\_s}$.
     $U_{\text{mem}} = R_{\text{mem}} - W_{\text{class1}}$.
     $U_{\text{unattrib,mem}} = 0$.

### 2.2 Domain 2: Ranked Reclaim Lists & Grouping
1. **Grouping**:
   - Default group key: `(user, command_hash or job_name)`: `command_hash` takes precedence; if null, use `job_name`.
   - Secondary aggregations: Group by `user`, group by `account`, group by `partition`.
   - Sample threshold: If total jobs in group $< \text{min\_samples}$ (default 5), group gets no rightsizing recommendations.
2. **Reclaimable Metrics**:
   - Reclaimable core-hours: Sum of idle CPU core-hours from rightsizing (and Class 4 if cache enabled).
   - Reclaimable GB-hours: Sum of over-requested GB-hours from rightsizing, EXCEPT for groups with any `OUT_OF_MEMORY` job in the window, where reclaimable GB-hours is forced to 0.
3. **Sorting**:
   - Primary ranking score:
     $$\text{Score} = \text{reclaimable\_core\_hours} + \left( \text{mem\_weight\_core\_hours\_per\_gb\_hour} \times \text{reclaimable\_gb\_hours} \right)$$
   - Default weight: derived from cluster spec:
     $$\text{mem\_weight\_core\_hours\_per\_gb\_hour} = \frac{\text{cores\_per\_node}}{\text{mem\_mb\_per\_node} / 1024}$$
   - Groups ranked descending by Score.
4. **Evidence Collection**:
   - Top 5 job IDs with the largest absolute waste in the group (sum of waste core-hours and weighted GB-hours).

### 2.3 Domain 3: Recommendations with Guardrails (G2)
1. **Memory Recommendation**:
   - Subset: Completed jobs in group: $C = \{j \in \text{group} \mid j.\text{state} = \text{COMPLETED}\}$.
   - Base recommendation:
     $$M_{\text{base}} = \lceil p99(\{j.\text{max\_rss\_mb} \mid j \in C\}) \times 1.2 \rceil$$
   - Floor Guardrail:
     $$M_{\text{floor}} = \max(\{j.\text{max\_rss\_mb} \mid j \in \text{group}\})$$
     Recommendation cannot be below $M_{\text{floor}}$.
     (In G2 property test: verify recommendation $\ge M_{\text{floor}}$).
   - OOM Guardrail:
     If $\exists j \in \text{group}$ with $j.\text{state} = \text{OUT\_OF\_MEMORY}$:
     - Direction = `increase`
     - $M_{\text{rec}} = \lceil \max(\{j.\text{max\_rss\_mb} \mid j \in \text{group}\}) \times 1.5 \rceil$
     - Excluded from reclaimable memory totals.
     - Never decrease memory for an OOM group.
   - Sample Size Guardrail:
     If $|\text{group}| < \text{min\_samples}$ (default 5): return `None`.

2. **CPU Recommendation**:
   - Short job guardrail: If $\forall j \in \text{group}: j.\text{run\_s} < 120$ (or if group average $< 120$ s): return `None`.
   - Per-job CPU utilization rate: $u(j) = j.\text{cpu\_time\_used\_s} / j.\text{run\_s}$.
   - Recommendation:
     $$\text{CPUs}_{\text{rec}} = \text{clamp}\left( \lceil p99(\{u(j) \mid j \in \text{group}\}) \times 1.2 \rceil, 1, \max(j.\text{alloc\_cpus}) \right)$$

3. **Timeouts Recommendation**:
   - If group contains any `TIMEOUT` job:
     $$T_{\text{rec}} = \lceil p99(\{j.\text{run\_s} \mid j \in C\}) \times 1.5 \rceil$$

4. **Early Failures**:
   - No resource recommendation. Output failure share: count(run_s <= 60) / total_jobs and unique exit codes.

5. **Recomputation**:
   - Recommend result cache keyed by `(command_hash, input_hash)`.
   - Simulated cache hit rate: $\text{Class4\_count} / \text{total\_group\_count}$.

### 2.4 Domain 4: Scheduler Simulator & Calibration (G4)
1. **Cluster Model & Capacity Index**:
   - $N$ homogeneous nodes, each with `cores_per_node` and `mem_mb_per_node`.
   - Can be loaded from `clusters/<name>.yaml` or inferred as:
     $\text{cores\_per\_node} = \max(\text{alloc\_cpus})$, $\text{mem\_mb\_per_node} = \max(\text{req\_mem\_mb})$.
   - State representation: Free cores and free memory per node.
2. **EASY Backfill Event-Driven Engine**:
   - Job requested time: $T_{\text{req}} = \text{requested\_time}$ if provided in trace, else $\text{ceil}(\text{run\_s} \times 1.2)$.
   - Job actual duration: $\text{run\_s}$ (or scaled $\text{run\_s}$ in proportional scenario).
   - Queue: sorted by `(submit_time, job_id)`.
   - Shadow reservation: Head of queue (Job 0) gets a reservation at earliest future timestamp $t_{\text{reserve}}$ where required resources are available.
   - Backfill: A later job $k$ can jump the queue and start at current time $t$ IF AND ONLY IF:
     1. Sufficient free resources exist on available nodes at time $t$ for job $k$.
     2. Job $k$ will not delay Job 0's start at $t_{\text{reserve}}$ (either finishes by $t + T_{\text{req}, k} \le t_{\text{reserve}}$ or uses nodes not required by Job 0's reservation).
3. **Simulation Scenarios**:
   - `baseline`: Original requests `(alloc_cpus, req_mem_mb, run_s)`.
   - `mem_rightsized`: Memory replaced by $M_{\text{rec}}$ (or original if no rec).
   - `cpu_rightsized`: CPU replaced by $\text{CPUs}_{\text{rec}}$.
     - Sub-model `none`: $\text{run\_s}$ unchanged.
     - Sub-model `proportional`: If $j.\text{cpu\_time\_used\_s} / j.\text{run\_s} > \text{CPUs}_{\text{rec}}$, scale $\text{run\_s}_{\text{new}} = \lceil j.\text{run\_s} \times (j.\text{alloc\_cpus} / \text{CPUs}_{\text{rec}}) \rceil$.
   - `cache_dedup`: Filter out all jobs identified as Class 4 redundant recomputation.
   - `all`: Combine `mem_rightsized`, `cpu_rightsized`, and `cache_dedup`.
4. **Calibration**:
   - Run `baseline` on actual workload trace.
   - For each job $j$, compare recorded wait $W_{\text{trace}}(j) = \text{wait\_s}$ with simulated wait $W_{\text{sim}}(j) = \text{sim\_start}(j) - \text{submit\_time}(j)$.
   - Compute:
     1. Median Absolute Error: $\text{median}(|W_{\text{sim}} - W_{\text{trace}}|)$.
     2. Spearman correlation coefficient $\rho$ between $W_{\text{sim}}$ and $W_{\text{trace}}$.
5. **G4 Validity Requirements**:
   - Every job scheduled exactly once.
   - $\text{sim\_start} \ge \text{submit\_time}$.
   - No node exceeds `cores_per_node` or `mem_mb_per_node` at any timestamp.
   - Brute-force validation on small synthetic fixtures.
6. **Performance Target**:
   - 1,000,000 jobs through `baseline` in $< 15$ minutes ($< 900$ s) on a laptop in pure Python ($> 1,111$ jobs/s). Requires heap event queue (`heapq`) and indexed per-node allocation.

---

## 3. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | Attribution | Precedence Ordering | Strict one-pass precedence: Class 3 -> Class 4 -> Class 2 -> Class 1 ensuring conservation G1 | Job record fields (state, run_s, hashes, metrics) | Attributed class & dimension values | Unattributed label if missing metric | SPEC.md §6.1 |
| 2 | Attribution | Class 3: Failed & Retried Work | Attributes entire core and memory reservation of failed/cancelled jobs to Class 3 | state in {FAILED, TIMEOUT, OOM, NODE_FAIL, PREEMPTED} or (CANCELLED and run_s > 0) | class3_core_s, class3_mem_mb_s, sub-label | Sub-label assigned (oom, timeout, early_failure, node_fail, cancelled_after_start, other_failure) | SPEC.md §6.1 |
| 3 | Attribution | Retry Chain Detection | Chains subsequent matching job by same user submitted within retry_window (default 24h) | user, command_hash/job_name, submit_time, end_time | retry_of pointer, aggregated chain reservation cost | Independent attribution of retried job | SPEC.md §6.1 |
| 4 | Attribution | Class 4: Redundant Recomputation | Attributes entire reservation of duplicate completed job to Class 4 | COMPLETED state, command_hash, input_hash matching earlier completed job within 30 days | class4_core_s, class4_mem_mb_s, confidence="declared_inputs" | If input_hash missing, marked possible_recompute (confidence="command_only"), not counted in Class 4 | SPEC.md §6.1 |
| 5 | Attribution | SWF Recomputation Disablement | For Standard Workload Format traces, recomputation attribution is disabled | source == "swf" | recompute_status = "not available" | Recomputation is never estimated on SWF traces | SPEC.md §5.2 |
| 6 | Attribution | Class 2: Idle Reserved CPU | Computes unused core-seconds from reserved minus CPU time used | alloc_cpus, run_s, cpu_time_used_s | idle_core_s, used_core_s | If cpu_time_used_s is null, labels unattributed_missing_cpu_time, counted in coverage not Class 2 | SPEC.md §6.1 |
| 7 | Attribution | Class 1: Memory Over-Request | Computes unused memory MB-seconds from req_mem minus max_rss | req_mem_mb, max_rss_mb, run_s | over_mem_mb_s, used_mem_mb_s | If max_rss_mb is null, labels unattributed_missing_rss, counted in coverage not Class 1 | SPEC.md §6.1 |
| 8 | Attribution | Guarantee G1 Conservation Check | Asserts reserved = used + class1_or_2 + class3 + class4 + unattributed for every job and trace total | Per-job attributed records | Exact equality in integer seconds and MB-seconds | Raises test failure if any job or total differs by even 1 unit | SPEC.md §6.1, §3 |
| 9 | Reclaim | Job Grouping | Groups jobs by configurable key; defaults to (user, command_hash or job_name) | Canonical job table, policy config | Group-level aggregated records | Groups with < min_samples (5) receive no recommendation | SPEC.md §5.4, §6.2 |
| 10 | Reclaim | Secondary Roll-ups | Aggregates waste and utilization by secondary dimensions | Canonical jobs and groups | Roll-ups by user, account, partition | Missing attributes grouped under "unknown" / null | SPEC.md §5.4, §6.2 |
| 11 | Reclaim | Ranked Reclaim Sorting | Sorts groups by reclaimable core-hours plus weighted reclaimable GB-hours | Group reclaimable core-hours, reclaimable GB-hours, mem_weight | Ranked group list | Default weight from cluster core-to-memory ratio | SPEC.md §6.2 |
| 12 | Reclaim | Evidence Sampling | Identifies the top 5 job IDs contributing most waste in each group | Group jobs and individual waste values | Top 5 job_ids array | Returns fewer if group has < 5 jobs | SPEC.md §6.2 |
| 13 | Recommendations | Percentile Memory Rightsizing | Recommends req_mem_mb = ceil(p99(max_rss_mb) * safety_factor) with floor at observed max | Group completed max_rss_mb values, safety_factor (1.2) | recommended_req_mem_mb | Recommendation never below max observed across all states | SPEC.md §7 |
| 14 | Recommendations | OOM Memory Increase Guardrail | If any job in group failed with OOM, forces direction to increase to ceil(max observed * 1.5) | Group job states and peak usage | recommended_req_mem_mb (increased), direction="increase" | Group excluded from reclaimable memory totals; never decreased | SPEC.md §7 |
| 15 | Recommendations | Percentile CPU Rightsizing | Recommends cpus = clamp(ceil(p99(cpu_rate) * safety_factor), 1, alloc_cpus) | cpu_time_used_s, run_s, alloc_cpus | recommended_cpus | If group jobs have run_s < 120, CPU recommendation is skipped | SPEC.md §7 |
| 16 | Recommendations | Timeout Limit Recommendation | Recommends time_limit = ceil(p99(run_s of completed) * 1.5) for groups experiencing timeouts | Completed job run_s in groups with TIMEOUT state | recommended_time_limit | Ignored if group has no timeouts | SPEC.md §7 |
| 17 | Recommendations | Early Failure Reporting | Identifies groups dominated by early failures (run_s <= 60) | Group job run_s, exit_code | Early failure share %, sample exit codes | No resource rightsizing recommendation emitted | SPEC.md §7 |
| 18 | Recommendations | Recomputation Cache Recommendation | Recommends result caching if Class 4 waste exceeds threshold | Group Class 4 waste, policy threshold | Recommended cache keyed by (command_hash, input_hash), simulated hit rate | Skipped if Class 4 below threshold | SPEC.md §7 |
| 19 | Recommendations | Guarantee G2 Safety Property Tests | Property-based testing with Hypothesis verifying rightsizing safety | 10,000 synthetic job groups | Pass/Fail on guardrail assertions | Triggers test failure on any recommendation violation | SPEC.md §7, §3, §14 |
| 20 | Simulator | Cluster Model Inference | Configures or infers cluster nodes, cores_per_node, mem_mb_per_node from trace | Cluster YAML config or job trace peak allocations | Cluster configuration struct, inference report | Emits report note if cluster is inferred | SPEC.md §8 |
| 21 | Simulator | FCFS + EASY Backfill Scheduler | Discrete-event scheduler maintaining head-of-queue reservation while backfilling subsequent jobs | Job submit_time, run_s, requested_time, cpus, mem, nodes | Simulated start times, end times, queue waits | Deterministic tie-breaking on (submit_time, job_id) | SPEC.md §8 |
| 22 | Simulator | Duration Estimation | Uses trace requested time if present, else run_s * 1.2 for scheduler reservations | Job requested time, run_s | Estimated walltime for shadow reservation | Jobs actually run for true run_s | SPEC.md §8 |
| 23 | Simulator | Five Simulation Scenarios | Replays trace under baseline, mem_rightsized, cpu_rightsized (none & proportional), cache_dedup, all | Job trace and recommendation parameters | Per-scenario wait metrics, makespan, utilization, throughput | Full trace replay per scenario | SPEC.md §8 |
| 24 | Simulator | Proportional CPU Runtime Scaling | In cpu_rightsized (proportional), scales run_s if utilization exceeded new allocation | Old cpus, new cpus, cpu_time_used_s, run_s | Adjusted run_s for simulation replay | Unchanged if utilization did not exceed new allocation | SPEC.md §8 |
| 25 | Simulator | Guarantee G4 Validity Checks | Asserts every job scheduled once, sim_start >= submit_time, and node capacity respected | Simulator execution logs | Verification assertions | Raises exception if capacity or validity violated | SPEC.md §8, §3 |
| 26 | Calibration | Real Trace Wait Calibration | Replays baseline scenario on real SWF trace and compares simulated vs recorded wait | Real trace recorded wait_s, simulated wait_s | Median absolute error, Spearman rank correlation | Calibration metrics stated next to all scenario outputs | SPEC.md §8, §9 |
| 27 | Performance | 1M Job Simulation Target | Executes 1,000,000 jobs through baseline in under 15 minutes in pure Python | Synthetic 1M job trace | Simulation results within 900 seconds | Requires heap event loop and per-node free capacity index | SPEC.md §8 |

---

## 4. Edge Cases

| # | Feature | Input | Observed Behavior |
|---|---------|-------|-------------------|
| 1 | Conservation G1 | Job with `run_s == 0` | $R_{\text{core}} = 0, R_{\text{mem}} = 0$; job kept as early failure and attributed to Class 3 with 0 consumption; G1 equation holds ($0 = 0$). |
| 2 | Attribution Class 2 | `cpu_time_used_s` is NULL | Core reservation cannot be split into used vs idle; labeled `unattributed_missing_cpu_time`; counted in coverage, not in Class 2; $R_{\text{core}} = U_{\text{unattrib,core}}$. |
| 3 | Attribution Class 1 | `max_rss_mb` is NULL | Memory reservation cannot be split into used vs over-request; labeled `unattributed_missing_rss`; counted in coverage, not in Class 1; $R_{\text{mem}} = U_{\text{unattrib,mem}}$. |
| 4 | Attribution Class 2 | Multithreaded job uses more CPU than allocated (`cpu_time_used_s > alloc_cpus * run_s`) | $\max(0, R_{\text{core}} - \text{cpu\_time}) = 0$; `idle_core_s = 0`; `used_core_s = reserved_core_s`; prevents negative waste; G1 exact. |
| 5 | Attribution Class 1 | Peak RSS exceeds requested memory (`max_rss_mb > req_mem_mb`) | $\max(0, \text{req\_mem} - \text{max\_rss}) = 0$; `over_mem_mb_s = 0`; `used_mem_mb_s = reserved_mem_mb_s`; prevents negative waste; G1 exact. |
| 6 | Attribution Class 3 | Job is `CANCELLED` with `run_s == 0` vs `run_s > 0` | If `run_s == 0`, 0 consumption early failure; if `run_s > 0`, attributed to Class 3 with sub-label `cancelled_after_start`. |
| 7 | Attribution Exclusion | Job state is `RUNNING` or `PENDING` | Excluded from attribution tables; counted in data-quality reporting section; does not distort finished job statistics. |
| 8 | Attribution Class 4 | `input_hash` is missing, but `command_hash` matches prior completed job | Labeled `possible_recompute` with `confidence = "command_only"`; NOT counted in Class 4 waste totals; falls through to Class 2 and Class 1. |
| 9 | Attribution Class 4 | Source is Standard Workload Format (`swf`) | Recomputation attribution is reported as "not available", never estimated (SWF has no input file hashes). |
| 10 | Recommendations G2 | Group with total jobs $< \text{min\_samples}$ (default 5) | Safety guardrail triggers: receives NO recommendation (`None`); excluded from reclaimable capacity totals. |
| 11 | Recommendations G2 | Group contains at least 1 job with `state == OUT_OF_MEMORY` | OOM safety guardrail triggers: recommendation direction is forced to `increase` to $\lceil \max(\text{observed}) \times 1.5 \rceil$; excluded from reclaimable memory totals; never decreased. |
| 12 | Recommendations CPU | Group has all jobs with `run_s < 120` | Short-job guardrail triggers: CPU recommendation is skipped (`None`) because utilization measurements on short jobs are noisy and unreliable. |
| 13 | Recommendations Memory | Group completed jobs p99 is lower than a failed job's max RSS | Floor guardrail triggers: recommended `req_mem_mb` is clamped to $\ge \max(\text{max\_rss\_mb})$ observed across all states in the group. |
| 14 | Recommendations Cache | Group has 0 Class 4 jobs or below policy threshold | No caching recommendation emitted; hit rate reported as 0%. |
| 15 | Simulator Ties | Multiple jobs submitted at identical timestamp | Deterministic tie-breaking on `(submit_time, job_id)`; prevents scheduler non-determinism (G3 compliance). |
| 16 | Simulator Backfill | Head of queue cannot start; second job fits free nodes and finishes before head reservation | Second job is backfilled and starts immediately at time $t$ without delaying head reservation. |
| 17 | Simulator Backfill | Head cannot start; second job fits free nodes but estimated duration extends past head reservation | Second job is NOT started (blocked by head reservation) unless it uses nodes not required by head. |
| 18 | Simulator CPU Rightsized | Scaled runtime in `proportional` model when job utilization was below new allocation | Runtime remains unchanged (`run_s`); only scaled when measured utilization exceeded new core allocation. |
| 19 | Simulator Capacity | Single job requesting multi-node allocation | Allocated across nodes; per-node capacity index verifies no individual node exceeds cores or memory limits. |
| 20 | Calibration | Real trace has zero wait time for all jobs | MAE evaluates to 0; Spearman correlation handles zero variance gracefully without division-by-zero crash. |

---

## 5. Caveats

1. **Memory Conversion Constant**:
   The specification states that memory in Slurm `--units=M` is in megabytes (MB) and reports summarize in gigabyte-hours (GB-hours). Standard binary conversion ($1 \text{ GB} = 1024 \text{ MB}$) is assumed throughout calculations, giving $1 \text{ GB-hour} = 1024 \times 3600 = 3,686,400 \text{ MB-s}$. If metric ($1 \text{ GB} = 1000 \text{ MB}$) is desired, it must be governed by a configuration toggle in `config.py`.
2. **Cluster Multi-Node Topology in Inference**:
   When cluster specification is not provided and inferred from the trace, the inference derives `cores_per_node = max(alloc_cpus)` and `mem_mb_per_node = max(req_mem_mb)`. For jobs that ran across multiple nodes (`nodes > 1`), if `alloc_cpus` in the accounting record is the total job core count across all nodes, the inferred node size will represent the whole job rather than per-node size unless normalized by `nodes`. `normalize.py` must account for `nodes` division where appropriate.
3. **Hypothesis Property Test Scope**:
   Phase 3 acceptance requires 10,000 generated groups tested against G2 guardrails without violation. The generators must explicitly cover boundary cases: all completed, all failed, mixed OOM, `run_s < 120`, and group sizes $1 \le N \le 4$ and $N \ge 5$.

---

## 6. Conclusion

The requirements for Attribution, Recommendations with Guardrails, EASY-Backfill Simulation, and Calibration are completely specified and mathematically well-defined:
1. **Attribution (G1)** enforces a strict, single-pass precedence hierarchy: Class 3 (failed) $\to$ Class 4 (recomputation) $\to$ Class 2 (idle CPU) $\to$ Class 1 (memory over-request), maintaining exact integer conservation across all jobs.
2. **Ranked Reclaim Lists** aggregate groups by configurable keys (default `(user, command_hash or job_name)`), sorting by weighted core-hours and GB-hours using the cluster core-to-memory ratio, supported by top-5 evidence jobs.
3. **Recommendations (G2)** enforce strict safety guardrails: p99 $\times$ 1.2 sizing bounded by observed maximum across all states, mandatory increase for OOM groups with total exclusion from reclaimable totals, suppression for short jobs ($< 120$ s), and silence for groups with $< 5$ samples.
4. **Simulator (G4) & Calibration** implements an event-driven FCFS + EASY backfill scheduler with deterministic tie-breaking, replaying 5 distinct scenarios, validated by calibration against recorded wait times (MAE and Spearman correlation), with a strict 1,000,000 jobs in $< 15$ minutes performance requirement.

---

## 7. Verification Method

To independently verify the facts and specifications documented in this report:

1. **Inspect Authoritative Specification Files**:
   ```bash
   # Verify Section 6 (Attribution and Ranked Reclaim)
   sed -n '146,162p' /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md

   # Verify Section 7 (Recommendations with Guardrails)
   sed -n '163,171p' /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md

   # Verify Section 8 (Simulator and Calibration)
   sed -n '172,180p' /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md

   # Verify Guarantees G1, G2, G4 and Non-goals
   sed -n '37,45p' /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md
   ```

2. **Verify ADR Definitions and Trade-offs**:
   ```bash
   # Verify ADR 001, 003, 004
   sed -n '220,227p' /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md
   ```

3. **Verify Phased Delivery Acceptance Requirements**:
   ```bash
   # Verify Phase 2, Phase 3, Phase 5 acceptance criteria
   sed -n '251,259p' /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md
   ```
