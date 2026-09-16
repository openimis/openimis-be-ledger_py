# openIMIS Backend Ledger reference module
This repository holds the files of the openIMIS Backend Ledger reference module.
It is dedicated to be deployed as a module of [openimis-be_py](https://github.com/openimis/openimis-be_py).

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
# Ledger Module

This module handles accounting journal entries, periods, analytic tagging, and deployment configuration. It builds on top of [Hordak](https://github.com/Hordak/hordak) for double-entry bookkeeping.

---

## Models


### AccountingPeriod
Lifecycle management for accounting periods (open → locked → closed).


### LedgerJournal
Defines a journal with default debit/credit accounts.

### AnalyticAxis
Categorises analytic entries (party or funder).

### AnalyticValue
Concrete values for an analytic axis (e.g., a specific insuree, health facility, or funder).

### LegTag
Attaches an analytic value to a specific Leg of a transaction. One leg may have at most one tag per axis.

### LedgerEntryMeta
Metadata for a journal entry: which journal, period, event type, and timestamp.

### DeploymentConfiguration
Global configuration: operating mode (local / replicated), external system (Odoo / Sage), currency, and retained earnings account.

---

### LedgerEntryService
The core service for posting ledger entries.

---

## Dependencies

- Django ORM
- Hordak (double-entry accounting)
- djmoney

## Database

The models map to tables prefixed with `tbl` (except `hordak_leg` and `hordak_transaction` which belong to Hordak).  
Note: `LegTag` is partitioned and references `hordak_leg(id, accounting_period_id)` via a raw SQL composite foreign key (not expressible as a Django FK).