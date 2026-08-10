# Assumptions & Trade-offs

Documented decisions where the spec or data was ambiguous. Each is encoded in
code with a pointer back here, and covered by tests where behavior-affecting.

1. **Consultation sub-limit binds the consultation-fee line item, not the whole
   claim.** TC010 approves ₹3,240 on a consultation claim (whole-claim cap at
   the ₹2,000 sub-limit would contradict it); TC004 is consistent. Other
   categories cap the whole claim at their sub-limit.

2. **`rejection_reasons` carries the primary reason only.** All violated rules
   still appear in `checks` and the trace. TC007 breaches both pre-auth and
   the per-claim cap but expects `[PRE_AUTH_MISSING]` — primary = first
   failing check in the §6 order.

3. **Test mode trusts declared ground truth.** `actual_type`, `quality`,
   `content`, `patient_name_on_doc` in test cases bypass vision extraction;
   the trace records the skip. Real uploads take the GPT-4o path behind the
   same contracts.

4. **Payload-supplied `ytd_claims_amount` / `claims_history` are trusted over
   DB state** (test determinism; production would join the store's history).

5. **Per-claim limit = `max(per_claim_limit, category sub_limit)`, checked on
   the eligible amount after excluded line items are removed.** A naive
   "claimed > ₹5,000 → reject" breaks TC006 (dental ₹12,000 → expected PARTIAL
   ₹8,000, itself above ₹5,000) while TC008 (consultation ₹7,500 → REJECTED)
   demands the hard check. This reconciliation satisfies all 12 cases; the
   check therefore runs after line-item adjudication.

6. **Exclusions are checked before waiting periods.** "Morbid Obesity" (TC012)
   matches both the obesity exclusion and the `obesity_treatment` waiting
   period; the permanent rule must win the primary reason over the time-bound
   one.

7. **Missing `submission_date` defaults to the treatment date.** Test cases
   carry no submission date; evaluating "today − treatment date" would fail
   every 2024-dated case. Production submissions stamp the actual date.

8. **Roster gaps are tolerated.** `policy_terms.json` references dependents
   DEP003–DEP006 that are not defined in `members`. Lookups skip them; a
   consistent-but-unknown patient name on documents is a review warning, not a
   rejection (the undefined dependents make a hard check unsafe).

9. **Diagnosis matching is exact-token, not substring**, with medical
   shorthand expanded first (HTN, T2DM). "Herniation" must not match the
   `hernia` waiting period; "Chronic Joint Pain" must not match
   `joint_replacement` (all distinctive tokens of a condition key required).

10. **All three stores (Neon Postgres, Qdrant, Neo4j) are integrated but
    optional.** Each activates via env vars and falls back per the resilience
    table; the 12-case eval intentionally runs on the deterministic tier so
    it is reproducible with zero accounts. Semantic hits are candidates the
    engine threshold-checks — the token tier wins whenever it matches.

11. **TC011's simulated failure hits the fraud checker** — the least critical
    stage (its absence can only under-flag, never mis-pay). The degradation
    machinery (skip, trace, −0.20 confidence, review recommendation) is the
    same code path a real outage takes.

12. **Member details are resolved from the roster, not collected at intake.**
    A submission carries `member_id`; name, join date and dependents come from
    `policy_terms.json`, which the spec names as authoritative. Re-collecting
    them on the form would duplicate the roster and create a conflict with no
    correct resolution when the two disagree. The details do real work once
    resolved: `join_date` drives every waiting-period date (TC005's eligibility
    date is computed, never supplied), and the roster name plus registered
    dependents are the set the patient name read off the documents is checked
    against — identity is verified against evidence rather than against a field
    the claimant types.

13. **A claim cannot declare which covered person it is for.** The patient is
    inferred from the names on the documents, which is why a claim for a
    dependent must carry that dependent's name throughout (TC003's guidance
    says so explicitly). Adequate for per-member rules; per-person logic
    (dependent sub-limits, age-based rules) would need a declared `patient_id`
    validated against `eligible_patients()`. No assignment case claims for a
    dependent, so the field is deliberately not built.

14. **Sub-limit/annual caps beyond the 12 cases** (e.g. consultation fee above
    ₹2,000 combined with discounts) follow the documented order
    (discount → co-pay → sub-limit → annual) with the excess scaled by the
    discount/co-pay factors; unit-tested, though no assignment case exercises
    them.
