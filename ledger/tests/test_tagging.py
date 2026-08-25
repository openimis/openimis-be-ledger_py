from django.test import TestCase
from unittest.mock import patch
from ledger.models import (
    LedgerEntryMeta,
    AnalyticAxis,
    AnalyticValue,
    LegTag,
    LedgerJournal,
    Sequence,
    Account,
    DeploymentConfiguration,
    AccountingPeriod
)
from core.test_helpers import create_test_interactive_user
from ledger.signals import on_claim_valuated
from decimal import Decimal
from claim.models import Claim
from claim.test_helpers import create_test_claim
from policyholder.models import PolicyHolder


class PostingTaggingTest(TestCase):

    @classmethod
    def setUpTestData(self):
        self.user = create_test_interactive_user()
        custom_props = {
            "date_claimed": "2026-01-01",
            "valuated": Decimal("100"),
            "approved": Decimal("100"),
            "status": Claim.STATUS_VALUATED
        }
        self.claim = create_test_claim(custom_props=custom_props)

        self.sequence = Sequence(
            code="GL",
            name="GL",
        )
        self.sequence.save(
            username=self.user.username,
        )

        self.account = Account.objects.create(
            code="1001",
            full_code="1001",
            name="Account 1",
        )

        self.exp_account = Account.objects.create(
            code="2001",
            full_code="2001",
            name="Account 2",
        )

        self.claims_journal = LedgerJournal(
            code="Claims",
            name="Claims",
            sequence_id=self.sequence,
            default_credit_account_id=self.account,
            default_debit_account_id=self.exp_account,
        )
        self.claims_journal.save(username=self.user.username)

        self.account = Account.objects.create(
            code="1008",
            full_code="1008",
            name="Test Account",
        )

        cfg = DeploymentConfiguration(
            currency_code="EUR",
            retained_earnings_account=self.account,
        )
        cfg.save(username=self.user.username)

        self.period = AccountingPeriod(
            name="2026-01",
            start_date='2026-01-01',
            end_date='2026-02-01',
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.period.save(username=self.user.username)

        policy_holder = PolicyHolder(
            is_deleted=False,
            trade_name="OMS",
            code="OMS"
        )
        policy_holder.save(username=self.user.username)

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
