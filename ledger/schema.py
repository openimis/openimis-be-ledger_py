import graphene
from core.schema import OrderedDjangoFilterConnectionField
from .gql_queries import (
    PartyLedgerBalanceGQLType,
    FunderActivityReportGQLType,
    LedgerEntryGQLType,
    AnalyticValueGQLType,
    AccountingPeriodGQLType
)
from .models import (
    LegTag,
    Leg,
    AnalyticAxis,
    LedgerEntryMeta
)
from decimal import Decimal
from django.db.models import Sum


class Query(graphene.ObjectType):

    party_ledger_balance = OrderedDjangoFilterConnectionField(
        PartyLedgerBalanceGQLType
    )

    analytic_value = OrderedDjangoFilterConnectionField(
        AnalyticValueGQLType
    )

    accounting_periods = OrderedDjangoFilterConnectionField(
        AccountingPeriodGQLType
    )

    ledger_entries = OrderedDjangoFilterConnectionField(
        LedgerEntryGQLType,
        party=graphene.UUID(),
        funder=graphene.UUID(),
    )

    funder_activity_report = graphene.Field(
        FunderActivityReportGQLType,
        analytic_value_id=graphene.UUID(required=True),
        accounting_period_id=graphene.UUID(required=True),
    )

    def resolve_ledger_entries(
        self,
        info,
        party=None,
        funder=None,
        **kwargs,
    ):

        queryset = LedgerEntryMeta.objects.all()

        if party:
            queryset = queryset.filter(
                transaction__legs__analytic_tags__analytic_value_id=party,
                transaction__legs__analytic_tags__axis__code=AnalyticAxis.PARTY,
            )

        if funder:
            queryset = queryset.filter(
                transaction__legs__analytic_tags__analytic_value_id=funder,
                transaction__legs__analytic_tags__axis__code=AnalyticAxis.FUNDER,
            )

        return queryset.distinct()

    def resolve_funder_activity_report(
        self,
        info,
        analytic_value_id,
        accounting_period_id,
    ):
        tagged_leg_ids = (
            LegTag.objects
            .filter(
                analytic_value_id=analytic_value_id,
                accounting_period_id=accounting_period_id,
                analytic_value__axis__code=AnalyticAxis.FUNDER,
            )
            .values_list(
                "leg_id",
                flat=True,
            )
            .distinct()
        )

        totals = (
            Leg.objects
            .filter(
                id__in=tagged_leg_ids,
            )
            .aggregate(
                debit_amount=Sum("debit"),
                credit_amount=Sum("credit"),
            )
        )

        debit_amount = totals["debit_amount"] or Decimal("0")
        credit_amount = totals["credit_amount"] or Decimal("0")

        return FunderActivityReportGQLType(
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            balance_amount=debit_amount - credit_amount,
        )
