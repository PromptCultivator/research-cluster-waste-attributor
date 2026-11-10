# Failure and Retry Chain Detector

## 1. Overview

The retry chain detector (`rcwa/retries.py`) links failed or terminated jobs to subsequent resubmission attempts. By correlating failures with subsequent executions, the system reveals hidden cluster waste resulting from repeated attempts, multi-hop debugging cycles, and cascading failures.

---

## 2. Retry Matching Criteria

A subsequent job $B$ is identified as a retry attempt of an earlier failed job $A$ when all of the following conditions are met:

1. **Failure State**:
   Job $A$ terminated in an abnormal state:
   $$\text{state}_A \in \{\text{FAILED}, \text{TIMEOUT}, \text{OUT\_OF\_MEMORY}, \text{NODE\_FAIL}, \text{PREEMPTED}\} \lor (\text{state}_A = \text{CANCELLED} \land \text{run\_s}_A > 0)$$

2. **Identical User**:
   $$\text{user}_B == \text{user}_A$$

3. **Command Signature Match**:
   If both jobs provide `command_hash`, they must match:
   $$\text{command\_hash}_B == \text{command\_hash}_A$$
   If `command_hash` is unavailable, matching falls back to `job_name`:
   $$\text{job\_name}_B == \text{job\_name}_A$$

4. **Temporal Ordering and Horizon Window**:
   Job $B$ must be submitted after Job $A$'s submission, within the configurable `retry_window` (default 24 hours):
   $$0 < \text{submit\_time}_B - \text{submit\_time}_A \le \text{retry\_window\_seconds}$$

---

## 3. Causal Multi-Hop Chain Linking

When users resubmit jobs repeatedly across a debugging session, failures chain into multi-hop sequences ($A \to B \to C$):

```
[ Job A: Failed (OOM) ]
       │  (Submitted: T=0, Window <= 24h)
       ▼
[ Job B: Failed (Timeout) ]  <-- Marked: retry_of = A
       │  (Submitted: T=4h, Window <= 24h)
       ▼
[ Job C: Completed ]         <-- Marked: retry_of = B
```

### Algorithmic Rules:
- **1-to-1 Earliest Candidate Assignment**:
  To guarantee deterministic, causal chains, each failed job claims the earliest eligible resubmission in chronological order. A single resubmission cannot serve as the direct retry of two distinct prior failures.
- **Chain Metrics**:
  The detector aggregates the cumulative cost across the chain:
  $$\text{chain\_core\_hours} = \sum_{j \in \text{chain}} \frac{\text{reserved\_core\_s}_j}{3600}$$
  $$\text{chain\_gb\_hours} = \sum_{j \in \text{chain}} \frac{\text{reserved\_mem\_mb\_s}_j}{3600 \times 1024}$$
- **Independent Attribution**:
  While chain associations are tracked for reporting, each individual job in the chain remains attributed strictly via the precedence cascade (Section 3 of attribution design). Failed links are assigned to Class 3; the eventual successful run is attributed according to its actual utilization and right-sizing opportunity.
