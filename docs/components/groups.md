# Job Grouping and Reclaim Ranking

## 1. Overview

The grouping and ranking module (`rcwa/groups.py`) aggregates attributed job records into distinct analytical cohorts, applies sample size floors, computes composite reclaim scores, and ranks candidate groups for capacity reclamation.

---

## 2. Grouping Hierarchy

Group definitions are declared in policy configuration files (`policies/default.yaml`).

### 2.1 Primary Group Key
By default, jobs are grouped by:
$$\text{Primary Key} = (\text{user}, \text{command\_hash\_or\_job\_name})$$
where `command_hash_or_job_name` evaluates to `command_hash` when present, or `job_name` otherwise.

### 2.2 Secondary Rollups
To support organizational accounting, the engine aggregates secondary tables across:
- `account`: Departmental or billing project charge codes.
- `partition`: Cluster queues and hardware tiers.
- `user`: Per-engineer summaries.

---

## 3. Sample Size Floor

Groups with sparse sample counts exhibit volatile statistical distributions. To ensure stability and prevent erroneous changes to production limits:
- The policy enforces `min_samples` (default: 5).
- Groups with fewer jobs than `min_samples` receive no rightsizing recommendation (`action = "below_sample_floor"`).
- Reclaimable capacity for these groups is excluded from actionable reclaim totals, though observed waste remains accounted for in data quality reports.

---

## 4. Reclaim Scoring and Prioritization

Groups are ranked by total reclaimable capacity, weighted by the cluster's core-to-memory hardware exchange ratio:

$$\text{Reclaim Score} = \text{reclaim\_core\_hours} + \left( w_{\text{mem}} \times \text{reclaim\_gb\_hours} \right)$$

where:
- $\text{reclaim\_core\_hours} = \sum (\text{class2\_core\_s} + \text{class4\_core\_s}) / 3600$
- $\text{reclaim\_gb\_hours} = \sum (\text{class1\_mem\_mb\_s} + \text{class4\_mem\_mb\_s}) / (3600 \times 1024)$
- $w_{\text{mem}}$: Configurable weight (`mem_weight_core_hours_per_gb_hour`), derived from cluster hardware configuration (default 0.25 core-hours per GB-hour, corresponding to nodes with 4 GB of RAM per core).

---

## 5. Evidence Extraction

For each ranked group, the engine extracts the top five job IDs contributing the highest individual waste values. These identifiers are included in summary tables and CSV exports, providing cluster operators with direct audit trails to verify recommendations against raw job traces.
