from types import SimpleNamespace

import graphene

from django.test import TestCase

from core.test_helpers import create_test_interactive_user

from ledger.models import (
    AccountingPeriod,
    AnalyticAxis,
    AnalyticValue,
    Account,
    LedgerJournal,
    Sequence,
    DeploymentConfiguration
)

from ledger.services import LedgerEntryService
from ledger.schema import Query


class LedgerEntriesFilterTest(TestCase):

    def setUp(self):

        self.user = create_test_interactive_user()

        self.context = SimpleNamespace(
            user=self.user,
        )

        self.period = AccountingPeriod(
            name="2026-01",
            code="2026-01",
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.period.save(
            username=self.user.username,
        )

        self.sequence = Sequence(
            code="GL",
            name="GL",
        )
        self.sequence.save(
            username=self.user.username,
        )

        self.account_1 = Account.objects.create(
            code="1001",
            full_code="1001",
            name="Account 1",
        )

        self.account_2 = Account.objects.create(
            code="2001",
            full_code="2001",
            name="Account 2",
        )

        self.journal = LedgerJournal(
            code="TEST",
            name="TEST",
            sequence_id=self.sequence,
            default_debit_account_id=self.account_1,
            default_credit_account_id=self.account_2,
        )
        self.journal.save(
            username=self.user.username,
        )

        self.party_axis = AnalyticAxis(
            code=AnalyticAxis.PARTY,
            name="Party",
        )
        self.party_axis.save(
            username=self.user.username,
        )

        self.funder_axis = AnalyticAxis(
            code=AnalyticAxis.FUNDER,
            name="Funder",
        )
        self.funder_axis.save(
            username=self.user.username,
        )

        self.party = AnalyticValue(
            axis=self.party_axis,
            party_type=(
                AnalyticValue.PARTY_HEALTH_FACILITY
            ),
            external_reference="HF001",
            display_name="HF001",
        )
        self.party.save(
            username=self.user.username,
        )

        self.funder = AnalyticValue(
            axis=self.funder_axis,
            funder_code="OMS",
            external_reference="OMS",
            display_name="OMS",
        )
        self.funder.save(
            username=self.user.username,
        )

        self.account_3 = Account.objects.create(
            code="2002",
            full_code="2002",
            name="Account 3",
        )

        self.conf = DeploymentConfiguration(
            currency_code="EUR",
            retained_earnings_account=self.account_3,
        )
        self.conf.save(username=self.user.username)

        meta = LedgerEntryService.post(
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="claim_payment",
            source_event_reference="REF001",
            legs=[
                {
                    "account": self.account_1,
                    "amount": 100,
                },
                {
                    "account": self.account_2,
                    "amount": -100,
                },
            ],
            tags={
                0: [
                    self.party,
                    self.funder,
                ],
                1: [
                    self.party,
                    self.funder,
                ],
            },
            user=self.user,
        )

        self.meta_id = meta.id

    def test_ledger_entries_filter_by_party(self):

        query = """
        query($party: UUID!) {
          ledgerEntries(
            party: $party
          ) {
            edges {
              node {
                id
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
            variables={
                "party": str(
                    self.party.uuid
                ),
            },
            context_value=self.context,
        )

        self.assertIsNone(
            result.errors,
        )

        self.assertEqual(
            len(
                result.data[
                    "ledgerEntries"
                ]["edges"]
            ),
            1,
        )

    def test_ledger_entries_filter_by_funder(self):

        query = """
        query($funder: UUID!) {
          ledgerEntries(
            funder: $funder
          ) {
            edges {
              node {
                id
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
            variables={
                "funder": str(
                    self.funder.uuid
                ),
            },
            context_value=self.context,
        )

        self.assertIsNone(
            result.errors,
        )

        self.assertEqual(
            len(
                result.data[
                    "ledgerEntries"
                ]["edges"]
            ),
            1,
        )
