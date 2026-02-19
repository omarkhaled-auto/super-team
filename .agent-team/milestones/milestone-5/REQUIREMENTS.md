## Milestone 5: Fix Pass + Defect Remediation
- ID: milestone-5
- Status: PENDING
- Dependencies: milestone-4
- Description: Catalog all defects from M2-M4, classify by priority (P0-P3), apply convergence-based fix passes, track effectiveness metrics, verify no regressions.

---

### Overview

Milestone 5 is the remediation engine. It takes all defects discovered in M2-M4, classifies them, applies iterative fix passes using builders, tracks convergence metrics, and stops when convergence criteria are met. This is the only milestone that modifies existing code (via builder fix passes).

### Estimated Effort
- **LOC**: ~600
- **Files**: fix_pass.py expansion + 1 test file
- **Risk**: MEDIUM (convergence may not reach target, regressions possible)
- **Duration**: 1-1.5 hours

---

### Source File Updates

#### `src/run4/fix_pass.py` (expand from stub, ~350 LOC total)
**Implements**: REQ-029 through REQ-033, TECH-007, TECH-008

##### Finding Dataclass (REQ-029, TECH-002)

Already defined in `src/run4/state.py` (M1). The Finding dataclass has these 10 fields:

```python
@dataclass
class Finding:
    finding_id: str          # FINDING-NNN pattern
    priority: str            # P0, P1, P2, P3
    system: str              # "Build 1", "Build 2", "Build 3", "Integration"
    component: str           # specific module/function
    evidence: str            # exact reproduction or test output
    recommendation: str      # specific fix action
    resolution: str          # "FIXED", "OPEN", "WONTFIX"
    fix_pass_number: int     # which pass fixed it (0 = unfixed)
    fix_verification: str    # test ID confirming fix
    created_at: str          # ISO 8601 timestamp
```

##### Priority Classification (REQ-030)

```python
def classify_priority(finding: dict) -> str:
    """Apply P0-P3 decision tree:
    P0: System cannot start/deploy, blocks everything
        - Health check failure
        - Container won't start
        - MCP server crashes on init
        - Database connection failure
    P1: Primary use case fails, no workaround
        - Core API endpoint returns error
        - Contract validation fails
        - Missing required field in response
        - Auth flow broken
    P2: Secondary feature broken
        - Non-critical endpoint error
        - Performance degradation
        - Minor schema mismatch
    P3: Cosmetic/performance/docs
        - Print statements instead of logger
        - Missing docstrings
        - Style violations
    """
```

##### Fix Pass Execution Loop (REQ-031)

```python
async def execute_fix_pass(
    state: Run4State,
    config: Run4Config,
    pass_number: int
) -> FixPassResult:
    """Execute one fix pass with 6 steps:
    1. DISCOVER: Run all scans, collect violations
    2. CLASSIFY: Apply P0-P3 decision tree
    3. GENERATE: Write FIX_INSTRUCTIONS.md targeting P0 first, then P1
    4. APPLY:
       - Infrastructure fixes: direct edit
       - Build 1/3 code: direct edit
       - Build 2 code: builder quick mode
    5. VERIFY: Re-run specific scan that found each violation
    6. REGRESS: Run full scan set, compare before/after snapshots
    """

@dataclass
class FixPassResult:
    pass_number: int
    violations_before: int
    violations_after: int
    fixes_attempted: int
    fixes_resolved: int
    regressions: list[dict]
    fix_effectiveness: float      # fixes_resolved / fixes_attempted
    regression_rate: float         # new_violations / total_fixes_applied
    new_defect_discovery_rate: int # new findings discovered
    score_delta: float             # score_after - score_before
    cost: float
    duration_s: float
```

##### Fix Pass Metrics (REQ-032)

Per-pass tracking:
- `fix_effectiveness = fixes_resolved / fixes_attempted`
- `regression_rate = new_violations / total_fixes_applied`
- `new_defect_discovery_rate = new_findings_count`
- `score_delta = score_after - score_before`

##### Convergence Criteria (REQ-033)

```python
def check_convergence(
    state: Run4State,
    config: Run4Config,
    pass_results: list[FixPassResult]
) -> tuple[bool, str]:
    """Check if fix loop should stop.

    Hard stop triggers (any one):
    - P0 == 0 AND P1 == 0
    - max_fix_passes reached
    - Budget exhausted (total_cost >= max_budget_usd)
    - fix_effectiveness < 30% for 2 consecutive passes
    - regression_rate > 25% for 2 consecutive passes

    Soft convergence ("good enough"):
    - P0 == 0
    - P1 <= 2
    - new_defect_rate < 3 per pass for 2 consecutive
    - aggregate_score >= 70

    Returns: (should_stop, reason)
    """
```

##### Convergence Formula (TECH-007)

```python
def compute_convergence(
    remaining_p0: int,
    remaining_p1: int,
    remaining_p2: int,
    initial_total_weighted: float
) -> float:
    """convergence = 1.0 - (remaining_p0 * 0.4 + remaining_p1 * 0.3 + remaining_p2 * 0.1) / initial_total_weighted

    Converged when >= 0.85
    """
```

##### Violation Snapshots (TECH-008)

```python
def take_violation_snapshot(scan_results: dict) -> dict[str, list[str]]:
    """Create snapshot: {scan_code: [file_path1, file_path2, ...]}
    Saved as JSON before and after each fix pass."""

def detect_regressions(
    before: dict[str, list[str]],
    after: dict[str, list[str]]
) -> list[dict]:
    """Compare snapshots. A regression is a violation that:
    - Was in 'before' snapshot
    - Was NOT in 'before' snapshot but IS in 'after' (new violation)
    - Was fixed (removed from 'after') but reappeared

    Returns list of {scan_code, file_path, type: "new"|"reappeared"}"""
```

##### Fix Loop Orchestrator

```python
async def run_fix_loop(
    state: Run4State,
    config: Run4Config
) -> list[FixPassResult]:
    """Main fix loop:
    1. Take initial violation snapshot
    2. For each pass (up to max_fix_passes):
       a. Execute fix pass
       b. Track metrics
       c. Check convergence
       d. If converged, break
    3. Return all pass results
    """
```

---

### Test File

#### `tests/run4/test_m5_fix_pass.py` (~250 LOC)
**Implements**: REQ-029 through REQ-033, TECH-007, TECH-008, TEST-013 through TEST-015

| Test | Requirement | Description |
|------|-------------|-------------|
| `test_finding_dataclass_fields` | REQ-029 | Finding has all 10 required fields with correct types |
| `test_finding_id_pattern` | REQ-029 | `next_finding_id()` generates FINDING-001, FINDING-002, ... |
| `test_priority_classification_p0` | REQ-030 | Health check failure -> P0 |
| `test_priority_classification_p1` | REQ-030 | Core API error -> P1 |
| `test_priority_classification_p2` | REQ-030 | Non-critical feature broken -> P2 |
| `test_priority_classification_p3` | REQ-030 | Print statement -> P3 |
| `test_fix_pass_6_step_cycle` | REQ-031 | All 6 steps execute in order: DISCOVER, CLASSIFY, GENERATE, APPLY, VERIFY, REGRESS |
| `test_fix_instructions_md_format` | REQ-031 | FIX_INSTRUCTIONS.md has correct markdown format with P0 before P1 |
| `test_fix_metrics_computation` | REQ-032 | fix_effectiveness, regression_rate computed correctly |
| `test_convergence_hard_stop_p0_p1_zero` | REQ-033 | Fix loop stops when P0=0 AND P1=0 |
| `test_convergence_hard_stop_max_passes` | REQ-033 | Fix loop stops at max_fix_passes |
| `test_convergence_hard_stop_budget` | REQ-033 | Fix loop stops when budget exhausted |
| `test_convergence_hard_stop_low_effectiveness` | REQ-033 | Fix loop stops when effectiveness < 30% for 2 consecutive passes |
| `test_convergence_hard_stop_high_regression` | REQ-033 | Fix loop stops when regression > 25% for 2 consecutive passes |
| `test_convergence_soft_good_enough` | REQ-033 | Soft convergence when P0=0, P1<=2, new_defect_rate<3 for 2 passes, score>=70 |
| `test_regression_detection` | TEST-013 | Create snapshot, apply mock fixes, verify `detect_regressions()` finds reappearing violations |
| `test_convergence_formula_values` | TEST-014 | Verify formula produces correct values: P0=0,P1=0,P2=0 -> 1.0; P0=5,P1=10,P2=20 -> low |
| `test_hard_stop_terminates_loop` | TEST-015 | Verify fix loop terminates when any hard stop condition is met |

---

### Test Matrix Mapping

| Matrix ID | Test Function | Priority |
|-----------|---------------|----------|
| X-07 | `test_fix_instructions_consumed` | P1 |

---

### Dependencies on M4

| M4 Output | M5 Usage |
|-----------|----------|
| MCP wiring results | Defects from failed MCP tests |
| Builder results | Defects from failed builds |
| Docker deployment results | Defects from unhealthy services |
| Integration test results | Defects from failed E2E flows |
| Quality Gate results | Defects from L1-L4 checks |
| Contract compliance results | Defects from Schemathesis |

### Defect Data Flow

```
M2 MCP wiring failures    ─┐
M3 Builder wiring failures ─┤
M4 Pipeline failures       ─┤──> Finding catalog ──> Classify ──> Fix Loop
M4 Docker health failures  ─┤
M4 Quality Gate violations ─┘
```

### Risk Analysis

| Risk | Impact | Mitigation |
|------|--------|------------|
| Fix passes don't converge | Stuck in loop | Hard stop at max_fix_passes |
| Fixes cause regressions | Score goes down | regression_rate_ceiling: 0.25 |
| Builder quick mode is too slow | Fix pass takes too long | builder_timeout_s: 600 for quick mode |
| Budget exhausted before fixing P0s | P0 defects remain | Prioritize P0 in FIX_INSTRUCTIONS.md |
| Automatic classification is wrong | Wrong priority assigned | Manual review of P0 classifications |

### Gate Condition

**Milestone 5 is COMPLETE when**: All REQ-029 through REQ-033, TECH-007, TECH-008, TEST-013 through TEST-015 tests pass, AND the fix loop has reached convergence (hard or soft). This unblocks M6.
