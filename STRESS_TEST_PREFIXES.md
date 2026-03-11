# Pre-Stress-Test Quick Fixes

Applied during codebase research phase (Step 1) in preparation for the SupplyForge stress test run.

| # | File | What Was Wrong | What You Fixed | Tests Run | Pass? |
|---|------|---------------|---------------|-----------|-------|
| 1 | `src/integrator/compose_generator.py:533-536` | Per-service memory limit 768MB prevents running 9 services within 4.5GB TECH-006 budget (768×9=6912MB > 4500MB) | Reduced `mem_limit` and `deploy.resources.limits.memory` from `"768m"` to `"384m"` per app service. Infrastructure unchanged (Traefik 256MB, PostgreSQL 512MB, Redis 256MB). New total: 384×9 + 1024 = 4480MB < 4500MB. | `pytest tests/ -k "compose"` — 237 passed, 0 failed (12.34s) | ✅ |

## Notes

- Fix #1 is required for the stress test since 9 app services at 768MB each (6,912MB) would vastly exceed the 4.5GB total RAM budget. At 384MB per service, runtime memory is still generous (FastAPI/NestJS typically use 50-200MB at runtime; 384MB provides ~2x headroom).
- No other quick fixes were identified as strictly necessary. The PRD was designed to use parser-optimal formatting, avoiding all known parser edge cases (ambiguous prose entities, multi-word entity names with spaces, vague state definitions).
