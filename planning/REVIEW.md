# Review of `PLAN.md`

## High priority

1. **Define the deployment security boundary ( §§2, 8, 9, 11).** The app has no login, exposes reset/trading/chat actions, and may execute LLM-requested trades automatically. Docker's `8000:8000` commonly publishes on every host interface, so the app may be reachable by other machines on the network. Specify a loopback-only port binding for the local workstation setup, or document the intended network exposure and protections. Also clarify that this is simulated trading and that the LLM must not claim actions succeeded until backend results confirm them.

2. **Resolve the Massive-mode add-then-trade contradiction ( §§6, 9).** Chat action ordering says a newly added ticker can be traded in the same response, but Massive mode explicitly has no price until a later poll. Such a trade will fail the no-cached-price rule. Define the behavior: e.g. return a clear failed action, defer trades (which requires asynchronous job/status handling), or disallow same-response trades until a price exists. Avoid promising immediate pricing outside simulator mode.

3. **Specify chat-history inclusion precisely ( §9, steps 1–5).** The flow stores the new user message, then loads the last 20 messages, and also says the prompt includes the user's new message. This can send the same message twice. State whether history is fetched before insertion or whether the new message is excluded from the history before appending it once.

## Medium priority

4. **Make portfolio snapshot semantics consistent with live valuation ( §§7–8, 10).** Portfolio values are recomputed client-side from live SSE prices, while snapshots are written every 30 seconds and after trades. Clarify that snapshots use the latest available cache prices and can lag live values, and define startup behavior when a held ticker has no price yet (the API fallback is `avg_cost`). Otherwise the P&L chart can appear to disagree with the header/table.

5. **Define reset behavior for in-memory market state ( §§6–8, 10).** Reset says to re-sync default tickers and clear sparklines, but does not say whether the price cache/history and session-open values are cleared. Specify whether reset is account-only (likely, preserving market session history) or also resets market state; align the frontend reset behavior with that choice.

6. **Clarify startup seeding versus user edits ( §7).** `INSERT OR IGNORE` is safe for existing rows, but the plan should explicitly say startup must not restore default watchlist entries after a user removes them. The profile seed should likewise initialize only a missing profile, never reset an existing cash balance.

7. **Define API ticker normalization consistently ( §§7–8).** Trade rules normalize ticker input, while watchlist routes only say malformed tickers return `400`, and DELETE behavior does not say whether path tickers are normalized. Specify one normalization/validation rule for all routes, including duplicates, and state how unsupported/nonexistent symbols behave in Massive mode.

## Lower priority / implementation clarity

8. **State the single-process requirement for in-memory market data ( §§3, 6, 11).** The price cache and market poller are process-local. Document one Uvicorn worker as a deployment requirement unless the cache/stream architecture is later made shared; multiple workers would otherwise show different prices and ticker tracking.

9. **Clarify snapshot retention and chart bounds ( §§7–8, 10).** Snapshots are described as never pruned, and history returns all snapshots oldest-first. At roughly 2,900 rows per day, define a retention or response-window policy (and pagination if needed) before long-running use makes every chart load an ever-growing dataset.

10. **Define whether an LLM response with empty action arrays has `actions: null` or an empty object ( §§8–9).** The frontend refresh rule keys off non-null `actions`; make the persisted/returned representation deterministic for no-op responses and responses where all proposed actions fail.

## Overall

The plan gives agents a useful shared contract and has good detail on trade rules, response shapes, and frontend data flow. The highest-risk ambiguities are the unauthenticated network boundary, chat action behavior when Massive has not priced a new ticker, and duplicate inclusion of the current chat message. Resolving those before implementation should prevent security surprises and divergent interpretations across agents.
