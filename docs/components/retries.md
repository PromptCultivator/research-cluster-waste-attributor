# Failure and Retry Chain Detector

## 1. Overview

[`rcwa/retries.py`](../../rcwa/retries.py) implements `detect_retry_chains(df, retry_window_s=86400)` to identify failed compute jobs and link causal resubmission sequences into structured retry chains.

---

## 2. Failure Criteria and Causal Matching

A job $A$ qualifies as a failure seed when:
$$\text{state}_A \in \{\text{FAILED}, \text{TIMEOUT}, \text{OUT\_OF\_MEMORY}, \text{NODE\_FAIL}, \text{PREEMPTED}\} \lor (\text{state}_A = \text{CANCELLED} \land \text{run\_s}_A > 0) \lor (\text{run\_s}_A = 0 \land \text{state}_A \notin \{\text{RUNNING}, \text{PENDING}\})$$

Effective end time for $A$ resolves using:
$$\text{eff\_end}_A = \text{coalesce}(\text{end\_time}_A,\ \text{start\_time}_A + \text{run\_s}_A,\ \text{submit\_time}_A + \text{wait\_s}_A + \text{run\_s}_A)$$

A subsequent job $B$ matches as a candidate retry of $A$ when all conditions hold:
1. **Identical User & Task Signature**: Rows group strictly by `(user, command_hash or job_name)`. Jobs lacking either `user` or a task identifier cannot participate in retry linking.
2. **Non-Self & Unclaimed**: $B \neq A$ and $B$ has not already been claimed as the child retry of an earlier failure.
3. **Causal Resubmission Window**: $B$'s `submit_time` occurs at or after $A$'s effective end time within `retry_window_s` (default `86400` seconds = 24 hours):
   $$0 \le (\text{submit\_time}_B - \text{eff\_end}_A).\text{total\_seconds}() \le \text{retry\_window\_s}$$

---

## 3. Deterministic 1-to-1 Claiming and Multi-Hop Chains

Within each `(user, task_id)` group:
1. Failures with known `eff_end` sort chronologically by `(eff_end, submit_time, row_index, job_id)`.
2. Each failure selects the earliest unclaimed eligible resubmission $B$ ordered by `(submit_time_B, job_id_B)`, guaranteeing causal 1-to-1 linkage without cycles or double-claiming.
3. Multi-hop chains ($A \to B \to C$) trace upward to the chain's root failure (`retry_chain_id`) and traverse depth-first to assign hop distances (`retry_count`, `0` at root, incremented along descendants). Chains require at least `2` participating jobs (root + at least one resubmission); unlinked standalone jobs retain `retry_chain_id = null` and `retry_count = 0`.

```text
[ Job A: OUT_OF_MEMORY ]   retry_of = null, retry_chain_id = A, retry_count = 0
       │  (submit_B - eff_end_A <= retry_window_s)
       ▼
[ Job B: TIMEOUT ]         retry_of = A,    retry_chain_id = A, retry_count = 1
       │  (submit_C - eff_end_B <= retry_window_s)
       ▼
[ Job C: COMPLETED ]       retry_of = B,    retry_chain_id = A, retry_count = 2
```

---

## 4. Emitted Columns

| Column | Type | Meaning |
|---|---|---|
| `retry_of` | `String?` | Immediate preceding failed job ID claimed by this resubmission (`null` for roots/unlinked jobs). |
| `retry_chain_id` | `String?` | Root job ID identifying the multi-hop retry chain (`null` if standalone). |
| `retry_count` | `Int32` | Hop distance from the chain root (`0` at root or standalone jobs; `>= 1` on retries). |
| `retry_chain_cost_core_s` | `Int64` | Total `reserved_core_s` summed across all jobs in the chain (`0` if standalone). |
| `retry_chain_cost_mem_mb_s` | `Int64?` | Total `reserved_mem_mb_s` across chain members (`null` if none record memory or standalone). |

Primary resource attribution still evaluates each row independently through the conservation precedence cascade (`attribute.py`).
