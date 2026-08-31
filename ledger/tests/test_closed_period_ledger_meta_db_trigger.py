from django.db import DatabaseError
from django.test import TestCase
from hordak.models import Transaction
from ledger.models import (
    Account,
    AccountingPeriod,
    LedgerEntryMeta,
    LedgerJournal,
    Sequence,
)
from core.test_helpers import create_test_interactive_user


class ClosedPeriodLedgerEntryMetaDBTriggerTest(
    TestCase
):

    def setUp(self):
        self.user = create_test_interactive_user()

        self.cash_account = Account.objects.create(
            code="1002",
            full_code="1002",
            name="Cash",
        )

        self.expense_account = Account.objects.create(
            code="6002",
            full_code="6002",
            name="Expense",
        )

        self.sequence = Sequence(
            code="GLMETA",
            name="General Ledger Meta",
        )
        self.sequence.save(username=self.user.username)

        self.journal = LedgerJournal(
            code="GENERAL_META",
            name="General Journal Meta",
            sequence_id=self.sequence,
            default_credit_account_id=self.cash_account,
            default_debit_account_id=self.expense_account,
        )
        self.journal.save(username=self.user.username)

        self.closed_period = AccountingPeriod(
            name="2026-02",
            code="2026-02",
            status=AccountingPeriod.STATUS_CLOSED,
        )
        self.closed_period.save(username=self.user.username)

    def create_transaction(self):
        return Transaction.objects.create()

    def create_meta(self, transaction):

        meta = LedgerEntryMeta(
            transaction=transaction,
            journal=self.journal,
            accounting_period=self.closed_period,
            source_event_type="claim_payment",
            source_event_reference="META-001",
        )

        meta.save(username=self.user.username)

        return meta

    def test_insert_closed_period_meta_rejected(self):

        transaction = self.create_transaction()

        with self.assertRaises(DatabaseError) as ctx:
            self.create_meta(transaction)

        self.assertIn(
            "closed accounting period",
            str(ctx.exception).lower(),
        )

    def test_update_closed_period_meta_rejected(self):

        self.closed_period.status = AccountingPeriod.STATUS_OPEN
        self.closed_period.save(
            username=self.user.username
        )

        transaction = self.create_transaction()
        meta = self.create_meta(transaction)

        self.closed_period.status = AccountingPeriod.STATUS_CLOSED
        self.closed_period.save(
            username=self.user.username
        )

        with self.assertRaises(DatabaseError) as ctx:
            LedgerEntryMeta.objects.filter(
                pk=meta.pk
            ).update(
                source_event_reference="MODIFIED"
            )

        self.assertIn(
            "closed accounting period",
            str(ctx.exception).lower(),
        )

    def test_delete_closed_period_meta_rejected(self):

        self.closed_period.status = AccountingPeriod.STATUS_OPEN
        self.closed_period.save(
            username=self.user.username
        )

        transaction = self.create_transaction()
        meta = self.create_meta(transaction)

        self.closed_period.status = AccountingPeriod.STATUS_CLOSED
        self.closed_period.save(
            username=self.user.username
        )

        with self.assertRaises(DatabaseError) as ctx:
            meta.delete(username=self.user.username)

        self.assertIn(
            "closed accounting period",
            str(ctx.exception).lower(),
        )
