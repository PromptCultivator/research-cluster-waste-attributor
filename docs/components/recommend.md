# Rightsizing Recommendations and Safety Guardrails

## 1. Overview

The recommendation engine (`rcwa/recommend.py`) computes right-sized resource requests across memory, CPU cores, and wallclock limits for qualifying job groups. The engine strictly enforces **Guarantee G2 (Safety Guardrails)** to prevent resource starvations or production disruptions.

---

## 2. Rightsizing Formulation

### 2.1 Memory Recommendations

Memory limits are calculated to prevent memory exhaustion while shedding idle buffer capacity:
$$\text{req\_mem\_mb}_{\text{rec}} = \left\lceil \text{P99}(\text{max\_rss\_mb} \mid \text{COMPLETED}) \times \text{safety\_factor} \right\rceil$$

Where:
- $\text{P99}$ evaluates across successful (`COMPLETED`) jobs within the group cohort.
- `safety_factor` defaults to $1.2$ (providing a 20% head-room margin above observed 99th percentile consumption).

#### Guardrail Constraints:
1. **Max RSS Floor**:
   The recommended memory is never lower than the absolute peak observed RSS across all jobs in the group (regardless of job state):
   $$\text{req\_mem\_mb}_{\text{rec}} \ge \max_{\text{all}}(\text{max\_rss\_mb})$$
2. **Out-of-Memory (OOM) Escalation**:
   If any job in the group cohort experienced an `OUT_OF_MEMORY` termination within the observation window:
   - The recommendation direction forces an **increase**:
     $$\text{req\_mem\_mb}_{\text{rec}} = \left\lceil \max_{\text{all}}(\text{max\_rss\_mb}) \times \text{oom\_multiplier} \right\rceil$$
     where `oom_multiplier` defaults to $1.5$.
   - The group is explicitly excluded from reclaimable memory capacity sums.

### 2.2 CPU Recommendations

CPU core allocations are right-sized by matching allocated capacity to active thread execution:
$$\text{cpus}_{\text{rec}} = \operatorname{clamp}\left( \left\lceil \text{P99}\left(\frac{\text{cpu\_time\_used\_s}}{\text{run\_s}}\right) \times \text{safety\_factor} \right\rceil, 1, \text{alloc\_cpus} \right)$$

#### Guardrail Constraints:
- **Short Job Exclusion**:
  Groups whose median runtime is under 120 seconds ($\text{run\_s} < 120$) receive no CPU core recommendation. Short jobs exhibit high startup and teardown measurement noise, making core-second utilization ratios unreliable.

### 2.3 Wallclock Time Limit Recommendations

Groups exhibiting `TIMEOUT` terminations receive right-sized time limit adjustments:
$$\text{time\_limit}_{\text{rec}} = \left\lceil \text{P99}(\text{run\_s} \mid \text{COMPLETED}) \times 1.5 \right\rceil$$

### 2.4 Early Failures

Groups dominated by early failures ($\text{run\_s} \le 60$) receive no resource adjustments. Instead, the engine surfaces the group in an Early Failure Diagnostic section with sample exit codes, indicating script or environment errors rather than capacity sizing problems.

---

## 3. Guarantee G2: Verification

Guarantee G2 is verified via automated property-based testing (`hypothesis`):
- Randomly generated groups with varying sample distributions, state distributions, and resource utilization profiles are evaluated.
- The property test asserts that:
  1. Memory recommendations never decrease below observed maximum peak RSS.
  2. Any group with an OOM occurrence receives an increased allocation.
  3. Groups with fewer samples than `min_samples` receive no recommendation.
- Zero guardrail violations across 10,000 generated groups are required for gate clearance.
