from graphene_django import DjangoObjectType
import graphene
from .models import (
    LedgerEntryMeta,
    PartyLedgerBalance,
    AccountingPeriod,
    LedgerJournal,
    AnalyticValue,
    ManualReviewQueueItem,
    ExternalReplicationRecord,
    DeploymentConfiguration,
    JournalTypes,
    AnalyticAxis,
    LegTag
)
from decimal import Decimal
from hordak.models import Account, Leg, Transaction
from core import prefix_filterset, ExtendedConnection


class AccountingPeriodGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()

    class Meta:
        model = AccountingPeriod
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "start_date": ["gte", "lte", "gt", "lt", "exact"],
            "end_date": ["gte", "lte", "gt", "lt", "exact"],
            "name": ["exact"],
            "code": ["exact"],
            "status": ["exact"],
        }
        connection_class = ExtendedConnection


class AnaliticAxisGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()

    class Meta:
        model = AnalyticAxis
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "name": ["exact"],
            "code": ["exact"],
        }
        connection_class = ExtendedConnection


class JournalTypeGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()

    class Meta:
        model = JournalTypes
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "id": ["exact"],
            "code": ["exact"],
            "type": ["exact"],
            "alt_language": ["exact"]
        }
        connection_class = ExtendedConnection


class LedgerJournalGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()

    class Meta:
        model = LedgerJournal
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "name": ["exact"],
            "code": ["exact"],
            **prefix_filterset(
                "type__",
                JournalTypeGQLType._meta.filter_fields
            ),
        }
        connection_class = ExtendedConnection


class TransactionGQLType(DjangoObjectType):
    balance = graphene.String()

    class Meta:
        model = Transaction
        interfaces = (graphene.relay.Node,)
        fields = ("id", "uuid", "date", "description", "legs", "ledger_meta")
        connection_class = ExtendedConnection

    def resolve_balance(self, info):
        return str(self.get_balance())


class LegGQLType(DjangoObjectType):
    debit = graphene.Decimal()
    credit = graphene.Decimal()

    class Meta:
        model = Leg
        interfaces = (graphene.relay.Node,)
        fields = ("id", "transaction", "account", "amount", "description", "tags")
        connection_class = ExtendedConnection

    def resolve_debit(self, info):
        return abs(self.amount.amount) if self.is_debit() else Decimal(0)

    def resolve_credit(self, info):
        return abs(self.amount.amount) if self.is_credit() else Decimal(0)


class AnalyticValueGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()

    class Meta:
        model = AnalyticValue
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "funder_code": ["exact"],
            "party_type": ["exact"],
            "external_reference": ["exact"],
            "display_name": ["exact"],
        }
        connection_class = ExtendedConnection


class LegTagGQLType(DjangoObjectType):
    class Meta:
        model = LegTag
        interfaces = (graphene.relay.Node,)
        fields = ("id", "leg", "analytic_value", "axis")
        connection_class = ExtendedConnection


class LedgerEntryGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()
    party = graphene.Field(AnalyticValueGQLType)
    funder = graphene.Field(AnalyticValueGQLType)
    account = graphene.String()

    def resolve_party(self, info):
        current_tag = None
        for leg in self.transaction.legs.all():
            for tag in leg.analytic_tags.all():
                if tag.axis.code == AnalyticAxis.PARTY:
                    current_tag = tag
                    return current_tag.analytic_value

        return None

    def resolve_funder(self, info):
        current_tag = None
        for leg in self.transaction.legs.all():
            for tag in leg.analytic_tags.all():
                if tag.axis.code == AnalyticAxis.FUNDER:
                    current_tag = tag
                    return current_tag.analytic_value

        return None

    class Meta:
        model = LedgerEntryMeta
        interfaces = (graphene.relay.Node,)
        fields = (
            "id", "transaction", "party", "source_event_type", "source_event_reference",
                  "posted_at", "journal", "accounting_period")
        filter_fields = {
            "source_event_type": ["exact"],
            "source_event_reference": ["exact"],
            "posted_at": [
                "gte",
                "lte",
                "gt",
                "lt",
                "exact",
            ],

            "transaction__legs__analytic_tags__analytic_value__id": [
                "exact",
            ],

            "transaction__legs__analytic_tags__analytic_value__axis__code": [
                "exact",
            ],

            **prefix_filterset(
                "journal__",
                LedgerJournalGQLType._meta.filter_fields
            ),

            **prefix_filterset(
                "accounting_period__",
                AccountingPeriodGQLType._meta.filter_fields
            ),
        }
        connection_class = ExtendedConnection


class DeploymentConfigurationGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()

    class Meta:
        model = DeploymentConfiguration
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "operating_mode": ["exact"],
            "external_system": ["exact"],
            "currency_code": ["exact"],
            "retained_earnings_account__id": ["exact"],
            "retained_earnings_account__name": ["exact"],
            "retained_earnings_account__code": ["exact"]
        }
        connection_class = ExtendedConnection


class PartyLedgerBalanceGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()

    class Meta:
        model = PartyLedgerBalance
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            **prefix_filterset(
                "analytic_value__",
                AnalyticValueGQLType._meta.filter_fields
            ),
            **prefix_filterset(
                "accounting_period__",
                AccountingPeriodGQLType._meta.filter_fields
            ),
        }
        connection_class = ExtendedConnection


class FunderActivityReportGQLType(graphene.ObjectType):
    debit_amount = graphene.Decimal()
    credit_amount = graphene.Decimal()
    balance_amount = graphene.Decimal()


class ReplicationRecordGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()

    class Meta:
        model = ExternalReplicationRecord
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "id": ["exact"],
            "target_system": ["exact"],
            "idempotency_key": ["exact"],
            "external_reference": ["exact"],
            "status": ["exact"],
            "rejection_reason": ["exact"],
            **prefix_filterset(
                "ledger_entry__",
                LedgerEntryGQLType._meta.filter_fields
            ),
        }
        connection_class = ExtendedConnection


class ManualReviewQueueItemGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()

    class Meta:
        model = ManualReviewQueueItem
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "resolution_note": ["exact"],
            "id": ["exact"],
            "resolved_by_transaction__id": ["exact"],
            **prefix_filterset(
                "replication_record__",
                ReplicationRecordGQLType._meta.filter_fields
            ),
        }
        connection_class = ExtendedConnection


class AccountGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()

    class Meta:
        model = Account
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "uuid": ["exact"],
            "parent": ["exact"],
            "code": ["exact"],
            "full_code": ["exact"],
            "type": ["exact"],
            "is_bank_account": ["exact"]
        }
        connection_class = ExtendedConnection
