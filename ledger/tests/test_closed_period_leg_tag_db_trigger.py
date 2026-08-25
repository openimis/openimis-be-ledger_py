from django.db import DatabaseError
from django.test import TestCase

from djmoney.money import Money
from hordak.models import Transaction, Leg

from ledger.models import (
    Account,
    AccountingPeriod,
    AnalyticAxis,
    AnalyticValue,
    LegTag,
)

from core.test_helpers import create_test_interactive_user


class ClosedPeriodLegTagDBTriggerTest(
    TestCase
):

    def setUp(self):
        self.user = create_test_interactive_user()

        self.account = Account.objects.create(
            code="1003",
            full_code="1003",
            name="Cash",
        )

        self.expense_account = Account.objects.create(
            code="6003",
            full_code="6003",
            name="Expense",
        )

        self.closed_period = AccountingPeriod(
            name="2026-03",
            code="2026-03",
            status=AccountingPeriod.STATUS_CLOSED,
        )
        self.closed_period.save(username=self.user.username)

        self.axis = AnalyticAxis(
            code=AnalyticAxis.PARTY,
            name="Party",
        )
        self.axis.save(username=self.user.username)

        self.analytic_value = AnalyticValue(
            axis=self.axis,
            party_type=AnalyticValue.PARTY_HEALTH_FACILITY,
            external_reference="HF001",
            display_name="Health Facility 001",
        )
        self.analytic_value.save(
            username=self.user.username
        )

        self.analytic_value_2 = AnalyticValue(
            axis=self.axis,
            party_type=AnalyticValue.PARTY_HEALTH_FACILITY,
            external_reference="HF002",
            display_name="Health Facility 002",
        )
        self.analytic_value_2.save(
            username=self.user.username
        )

    def create_transaction_and_leg(self):

        transaction = Transaction.objects.create()

        leg = Leg.objects.create(
            transaction=transaction,
            account=self.account,
            amount=Money(100, "EUR"),
        )

        return transaction, leg

    def create_leg_tag(self, leg):

        leg_tag = LegTag(
            leg=leg,
            analytic_value=self.analytic_value,
            accounting_period_id=self.closed_period.uuid,
        )

        leg_tag.save(username=self.user.username)

        return leg_tag

    def test_insert_closed_period_leg_tag_rejected(self):

        self.closed_period.status = AccountingPeriod.STATUS_OPEN
        self.closed_period.save(
            username=self.user.username
        )

        _, leg = self.create_transaction_and_leg()

        self.closed_period.status = AccountingPeriod.STATUS_CLOSED
        self.closed_period.save(
            username=self.user.username
        )

        with self.assertRaises(DatabaseError) as ctx:
            self.create_leg_tag(leg)

        self.assertIn(
            "closed accounting period",
            str(ctx.exception).lower(),
        )

    def test_update_closed_period_leg_tag_rejected(self):

        self.closed_period.status = AccountingPeriod.STATUS_OPEN
        self.closed_period.save(
            username=self.user.username
        )

        _, leg = self.create_transaction_and_leg()
        leg_tag = self.create_leg_tag(leg)

        self.closed_period.status = AccountingPeriod.STATUS_CLOSED
        self.closed_period.save(
            username=self.user.username
        )

        with self.assertRaises(DatabaseError) as ctx:
            LegTag.objects.filter(
                pk=leg_tag.pk
            ).update(
                analytic_value=self.analytic_value
            )

        self.assertIn(
            "closed accounting period",
            str(ctx.exception).lower(),
        )

        with self.assertRaises(DatabaseError) as ctx:
            LegTag.objects.filter(
                pk=leg_tag.pk
            ).update(
                analytic_value=self.analytic_value_2
            )

    def test_delete_closed_period_leg_tag_rejected(self):

        self.closed_period.status = AccountingPeriod.STATUS_OPEN
        self.closed_period.save(
            username=self.user.username
        )

        _, leg = self.create_transaction_and_leg()
        leg_tag = self.create_leg_tag(leg)

        self.closed_period.status = AccountingPeriod.STATUS_CLOSED
        self.closed_period.save(
            username=self.user.username
        )

        with self.assertRaises(DatabaseError) as ctx:
            leg_tag.delete(username=self.user.username)

        self.assertIn(
            "closed accounting period",
            str(ctx.exception).lower(),
        )
