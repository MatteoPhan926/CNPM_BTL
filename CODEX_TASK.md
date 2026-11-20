# SMART E-MOBILITY HUB — NEXT IMPLEMENTATION PHASE

## TASK

Continue from the actual current workspace, its UI prototype, submitted Assignments #1–#3 and supplementary integration/design artifacts.

**Build a genuinely functional, integrated MVP for Roles A, B and C:**

- **A — UC-A01–A07:** rental, reservations and journeys.
- **B — UC-B01–B05:** parking rights, occupancy and Hub capacity.
- **C — UC-C01–C03:** charging registration, session management and scheduling.

The starting workspace has design artifacts and a static UI prototype, not an established working application. Treat this as an implementation task rather than a request for further diagrams.

## INVESTIGATE INDEPENDENTLY

Inspect the sources and current files before choosing an approach. Reconstruct requirements, shared state and dependencies. Identify spec/design conflicts, hidden assumptions, missing prerequisites and possible simplifications.

Treat prior architectural decisions as hypotheses to validate, not mandatory instructions. Do not impose a predetermined framework, database, folder layout or fixed service architecture merely because it appears in an earlier document.

## MULTI-AGENT STRATEGY

Use independent agents dynamically where useful. Explore materially different implementation options before convergence, and use adversarial review to test architectural and correctness assumptions. The root agent owns integration decisions and reconciliation against the actual requirements.

## IMPLEMENT

Build working end-to-end flows for A/B/C across the UI, application logic and persisted/shared state. Prefer the simplest coherent solution that preserves the required behaviors and leaves clean integration boundaries.

Role D is outside the implementation scope. Make dependencies on D and physical/IoT verification honest and explicit; do not report unverified physical actions as confirmed. A controlled simulator or stub may be used only when its behavior and limitations are unmistakable and independently tested.

## VALIDATE

Test against submitted use cases and business rules, including conflicts, concurrency, duplicate operations, stale observations, authorization and ambiguous outcomes. Verify actual user journeys rather than only isolated unit tests. Rerun tests after substantive fixes; report failures and gaps candidly.

## SUCCESS CRITERION

A locally runnable, integrated A/B/C MVP with real working user journeys, meaningful persistent state, reproducible tests and clear limitations. Static screens, renamed components, fake success messages or test plans alone are not sufficient.

## OUTPUT

Implement directly in this workspace. End with a concise report of what works, run/test commands, architectural choices and deviations from specifications, verified evidence, remaining Role D dependencies and the most valuable next phase.
