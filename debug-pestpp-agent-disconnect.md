# Debug Session: pestpp-agent-disconnect
- **Status**: [OPEN]
- **Issue**: Two-spring default-N calibration entered a Panther stall: manager kept running while agents eventually disconnected, and the controller did not fail fast enough to prevent a long apparent hang.
- **Debug Server**: http://127.0.0.1:7777/event
- **Log File**: .dbg/trae-debug-log-pestpp-agent-disconnect.ndjson

## Reproduction Steps
1. Launch `tools/calibration/run_e02_spring_pair_defaultn_v1.py --n-reals 150 --noptmax 5 --n-agents 7 --execute`.
2. Observe the failing run `workspace/runs/e02_spring_pair_defaultn_v1_observedshape_150x5_20260730`.
3. Compare manager and agent logs around the late-stage stall window.

## Hypotheses & Verification
| ID | Hypothesis | Likelihood | Effort | Evidence |
|----|------------|------------|--------|----------|
| A | Controller only fails after agent processes fully exit, so a disconnected-but-still-alive Panther loop looks like a hang | High | Low | Partially confirmed from old run logs; runtime instrumentation added |
| B | Manager enters a stable `T>0, W=0, U=0` stall while all agents repeatedly report `receive from master failed` | High | Low | Confirmed from old run logs at 21:09:49-21:10:15 onward |
| C | Host/port session becomes half-open on Windows, leaving master alive but unable to serve workers | Medium | Medium | Supported by `receive from master failed: 198.18.0.1:4010`; root trigger still inconclusive |
| D | Failure cleanup leaves confusing residual state after the stall and masks the real failure point | Medium | Low | Confirmed in effect; controller ends as `runtime_failed` after delayed exception path |

## Log Evidence
- Manager log: `panther_manager.stdout.log` first reaches `runs(C44|F0|T1) agents(R7|W0|U0)` at 2026-07-30 21:09:49.
- Agent log: `agent_01/panther_agent.stdout.log` first reports `receive from master failed: 198.18.0.1:4010` at 2026-07-30 21:10:15.
- Controller status: `run_status.json` finally records `parallel_controller_exception` only after all agents exit.

## Verification Conclusion
- Pre-fix evidence indicates the main bug is not a single dead worker; it is a missing stall detector in the controller.
- Instrumentation was added to `tools/parallel/run_parallel.py` to record manager/agent lifecycle and stall signatures to the debug server.
- Minimal fix added: when manager progress remains at `T>0, W=0, U=0` and all agents are in `receive from master failed` state for a sustained timeout, abort early with a traceable controller error instead of waiting indefinitely.
