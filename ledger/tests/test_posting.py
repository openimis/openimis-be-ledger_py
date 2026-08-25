# ledger/tests/test_posting.py
from decimal import Decimal
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from ledger.models import (
    AccountingPeriod,
    Account,
    LedgerEntryMeta,
    LedgerJournal,
    Sequence,
    DeploymentConfiguration,
    UnmappedFinancialEvent,
    AnalyticAxis,
    AnalyticValue,
    LegTag
)
from policyholder.models import PolicyHolder
from claim.test_helpers import create_test_claim
from ledger.signals import (
    on_claim_valuated,
    on_invoice_issued,
    on_payroll_disbursed,
    on_payment_point_reconciled,
)
from core.test_helpers import create_test_interactive_user
from claim.models import Claim
from datetime import date, timedelta
from calendar import monthrange


def create_accounting_periods(user):
    """Crée 50 périodes comptables de janvier 2020 à février 2024."""
    current = date(2020, 1, 1)
    end_loop = date(2024, 2, 1)  # 50 mois

    while current < end_loop:
        # Dernier jour du mois
        last_day = monthrange(current.year, current.month)[1]
        period_end = current.replace(day=last_day)

        period = AccountingPeriod(
            uuid=uuid.uuid4(),                     # gen_random_uuid()
            is_deleted=False,
            version=1,
            status=1,
            user_created=user,
            user_updated=user,
            name=f'Period {current.strftime("%Y-%m")}',
            code=f'P{current.strftime("%Y%m")}',
            start_date=current,
            end_date=period_end,
            date_created=date.today(),             # ou timezone.now() si besoin
            date_updated=date.today(),
        )
        period.save(username=user.username)
        current = (current.replace(day=1) + timedelta(days=32)).replace(day=1)


class PostingSignalsTest(TestCase):

    @classmethod
    def setUpTestData(cls):

        cls.user = create_test_interactive_user()

        create_accounting_periods(cls.user)

        policy_holder = PolicyHolder(
            is_deleted=False,
            trade_name="OMS",
            code="OMS"
        )
        policy_holder.save(username=cls.user.username)

        custom_props = {
            "date_claimed": "2021-02-01",
            "valuated": Decimal("100"),
            "approved": Decimal("100"),
            "status": Claim.STATUS_VALUATED
        }
        cls.claim = create_test_claim(custom_props=custom_props)

        cls.account = Account.objects.create(
            code="1008",
            full_code="1008",
            name="Test Account",
        )
        cls.exp_account = Account.objects.create(
            code="1002",
            full_code="1002",
            name="Test Account Expense",
        )

        cls.sequence = Sequence(
            code="GLA",
            name="General Ledger A"
        )
        cls.sequence.save(username=cls.user.username)

        cls.period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_OPEN,
        )
        cls.period.save(username=cls.user.username)

        cls.claims_journal = LedgerJournal(
            code="Claims",
            name="Claims",
            sequence_id=cls.sequence,
            default_credit_account_id=cls.account,
            default_debit_account_id=cls.exp_account,
        )
        cls.claims_journal.save(username=cls.user.username)

        cls.sales_journal = LedgerJournal(
            code="Sales",
            name="Sales",
            sequence_id=cls.sequence,
            default_credit_account_id=cls.account,
            default_debit_account_id=cls.exp_account,
        )
        cls.sales_journal.save(username=cls.user.username)

        cls.payroll_journal = LedgerJournal(
            code="Payroll",
            name="Payroll",
            sequence_id=cls.sequence,
            default_credit_account_id=cls.account,
            default_debit_account_id=cls.exp_account,
        )
        cls.payroll_journal.save(username=cls.user.username)

        cls.bank_journal = LedgerJournal(
            code="Bank",
            name="Bank",
            sequence_id=cls.sequence,
            default_credit_account_id=cls.account,
            default_debit_account_id=cls.exp_account,
        )
        cls.bank_journal.save(username=cls.user.username)

        cfg = DeploymentConfiguration(
            currency_code="EUR",
            retained_earnings_account=cls.account,
        )
        cfg.save(username=cls.user.username)

    # ------------------------------------------------------------------
    # T020
    # ------------------------------------------------------------------

    def test_claim_valuated_posts_balanced_entry(self):

        on_claim_valuated(
            sender=None,
            claim=self.claim,
            user=self.user,
            kwargs={"claim": self.claim.uuid}
        )

        self.assertEqual(
            LedgerEntryMeta.objects.count(),
            1,
        )

        meta = LedgerEntryMeta.objects.first()

        self.assertEqual(
            meta.journal.code,
            "Claims",
        )

        balance = sum(
            (
                leg.debit.amount if leg.debit else 0
            ) - (
                leg.credit.amount if leg.credit else 0
            )
            for leg in meta.transaction.legs.all()
        )

        self.assertEqual(
            balance,
            Decimal("0"),
        )

    # ------------------------------------------------------------------
    # T021
    # ------------------------------------------------------------------

    @patch("ledger.signals.resolve_party_tag")
    def test_invoice_issued_posts_to_sales_journal(self, mock_resolve_party_tag):

        party_axis = AnalyticAxis(
            code=AnalyticAxis.PARTY,
            name="Party",
        )
        party_axis.save(username=self.user.username)

        party_value = AnalyticValue(
            axis=party_axis,
            party_type=AnalyticValue.PARTY_HEALTH_FACILITY,
            external_reference="HF001",
            display_name="HF 001",
        )
        party_value.save(username=self.user.username)

        mock_resolve_party_tag.return_value = party_value

        on_invoice_issued(
            sender=None,
            result={
                "data": {
                    "id": "INV001",
                    "amount_total": "250",
                    "invoice_date": "2021-02-01",
                    "health_facility_id": self.claim.health_facility
                }
            },
            user=self.user,
        )

        meta = LedgerEntryMeta.objects.get()

        self.assertEqual(
            meta.journal.code,
            "Sales"
        )

    # ------------------------------------------------------------------
    # T022
    # ------------------------------------------------------------------

    def test_payroll_disbursed_posts_entry(self):

        benefits = [
            SimpleNamespace(amount=100),
            SimpleNamespace(amount=50),
        ]

        on_payroll_disbursed(
            sender=None,
            benefits=benefits,
            user=self.user,
            payroll_id="PAY001",
            payroll_date="2021-02-01",
            payment_point_manager_id=1
        )

        meta = LedgerEntryMeta.objects.get()

        self.assertEqual(
            meta.journal.code,
            "Payroll"
        )

        self.assertEqual(
            meta.transaction.legs.count(),
            2
        )

    # ------------------------------------------------------------------
    # T023
    # ------------------------------------------------------------------

    def test_payment_point_reconciled_posts_variance(self):

        benefits = [
            SimpleNamespace(amount=100)
        ]

        on_payment_point_reconciled(
            sender=None,
            benefits=benefits,
            variance=Decimal("5"),
            user=self.user,
            payroll_id="PAY001",
            payroll_date="2021-02-01",
            payment_point_manager_id=1
        )

        meta = LedgerEntryMeta.objects.get()

        self.assertEqual(
            meta.journal.code,
            "Bank"
        )

        self.assertEqual(
            meta.transaction.legs.count(),
            4
        )

    # ------------------------------------------------------------------
    # T024
    # ------------------------------------------------------------------

    def test_zero_claim_valuation_skipped(self):

        self.claim.valuated = Decimal("0")
        self.claim.approved = Decimal("0")
        self.claim.save()

        on_claim_valuated(
            sender=None,
            claim=self.claim,
            user=self.user,
            kwargs={"claim": self.claim.uuid}
        )

        self.assertFalse(
            LedgerEntryMeta.objects.exists()
        )
        self.claim.valuated = Decimal("1000")
        self.claim.approved = Decimal("1000")
        self.claim.save()

    def test_zero_invoice_skipped(self):

        on_invoice_issued(
            sender=None,
            result={
                "data": {
                    "id": "INV001",
                    "amount_total": "0",
                    "invoice_date": "2021-02-01",
                    "health_facility_id": self.claim.health_facility
                }
            },
            user=self.user,
        )

        self.assertFalse(
            LedgerEntryMeta.objects.exists()
        )

    def test_zero_payroll_skipped(self):

        benefits = [
            SimpleNamespace(amount=0)
        ]

        on_payroll_disbursed(
            sender=None,
            benefits=benefits,
            user=self.user,
            payroll_id="PAY001",
            payroll_date="2021-02-01",
            payment_point_manager_id=1
        )

        self.assertFalse(
            LedgerEntryMeta.objects.exists()
        )

    def test_zero_reconciliation_skipped(self):

        benefits = [
            SimpleNamespace(amount=0)
        ]

        on_payment_point_reconciled(
            sender=None,
            benefits=benefits,
            variance=Decimal("0"),
            user=self.user,
            payroll_id="PAY001",
            payroll_date="2021-02-01"
        )

        self.assertFalse(
            LedgerEntryMeta.objects.exists()
        )

    def test_claim_not_valuated_skipped(self):

        # claim = SimpleNamespace(status=Claim.STATUS_PROCESSED)

        self.claim.status = Claim.STATUS_PROCESSED
        self.claim.save()
        on_claim_valuated(
            sender=None,
            claim=self.claim,
            user=self.user,
            kwargs={"claim": self.claim.uuid}
        )

        self.assertFalse(
            LedgerEntryMeta.objects.exists()
        )

    # ------------------------------------------------------------------
    # T025
    # ------------------------------------------------------------------

    @patch(
        "ledger.signals.resolve_mapping",
        return_value=None,
    )
    def test_unmapped_claim_valuated_event_is_surfaced(
        self,
        _
    ):

        self.claim.status = Claim.STATUS_VALUATED
        self.claim.save()

        on_claim_valuated(
            sender=None,
            claim=self.claim,
            user=self.user,
            kwargs={"claim": self.claim.uuid},
        )

        self.assertEqual(
            LedgerEntryMeta.objects.count(),
            0,
        )

        self.assertEqual(
            UnmappedFinancialEvent.objects.count(),
            1,
        )

        event = (
            UnmappedFinancialEvent.objects.first()
        )

        self.assertEqual(
            event.event_type,
            "claim_valuated",
        )

    @patch(
        "ledger.signals.resolve_mapping",
        return_value=None,
    )
    def test_unmapped_invoice_event_is_surfaced(self, _):

        on_invoice_issued(
            sender=None,
            result={
                "data": {
                    "id": "INV001",
                    "amount_total": "100",
                    "invoice_date": "2021-02-01"
                }
            },
            user=self.user,
        )

        self.assertEqual(
            LedgerEntryMeta.objects.count(),
            0,
        )

        self.assertEqual(
            UnmappedFinancialEvent.objects.count(),
            1,
        )

        event = UnmappedFinancialEvent.objects.first()

        self.assertEqual(
            event.event_type,
            "invoice_issued",
        )

    @patch(
        "ledger.signals.resolve_mapping",
        return_value=None,
    )
    def test_unmapped_payroll_event_is_surfaced(self, _):

        benefits = [
            SimpleNamespace(amount=100)
        ]

        on_payroll_disbursed(
            sender=None,
            benefits=benefits,
            payroll_id="PAY001",
            user=self.user,
            payroll_date="2021-02-01"
        )

        self.assertEqual(
            LedgerEntryMeta.objects.count(),
            0,
        )

        self.assertEqual(
            UnmappedFinancialEvent.objects.count(),
            1,
        )

        event = UnmappedFinancialEvent.objects.first()

        self.assertEqual(
            event.event_type,
            "payroll_disbursement",
        )

    @patch(
        "ledger.signals.resolve_mapping",
        return_value=None,
    )
    def test_unmapped_reconciliation_event_is_surfaced(self, _):

        benefits = [
            SimpleNamespace(amount=100)
        ]

        on_payment_point_reconciled(
            sender=None,
            benefits=benefits,
            variance=Decimal("5"),
            payroll_id="PAY001",
            user=self.user,
            payroll_date="2021-02-01"
        )

        self.assertEqual(
            LedgerEntryMeta.objects.count(),
            0,
        )

        self.assertEqual(
            UnmappedFinancialEvent.objects.count(),
            1,
        )

        event = UnmappedFinancialEvent.objects.first()

        self.assertEqual(
            event.event_type,
            "payment_point_reconciliation",
        )

    @patch("ledger.signals.LedgerEntryService.post")
    @patch("ledger.signals.resolve_party_tag")
    def test_invoice_posts_party_tag(
        self,
        mock_resolve_party_tag,
        mock_post,
    ):
        party_axis = AnalyticAxis(
            code=AnalyticAxis.PARTY,
            name="Party",
        )
        party_axis.save(username=self.user.username)

        party_value = AnalyticValue(
            axis=party_axis,
            party_type=AnalyticValue.PARTY_HEALTH_FACILITY,
            external_reference="HF001",
            display_name="HF 001",
        )
        party_value.save(username=self.user.username)

        mock_resolve_party_tag.return_value = party_value

        on_invoice_issued(
            sender=None,
            result={
                "data": {
                    "id": "INV001",
                    "amount_total": "100",
                    "health_facility_id": "HF001",
                    "invoice_date": "2021-02-01",
                }
            },
            user=self.user,
        )

        mock_post.assert_called_once()

        tags = mock_post.call_args.kwargs["tags"]

        self.assertEqual(
            tags,
            {
                0: [party_value],
                1: [party_value],
            },
        )

    @patch(
        "ledger.signals.resolve_party_tag",
        return_value=None,
    )
    def test_invoice_issued_posts_without_party_tag_when_health_facility_is_unmapped(
        self,
        mock_resolve_party_tag,
    ):
        on_invoice_issued(
            sender=None,
            result={
                "data": {
                    "id": "INV001",
                    "amount_total": "250",
                    "invoice_date": "2021-02-01",
                    "health_facility_id": "UNKNOWN-HF",
                }
            },
            user=self.user,
        )

        # L'écriture doit quand même être créée.
        meta = LedgerEntryMeta.objects.get()

        self.assertEqual(
            meta.journal.code,
            "Sales",
        )

        # Aucun tag PARTY ne doit être créé.
        self.assertEqual(
            LegTag.objects.count(),
            0,
        )

        # Le resolver doit bien avoir été appelé.
        mock_resolve_party_tag.assert_called_once_with(
            "UNKNOWN-HF",
            AnalyticValue.PARTY_HEALTH_FACILITY,
        )

    @patch("ledger.signals.LedgerEntryService.post")
    @patch("ledger.signals.resolve_party_tag")
    def test_payroll_posts_payment_point_manager_tag(
        self,
        mock_resolve_party_tag,
        mock_post,
    ):

        party_axis = AnalyticAxis(
            code=AnalyticAxis.PARTY,
            name="Party",
        )
        party_axis.save(username=self.user.username)

        party_value = AnalyticValue(
            axis=party_axis,
            party_type=AnalyticValue.PARTY_PAYMENT_POINT_MANAGER,
            external_reference="PPM001",
            display_name="Payment Point Manager",
        )
        party_value.save(username=self.user.username)

        mock_resolve_party_tag.return_value = party_value

        benefits = [
            SimpleNamespace(amount=100)
        ]

        on_payroll_disbursed(
            sender=None,
            benefits=benefits,
            user=self.user,
            payroll_id="PAY001",
            payment_point_manager_id="PPM001",
            payroll_date="2021-02-01"
        )

        mock_post.assert_called_once()

        tags = mock_post.call_args.kwargs["tags"]

        self.assertIn(party_value, tags[0])
        self.assertIn(party_value, tags[1])

    @patch("ledger.signals.LedgerEntryService.post")
    @patch("ledger.signals.resolve_party_tag")
    def test_reconciliation_posts_payment_point_manager_tag(
        self,
        mock_resolve_party_tag,
        mock_post,
    ):

        party_axis = AnalyticAxis(
            code=AnalyticAxis.PARTY,
            name="Party",
        )
        party_axis.save(username=self.user.username)

        party_value = AnalyticValue(
            axis=party_axis,
            party_type=AnalyticValue.PARTY_PAYMENT_POINT_MANAGER,
            external_reference="PPM001",
            display_name="Payment Point Manager",
        )
        party_value.save(username=self.user.username)

        mock_resolve_party_tag.return_value = party_value

        benefits = [
            SimpleNamespace(amount=100)
        ]

        on_payment_point_reconciled(
            sender=None,
            benefits=benefits,
            variance=Decimal("5"),
            user=self.user,
            payroll_id="PAY001",
            payment_point_manager_id="PPM001",
            payroll_date="2021-02-01"
        )

        mock_post.assert_called_once()

        tags = mock_post.call_args.kwargs["tags"]

        self.assertIn(party_value, tags[0])
        self.assertIn(party_value, tags[1])

    @patch("ledger.signals.resolve_funder_tag")
    @patch("ledger.signals.resolve_party_tag")
    def test_claim_valuated_tags_party_and_funder_on_same_legs(
        self,
        mock_resolve_party_tag,
        mock_resolve_funder_tag,
    ):
        """
        T036:
        Une écriture claim_valuated doit pouvoir porter simultanément
        un tag PARTY et un tag FUNDER sur chacun de ses legs.

        Les deux axes doivent rester indépendamment interrogeables.
        """

        party = AnalyticAxis(
            code=AnalyticAxis.PARTY,
            name="Party",
        )
        party.save(username=self.user.username)
        party_value = AnalyticValue(
            axis=party,
            party_type=AnalyticValue.PARTY_HEALTH_FACILITY,
            external_reference="HF001",
            display_name="HF 001",
        )
        party_value.save(username=self.user.username)

        funder = AnalyticAxis(
            code=AnalyticAxis.FUNDER,
            name="Funder",
        )
        funder.save(username=self.user.username)
        funder_value = AnalyticValue(
            axis=funder,
            party_type=AnalyticValue.PARTY_PAYMENT_POINT_MANAGER,
            external_reference="HF002",
            display_name="HF 002",
            funder_code="OMS"
        )
        funder_value.save(username=self.user.username)

        mock_resolve_party_tag.return_value = party_value
        mock_resolve_funder_tag.return_value = funder_value

        on_claim_valuated(
            sender=None,
            claim=self.claim,
            user=self.user,
        )

        meta = LedgerEntryMeta.objects.get()

        legs = list(
            meta.transaction.legs.all()
        )

        self.assertEqual(
            len(legs),
            2,
        )

        for leg in legs:

            tags = list(
                LegTag.objects
                .filter(leg=leg)
                .select_related(
                    "analytic_value",
                    "axis",
                )
            )

            self.assertEqual(
                len(tags),
                2,
            )

            # --------------------------------------------------------
            # PARTY
            # --------------------------------------------------------

            party_tags = [
                tag
                for tag in tags
                if tag.axis.code == AnalyticAxis.PARTY
            ]

            self.assertEqual(
                len(party_tags),
                1,
            )

            self.assertEqual(
                party_tags[0].analytic_value,
                party_value,
            )

            # --------------------------------------------------------
            # FUNDER
            # --------------------------------------------------------

            funder_tags = [
                tag
                for tag in tags
                if tag.axis.code == AnalyticAxis.FUNDER
            ]

            self.assertEqual(
                len(funder_tags),
                1,
            )

            self.assertEqual(
                funder_tags[0].analytic_value,
                funder_value,
            )

    @patch("ledger.signals.resolve_funder_tag")
    @patch("ledger.signals.resolve_party_tag")
    def test_claim_valuated_party_and_funder_are_independently_queryable(
        self,
        mock_resolve_party_tag,
        mock_resolve_funder_tag,
    ):
        """
        T036:
        PARTY et FUNDER sont attachés aux mêmes legs mais peuvent
        être interrogés indépendamment via leur axe.
        """

        party = AnalyticAxis(
            code=AnalyticAxis.PARTY,
            name="Party",
        )
        party.save(username=self.user.username)
        party_value = AnalyticValue(
            axis=party,
            party_type=AnalyticValue.PARTY_HEALTH_FACILITY,
            external_reference="HF001",
            display_name="HF 001",
        )
        party_value.save(username=self.user.username)

        funder = AnalyticAxis(
            code=AnalyticAxis.FUNDER,
            name="Funder",
        )
        funder.save(username=self.user.username)
        funder_value = AnalyticValue(
            axis=funder,
            party_type=AnalyticValue.PARTY_PAYMENT_POINT_MANAGER,
            external_reference="HF002",
            display_name="HF 002",
            funder_code="OMS"
        )
        funder_value.save(username=self.user.username)

        mock_resolve_party_tag.return_value = party_value
        mock_resolve_funder_tag.return_value = funder_value

        on_claim_valuated(
            sender=None,
            claim=self.claim,
            user=self.user,
        )

        meta = LedgerEntryMeta.objects.get()

        # ------------------------------------------------------------
        # Recherche par PARTY
        # ------------------------------------------------------------

        party_tags = LegTag.objects.filter(
            leg__transaction=meta.transaction,
            axis__code=AnalyticAxis.PARTY,
            analytic_value=party_value,
        )

        self.assertEqual(
            party_tags.count(),
            2,
        )

        # ------------------------------------------------------------
        # Recherche par FUNDER
        # ------------------------------------------------------------

        funder_tags = LegTag.objects.filter(
            leg__transaction=meta.transaction,
            axis__code=AnalyticAxis.FUNDER,
            analytic_value=funder_value,
        )

        self.assertEqual(
            funder_tags.count(),
            2,
        )

        # ------------------------------------------------------------
        # Les deux axes concernent les mêmes legs
        # ------------------------------------------------------------

        party_leg_ids = set(
            party_tags.values_list(
                "leg_id",
                flat=True,
            )
        )

        funder_leg_ids = set(
            funder_tags.values_list(
                "leg_id",
                flat=True,
            )
        )

        self.assertEqual(
            party_leg_ids,
            funder_leg_ids,
        )
