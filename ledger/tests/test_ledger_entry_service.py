from django.test import TestCase

from ledger.services import (
    LedgerEntryService,
    ClosedPeriodException,
    MissingAccountMappingException,
    MissingDeploymentConfigurationException
)

from ledger.models import (
    AccountingPeriod,
    Account,
    LedgerJournal,
    Sequence,
    LegTag,
    AnalyticValue,
    AnalyticAxis,
    DeploymentConfiguration,
    PartyLedgerBalance,
    AccountBalanceSnapshot
)
from core.test_helpers import create_test_interactive_user
from django.core.exceptions import ValidationError
from hordak.models import Leg
from decimal import Decimal


class LedgerEntryServiceTests(TestCase):

    def setUp(self):
        """
        Préparation des données communes utilisées par les tests.
        """

        self.test_user = create_test_interactive_user()

        # Création des comptes
        self.cash_account = Account.objects.create(
            code="1003",
            full_code="1003",
            name="Cash Account",
        )

        self.expense_account = Account.objects.create(
            code="6001",
            full_code="6001",
            name="Expense Account",
        )

        self.sequence = Sequence(
            code="GL",
            name="General Ledger"
        )
        self.sequence.save(username=self.test_user.username)

        self.analytic_axis = AnalyticAxis(
            code="party",
            name="Party1"
        )
        self.analytic_axis.save(username=self.test_user.username)

        self.analytic_axis2 = AnalyticAxis(
            code="funder",
            name="Party2"
        )
        self.analytic_axis2.save(username=self.test_user.username)

        self.analytic = AnalyticValue(
            axis_id=self.analytic_axis.uuid,
            party_type="insuree_family",
            funder_code="Test001",
            external_reference="001",
            display_name="test"
        )
        self.analytic.save(username=self.test_user.username)

        self.analytic2 = AnalyticValue(
            axis_id=self.analytic_axis2.uuid,
            party_type="insuree_family",
            funder_code="Test002",
            external_reference="002",
            display_name="test2"
        )
        self.analytic2.save(username=self.test_user.username)

        # Création du journal
        self.journal = LedgerJournal(
            code="GENERAL",
            name="General Journal",
            sequence_id=self.sequence,
            default_credit_account_id=self.cash_account,
            default_debit_account_id=self.expense_account,
        )
        self.journal.save(username=self.test_user.username)

        # Période ouverte
        self.open_period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.open_period.save(username=self.test_user.username)

        # Période verrouillée
        self.locked_period = AccountingPeriod(
            name="2026-02",
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.locked_period.save(username=self.test_user.username)

        # Période fermée
        self.closed_period = AccountingPeriod(
            name="2026-03",
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.closed_period.save(username=self.test_user.username)

        # Legs équilibrés réutilisables
        self.valid_legs = [
            {
                "account": self.cash_account,
                "amount": 100,
            },
            {
                "account": self.expense_account,
                "amount": -100,
            },
        ]

        config = DeploymentConfiguration(
            currency_code="EUR",
            retained_earnings_account=self.cash_account
        )
        config.save(username=self.test_user.username)

    def test_successful_balanced_post(self):

        result = LedgerEntryService.post(
            journal=self.journal,
            accounting_period=self.open_period,
            source_event_type="claim_payment",
            source_event_reference="CLAIM-1",
            legs=self.valid_legs,
            user=self.test_user
        )

        self.assertIsNotNone(result.pk)

    def test_locked_period_rejected(self):

        self.locked_period.status = (
            AccountingPeriod.STATUS_LOCKED
        )

        self.locked_period.save(username=self.test_user.username)

        with self.assertRaises(
            ClosedPeriodException
        ):

            LedgerEntryService.post(
                journal=self.journal,
                accounting_period=self.locked_period,
                source_event_type="claim_payment",
                source_event_reference="1",
                legs=self.valid_legs,
                user=self.test_user
            )

    def test_closed_period_rejected(self):

        self.closed_period.status = (
            AccountingPeriod.STATUS_CLOSED
        )

        self.closed_period.save(username=self.test_user.username)

        with self.assertRaises(
            ClosedPeriodException
        ):

            LedgerEntryService.post(
                journal=self.journal,
                accounting_period=self.closed_period,
                source_event_type="claim_payment",
                source_event_reference="1",
                legs=self.valid_legs,
                user=self.test_user
            )

    def test_missing_account_mapping(self):

        with self.assertRaises(
            MissingAccountMappingException
        ):

            LedgerEntryService.post(
                journal=self.journal,
                accounting_period=self.open_period,
                source_event_type="claim_payment",
                source_event_reference="1",
                legs=[
                    {
                        "account": None,
                        "amount": 100,
                    },
                    {
                        "account": self.cash_account,
                        "amount": -100,
                    },
                ],
                user=self.test_user
            )

    def test_unbalanced_entry_rejected(self):
        with self.assertRaises(ValidationError) as ctx:

            LedgerEntryService.post(
                journal=self.journal,
                accounting_period=self.open_period,
                source_event_type="claim_payment",
                source_event_reference="CLAIM-UNBALANCED",
                legs=[
                    {
                        "account": self.cash_account,
                        "amount": 100,
                    },
                    {
                        "account": self.expense_account,
                        "amount": -50,
                    },
                ],
                user=self.test_user,
            )

        self.assertIn(
            "balanced",
            str(ctx.exception).lower(),
        )

    def test_tags_are_attached_to_legs(self):
        result = LedgerEntryService.post(
            journal=self.journal,
            accounting_period=self.open_period,
            source_event_type="claim_payment",
            source_event_reference="CLAIM-TAGS",
            legs=self.valid_legs,
            tags={
                0: [self.analytic],
                1: [self.analytic2],
            },
            user=self.test_user,
        )

        self.assertIsNotNone(result.pk)

        self.assertEqual(
            LegTag.objects.count(),
            2,
        )

        legs = Leg.objects.filter(
            transaction=result.transaction
        )

        self.assertEqual(
            LegTag.objects.filter(
                leg=legs[0]
            ).count(),
            1,
        )

        self.assertEqual(
            LegTag.objects.filter(
                leg=legs[1]
            ).count(),
            1,
        )


class LedgerEntryServiceTest(TestCase):

    def setUp(self):

        self.test_user = create_test_interactive_user()

        self.sequence = Sequence(
            code="GL2",
            name="General Ledger2"
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

        self.journal = LedgerJournal(
            code="GENERAL1",
            name="General Journal1",
            sequence_id=self.sequence,
            default_credit_account_id=self.cash_account,
            default_debit_account_id=self.expense_account,
        )
        self.journal.save(username=self.test_user.username)

        self.period = AccountingPeriod(
            code="2021-05",
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.period.save(username=self.test_user.username)

    def test_post_requires_deployment_configuration(self):

        DeploymentConfiguration.objects.all().delete()

        with self.assertRaises(
            MissingDeploymentConfigurationException
        ):
            LedgerEntryService.post(
                journal=self.journal,
                accounting_period=self.period,
                source_event_type="invoice",
                source_event_reference="INV-001",
                legs=[
                    {
                        "account": self.expense_account,
                        "amount": Decimal("100"),
                    },
                    {
                        "account": self.cash_account,
                        "amount": Decimal("-100"),
                    },
                ],
                user=self.test_user,
            )


class LedgerEntryServiceAdditionalTests(TestCase):

    def setUp(self):
        self.user = create_test_interactive_user()

        self.cash_account = Account.objects.create(
            code="8101",
            full_code="8101",
            name="Cash",
        )

        self.expense_account = Account.objects.create(
            code="8102",
            full_code="8102",
            name="Expense",
        )

        self.sequence = Sequence(
            code="GL-ADD",
            name="General Ledger Additional",
        )
        self.sequence.save(username=self.user.username)

        self.journal = LedgerJournal(
            code="GENERAL-ADD",
            name="General Additional",
            sequence_id=self.sequence,
            default_credit_account_id=self.cash_account,
            default_debit_account_id=self.expense_account,
        )
        self.journal.save(username=self.user.username)

        self.period = AccountingPeriod(
            name="2026-10",
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.period.save(username=self.user.username)

        self.party_axis = AnalyticAxis(
            code=AnalyticAxis.PARTY,
            name="Party",
        )
        self.party_axis.save(username=self.user.username)

        self.party_value = AnalyticValue(
            axis=self.party_axis,
            party_type=AnalyticValue.PARTY_HEALTH_FACILITY,
            external_reference="HF-TEST",
            display_name="Test HF",
        )
        self.party_value.save(username=self.user.username)

        self.funder_axis = AnalyticAxis(
            code=AnalyticAxis.FUNDER,
            name="Funder",
        )
        self.funder_axis.save(username=self.user.username)

        self.funder_value = AnalyticValue(
            axis=self.funder_axis,
            party_type="insuree_family",
            funder_code="FUNDER-001",
            external_reference="FUNDER-001",
            display_name="Test Funder",
        )
        self.funder_value.save(username=self.user.username)

        cnfg = DeploymentConfiguration(
            currency_code="EUR",
            retained_earnings_account=self.cash_account,
        )
        cnfg.save(username=self.user.username)

    def test_post_requires_user(self):
        with self.assertRaises(ValidationError):
            LedgerEntryService.post(
                journal=self.journal,
                accounting_period=self.period,
                source_event_type="invoice",
                source_event_reference="INV-USER",
                legs=[
                    {
                        "account": self.cash_account,
                        "amount": 100,
                    },
                    {
                        "account": self.expense_account,
                        "amount": -100,
                    },
                ],
                user=None,
            )

    def test_post_requires_at_least_two_legs(self):
        with self.assertRaises(ValidationError):
            LedgerEntryService.post(
                journal=self.journal,
                accounting_period=self.period,
                source_event_type="invoice",
                source_event_reference="INV-ONE-LEG",
                legs=[
                    {
                        "account": self.cash_account,
                        "amount": 100,
                    },
                ],
                user=self.user,
            )

    def test_invalid_leg_tag_index_rejected(self):
        with self.assertRaises(ValidationError):
            LedgerEntryService.post(
                journal=self.journal,
                accounting_period=self.period,
                source_event_type="invoice",
                source_event_reference="INV-BAD-TAG",
                legs=[
                    {
                        "account": self.cash_account,
                        "amount": 100,
                    },
                    {
                        "account": self.expense_account,
                        "amount": -100,
                    },
                ],
                tags={
                    10: [self.party_value],
                },
                user=self.user,
            )

    def test_post_updates_account_balance_snapshot(self):
        LedgerEntryService.post(
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="invoice",
            source_event_reference="INV-SNAPSHOT",
            legs=[
                {
                    "account": self.cash_account,
                    "amount": 100,
                },
                {
                    "account": self.expense_account,
                    "amount": -100,
                },
            ],
            user=self.user,
        )

        cash_snapshot = AccountBalanceSnapshot.objects.get(
            accounting_period=self.period,
            account=self.cash_account,
        )

        expense_snapshot = AccountBalanceSnapshot.objects.get(
            accounting_period=self.period,
            account=self.expense_account,
        )

        self.assertEqual(
            cash_snapshot.balance_amount,
            Decimal("100"),
        )

        self.assertEqual(
            expense_snapshot.balance_amount,
            Decimal("100"),
            # normalement -100 mais les valeurs sont
            # passé par hordak en valeur absolu
        )

    def test_post_updates_party_balance(self):
        LedgerEntryService.post(
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="invoice",
            source_event_reference="INV-PARTY",
            legs=[
                {
                    "account": self.cash_account,
                    "amount": 100,
                },
                {
                    "account": self.expense_account,
                    "amount": -100,
                },
            ],
            tags={
                0: [self.party_value],
            },
            user=self.user,
        )

        balance = PartyLedgerBalance.objects.get(
            accounting_period=self.period,
            analytic_value=self.party_value,
        )

        self.assertEqual(
            balance.debit_amount,
            Decimal("100"),
        )

        self.assertEqual(
            balance.credit_amount,
            Decimal("0"),
        )

        self.assertEqual(
            balance.balance_amount,
            Decimal("100"),
        )

    def test_funder_tag_does_not_update_party_balance(self):
        LedgerEntryService.post(
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="invoice",
            source_event_reference="INV-FUNDER",
            legs=[
                {
                    "account": self.cash_account,
                    "amount": 100,
                },
                {
                    "account": self.expense_account,
                    "amount": -100,
                },
            ],
            tags={
                0: [self.funder_value],
            },
            user=self.user,
        )

        self.assertFalse(
            PartyLedgerBalance.objects.filter(
                accounting_period=self.period,
                analytic_value=self.funder_value,
            ).exists()
        )

    def test_post_creates_ledger_entry_meta(self):
        result = LedgerEntryService.post(
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="invoice",
            source_event_reference="INV-META",
            legs=[
                {
                    "account": self.cash_account,
                    "amount": 100,
                },
                {
                    "account": self.expense_account,
                    "amount": -100,
                },
            ],
            user=self.user,
        )

        self.assertEqual(
            result.accounting_period_id,
            self.period.uuid,
        )

        self.assertEqual(
            result.source_event_type,
            "invoice",
        )

        self.assertEqual(
            result.source_event_reference,
            "INV-META",
        )
