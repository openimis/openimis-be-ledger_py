# openIMIS Backend Ledger reference module

This repository holds the files of the openIMIS Backend Ledger reference module.
It is dedicated to be deployed as a module of [openimis-be_py](https://github.com/openimis/openimis-be_py).

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

# Ledger Module

This module handles accounting journal entries, periods, analytic tagging, deployment configuration, and party/funder balances.
It builds on top of [Hordak](https://github.com/Hordak/hordak) for double-entry bookkeeping.

---

## Conditions for creating a `LedgerEntryMeta`

A `LedgerEntryMeta` row is created only when `LedgerEntryService.post()` completes successfully. The following conditions must **all** be satisfied before and during that call.

### 1. Upstream signal prerequisites

Each financial event handler (`ledger/signals/__init__.py`) performs preliminary validations before calling `LedgerEntryService.post()`.

| Event / Signal | Required business conditions |
|---------------|------------------------------|
| **claim_valuated** (`claim.claim_valuated`) | – `result` is a `Claim` instance.<br>– Claim status is `STATUS_VALUATED`.<br>– Valuated/approved/claimed amount is not zero.<br>– Journal mapping exists for `"claim_valuated"`.<br>– `LedgerJournal` with the mapped ID exists.<br>– An open `AccountingPeriod` covers `claim.date_claimed`.<br>– Party tag for the health facility exists or is created.<br>– If a `Payer` exists for the claim's location, a funder tag is resolved/created. |
| **invoice_issued** (`signal_after_invoice_module_invoice_create_service`) | – Invoice amount is not zero.<br>– Journal mapping exists for `"invoice_issued"`.<br>– `LedgerJournal` exists.<br>– Open period covers the invoice date.<br>– An `Insuree` with the invoice's `thirdparty_id` exists.<br>– Party tag for the insuree (family) exists or is created. |
| **invoice_paid** (`signal_after_payment_detail_received`) | – Payment amount is not zero.<br>– Journal mapping exists for `"invoice_paid"`.<br>– `LedgerJournal` exists.<br>– Open period covers the payment date.<br>– `Invoice` with the given UUID exists.<br>– `Insuree` linked to the invoice exists.<br>– Party tag for that insuree exists or is created. |
| **payroll_disbursed** (`payroll.disbursed`) | – Sum of benefit amounts is not zero.<br>– Journal mapping exists for `"payroll_disbursement"`.<br>– `LedgerJournal` exists.<br>– Open period covers `kwargs["payroll_date"]`.<br>– (Optional) party tag for `payment_point_manager_id` is resolved if available. |
| **payment_point_reconciled** (`payroll.payment_point_reconciled`) | – Sum of benefit amounts is not zero.<br>– Journal mapping exists for `"payment_point_reconciliation"`.<br>– `LedgerJournal` exists.<br>– Open period covers `kwargs["payroll_date"]`.<br>– If `variance` is non-zero, a `DeploymentConfiguration` with a retained earnings account must exist.<br>– (Optional) party tag for `payment_point_manager_id` is resolved if available. |

If any of these initial checks fail, the event is stored as an `UnmappedFinancialEvent` (when appropriate) and no `LedgerEntryMeta` is created.

### 2. `LedgerEntryService.post()` validations

Once the signal handler calls `post()`, the service enforces a second set of conditions:

| Condition | Error raised if violated |
|-----------|--------------------------|
| `user` must be provided | `ValidationError("User is required to post ledger entries")` |
| `accounting_period.status` must be `STATUS_OPEN` | `ClosedPeriodException("Cannot post into a non-open accounting period")` |
| `len(legs) >= 2` | `ValidationError("At least two legs required")` |
| Every leg dictionary contains an `"account"` key | `MissingAccountMappingException("Missing account mapping")` |
| Sum of all `leg["amount"]` values must equal `Decimal("0")` (balanced) | `ValidationError("Ledger entry must be balanced")` |
| A `DeploymentConfiguration` record must exist | `MissingDeploymentConfigurationException` |

If all validations pass, the service performs atomically:

1. Creates a `Transaction`.
2. Creates and saves the `LedgerEntryMeta` with the transaction, journal, period, event type, and source reference.
3. Creates each `Leg` using the provided account and amount (converted to the configured `currency_code`).
4. Attaches `LegTag` objects for the provided `tags` dictionary (keys are leg indices, values are lists of `AnalyticValue`). Each leg may have at most one tag per axis.
5. Updates `AccountBalanceSnapshot` for each leg.
6. Updates `PartyLedgerBalance` only for tags whose axis is `PARTY` (funder tags are ignored).
7. If `operating_mode` is `REPLICATED`, schedules a `replicate_entry` Celery task `on_commit`.

Thus, a `LedgerEntryMeta` is created only after every condition above is met.

---

## Models

### AccountingPeriod
Lifecycle management for accounting periods: `STATUS_OPEN` → `STATUS_LOCKED` → `STATUS_CLOSED`.  
* Opening: requires `start_date ≤ end_date`, no overlapping periods, and chronological order after the latest existing period.
* Locking: only the earliest open period may be locked.
* Closing: only the earliest non-closed period may be closed; requires a `DeploymentConfiguration` and a retained earnings account that is not of type income or expense.
* Reopening: only a locked period may be reopened (a closed period cannot).

### LedgerJournal
Defines a journal with a unique `type` (e.g. purchase, sales, treasury) and default debit/credit accounts. Used by `resolve_mapping()` to obtain the correct accounts.

### AnalyticAxis
Categorises analytic entries; currently supports two codes: `PARTY` and `FUNDER`.

### AnalyticValue
Concrete value for an analytic axis, identified by `external_reference`, `party_type`, and/or `funder_code`. Examples: a specific health facility, insured family, payment point manager, or funder.

### LegTag
Attaches an `AnalyticValue` to a specific `Leg` of a transaction. One leg may have at most one tag per axis.  
The `LegTag` table references `hordak_leg(id, accounting_period_id)` via a raw SQL composite foreign key (not expressible as a Django `ForeignKey`).

### LedgerEntryMeta
Metadata for a journal entry: which journal, accounting period, event type, and timestamp. Its creation is the endpoint of the posting flow.

### DeploymentConfiguration
Global configuration:
- `operating_mode`: `LOCAL` or `REPLICATED`.
- `external_system`: target for replication (Odoo / Sage).
- `currency_code`: currency for all monetary amounts.
- `retained_earnings_account`: used when closing a period (must not be income/expense).

### UnmappedFinancialEvent
Stores events that fail upstream validation (missing journal, no open period, etc.) for later manual review.

### PartyLedgerBalance
Running totals per party per accounting period. Only updated from `PARTY`-axis tags.

### AccountBalanceSnapshot
Running totals per account per accounting period.

### ManualReviewQueueItem
Items awaiting manual review (e.g., unreconciled transactions). Can be resolved via `ManualReviewService`.

---

## Services

### LedgerEntryService
`post(journal, accounting_period, source_event_type, source_event_reference, legs, tags=None, user=None)`  
Validates all conditions described above and creates the `LedgerEntryMeta`, legs, tags, snapshots, and party balances.

Private helpers:
- `_update_account_snapshot(accounting_period, leg, username)` – updates or creates an `AccountBalanceSnapshot` for the leg’s account in the period.
- `_update_party_balance(accounting_period, leg, username)` – updates `PartyLedgerBalance` for each `PARTY`-axis tag attached to the leg.

### PeriodService
Manages the accounting period lifecycle.

- `open(start_date, end_date, name, code, user)`  
  Creates a new open period after validating dates, overlap, and chronological order. Requires a valid core `User`.

- `lock(period, user)`  
  Transitions an open period to locked. Only the earliest open period may be locked. Requires the period to be `STATUS_OPEN`.

- `close(period, user)`  
  Transitions a locked period to closed. Requires a `DeploymentConfiguration` and a valid retained earnings account (not income or expense). Automatically creates a closing transaction that reverses all income/expense balances into retained earnings. Only the earliest non‑closed period may be closed.

- `reopen(period, user)`  
  Transitions a locked period back to open. Closed periods cannot be reopened.

### ManualReviewService
`resolve(review_item, correcting_entry, note, user)`  
Marks a `ManualReviewQueueItem` as resolved, links it to a correcting transaction, and stores a note. Raises `ValidationError` if already resolved.

---

## Signals / Event Handlers

The module binds its handlers to the core service signal bus in `ledger/signals/__init__.py`.

| Service signal | Handler | Journal type |
|----------------|---------|--------------|
| `claim.claim_valuated` | `on_claim_valuated` | `purchase` |
| `signal_after_invoice_module_invoice_create_service` | `on_invoice_issued` | `sales` |
| `payroll.disbursed` | `on_payroll_disbursed` | `treasury` |
| `payroll.payment_point_reconciled` | `on_payment_point_reconciled` | `treasury` |
| `signal_after_payment_detail_received` | `on_invoice_paid` | `treasury` |

Each handler:
- Validates event‑specific conditions (as listed in the first table).
- Resolves the journal and default accounts via `resolve_mapping()`.
- Finds an open `AccountingPeriod` for the transaction date.
- Resolves or creates party/funder `AnalyticValue`s.
- Builds the `tags` dictionary (always attaching party tags to both legs when available).
- Calls `LedgerEntryService.post()`.

For `payment_point_reconciled`, if a non‑zero `variance` is given, two additional legs are added to the retained earnings account.

---

## GraphQL API

Exposed via `ledger/schema.py`.

### Queries
- `partyLedgerBalance`
- `analyticValue`
- `deploymentConfiguration`
- `accountingPeriods`
- `manualReviewQueue`
- `accounts`
- `ledgerEntries` (filterable by `party` or `funder` UUID)
- `ledgerJournal`
- `journalTypes`
- `funderActivityReport` (aggregated debit/credit/balance for a funder within a period)

All queries require authentication and the `gql_query_ledger_perms` permission (unless overridden in `LedgerConfig`).

### Mutations
- `createDeploymentConfiguration`
- `openAccountingPeriod`
- `lockAccountingPeriod`
- `closeAccountingPeriod`
- `reopenAccountingPeriod`
- `createAccount`
- `updateAccount`
- `resolveManualReview`
- `createJournal`
- `updateJournal`
- `createJournalType`
- `deleteJournal`
- `deleteAccount`
- `deleteAccountingPeriod`

All mutations enforce appropriate permissions and user authentication (see `LedgerConfig.gql_query_ledger_perms` and `gql_mutation_ledger_perms`).

---

## Dependencies
- Django ORM
- Hordak (double-entry accounting)
- djmoney

## Database
The models map to tables prefixed with `tbl` (except `hordak_leg` and `hordak_transaction` which belong to Hordak).  
Note: `LegTag` is partitioned and references `hordak_leg(id, accounting_period_id)` via a raw SQL composite foreign key (not expressible as a Django FK).

## Tanzania Relative Pricing (Performance-Based Implementation)

The default claim valuation signal (`on_claim_valuated`) computes the posting amount from `claim.valuated`, `claim.approved`, or `claim.claimed`, and assumes this amount is final once the claim reaches `STATUS_VALUATED`. This assumption works for most implementations (approximately 99% of cases) where valuation amounts are fixed after valuation.

In Tanzania, which implements performance-based relative pricing, claim prices can change **after** the claim has been valuated. As a result, the automatic ledger entry posted at `claim_valuated` time may not reflect later price adjustments. Such adjustments require a different accounting treatment and should be managed outside this default signal (for example, by posting a separate adjusting entry when the final price is known).

Implementations with similar dynamic pricing mechanisms should review whether the `claim_valuated` signal should be disabled or extended to handle price revisions, rather than relying on the one-time entry created here.