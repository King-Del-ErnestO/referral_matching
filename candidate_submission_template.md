# Decision Note — DevSageSenior

## What I investigated

- Reviewed the referral-matching pilot brief and the operations dry-run reports to identify launch risks.
- Focused on the backend flow for webhook intake, eligibility filtering, offer lifecycle, and claim assignment.
- Confirmed the most damaging issues were: duplicate upstream deliveries, a claim system that could leave referrals in an inconsistent state, and stalled referrals after decline or expiry.
- Traced the relevant logic across the matching, claim, webhook, and view layers to isolate the root causes before changing behavior.

## What I prioritized, and why

1. Duplicate webhook intake protection.
   - Upstream retries are expected, so robust deduplication is a launch-safety requirement.
   - I added persisted duplicate detection to avoid creating the same referral twice.

2. Atomic claim handling.
   - A referral must never be assigned to two agents or leave a partially accepted state behind a notification error.
   - I tightened the claim flow so the assignment, claim creation, and offer state update are handled together and fail safely.

3. Re-queuing after decline/expiry.
   - A referral stuck in "offered" after the first eligible agent declines or lets the offer expire is a missed referral and an operational failure.
   - I gated re-offering logic so the workflow can continue to another eligible candidate without re-opening already assigned referrals.

4. Dashboard performance cleanup.
   - The Operations dashboard was doing unnecessary repeated lookups during listing, which made it feel unreliable under load.
   - I reduced the query overhead with prefetching and cleaner nested serialization.

## What I intentionally deferred

- I did not broaden the scope to a large redesign of the frontend or notification stack.
- I did not attempt to solve every theoretical edge case in the broader pilot; instead, I focused on the highest-risk launch problems and left the app in a coherent state.
- I did not add new product workflows beyond what was necessary to keep the referral lifecycle safe and auditable.

## Assumptions

- Upstream retry delivery behavior is expected and should be idempotent at the referral-ingest boundary.
- If a notification or downstream side effect fails after a claim is created, the app should fail closed rather than leave a referral in a misleading state.
- The Operations dashboard is read-heavy and should prioritize efficient prefetching over additional UI complexity within the time box.

## How I validated my work

- Added focused regression tests for duplicate webhook intake and claim handling.
- Verified the edited Python files compile cleanly with the project environment:

```bash
Set-Location 'c:\Users\JEIC Technologies\Desktop\clever real estate\referral-matching-trial'
.\.venv\Scripts\python -m py_compile backend\referrals\claims.py backend\referrals\webhooks.py backend\referrals\matching.py backend\referrals\views.py backend\referrals\serializers.py backend\referrals\tests\test_webhook.py backend\referrals\tests\test_claims.py
```

- Targeted backend checks to run in a full local setup:

```bash
cd backend
python -m pytest referrals/tests/test_webhook.py referrals/tests/test_claims.py
```

- I also attempted to run the Postgres-backed Django suite in the local environment, but Docker/Postgres was unavailable in this session, so full DB validation remains to be completed in a machine with Docker enabled.

## AI usage

- I used AI assistance to quickly trace the likely root causes across the webhook, matching, and claim flow.
- It was especially useful for narrowing the bug locations and drafting a small set of regression tests.
- I checked the output against the actual code paths in the repo and verified the behavior with compile-time validation and targeted evidence before relying on it.
- The main risk was over-generalizing the fix; I reduced that by keeping the changes scoped to the identified launch-safety gaps.

## Remaining launch risks

- A full end-to-end Postgres-backed verification still needs to be run in an environment with Docker available.
- The notification gateway still represents a real operational dependency; if it fails, the system should continue to surface clear error states and visible audit events.
- I would continue by validating the full operations dashboard and claim flow against seed data once the DB environment is available, especially around stale offers and override behavior.
