import graphene
from django.contrib.auth.models import AnonymousUser
from decimal import Decimal
import logging
from django.db.models import Sum
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from core.schema import OrderedDjangoFilterConnectionField
from django.utils.translation import gettext as _
from .gql_queries import (
    PartyLedgerBalanceGQLType,
    FunderActivityReportGQLType,
    LedgerEntryGQLType,
    AnalyticValueGQLType,
    AccountingPeriodGQLType,
    ManualReviewQueueItemGQLType,
    DeploymentConfigurationGQLType,
    AccountGQLType
)
from .gql_mutations import (
    CreateDeploymentConfigurationMutation,
    OpenAccountingPeriodMutation,
    LockAccountingPeriodMutation,
    CloseAccountingPeriodMutation,
    ReopenAccountingPeriodMutation,
    CreateAccountMutation,
    ManualReviewItemMutation
)
from .models import (
    LegTag,
    Leg,
    AnalyticAxis,
    LedgerEntryMeta,
    AccountingPeriod,
    ManualReviewQueueItem,
    DeploymentConfiguration
)
from .apps import LedgerConfig
logger = logging.getLogger(__name__)


class Query(graphene.ObjectType):

    party_ledger_balance = OrderedDjangoFilterConnectionField(
        PartyLedgerBalanceGQLType
    )

    analytic_value = OrderedDjangoFilterConnectionField(
        AnalyticValueGQLType
    )

    deployment_configuration = OrderedDjangoFilterConnectionField(
        DeploymentConfigurationGQLType,
        orderBy=graphene.List(of_type=graphene.String)
    )

    accounting_periods = OrderedDjangoFilterConnectionField(
        AccountingPeriodGQLType,
        orderBy=graphene.List(of_type=graphene.String)
    )

    manual_review_queue = OrderedDjangoFilterConnectionField(
        ManualReviewQueueItemGQLType
    )

    accounts = OrderedDjangoFilterConnectionField(
        AccountGQLType
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

        queryset = LedgerEntryMeta.objects.filter(is_deleted=False).all()

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

    def resolve_accounting_periods(
        self,
        info,
        **kwargs,
    ):
        if type(info.context.user) is AnonymousUser or not info.context.user.id:
            raise ValidationError("mutation.authentication_required")
        if not info.context.user.has_perms(
                LedgerConfig.gql_query_ledger_perms):
            raise PermissionDenied(_("unauthorized"))
        queryset = AccountingPeriod.objects.filter(is_deleted=False).all()

        return queryset.distinct()

    def resolve_deployment_configuration(
        self,
        info,
        **kwargs,
    ):
        if type(info.context.user) is AnonymousUser or not info.context.user.id:
            raise ValidationError("mutation.authentication_required")
        if not info.context.user.has_perms(
                LedgerConfig.gql_query_ledger_perms):
            raise PermissionDenied(_("unauthorized"))
        queryset = DeploymentConfiguration.objects.filter(is_deleted=False).all()

        return queryset.distinct()

    def resolve_manual_review_queue(
        self,
        info,
        **kwargs,
    ):
        logger.debug("get ManualReviewQueueItem...")
        if type(info.context.user) is AnonymousUser or not info.context.user.id:
            raise ValidationError("mutation.authentication_required")
        if not info.context.user.has_perms(
                LedgerConfig.gql_query_ledger_perms):
            raise PermissionDenied(_("unauthorized"))
        queryset = ManualReviewQueueItem.objects.filter(is_deleted=False).all()

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


class Mutation(graphene.ObjectType):
    create_deployment_configuration = CreateDeploymentConfigurationMutation.Field()
    open_accounting_period = OpenAccountingPeriodMutation.Field()
    lock_accounting_period = LockAccountingPeriodMutation.Field()
    close_accounting_period = CloseAccountingPeriodMutation.Field()
    reopen_accounting_period = ReopenAccountingPeriodMutation.Field()
    create_account = CreateAccountMutation.Field()
    resolve_manual_review = ManualReviewItemMutation.Field()
