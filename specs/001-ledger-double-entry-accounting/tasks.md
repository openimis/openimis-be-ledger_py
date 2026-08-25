---

description: "Task list for implementing the Ledger Double-Entry Accounting Module"
---

# Tasks: Ledger Double-Entry Accounting Module

**Input**: Design documents from `/specs/001-ledger-double-entry-accounting/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md (all present)

**Tests**: Included — the repository's `CLAUDE.md` mandates unit tests for every new function, so test tasks are generated alongside implementation for each user story.

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- File paths are relative to the repository root (`openimis-be-ledger_py/`), following the module layout in `plan.md`

## Path Conventions

Single Django app module: `ledger/` (app package) with `models.py`, `services.py`, `signals/`, `replication/`, `export/`, `gql_queries.py`/`gql_mutations.py`/`schema.py`, `admin.py`, `migrations/`, `tests/`, at the repository root, per `plan.md`'s Project Structure.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project/package initialization

- [ ] T001 Create the `ledger` Django app package skeleton (`ledger/__init__.py`, `ledger/apps.py` with `LedgerConfig` + `DEFAULT_CFG` permission keys, `ledger/models.py`, `ledger/migrations/__init__.py`) per plan.md's Project Structure
- [ ] T002 Write `setup.py` at repo root declaring `openimis-be-ledger` package metadata and dependencies (`django`, `django-hordak`, `django-db-signals`, `djangorestframework`, `graphene-django`, `celery`, `kombu`, `psycopg2`, `openimis-be-core`)
- [X] T003 [P] ~~Add `ledger` to a local dev `openimis.json`/requirements reference so it installs alongside `openimis-be-core`, `django-hordak`, and a source module (e.g. `openimis-be-claim`) for integration testing~~ — N/A: `openimis.json` belongs to the umbrella `openimis-be_py` project, not this repo; out of scope here (2026-07-27 review)
- [ ] T004 [P] Configure linting/formatting (`.flake8` or `pyproject.toml` black/isort config) consistent with sibling openIMIS modules

**Checkpoint**: Package installs and Django recognizes the `ledger` app.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core schema and infrastructure shared by every user story — django-hordak integration, journals, periods, analytic tagging, deployment config, and the partitioning/trigger migrations. No user story can be implemented until this phase is complete.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T005 Add `django-hordak` to `INSTALLED_APPS` wiring notes and run its migrations in the dev environment (document in `ledger/README.md`); confirm `Account`/`Transaction`/`Leg` tables exist
- [ ] T006 Implement `AccountingPeriod` model (`start_date`, `end_date`, `status` enum, `closing_transaction` FK, audit fields) in `ledger/models.py`
- [ ] T007 [P] Implement `LedgerJournal` model (`code`, `name`) in `ledger/models.py`
- [ ] T008 [P] Implement `AnalyticAxis` and `AnalyticValue` models (`party`/`funder` axis, `party_type`/`funder_code`, `external_reference`, `display_name`) in `ledger/models.py`
- [X] T009 [US-shared] Implement `LegTag` model (FK to Hordak `Leg`, FK to `AnalyticValue`, unique-per-axis constraint) in `ledger/models.py` (depends on T008) — DB-level `UniqueConstraint(leg, axis)` in place (`models.py:298-302`) and `save()` now calls `self.clean()` before persisting (`models.py:267`), so the applicative check is actually exercised, not just defined (2026-08-03 review)
- [ ] T010 Implement `LedgerEntryMeta` model (one-to-one to Hordak `Transaction`, FKs to `LedgerJournal`/`AccountingPeriod`, `source_event_type`, `source_event_reference`, `posted_at`) in `ledger/models.py` (depends on T006, T007)
- [ ] T011 [P] Implement `DeploymentConfiguration` model (`operating_mode`, `external_system`, `currency_code`, `retained_earnings_account`) in `ledger/models.py`
- [ ] T012 Generate initial Django migration for T006–T011 models in `ledger/migrations/0001_initial.py`
- [ ] T013 Write a migration in `ledger/migrations/0002_partition_leg.py` applying Postgres declarative range partitioning to Hordak's `Leg` table, partitioned by `accounting_period_id`, with a partition created per `AccountingPeriod` (per research.md §4)
- [ ] T014 Write a migration in `ledger/migrations/0003_balance_trigger.py` adding/confirming the deferrable Postgres trigger enforcing debit=credit balance on `Transaction`/`Leg` (verifying Hordak's own trigger is active; add a defense-in-depth closed-period write-rejection trigger per data-model.md's validation rules)
- [X] T015 [P] ~~Register `AccountingPeriod`, `LedgerJournal`, `AnalyticAxis`, `AnalyticValue`, `DeploymentConfiguration` in `ledger/admin.py`~~ — N/A: no other openIMIS backend module uses Django Admin; the frontend/GraphQL surface is the only UI convention here (2026-07-27 review)
- [ ] T016 [P] Unit tests for `AccountingPeriod`/`LedgerJournal`/`AnalyticAxis`/`AnalyticValue`/`LegTag`/`DeploymentConfiguration` model validation (uniqueness, axis constraint) in `ledger/tests/test_foundational_models.py`
- [ ] T017 Unit/DB test proving the balance trigger rejects an unbalanced `Transaction`/`Leg` insert and that partitions exist per period, in `ledger/tests/test_partitioning.py` (depends on T013, T014)
- [ ] T018 Implement base `LedgerEntryService` in `ledger/services.py` with a `post(journal, accounting_period, source_event_type, source_event_reference, legs, tags)` method that validates the target period is `open` (FR-008), constructs the Hordak `Transaction`/`Leg`s and `LedgerEntryMeta`, attaches `LegTag`s, and is decorated with `@register_service_signal("ledger_service.post_entry")` (depends on T009, T010)
- [ ] T019 [P] Unit tests for `LedgerEntryService.post()` covering: successful balanced post, rejection into locked/closed period, rejection of missing account mapping (FR-022) in `ledger/tests/test_ledger_entry_service.py` (depends on T018)

**Checkpoint**: Foundation ready — `LedgerEntryService.post()` can create valid, DB-enforced-balanced entries into an open period; user story implementation can now begin.

---

## Phase 3: User Story 1 - Automatic ledger posting from financial events (Priority: P1) 🎯 MVP

**Goal**: Every claim payment, invoice, payroll disbursement, and payment-point reconciliation event automatically produces a balanced ledger entry in the correct journal, with zero-value events skipped and unmappable events surfaced for manual resolution.

**Independent Test**: Trigger a claim payment (or invoice/payroll/payment-point event) and verify a balanced `LedgerEntryMeta`/`Transaction` appears in the correct journal, referencing the source event; verify a zero-amount event produces none.

### Tests for User Story 1

- [~] T020 [P] [US1] Integration test: firing the claim-payment service signal produces exactly one balanced `LedgerEntryMeta` in the correct journal, in `ledger/tests/test_posting.py` — partial: `test_claim_valuated_posts_balanced_entry` (`test_posting.py:105-144`) calls `on_claim_valuated(...)` directly rather than dispatching a real Django/service signal, so `bind_service_signals()` wiring is never exercised; the balance/journal assertions themselves are real (2026-08-04 review)
- [~] T021 [P] [US1] Integration test: firing the invoice-issued service signal posts to the Sales journal, in `ledger/tests/test_posting.py` — partial: same direct-call limitation as T020 (`test_posting.py:150-168`); also weaker than T020 (only checks `journal.code == "Sales"`, no balance/amount assertion) (2026-08-04 review)
- [~] T022 [P] [US1] Integration test: firing the payroll-disbursed service signal posts expense + bank legs, in `ledger/tests/test_posting.py` — partial: direct-call, not real signal dispatch (`test_posting.py:174-198`); checks `legs.count() == 2` but the test fixtures reuse the same generic accounts across journals, so "expense vs bank" account distinction isn't actually demonstrated (2026-08-04 review)
- [~] T023 [P] [US1] Integration test: firing the payment-point-reconciled service signal posts to the Bank journal including a variance leg when applicable, in `ledger/tests/test_posting.py` — partial: direct-call, not real signal dispatch (`test_posting.py:204-228`); variance-leg count assertion is real, but no balance assertion (2026-08-04 review)
- [X] T024 [P] [US1] Unit test: a zero-amount event of each type produces no `LedgerEntryMeta` (Clarification 2026-07-10), in `ledger/tests/test_posting.py` — done: all 4 handlers covered with real `assertFalse(LedgerEntryMeta.objects.exists())` assertions (`test_posting.py:234-303`) (2026-08-04 review)
- [X] T025 [P] [US1] Unit test: an event with no chart-of-accounts mapping is surfaced for manual resolution rather than posted (FR-022), in `ledger/tests/test_posting.py` — done: now covers all 4 handlers (`test_unmapped_claim_valuated_event_is_surfaced`, `test_unmapped_invoice_event_is_surfaced`, `test_unmapped_payroll_event_is_surfaced`, `test_unmapped_reconciliation_event_is_surfaced`, lines 394-537) (2026-08-17 review)

### Implementation for User Story 1

- [X] T026 [US1] Create `ledger/signals/__init__.py` with `bind_service_signals()` skeleton and account/journal-mapping lookup helper, per contracts/service-signals.md — done: `bind_service_signals()` + `resolve_mapping()`/`resolve_accounts()` present; mapping is a hardcoded dict placeholder, acceptable per its own comment (2026-08-04 review)
- [X] T027 [US1] Implement `on_claim_payment(sender, **kwargs)` handler in `ledger/signals/__init__.py`: resolve period/account mapping, skip if zero amount, call `LedgerEntryService.post()` tagged with Health Facility party and funder if resolvable (depends on T018, T026) — done as of 2026-08-17: implemented as `on_claim_valuated` (`signals/__init__.py:120-228`); `get_open_period()` (lines 75-85) now resolves the period by the claim's `date_claimed` against `start_date`/`end_date` rather than grabbing the latest open period, with `raise_unmapped()` fallback when no period covers that date; Health Facility party tag and (if an active `PolicyHolder` exists) funder tag are now resolved and passed via `tags=` (lines 173-210) — previously-noted gaps are closed (2026-08-17 review)
- [~] T028 [US1] Implement `on_invoice_issued(sender, **kwargs)` handler in `ledger/signals/__init__.py`, posting to the Sales journal (depends on T018, T026) — partial as of 2026-08-17: the earlier `raise_unmapped(..., "user")` literal-string bug is fixed (now passes the real `user` object, `signals/__init__.py:256,263,277`), and period resolution/party tagging are implemented; but **new real bug**: lines 279-286 build `tags = {0: [party_tag], 1: [party_tag]}` unconditionally, unlike the other 3 handlers which guard with `if party_tag:` — when `resolve_party_tag()` returns `None` (unmatched `health_facility_id`), `LedgerEntryService.post()` is called with `analytic_value=None`, which violates `LegTag.analytic_value`'s non-nullable FK (`models.py:245-250`) and raises instead of posting. Untested: both `test_invoice_issued_posts_to_sales_journal` and `test_invoice_posts_party_tag` mock `resolve_party_tag` to always return a real value, so this path is never exercised (2026-08-17 review)
- [X] T029 [US1] Implement `on_payroll_disbursed(sender, **kwargs)` handler in `ledger/signals/__init__.py`, posting expense/bank legs (depends on T018, T026) — done as of 2026-08-17: handler present (`signals/__init__.py:311-392`), posts 2 legs, now resolves and guards Payment Point Manager party tag with `if party_tag:` before passing `tags=` (lines 360-371), tested by `test_payroll_posts_payment_point_manager_tag` (2026-08-17 review)
- [X] T030 [US1] Implement `on_payment_point_reconciled(sender, **kwargs)` handler in `ledger/signals/__init__.py`, posting to the Bank journal with variance handling (depends on T018, T026) — done as of 2026-08-17: handler present (`signals/__init__.py:394-496`), variance legs implemented, Payment Point Manager party tag resolved and guarded with `if party_tag:` (lines 472-483), tested by `test_reconciliation_posts_payment_point_manager_tag`; no funder tagging here, which matches the contract's party-only scope for this event (2026-08-17 review)
- [X] T031 [US1] Bind all four handlers to their source-module service signals in `bind_service_signals()`, resolving exact signal names against the source modules (depends on T027–T030) — done: `bind_service_signals()` (`signals/__init__.py:498-522`) calls `bind_service_signal(...)` with the correct API (`ServiceSignalBindType.AFTER`) for all 4 handlers, using real upstream signal names. No cross-repo end-to-end dispatch test exists (T020-T023 call handlers directly), but that's a test-coverage gap tracked separately, not a reason to hold T031 open (2026-08-04 review)
- [X] T032 [US1] Implement manual-mapping-resolution surfacing: raise/log a structured `UnmappedFinancialEvent` record or exception path when account mapping is missing (FR-022) in `ledger/signals/__init__.py` and `ledger/models.py` (depends on T026) — done: `UnmappedFinancialEvent` model (`models.py:412-435`, migration `0003_unmappedfinancialevent_and_more.py`) with `event_type`/`source_reference`/`payload`/`status`; `raise_unmapped()` creates and saves it (`signals/__init__.py:50-71`), now tested for all 4 handlers (T025 above) (2026-08-17 review)
- [X] T033 [US1] Add logging for each posting handler (event received, entry posted, skipped-zero, unmapped) in `ledger/signals/__init__.py` — done: each handler logs received/skipped-zero/posted, `raise_unmapped()` logs a structured warning; the leftover debug `print(...)` line has been removed (2026-08-17 review)
- [X] T033a [US1] Cleanup pass on `ledger/signals/__init__.py` — done as of 2026-08-17: (1) the leftover `print("payload ", payload, " and ", event_type)` debug line is gone; (2) the stale commented-out hypothetical signal definitions are gone, `bind_service_signals()` is clean; (3) `on_invoice_issued`'s `raise_unmapped(..., "user")` literal-string bug is fixed, now passes the real user object. Superseded by a new, different bug in T028 (unconditional `tags` with a possibly-`None` party_tag) — tracked there rather than reopening this cleanup task (2026-08-17 review)

**Checkpoint**: User Story 1 fully functional and independently testable — this is the MVP.

---

## Phase 4: User Story 2 - Party and funder tagging for sub-ledger and profitability reporting (Priority: P2)

**Goal**: Party and funder tags on entry lines are independently queryable, backed by fast pre-aggregated balances.

**Independent Test**: Post entries with varied party/funder tag combinations, then query a party's sub-ledger and a funder's activity report and confirm correct, independent filtering.

### Tests for User Story 2

- [x] T034 [P] [US2] Unit test: `PartyLedgerBalance` updates incrementally and correctly on each tagged `Leg` insert, in `ledger/tests/test_ledger_entry_service.py` (`test_post_updates_party_balance`)
- [x] T035 [P] [US2] Unit test: `AccountBalanceSnapshot` updates incrementally per account/period, in `ledger/tests/test_ledger_entry_service.py` (`test_post_updates_account_balance_snapshot`)
- [x] T036 [P] [US2] Integration test: a line tagged with both party and funder is independently queryable on each axis, in `ledger/tests/test_tagging.py` — done as of 2026-08-21: `PostingTaggingTest.test_claim_valuated_tags_party_and_funder_on_same_legs` and `test_claim_valuated_party_and_funder_are_independently_queryable` post a real `claim_valuated` event tagging the same legs with both PARTY and FUNDER, then query each axis independently and assert they resolve to the same leg set (2026-08-21 review)
- [x] T037 [P] [US2] Integration test: an untagged line is excluded from party/funder-filtered reports but included in general ledger totals, in `ledger/tests/test_gql_queries.py` — done: `test_ignores_untagged_leg_on_same_account` (line 369) now covers exactly this case, and the underlying resolver bug it was written against is fixed (see T042) (2026-08-18 review)
- [x] T038 [P] [US2] GraphQL contract test for `ledgerEntries`, `partyLedgerBalance`, `funderActivityReport` queries in `ledger/tests/test_gql_queries.py` — done as of 2026-08-21: `funderActivityReport` well covered (`FunderActivityReportQueryTest`, 12 tests); `partyLedgerBalance` covered (`PartyLedgerBalanceQueryTest.test_returns_all_balances`); `ledgerEntries` gap closed by `ledger/tests/test_ledger_entries_filters.py` (`test_ledger_entries_filter_by_party`, `test_ledger_entries_filter_by_funder`), which posts a real tagged transaction via `LedgerEntryService.post()` and asserts the `party`/`funder` GQL filters added in T042 (2026-08-21 review)

### Implementation for User Story 2

- [x] T039 [P] [US2] Implement `PartyLedgerBalance` model in `ledger/models.py` and migration in `ledger/migrations/0004_balance_tables.py` (delivered via `ledger/migrations/0006_partyledgerbalance_historicalpartyledgerbalance_and_more.py`)
- [x] T040 [P] [US2] Implement `AccountBalanceSnapshot` model in `ledger/models.py` (same migration as T039)
- [x] T041 [US2] Implement synchronous balance-maintenance logic in `LedgerEntryService.post()` that upserts `PartyLedgerBalance`/`AccountBalanceSnapshot` rows within the same DB transaction as the `Leg` insert (depends on T018, T039, T040)
- [X] T042 [US2] Implement `ledger/gql_queries.py` with `ledgerEntries(journal, accountingPeriod, party, funder, sourceEventType)`, `partyLedgerBalance(analyticValueId, accountingPeriod)`, `funderActivityReport(analyticValueId, accountingPeriod)` resolvers, per contracts/graphql-api.md (depends on T039, T040, T041) — done as of 2026-08-19: `ledgerEntries` has real `filter_fields` (source_event_type, posted_at, journal__*/accounting_period__* prefixes, and `transaction__legs__analytic_tags__analytic_value__id`/`__axis__code` for party/funder filtering), untested but functionally in place (see T038); `funderActivityReport` aggregates `Leg.debit`/`Leg.credit` directly for tagged legs, fixing the earlier data-leakage bug (tested); previously-noted gap — `PartyLedgerBalanceGQLType.filter_fields` empty — is now fixed with `analytic_value__*`/`accounting_period__*` prefixed filters and covered by `test_returns_all_balances` (2026-08-19 review)
- [x] T043 [US2] Wire query types/root into `ledger/schema.py` (depends on T042) — done as of 2026-08-18: `ledger/schema.py` now defines a real `Query(graphene.ObjectType)` exposing `party_ledger_balance`, `ledger_entries`, and `funder_activity_report`; no longer an empty file (2026-08-18 review)

**Checkpoint**: User Stories 1 AND 2 both work independently; reporting is fast via pre-aggregated tables.

---

## Phase 5: User Story 3 - Accounting period lifecycle and closing (Priority: P2)

**Goal**: Periods can be opened, locked, and closed; closing generates a correct closing entry and blocks further postings; corrections only land in open periods.

**Independent Test**: Open a period, post entries, lock it, attempt a new posting (expect rejection), close it, verify the closing entry balances P&L to retained earnings.

### Tests for User Story 3

- [ ] T044 [P] [US3] Unit test: posting into an open period succeeds; into a locked/closed period is rejected (FR-008), in `ledger/tests/test_periods.py`
- [ ] T045 [P] [US3] Unit test: closing a period generates a closing `Transaction` zeroing P&L into retained earnings (FR-009), in `ledger/tests/test_periods.py`
- [ ] T046 [P] [US3] Unit test: closed-period entries cannot be edited/deleted through the service layer or DB trigger (FR-010), in `ledger/tests/test_periods.py`
- [ ] T047 [P] [US3] Unit test: lock/close is rejected when the target period is not the earliest open/locked period (chronological ordering edge case), in `ledger/tests/test_periods.py`
- [ ] T048 [P] [US3] GraphQL contract test for `openAccountingPeriod`, `lockAccountingPeriod`, `closeAccountingPeriod`, `reopenAccountingPeriod` mutations in `ledger/tests/test_gql_periods.py`

### Implementation for User Story 3

- [ ] T049 [US3] Implement `PeriodService.open(start_date, end_date)` in `ledger/services.py` with overlap/chronological validation, decorated with `@register_service_signal`
- [ ] T050 [US3] Implement `PeriodService.lock(period)` with earliest-open-period ordering check (depends on T049)
- [ ] T051 [US3] Implement `PeriodService.close(period)`: computes P&L account balances from `AccountBalanceSnapshot` (depends on Phase 4 T040), constructs the closing `Transaction` into `retained_earnings_account`, sets `AccountingPeriod.status = closed` and `closing_transaction`, decorated with `@register_service_signal("ledger_service.close_period")` (depends on T050, T040)
- [ ] T052 [US3] Implement `PeriodService.reopen(period)` restricted to `locked → open` transitions only (depends on T049)
- [ ] T053 [US3] Add a service-layer + DB-level guard preventing edit/delete of `LedgerEntryMeta`/`Leg`/`LegTag` once `accounting_period.status == closed`, in `ledger/services.py` and `ledger/migrations/0003_balance_trigger.py` follow-up if needed (depends on T014, T051)
- [ ] T054 [US3] Implement `ledger/gql_mutations.py` mutations `openAccountingPeriod`, `lockAccountingPeriod`, `closeAccountingPeriod`, `reopenAccountingPeriod`, `accountingPeriods` query, wired into `ledger/schema.py` (depends on T049–T052)

**Checkpoint**: User Stories 1, 2, and 3 all independently functional; period integrity enforced end-to-end.

---

## Phase 6: User Story 4 - External accounting system replication with manual review queue (Priority: P3)

**Goal**: Locally posted entries replicate to Odoo/Sage in real time; rejections and timeouts land in a manual review queue; corrections are always new entries.

**Independent Test**: Configure replication mode with a mock adapter; post an accepted entry (verify success), a rejected entry (verify review queue, no auto-retry-with-modification), and a timing-out entry (verify bounded retry then "unconfirmed").

### Tests for User Story 4

- [ ] T055 [P] [US4] Unit test: `ExternalLedgerAdapter` interface contract (success/reject/timeout return shapes) in `ledger/tests/test_replication.py`
- [ ] T056 [P] [US4] Integration test: successful replication marks `ExternalReplicationRecord.status = succeeded` with external reference, in `ledger/tests/test_replication.py`
- [ ] T057 [P] [US4] Integration test: explicit rejection creates a `ManualReviewQueueItem` with reason and never auto-modifies/resubmits the original entry, in `ledger/tests/test_replication.py`
- [ ] T058 [P] [US4] Integration test: timeout triggers bounded retry (~3 attempts over a few minutes) then marks `unconfirmed` and creates a review item, distinct from `rejected` (FR-013a), in `ledger/tests/test_replication.py`
- [ ] T059 [P] [US4] Integration test: resolving a review item links a new correcting `Transaction` via `resolved_by_transaction` without altering the original entry (FR-014), in `ledger/tests/test_replication.py`
- [ ] T060 [P] [US4] Unit test: idempotency key prevents duplicate external posting on message redelivery, in `ledger/tests/test_replication.py`
- [ ] T061 [P] [US4] GraphQL contract test for `manualReviewQueue` query and `resolveManualReviewItem`, `configureDeployment` mutations in `ledger/tests/test_gql_replication.py`

### Implementation for User Story 4

- [ ] T062 [P] [US4] Implement `ExternalReplicationRecord` and `ManualReviewQueueItem` models in `ledger/models.py` and migration `ledger/migrations/0005_replication.py`
- [ ] T063 [US4] Implement `ledger/replication/base.py` with the `ExternalLedgerAdapter` abstract interface (`send(transaction) -> AdapterResult`) (depends on T062)
- [ ] T064 [P] [US4] Implement `ledger/replication/odoo.py` adapter (depends on T063)
- [ ] T065 [P] [US4] Implement `ledger/replication/sage.py` adapter (depends on T063)
- [ ] T066 [US4] Implement `ledger/replication/tasks.py`: `replicate_entry(ledger_entry_id, target_system)` Celery task on the `ledger.sync.external` queue, deriving the idempotency key from the `Transaction` UUID, applying bounded retry/backoff (max 3 attempts, short window) on timeout, and creating `ExternalReplicationRecord`/`ManualReviewQueueItem` rows per outcome (depends on T062, T063)
- [ ] T067 [US4] Enqueue `replicate_entry` from `LedgerEntryService.post()` after commit when `DeploymentConfiguration.operating_mode == replicated` (depends on T018, T066)
- [ ] T068 [US4] Implement `resolveManualReviewItem` service method and mutation wiring in `ledger/services.py` / `ledger/gql_mutations.py` (depends on T062)
- [ ] T069 [US4] Implement `manualReviewQueue` query and `configureDeployment` mutation for `DeploymentConfiguration` in `ledger/gql_queries.py`/`ledger/gql_mutations.py`, wired into `ledger/schema.py` (depends on T062, T068)

**Checkpoint**: User Stories 1–4 all independently functional; replication and review queue operate per FR-011–FR-014/FR-013a.

---

## Phase 7: User Story 5 - Period export for external audit and accounting use (Priority: P3)

**Goal**: Export a period's entries as CSV with sequential, gap-free, idempotent per-journal numbering, in OHADA/FEC and generic formats.

**Independent Test**: Export a period with known entries; verify sequential gap-free numbering per journal, identical numbering on re-export, and correct field sets for both formats.

### Tests for User Story 5

- [ ] T070 [P] [US5] Unit test: `ExportSequence` assigns sequential gap-free numbers per journal within a period, in `ledger/tests/test_export.py`
- [ ] T071 [P] [US5] Unit test: re-exporting an unchanged period reuses prior numbers (FR-017), in `ledger/tests/test_export.py`
- [ ] T072 [P] [US5] Unit test: exporting an open period marks numbers `provisional`, in `ledger/tests/test_export.py`
- [ ] T073 [P] [US5] Unit test: OHADA/FEC CSV writer includes all required fields (journal code, entry number, date, account, auxiliary reference, debit, credit, description, validation date), in `ledger/tests/test_export.py`
- [ ] T074 [P] [US5] Unit test: generic CSV writer includes date/journal/account/debit/credit/description, in `ledger/tests/test_export.py`
- [ ] T075 [P] [US5] GraphQL contract test for `exportAccountingPeriod` mutation and `exportSequences` query in `ledger/tests/test_gql_export.py`

### Implementation for User Story 5

- [ ] T076 [US5] Implement `ExportSequence` model in `ledger/models.py` and migration `ledger/migrations/0006_export_sequence.py`
- [ ] T077 [US5] Implement `ledger/export/numbering.py`: `assign_or_reuse_sequence(accounting_period, journal)` — per-journal monotonic numbering, idempotent, `provisional` flagging (depends on T076)
- [ ] T078 [P] [US5] Implement `ledger/export/formats.py`: `write_ohada_fec(rows, out)` and `write_generic(rows, out)` streaming CSV writers (depends on T076)
- [ ] T079 [US5] Implement `ledger/export/tasks.py`: `export_period(accounting_period_id, format)` Celery task on the `ledger.export` queue, using a server-side cursor over the partitioned `Leg`/`Transaction` tables and `numbering.assign_or_reuse_sequence` (depends on T077, T078, T013)
- [ ] T080 [US5] Implement `exportAccountingPeriod` mutation and `exportSequences` query, wired into `ledger/schema.py` (depends on T079)

**Checkpoint**: All five user stories independently functional — full feature complete.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Improvements spanning multiple user stories

- [ ] T081 [P] Write `ledger/README.md` documenting installation, migration order (Hordak → foundational → partitioning/trigger → per-story), and configuration of `DeploymentConfiguration`
- [ ] T082 [P] Add RBAC permission checks (finance-administrator vs. general-reporting-permission) to all mutations/queries per contracts/graphql-api.md's Access Control section, across `ledger/gql_mutations.py`/`ledger/gql_queries.py`
- [ ] T083 [P] Add structured logging/observability around period close, replication outcomes, and export runs
- [ ] T084 Run the full `quickstart.md` validation (all 5 scenarios) end-to-end against a local Postgres + Celery dev environment and fix any gaps found
- [ ] T085 [P] Review and tune indexes on `Leg` partitions and `PartyLedgerBalance`/`AccountBalanceSnapshot` for the SC-002 <5s latency target under realistic data volume

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; reads `LegTag`/`LedgerEntryMeta` created by any posting path (US1 provides the natural data source, but US2's own tests can post directly via `LedgerEntryService`)
- **User Story 3 (Phase 5)**: Depends on Foundational; uses `AccountBalanceSnapshot` from Phase 4 (T040) for the closing-entry calculation — sequence Phase 4 before Phase 5, or stub the snapshot read in Phase 5's tests if parallelized
- **User Story 4 (Phase 6)**: Depends on Foundational (T018 `LedgerEntryService.post()`); independent of Phases 4–5 otherwise
- **User Story 5 (Phase 7)**: Depends on Foundational and the partitioning migration (T013); independent of Phases 4–6 otherwise
- **Polish (Phase 8)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1 (P1)**: No dependencies on other stories — MVP
- **US2 (P2)**: Independently testable once Foundational is done; benefits from but does not require US1
- **US3 (P2)**: Independently testable once Foundational is done; its closing-entry calculation depends on the `AccountBalanceSnapshot` maintenance introduced in US2 (T040/T041) — implement US2 before US3, or have US3 maintain its own minimal P&L aggregation if strict independence is required
- **US4 (P3)**: Independently testable once Foundational is done — no dependency on US2/US3
- **US5 (P3)**: Independently testable once Foundational is done — no dependency on US2/US3/US4, but typically exercised against a period closed by US3

### Within Each User Story

- Tests written first, expected to fail before implementation
- Models before services
- Services before GraphQL layer (queries/mutations)
- Core implementation before cross-story integration (e.g. replication hook into `LedgerEntryService.post()`)

### Parallel Opportunities

- All [P] Setup tasks (T004) in parallel (T003 dropped as N/A)
- Foundational [P] tasks: T007, T008, T011, T016 in parallel once their model dependencies (T006 where relevant) exist (T015 dropped as N/A)
- Once Foundational (Phase 2) completes: US1, US4, and US5 can proceed in parallel; US2 and US3 have the noted P&L-snapshot ordering dependency between them
- All test tasks within a story marked [P] can run in parallel (different assertions in the same or sibling test files, written before their implementation tasks)

---

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together:
Task: "Integration test: claim-payment signal produces balanced entry in ledger/tests/test_posting.py"
Task: "Integration test: invoice-issued signal posts to Sales journal in ledger/tests/test_posting.py"
Task: "Integration test: payroll-disbursed signal posts expense+bank legs in ledger/tests/test_posting.py"
Task: "Integration test: payment-point-reconciled signal posts to Bank journal in ledger/tests/test_posting.py"
Task: "Unit test: zero-amount event produces no entry in ledger/tests/test_posting.py"
Task: "Unit test: unmapped event surfaced for manual resolution in ledger/tests/test_posting.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Run quickstart.md Scenario 1 independently
5. Deploy/demo if ready — this alone gives every financial event an automatic, balanced ledger entry

### Incremental Delivery

1. Setup + Foundational → foundation ready (Hordak wired, journals/periods/analytic tags/config models exist, posting service works)
2. Add US1 → validate via quickstart Scenario 1 → deploy/demo (MVP)
3. Add US2 → validate via quickstart Scenario 2 → deploy/demo (party/funder reporting)
4. Add US3 → validate via quickstart Scenario 3 → deploy/demo (period close/lock)
5. Add US4 → validate via quickstart Scenario 4 → deploy/demo (external replication)
6. Add US5 → validate via quickstart Scenario 5 → deploy/demo (CSV export)
7. Polish (Phase 8) → RBAC hardening, docs, index tuning

### Parallel Team Strategy

With multiple developers, after Foundational (Phase 2) is done:
- Developer A: US1 (signal handlers)
- Developer B: US4 (replication) — independent of US1's internals beyond calling `LedgerEntryService.post()`
- Developer C: US5 (export) — independent of US1/US4
- US2 and US3 are best sequenced together (or split with a stubbed snapshot interface) given the closing-entry dependency noted above

---

## Notes

- [P] tasks = different files or independent test assertions, no dependencies
- [Story] label maps each task to its user story for traceability
- Tests are included per this repository's `CLAUDE.md` unit-testing policy; write them first and confirm they fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving to the next
- Avoid: same-file conflicts on `ledger/models.py`/`ledger/services.py` when parallelizing — coordinate ordering on those shared files even where tasks are logically independent

---

## Phase 9: Convergence

- [ ] T086 CRITICAL: Reconcile the pre-existing legacy `AccountPeriod`/`AccountJournal`/`Sequence` models in `ledger/models.py` and `ledger/migrations/0001_initial.py` (non-Hordak-based, only two period states) with the plan-mandated `AccountingPeriod`/`LedgerJournal`/`ExportSequence` schema before/while completing T006, T007, and T076, ensuring the accounting period lifecycle supports open/locked/closed per FR-007 (plan.md Foundational Phase) (contradicts)
- [ ] T087 Remove or justify the unrequested `read_all_calculation_rules()`/`CALCULATION_RULES` code in `ledger/apps.py`, which imports an unrelated `calculation_comores.calculation_rule` module not called for by spec.md or plan.md (plan.md Project Structure) (unrequested)
