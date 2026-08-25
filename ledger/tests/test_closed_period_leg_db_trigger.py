from django.db import DatabaseError
from django.test import TestCase
from djmoney.money import Money
from hordak.models import Transaction, Leg
from ledger.models import (
    Account,
    AccountingPeriod,
    LedgerEntryMeta,
    LedgerJournal,
    Sequence,
)
from core.test_helpers import create_test_interactive_user


class ClosedPeriodLegDBTriggerTest(TestCase):

    def setUp(self):
        self.user = create_test_interactive_user()

        self.cash_account = Account.objects.create(
            code="1001",
            full_code="1001",
            name="Cash",
        )

        self.expense_account = Account.objects.create(
            code="6001",
            full_code="6001",
            name="Expense",
        )

        self.sequence = Sequence(
            code="GL",
            name="General Ledger",
        )
        self.sequence.save(username=self.user.username)

        self.journal = LedgerJournal(
            code="GENERAL",
            name="General Journal",
            sequence_id=self.sequence,
            default_credit_account_id=self.cash_account,
            default_debit_account_id=self.expense_account,
        )
        self.journal.save(username=self.user.username)

        self.closed_period = AccountingPeriod(
            name="2026-01",
            code="2026-01",
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.closed_period.save(username=self.user.username)

        self.transaction = Transaction.objects.create()

        self.meta = LedgerEntryMeta(
            transaction=self.transaction,
            journal=self.journal,
            accounting_period=self.closed_period,
            source_event_type="claim_payment",
            source_event_reference="TEST-001",
        )
        self.meta.save(username=self.user.username)

    def create_leg(self):
        return Leg.objects.create(
            transaction=self.transaction,
            account=self.cash_account,
            amount=Money(100, "EUR"),
        )

    def test_insert_closed_period_leg_rejected(self):
        self.closed_period.status = AccountingPeriod.STATUS_CLOSED
        self.closed_period.save(username=self.user.username)

        with self.assertRaises(DatabaseError) as ctx:
            self.create_leg()

        self.assertIn(
            "closed accounting period",
            str(ctx.exception).lower(),
        )

    def test_update_closed_period_leg_rejected(self):

        leg = self.create_leg()

        # Refermer la période.
        self.closed_period.status = AccountingPeriod.STATUS_CLOSED
        self.closed_period.save(
            username=self.user.username
        )

        with self.assertRaises(DatabaseError) as ctx:
            Leg.objects.filter(pk=leg.pk).update(
                description="Modified after closing"
            )

        self.assertIn(
            "closed accounting period",
            str(ctx.exception).lower(),
        )

    def test_delete_closed_period_leg_rejected(self):

        leg = self.create_leg()

        self.closed_period.status = AccountingPeriod.STATUS_CLOSED
        self.closed_period.save(
            username=self.user.username
        )

        with self.assertRaises(DatabaseError) as ctx:
            leg.delete()

        self.assertIn(
            "closed accounting period",
            str(ctx.exception).lower(),
        )
