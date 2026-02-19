## Milestone 6: Audit Report + Final Verification
- ID: milestone-6
- Status: PENDING
- Dependencies: milestone-5
- Description: Compute per-system and aggregate scores, generate the final SUPER_TEAM_AUDIT_REPORT.md with honest assessment of gaps, produce all appendices.

---

### Overview

Milestone 6 is the final deliverable milestone. It takes all verification data from M1-M5, computes scored assessments, generates the comprehensive audit report, and produces the appendices (RTM, coverage matrices, cost breakdown). This milestone is primarily report generation — low risk, high documentation effort.

### Estimated Effort
- **LOC**: ~800
- **Files**: scoring.py + audit_report.py expansion + 1 test file
- **Risk**: LOW (pure computation and report generation)
- **Duration**: 1-1.5 hours

---

### Source File Updates

#### `src/run4/scoring.py` (expand from stub, ~250 LOC)
**Implements**: REQ-034 through REQ-036

##### Per-System Scoring (REQ-034)

```python
@dataclass
class SystemScore:
    system_name: str                    # "Build 1", "Build 2", "Build 3"
    functional_completeness: float      # 0-30 (REQ pass rate * 30)
    test_health: float                  # 0-20 (test pass rate * 20)
    contract_compliance: float          # 0-20 (schema validation pass rate * 20)
    code_quality: float                 # 0-15 (inverse violation density)
    docker_health: float                # 0-10 (health check pass rate * 10)
    documentation: float                # 0-5 (binary per artifact)
    total: float                        # sum of above
    traffic_light: str                  # GREEN/YELLOW/RED

def compute_system_score(
    system_name: str,
    req_pass_rate: float,              # 0.0-1.0
    test_pass_rate: float,             # 0.0-1.0
    contract_pass_rate: float,         # 0.0-1.0
    total_violations: int,
    total_loc: int,                    # .py files, excluding tests/__pycache__/venv
    health_check_rate: float,          # 0.0-1.0
    artifacts_present: int,
    artifacts_required: int = 5        # Dockerfile, requirements.txt/pyproject.toml, README.md, spec file, /health
) -> SystemScore:
    """
    Formula:
    score = (req_pass_rate * 30)
          + (test_pass_rate * 20)
          + (contract_pass_rate * 20)
          + max(0, 15 - violation_density * 1.5)
          + (health_check_rate * 10)
          + (artifacts_present / artifacts_required * 5)

    Where: violation_density = total_violations / (total_loc / 1000)

    Traffic light:
    - GREEN: 80-100
    - YELLOW: 50-79
    - RED: 0-49
    """
```

##### Integration Scoring (REQ-035)

```python
@dataclass
class IntegrationScore:
    mcp_connectivity: float             # 0-25 (mcp_tools_ok / 20 * 25)
    data_flow_integrity: float          # 0-25 (flows_passing / flows_total * 25)
    contract_fidelity: float            # 0-25 (max(0, 25 - cross_build_violations * 2.5))
    pipeline_completion: float          # 0-25 (phases_complete / phases_total * 25)
    total: float                        # sum of above
    traffic_light: str                  # GREEN/YELLOW/RED

def compute_integration_score(
    mcp_tools_ok: int,                  # out of 20
    flows_passing: int,
    flows_total: int,
    cross_build_violations: int,
    phases_complete: int,
    phases_total: int
) -> IntegrationScore:
    """
    Formula:
    score = (mcp_tools_ok / 20 * 25)
          + (flows_passing / flows_total * 25)
          + max(0, 25 - cross_build_violations * 2.5)
          + (phases_complete / phases_total * 25)
    """
```

##### Aggregate Scoring (REQ-036)

```python
@dataclass
class AggregateScore:
    build1: float
    build2: float
    build3: float
    integration: float
    aggregate: float
    traffic_light: str                  # GREEN/YELLOW/RED

def compute_aggregate(
    build1_score: float,
    build2_score: float,
    build3_score: float,
    integration_score: float
) -> AggregateScore:
    """
    Formula: aggregate = (build1 * 0.30) + (build2 * 0.25) + (build3 * 0.25) + (integration * 0.20)

    Traffic light:
    - GREEN: 80-100
    - YELLOW: 50-79
    - RED: 0-49
    """
```

##### "Good Enough" Thresholds (TECH-009)

```python
THRESHOLDS = {
    "per_system_minimum": 60,           # YELLOW
    "integration_minimum": 50,
    "aggregate_minimum": 65,
    "p0_remaining_max": 0,              # Hard requirement
    "p1_remaining_max": 3,
    "test_pass_rate_min": 0.85,
    "mcp_tool_coverage_min": 0.90,
    "fix_convergence_min": 0.70,
}

def is_good_enough(
    aggregate: AggregateScore,
    p0_count: int,
    p1_count: int,
    test_pass_rate: float,
    mcp_coverage: float,
    convergence: float
) -> tuple[bool, list[str]]:
    """Check all thresholds. Returns (passed, list_of_failures)."""
```

---

#### `src/run4/audit_report.py` (expand from stub, ~400 LOC)
**Implements**: REQ-037 through REQ-042

##### Report Generation (REQ-037)

```python
def generate_audit_report(
    state: Run4State,
    scores: AggregateScore,
    system_scores: dict[str, SystemScore],
    integration_score: IntegrationScore,
    fix_results: list[FixPassResult],
    rtm: list[dict],
    interface_matrix: list[dict],
    flow_coverage: list[dict],
    dark_corners: list[dict],
    cost_breakdown: dict
) -> str:
    """Generate SUPER_TEAM_AUDIT_REPORT.md with 7 sections:

    1. Executive Summary
       - Aggregate score + traffic light
       - Per-system scores
       - Fix passes executed
       - Total defects found/fixed
       - Overall verdict

    2. Methodology
       - Test approach (unit, integration, E2E)
       - Scoring rubric summary
       - Tools used (pytest, Schemathesis, Testcontainers, MCP SDK)

    3. Per-System Assessment
       - Build 1: Foundation Services
       - Build 2: Builder Fleet
       - Build 3: Orchestration Layer
       Each with: score breakdown, top defects, status

    4. Integration Assessment
       - MCP connectivity results
       - Data flow integrity
       - Contract fidelity
       - Pipeline completion status

    5. Fix Pass History
       - Per-pass metrics table
       - Convergence chart (text-based)
       - Effectiveness trend

    6. Gap Analysis
       - RTM summary (requirements covered vs gaps)
       - Known limitations
       - Recommended future work

    7. Appendices
       A. Requirements Traceability Matrix
       B. Full Violation Catalog
       C. Test Results Summary
       D. Cost Breakdown
    """
```

##### Requirements Traceability Matrix (REQ-038)

```python
def build_rtm(
    build_prds: dict[str, list[dict]],  # {build_name: [{req_id, description}]}
    implementations: dict[str, list[str]],  # {req_id: [file_path]}
    test_results: dict[str, dict]       # {req_id: {test_id, status}}
) -> list[dict]:
    """For each REQ-xxx across all 3 Build PRDs:
    - implementation file(s)
    - test ID(s)
    - test status (PASS/FAIL/UNTESTED)
    - verification status (Verified/Gap)

    Returns list of RTM entries for table rendering."""
```

##### Interface Coverage Matrix (REQ-039)

```python
def build_interface_matrix(
    mcp_test_results: dict[str, dict]
) -> list[dict]:
    """For each of 20 MCP tools:
    - valid request tested (Y/N)
    - error request tested (Y/N)
    - response parseable (Y/N)
    - status (GREEN/YELLOW/RED)

    Target: 100% valid, >= 80% error"""
```

##### Data Flow Path Coverage (REQ-040)

```python
def build_flow_coverage(
    flow_test_results: dict[str, dict]
) -> list[dict]:
    """For each of 5 primary data flows + error paths:
    1. User registration flow
    2. User login flow
    3. Order creation flow (with JWT)
    4. Order event notification flow
    5. Notification delivery flow

    Each: tested (Y/N), status, evidence"""
```

##### Dark Corners Catalog (REQ-041)

```python
async def test_dark_corners(
    config: Run4Config,
    state: Run4State
) -> list[dict]:
    """5 specific edge case tests:

    1. MCP server startup race condition
       - Start all 3 MCP servers simultaneously via asyncio.gather
       - PASS: all 3 healthy within mcp_startup_timeout_ms
       - FAIL: any server fails or deadlocks

    2. Docker network DNS resolution
       - From architect container: curl http://contract-engine:8000/api/health
       - PASS: HTTP 200
       - FAIL: DNS failure or connection refused

    3. Concurrent builder file conflicts
       - Launch 3 builders targeting separate directories
       - PASS: zero cross-directory writes
       - FAIL: any file in wrong directory

    4. State machine resume after crash
       - Run pipeline to phase 3, kill process (SIGINT)
       - Restart, verify resume from phase 3 checkpoint
       - PASS: resumes from phase 3
       - FAIL: restarts from phase 1

    5. Large PRD handling
       - Feed 200KB PRD (4x normal) to Architect decompose
       - PASS: valid ServiceMap within 2x normal timeout
       - FAIL: timeout or crash
    """
```

##### Cost Breakdown (REQ-042)

```python
def build_cost_breakdown(
    state: Run4State
) -> dict:
    """Per-phase cost and duration:
    - M1 through M6 totals
    - Grand total
    - Comparison to budget estimate ($36-66 estimated)
    - Per-phase breakdown table
    """
```

---

### Test File

#### `tests/run4/test_m6_audit.py` (~300 LOC)
**Implements**: REQ-034 through REQ-042, TECH-009, TEST-016 through TEST-018

| Test | Requirement | Description |
|------|-------------|-------------|
| `test_system_score_formula_known_inputs` | TEST-016, REQ-034 | Known inputs -> expected score: req_pass=1.0, test_pass=0.9, contract=0.8, violations=5, loc=5000, health=1.0, artifacts=5/5 |
| `test_system_score_zero_violations` | REQ-034 | violation_density=0 -> code_quality=15 (maximum) |
| `test_system_score_high_violations` | REQ-034 | violation_density>10 -> code_quality=0 |
| `test_system_score_traffic_light` | REQ-034 | score>=80 -> GREEN, 50-79 -> YELLOW, <50 -> RED |
| `test_integration_score_formula` | REQ-035 | Known inputs -> expected integration score |
| `test_integration_score_zero_violations` | REQ-035 | cross_build_violations=0 -> fidelity=25 |
| `test_integration_score_many_violations` | REQ-035 | cross_build_violations=10 -> fidelity=0 |
| `test_aggregate_score_weights` | REQ-036 | Verify weights: build1*0.30 + build2*0.25 + build3*0.25 + integration*0.20 |
| `test_aggregate_score_all_100` | REQ-036 | All systems 100 -> aggregate = 100 |
| `test_aggregate_score_all_0` | REQ-036 | All systems 0 -> aggregate = 0 |
| `test_aggregate_traffic_light` | REQ-036 | Score classification matches thresholds |
| `test_audit_report_has_all_sections` | TEST-017, REQ-037 | Generated report contains all 7 section headers |
| `test_audit_report_valid_markdown` | TEST-017 | Report is valid markdown with proper heading hierarchy |
| `test_audit_report_executive_summary` | REQ-037 | Executive summary contains scores, verdict, defect counts |
| `test_audit_report_appendices` | REQ-037 | All 4 appendices present (RTM, Violations, Tests, Cost) |
| `test_rtm_maps_all_reqs` | TEST-018, REQ-038 | RTM correctly maps Build PRD requirements to test results |
| `test_rtm_identifies_gaps` | REQ-038 | RTM marks untested requirements as "Gap" |
| `test_interface_matrix_20_tools` | REQ-039 | Matrix has 20 entries with valid/error/response columns |
| `test_interface_matrix_coverage_target` | REQ-039 | 100% valid coverage, >= 80% error coverage |
| `test_flow_coverage_5_paths` | REQ-040 | 5 primary data flows covered |
| `test_dark_corners_5_tests` | REQ-041 | 5 dark corner tests defined with PASS/FAIL criteria |
| `test_cost_breakdown_per_phase` | REQ-042 | Cost breakdown has M1-M6 entries with totals |
| `test_cost_breakdown_budget_comparison` | REQ-042 | Budget comparison against $36-66 estimate |
| `test_good_enough_all_pass` | TECH-009 | All thresholds met -> is_good_enough = True |
| `test_good_enough_p0_remaining` | TECH-009 | P0 > 0 -> is_good_enough = False (hard requirement) |
| `test_good_enough_below_aggregate` | TECH-009 | aggregate < 65 -> is_good_enough = False |

---

### Test Matrix Mapping

| Matrix ID | Test Function | Priority |
|-----------|---------------|----------|
| B3-10 | `test_budget_tracking` | P2 |

---

### Report Output

The final report is written to: `.run4/SUPER_TEAM_AUDIT_REPORT.md`

Expected structure:

```markdown
# Super Team Audit Report

## 1. Executive Summary

**Aggregate Score**: XX/100 (TRAFFIC_LIGHT)

| System | Score | Status |
|--------|-------|--------|
| Build 1 | XX/100 | GREEN/YELLOW/RED |
| Build 2 | XX/100 | GREEN/YELLOW/RED |
| Build 3 | XX/100 | GREEN/YELLOW/RED |
| Integration | XX/100 | GREEN/YELLOW/RED |

**Fix Passes**: N executed
**Defects**: N found, N fixed, N remaining
**Verdict**: PASS/CONDITIONAL_PASS/FAIL

## 2. Methodology
...

## 3. Per-System Assessment
### 3.1 Build 1: Foundation Services
...
### 3.2 Build 2: Builder Fleet
...
### 3.3 Build 3: Orchestration Layer
...

## 4. Integration Assessment
### 4.1 MCP Connectivity
...
### 4.2 Data Flow Integrity
...
### 4.3 Contract Fidelity
...
### 4.4 Pipeline Completion
...

## 5. Fix Pass History
...

## 6. Gap Analysis
### 6.1 RTM Summary
...
### 6.2 Known Limitations
...
### 6.3 Recommended Future Work
...

## 7. Appendices
### Appendix A: Requirements Traceability Matrix
...
### Appendix B: Full Violation Catalog
...
### Appendix C: Test Results Summary
...
### Appendix D: Cost Breakdown
...
```

---

### Dependencies on M5

| M5 Output | M6 Usage |
|-----------|----------|
| Finding catalog | Violation catalog for appendix B |
| Fix pass results | Fix pass history section, convergence data |
| Final violation counts | P0/P1/P2 counts for scoring and thresholds |
| Convergence metrics | Convergence assessment in report |

### Dependencies on All Milestones

| Milestone | Data Consumed |
|-----------|--------------|
| M1 | Config, state, fixture validation results |
| M2 | MCP tool test results (20 tools), wiring status |
| M3 | Builder invocation results, config compatibility |
| M4 | Pipeline phase results, Docker health, contract compliance |
| M5 | Defect catalog, fix pass metrics, convergence |

### Risk Analysis

| Risk | Impact | Mitigation |
|------|--------|------------|
| Incomplete data from prior milestones | Report has gaps | Mark gaps explicitly in report |
| Scoring formula edge cases (division by zero) | Crash | Guard all divisions with max(1, denominator) |
| Large violation catalog | Report too long | Summarize in body, full list in appendix |
| RTM mapping errors | Wrong traceability | Cross-reference against PRD REQ-IDs |

### Gate Condition

**Milestone 6 is COMPLETE when**:
- All TEST-016 through TEST-018 pass
- `SUPER_TEAM_AUDIT_REPORT.md` is generated at `.run4/SUPER_TEAM_AUDIT_REPORT.md`
- Report contains all 7 sections and 4 appendices
- All scores are computed and traffic lights assigned
- `is_good_enough()` evaluation is complete (pass or fail with documented reasons)

**RUN 4 IS COMPLETE when Milestone 6 gate condition is met.**
