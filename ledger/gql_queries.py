from graphene_django import DjangoObjectType
import graphene
from .models import (
    LedgerEntryMeta,
    PartyLedgerBalance,
    AccountingPeriod,
    LedgerJournal,
    AnalyticValue
)
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


class LedgerJournalGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()

    class Meta:
        model = LedgerJournal
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "name": ["exact"],
            "code": ["exact"],
            "type": ["exact"]
        }
        connection_class = ExtendedConnection


class LedgerEntryGQLType(DjangoObjectType):

    client_mutation_id = graphene.String()

    class Meta:
        model = LedgerEntryMeta
        interfaces = (graphene.relay.Node,)
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
