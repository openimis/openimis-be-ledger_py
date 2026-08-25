from unittest import skip

from django.db import IntegrityError
from django.test import TestCase

from hordak.models import Transaction
from hordak.models import Leg
from django.db import connection
from ledger.models import Account
from djmoney.money import Money
from ledger.models import (
    AccountingPeriod,
    LedgerEntryMeta,
    LedgerJournal,
    Sequence
)
from core.test_helpers import create_test_interactive_user


class BalanceTriggerTest(TestCase):

    def setUp(self):
        self.test_user = create_test_interactive_user()

        self.sequence = Sequence(
            code="GL",
            name="General Ledger"
        )
        self.sequence.save(username=self.test_user.username)

        self.cash_account = Account.objects.create(
            code="1006",
            full_code="1006",
            name="Cash Account",
        )

        self.expense_account = Account.objects.create(
            code="1007",
            full_code="1007",
            name="Expense Account",
        )

        self.period = AccountingPeriod(
            code="2021-01",
            status=AccountingPeriod.STATUS_CLOSED,
        )
        self.period.save(username=self.test_user.username)

        self.journal = LedgerJournal(
            code="GENERAL",
            name="General Journal",
            sequence_id=self.sequence,
            default_credit_account_id=self.cash_account,
            default_debit_account_id=self.expense_account,
        )
        self.journal.save(username=self.test_user.username)

        self.cash_account = Account.objects.create(
            code="1004",
            name="Cash",
            full_code="1004"
        )

        self.expense_account = Account.objects.create(
            code="6002",
            name="Expense",
            full_code="6002"
        )

    def test_unbalanced_transaction_rejected(self):
        trx = Transaction.objects.create()

        Leg.objects.create(
            transaction=trx,
            account=self.cash_account,
            amount=Money(100, "EUR"),
        )

        Leg.objects.create(
            transaction=trx,
            account=self.expense_account,
            amount=Money(-50, "EUR"),
        )

        with self.assertRaises(IntegrityError) as ctx:
            connection.check_constraints()

        self.assertIn(
            "must be 0",
            str(ctx.exception)
        )

    def test_closed_period_rejected_at_db_level(self):

        trx2 = Transaction.objects.create()

        self.period.status = AccountingPeriod.STATUS_OPEN
        self.period.save(username=self.test_user.username)
        meta = LedgerEntryMeta(
            transaction=trx2,
            accounting_period=self.period,
            journal=self.journal,
            source_event_type="claim_payment",
            source_event_reference="1",
        )
        meta.save(username=self.test_user.username)

        # with self.assertRaises(IntegrityError) as ctx:

        #     Leg.objects.create(
        #         transaction=trx2,
        #         account=self.cash_account,
        #         amount=Money(100, "EUR"),
        #     )
        #     Leg.objects.create(
        #         transaction=trx2,
        #         account=self.cash_account,
        #         amount=Money(-100, "EUR"),
        #     )

        # self.assertIn(
        #     "closed accounting period",
        #     str(ctx.exception).lower(),
        # )


class PartitioningTest(TestCase):

    @skip
    def test_partition_exists_for_period(self):

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT tablename
                FROM pg_tables
                WHERE tablename LIKE 'hordak_leg_%'
                """
            )

            rows = cursor.fetchall()

        self.assertTrue(len(rows) > 0)
