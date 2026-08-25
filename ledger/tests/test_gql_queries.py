from decimal import Decimal
import graphene
from django.test import TestCase
from djmoney.money import Money

from core.test_helpers import create_test_interactive_user
from types import SimpleNamespace
from hordak.models import Transaction, Leg

from ledger.models import (
    AccountingPeriod,
    AnalyticAxis,
    AnalyticValue,
    LegTag,
    Account,
    PartyLedgerBalance
)

from ledger.schema import Query


class FunderActivityReportQueryTest(TestCase):

    def setUp(self):
        self.user = create_test_interactive_user()

        self.currency = "EUR"

        self.period = AccountingPeriod(
            name="2026-01",
            code="2026-01",
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.period.save(username=self.user.username)

        self.other_period = AccountingPeriod(
            name="2026-02",
            code="2026-02",
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.other_period.save(username=self.user.username)

        # ---------------------------------------------------------
        # Analytic axes
        # ---------------------------------------------------------

        self.funder_axis = AnalyticAxis(
            code=AnalyticAxis.FUNDER,
            name="Funder",
        )
        self.funder_axis.save(username=self.user.username)

        self.party_axis = AnalyticAxis(
            code=AnalyticAxis.PARTY,
            name="Party",
        )
        self.party_axis.save(username=self.user.username)

        # ---------------------------------------------------------
        # Funders
        # ---------------------------------------------------------

        self.funder = AnalyticValue(
            axis=self.funder_axis,
            funder_code="FUNDER001",
            external_reference="F001",
            display_name="Funder 001",
        )
        self.funder.save(username=self.user.username)

        self.other_funder = AnalyticValue(
            axis=self.funder_axis,
            funder_code="FUNDER002",
            external_reference="F002",
            display_name="Funder 002",
        )
        self.other_funder.save(username=self.user.username)

        # ---------------------------------------------------------
        # Party
        # ---------------------------------------------------------

        self.party = AnalyticValue(
            axis=self.party_axis,
            party_type=AnalyticValue.PARTY_HEALTH_FACILITY,
            external_reference="HF001",
            display_name="Health Facility 001",
        )
        self.party.save(username=self.user.username)

        # ---------------------------------------------------------
        # Accounts
        # ---------------------------------------------------------

        self.account_1 = Account.objects.create(
            code="1001",
            full_code="1001",
            name="Account 1",
        )

        self.account_2 = Account.objects.create(
            code="1002",
            full_code="1002",
            name="Account 2",
        )

        self.account_3 = Account.objects.create(
            code="1003",
            full_code="1003",
            name="Account 3",
        )

    # =============================================================
    # Helpers
    # =============================================================

    def _create_transaction_with_legs(
        self,
        debit_account,
        debit_amount,
        credit_account=None,
        period=None,
    ):
        """
        Creates a balanced transaction.

        The target debit leg is returned so it can receive
        the Funder LegTag.
        """

        period = period or self.period
        credit_account = credit_account or self.account_2

        transaction = Transaction.objects.create()

        debit_leg = Leg.objects.create(
            transaction=transaction,
            account=debit_account,
            debit=Money(
                Decimal(str(debit_amount)),
                self.currency,
            ),
        )

        Leg.objects.create(
            transaction=transaction,
            account=credit_account,
            credit=Money(
                Decimal(str(debit_amount)),
                self.currency,
            ),
        )

        return debit_leg

    def _create_funder_tag(
        self,
        leg,
        funder=None,
        period=None,
    ):
        funder = funder or self.funder
        period = period or self.period

        tag = LegTag(
            leg=leg,
            analytic_value=funder,
            accounting_period_id=period.uuid,
        )
        tag.save(username=self.user.username)

        return tag

    def _create_party_tag(
        self,
        leg,
        period=None,
    ):
        period = period or self.period

        tag = LegTag(
            leg=leg,
            analytic_value=self.party,
            accounting_period_id=period.uuid,
        )
        tag.save(username=self.user.username)

        return tag

    def _resolve(
        self,
        funder=None,
        period=None,
    ):
        funder = funder or self.funder
        period = period or self.period

        return Query().resolve_funder_activity_report(
            info=None,
            analytic_value_id=funder.uuid,
            accounting_period_id=period.uuid,
        )

    # =============================================================
    # Basic aggregation
    # =============================================================

    def test_returns_funder_tagged_leg_totals(self):
        """
        Les débits/crédits des Legs tagués avec le funder doivent
        être agrégés correctement.
        """

        leg_1 = self._create_transaction_with_legs(
            self.account_1,
            Decimal("100"),
        )

        leg_2 = self._create_transaction_with_legs(
            self.account_3,
            Decimal("250"),
        )

        self._create_funder_tag(leg_1)
        self._create_funder_tag(leg_2)

        result = self._resolve()

        self.assertEqual(
            result.debit_amount,
            Decimal("350"),
        )

        self.assertEqual(
            result.credit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            result.balance_amount,
            Decimal("350"),
        )

    # =============================================================
    # Credit legs
    # =============================================================

    def test_returns_credit_amount_for_tagged_credit_leg(self):
        """
        Le resolver doit également fonctionner lorsqu'un Leg tagué
        est un crédit.
        """

        transaction = Transaction.objects.create()

        Leg.objects.create(
            transaction=transaction,
            account=self.account_1,
            debit=Money(
                Decimal("100"),
                self.currency,
            ),
        )

        credit_leg = Leg.objects.create(
            transaction=transaction,
            account=self.account_2,
            credit=Money(
                Decimal("100"),
                self.currency,
            ),
        )

        self._create_funder_tag(credit_leg)

        result = self._resolve()

        self.assertEqual(
            result.debit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            result.credit_amount,
            Decimal("100"),
        )

        self.assertEqual(
            result.balance_amount,
            Decimal("-100"),
        )

    # =============================================================
    # Debit + credit
    # =============================================================

    def test_balance_is_debit_minus_credit(self):
        """
        Le solde retourné doit être :

            debit_amount - credit_amount
        """

        transaction = Transaction.objects.create()

        debit_leg = Leg.objects.create(
            transaction=transaction,
            account=self.account_1,
            debit=Money(
                Decimal("300"),
                self.currency,
            ),
        )

        Leg.objects.create(
            transaction=transaction,
            account=self.account_2,
            credit=Money(
                Decimal("300"),
                self.currency,
            ),
        )

        self._create_funder_tag(debit_leg)

        # Une autre transaction dont le crédit est également tagué.
        transaction_2 = Transaction.objects.create()

        Leg.objects.create(
            transaction=transaction_2,
            account=self.account_1,
            debit=Money(
                Decimal("100"),
                self.currency,
            ),
        )

        tagged_credit_leg = Leg.objects.create(
            transaction=transaction_2,
            account=self.account_2,
            credit=Money(
                Decimal("100"),
                self.currency,
            ),
        )

        self._create_funder_tag(tagged_credit_leg)

        result = self._resolve()

        self.assertEqual(
            result.debit_amount,
            Decimal("300"),
        )

        self.assertEqual(
            result.credit_amount,
            Decimal("100"),
        )

        self.assertEqual(
            result.balance_amount,
            Decimal("200"),
        )

    # =============================================================
    # Untagged leg on the same account
    # =============================================================

    def test_ignores_untagged_leg_on_same_account(self):
        """
        C'est le cas important qui corrige le problème signalé par le PO.

        Un compte peut avoir plusieurs Legs, dont certains tagués
        avec le funder et d'autres non.

        Le rapport doit uniquement prendre le LegTag correspondant,
        et non le solde global du compte.
        """

        # Transaction 1
        tagged_leg = self._create_transaction_with_legs(
            self.account_1,
            Decimal("100"),
        )

        self._create_funder_tag(tagged_leg)

        # Transaction 2
        # Même compte, mais aucun tag Funder.
        self._create_transaction_with_legs(
            self.account_1,
            Decimal("500"),
        )

        result = self._resolve()

        self.assertEqual(
            result.debit_amount,
            Decimal("100"),
        )

        self.assertEqual(
            result.credit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            result.balance_amount,
            Decimal("100"),
        )

    # =============================================================
    # Other funder
    # =============================================================

    def test_ignores_leg_tagged_with_another_funder(self):
        """
        Un Leg tagué avec FUND-002 ne doit pas apparaître
        dans le rapport de FUND-001.
        """

        leg_1 = self._create_transaction_with_legs(
            self.account_1,
            Decimal("100"),
        )

        leg_2 = self._create_transaction_with_legs(
            self.account_3,
            Decimal("500"),
        )

        self._create_funder_tag(
            leg_1,
            funder=self.funder,
        )

        self._create_funder_tag(
            leg_2,
            funder=self.other_funder,
        )

        result = self._resolve(
            funder=self.funder,
        )

        self.assertEqual(
            result.debit_amount,
            Decimal("100"),
        )

        self.assertEqual(
            result.credit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            result.balance_amount,
            Decimal("100"),
        )

    # =============================================================
    # Party tag
    # =============================================================

    def test_ignores_party_tag(self):
        """
        Un LegTag PARTY ne doit jamais être considéré comme
        un tag FUNDER.
        """

        leg = self._create_transaction_with_legs(
            self.account_1,
            Decimal("100"),
        )

        self._create_party_tag(leg)

        result = self._resolve()

        self.assertEqual(
            result.debit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            result.credit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            result.balance_amount,
            Decimal("0"),
        )

    # =============================================================
    # Accounting period
    # =============================================================

    def test_ignores_leg_from_another_accounting_period(self):
        """
        Un LegTag appartenant à une autre période ne doit pas être
        pris en compte.
        """

        current_period_leg = self._create_transaction_with_legs(
            self.account_1,
            Decimal("100"),
        )

        self._create_funder_tag(
            current_period_leg,
            period=self.period,
        )

        other_period_leg = self._create_transaction_with_legs(
            self.account_3,
            Decimal("500"),
        )

        self._create_funder_tag(
            other_period_leg,
            period=self.other_period,
        )

        result = self._resolve(
            period=self.period,
        )

        self.assertEqual(
            result.debit_amount,
            Decimal("100"),
        )

        self.assertEqual(
            result.credit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            result.balance_amount,
            Decimal("100"),
        )

    # =============================================================
    # Unknown funder
    # =============================================================

    def test_returns_zero_for_unknown_funder(self):
        """
        Aucun LegTag correspondant au funder demandé.
        """

        result = self._resolve(
            funder=self.other_funder,
        )

        self.assertEqual(
            result.debit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            result.credit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            result.balance_amount,
            Decimal("0"),
        )

    # =============================================================
    # No data
    # =============================================================

    def test_returns_zero_when_no_ledger_data_exists(self):
        """
        Aucun LegTag et aucun Leg correspondant.
        """

        result = self._resolve()

        self.assertEqual(
            result.debit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            result.credit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            result.balance_amount,
            Decimal("0"),
        )

    # =============================================================
    # Multiple tagged legs in same transaction
    # =============================================================

    def test_aggregates_multiple_tagged_legs(self):
        """
        Plusieurs Legs tagués avec le même funder doivent être
        agrégés.
        """

        transaction = Transaction.objects.create()

        debit_leg = Leg.objects.create(
            transaction=transaction,
            account=self.account_1,
            debit=Money(
                Decimal("300"),
                self.currency,
            ),
        )

        credit_leg = Leg.objects.create(
            transaction=transaction,
            account=self.account_2,
            credit=Money(
                Decimal("300"),
                self.currency,
            ),
        )

        self._create_funder_tag(debit_leg)
        self._create_funder_tag(credit_leg)

        result = self._resolve()

        self.assertEqual(
            result.debit_amount,
            Decimal("300"),
        )

        self.assertEqual(
            result.credit_amount,
            Decimal("300"),
        )

        self.assertEqual(
            result.balance_amount,
            Decimal("0"),
        )

    # =============================================================
    # No double counting
    # =============================================================

    def test_does_not_double_count_same_leg(self):
        """
        Le DISTINCT sur leg_id garantit qu'un même Leg ne soit pas
        compté plusieurs fois.

        Avec la contrainte uniq_legtag_leg_axis, un Leg ne peut avoir
        qu'un tag Funder, mais ce test vérifie quand même le comportement
        du resolver.
        """

        leg = self._create_transaction_with_legs(
            self.account_1,
            Decimal("100"),
        )

        self._create_funder_tag(leg)

        result = self._resolve()

        self.assertEqual(
            result.debit_amount,
            Decimal("100"),
        )

        self.assertEqual(
            result.credit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            result.balance_amount,
            Decimal("100"),
        )


class PartyLedgerBalanceQueryTest(TestCase):

    def setUp(self):

        self.user = create_test_interactive_user()

        self.period = AccountingPeriod(
            name="2026-01",
            code="2026-01",
        )
        self.period.save(username=self.user.username)

        self.axis = AnalyticAxis(
            code=AnalyticAxis.PARTY,
            name="Party",
        )
        self.axis.save(username=self.user.username)

        self.party = AnalyticValue(
            axis=self.axis,
            party_type=AnalyticValue.PARTY_HEALTH_FACILITY,
            external_reference="HF001",
            display_name="HF 001",
        )
        self.party.save(username=self.user.username)

        self.balance = PartyLedgerBalance(
            accounting_period=self.period,
            analytic_value=self.party,
            debit_amount=Decimal("100"),
            credit_amount=Decimal("20"),
            balance_amount=Decimal("80"),
        )
        self.balance.save(username=self.user.username)

        self.context = SimpleNamespace(
            user=self.user
        )

    def test_returns_all_balances(self):

        query = """
            query {
            partyLedgerBalance {
                edges {
                node {
                    analyticValue
                    {
                    partyType
                    funderCode
                    }
                    debitAmount
                }
                }
            }
            }
        """
        schema = graphene.Schema(
            query=Query,
        )

        result = schema.execute(
            query,
            context_value=self.context
        )
        self.assertEqual(
            len(
                result.data["partyLedgerBalance"]["edges"]
            ),
            1,
        )


class AnalyticValueQueryTest(TestCase):

    def setUp(self):
        self.user = create_test_interactive_user()

        self.context = SimpleNamespace(
            user=self.user
        )

        self.axis = AnalyticAxis(
            code=AnalyticAxis.FUNDER,
            name="Funder",
        )
        self.axis.save(username=self.user.username)

        self.value = AnalyticValue(
            axis=self.axis,
            funder_code="FUNDER001",
            external_reference="F001",
            display_name="Test Funder",
        )
        self.value.save(username=self.user.username)

    def test_queryset_contains_values(self):

        query = """
            query {
            analyticValue {
            totalCount
                edges {
                node {
                    displayName
                    externalReference
                }
                }
            }
            }
        """
        schema = graphene.Schema(
            query=Query,
        )

        result = schema.execute(
            query,
            context_value=self.context
        )

        self.assertEqual(
            len(
                result.data["analyticValue"]["edges"]
            ),
            1,
        )


class AccountingPeriodQueryTest(TestCase):

    def setUp(self):

        self.user = create_test_interactive_user()

        self.period = AccountingPeriod(
            name="2026-01",
            code="2026-01",
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.period.save(username=self.user.username)

        self.context = SimpleNamespace(
            user=self.user
        )

    def test_queryset_contains_period(self):

        query = """
            query {
            accountingPeriods {
            totalCount
                edges {
                node {
                    startDate
                    endDate
                    name
                    code
                    status
                }
                }
            }
            }
        """
        schema = graphene.Schema(
            query=Query,
        )

        result = schema.execute(
            query,
            context_value=self.context
        )
        self.assertEqual(
            len(
                result.data["accountingPeriods"]["edges"]
            ),
            1,
        )
        self.assertEqual(
            result.data["accountingPeriods"]["edges"][0]["node"]["code"],
            "2026-01",
        )
