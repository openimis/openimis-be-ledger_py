from django.core.exceptions import ValidationError
from django.test import TestCase
from hordak.models import Leg
from hordak.models import Transaction
from ledger.models import (
    AnalyticAxis,
    AnalyticValue,
    LegTag,
    AccountingPeriod,
    LedgerJournal,
    Sequence,
    DeploymentConfiguration
)
from ledger.models import Account
from djmoney.money import Money
from core.test_helpers import create_test_interactive_user


class AnalyticAxisTest(TestCase):

    def test_code_unique(self):
        test_user = create_test_interactive_user()
        analytic_axis = AnalyticAxis(
            code="party",
            name="Party"
        )
        analytic_axis.save(username=test_user.username)

        with self.assertRaises(Exception):
            analytic_axis2 = AnalyticAxis(
                code="party",
                name="Duplicate"
            )
            analytic_axis2.save(username=test_user.username)


class AnalyticValueTest(TestCase):

    def setUp(self):
        self.test_user = create_test_interactive_user()

    def test_party_requires_party_type(self):
        axis = AnalyticAxis(
            code="party",
            name="Party"
        )
        axis.save(username=self.test_user.username)

        value = AnalyticValue(
            axis=axis,
            display_name="HF",
            external_reference="1"
        )

        with self.assertRaises(ValidationError):
            value.clean()

    def test_funder_requires_funder_code(self):
        axis = AnalyticAxis(
            code="funder",
            name="Funder"
        )
        axis.save(username=self.test_user.username)

        value = AnalyticValue(
            axis=axis,
            display_name="GIZ",
            external_reference="1"
        )

        with self.assertRaises(ValidationError):
            value.clean()


class LegTagConstraintTest(TestCase):

    def setUp(self):

        self.test_user = create_test_interactive_user()
        self.account = Account.objects.create(
            code="1002",
            full_code="1002",
            name="Cash"
        )
        self.transaction = Transaction.objects.create()

        self.expense_account = Account.objects.create(
            code="6003",
            name="Expense",
            full_code="6003"
        )

        self.open_period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.open_period.save(username=self.test_user.username)

    def create_leg(self):

        Leg.objects.create(
            transaction=self.transaction,
            account=self.expense_account,
            amount=Money(-100, "EUR"),
        )
        return Leg.objects.create(
            transaction=self.transaction,
            account=self.account,
            amount=Money(100, "EUR"),
        )

    def test_single_value_per_axis(self):
        """
        One party per leg.
        """

        leg = self.create_leg()

        party_axis = AnalyticAxis(
            code="party",
            name="Party"
        )
        party_axis.save(username=self.test_user.username)

        first = AnalyticValue(
            axis=party_axis,
            party_type="health_facility",
            external_reference="1",
            display_name="HF1",
        )
        first.save(username=self.test_user.username)

        second = AnalyticValue(
            axis=party_axis,
            party_type="health_facility",
            external_reference="2",
            display_name="HF2",
        )
        second.save(username=self.test_user.username)

        legtag = LegTag(
            accounting_period_id=self.open_period.uuid,
            leg=leg,
            analytic_value=first,
        )
        legtag.save(username=self.test_user.username)

        duplicate = LegTag(
            accounting_period_id=self.open_period.uuid,
            leg=leg,
            analytic_value=second,
        )

        with self.assertRaises(ValidationError):
            duplicate.clean()


class AccountingPeriodModelTest(TestCase):

    def setUp(self):
        self.test_user = create_test_interactive_user()

    def test_is_open(self):
        period = AccountingPeriod(
            name="2026-02",
            status=AccountingPeriod.STATUS_OPEN
        )
        period.save(username=self.test_user.username)
        self.assertTrue(period.is_open)
        self.assertFalse(period.is_locked)
        self.assertFalse(period.is_closed)

    def test_is_locked(self):
        period = AccountingPeriod(
            name="2026-03",
            status=AccountingPeriod.STATUS_LOCKED
        )
        period.save(username=self.test_user.username)
        self.assertTrue(period.is_locked)

    def test_is_closed(self):
        period = AccountingPeriod(
            name="2026-03",
            status=AccountingPeriod.STATUS_CLOSED
        )
        period.save(username=self.test_user.username)
        self.assertTrue(period.is_closed)


class LedgerJournalModelTest(TestCase):

    def setUp(self):

        self.test_user = create_test_interactive_user()

        self.sequence = Sequence(
            code="PS",
            name="Purchase seq"
        )
        self.sequence.save(username=self.test_user.username)

        self.cash_account = Account.objects.create(
            code="2003",
            full_code="2003",
            name="Cash Account2",
        )

        self.expense_account = Account.objects.create(
            code="3003",
            full_code="3003",
            name="Expense Account2",
        )

    def test_str_returns_code_first(self):
        journal1 = LedgerJournal(
            code="PURCHASE",
            name="Purchase Journal",
            sequence_id=self.sequence,
            default_credit_account_id=self.cash_account,
            default_debit_account_id=self.expense_account,
        )
        journal1.save(username=self.test_user.username)
        self.assertEqual(str(journal1), "PURCHASE")

    def test_str_returns_name_when_code_missing(self):
        journal = LedgerJournal(
            name="Purchase Journal 2",
            sequence_id=self.sequence,
            default_credit_account_id=self.cash_account,
            default_debit_account_id=self.expense_account,
        )
        journal.save(username=self.test_user.username)
        self.assertEqual(str(journal), "Purchase Journal 2")


class DeploymentConfigurationTest(TestCase):

    def setUp(self):

        self.test_user = create_test_interactive_user()

        self.account = Account.objects.create(
            code="4002",
            full_code="4002",
            name="Cash 2"
        )
        self.transaction = Transaction.objects.create()

    def test_default_operating_mode(self):
        config = DeploymentConfiguration(
            currency_code="EUR",
            retained_earnings_account=self.account
        )
        config.save(username=self.test_user.username)
        self.assertEqual(
            config.operating_mode,
            DeploymentConfiguration.OPERATING_MODE_LOCAL
        )

    def test_modes_constants(self):
        self.assertEqual(
            DeploymentConfiguration.OPERATING_MODE_LOCAL,
            "local_only"
        )
        self.assertEqual(
            DeploymentConfiguration.OPERATING_MODE_REPLICATED,
            "replicated"
        )
