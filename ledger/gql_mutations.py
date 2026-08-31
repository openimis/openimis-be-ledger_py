import graphene
import logging
from hordak.models import Account, Transaction, AccountType
from core.schema import OpenIMISMutation
from django.contrib.auth.models import AnonymousUser
from django.utils.translation import gettext as _
from django.core.exceptions import ValidationError, PermissionDenied
from .models import (
    DeploymentConfiguration,
    AccountingPeriod,
    ManualReviewQueueItem,
    ExternalReplicationRecord
)
from .services import PeriodService
from datetime import datetime, timezone
from .apps import LedgerConfig
logger = logging.getLogger(__name__)


class CreateDeploymentConfigurationInputType(OpenIMISMutation.Input):

    operating_mode = graphene.String(required=True)

    external_system = graphene.String(required=False)

    currency_code = graphene.String(required=True)

    retained_earnings_account_id = graphene.UUID(required=True)


class CreateAccountInputType(OpenIMISMutation.Input):

    name = graphene.String(required=True)

    parent_id = graphene.UUID(required=False)

    code = graphene.String(required=True)

    full_code = graphene.String(required=True)

    type = graphene.String(required=True)

    is_bank_account = graphene.Boolean(required=True)

    currencies = graphene.JSONString(required=False)


class ManualReviewMutationInputType(OpenIMISMutation.Input):

    replication_record_id = graphene.UUID(required=True)

    resolved_at = graphene.Date(required=False)

    resolved_by_transaction_id = graphene.UUID(required=True)

    resolution_note = graphene.String(required=True)


class OpenAccountingPeriodInputType(OpenIMISMutation.Input):

    start_date = graphene.Date(required=True)

    end_date = graphene.Date(required=True)

    name = graphene.String(required=True)

    code = graphene.String(required=True)


class LockAccountingPeriodInputType(OpenIMISMutation.Input):

    id = graphene.UUID(required=True)


class CloseAccountingPeriodInputType(OpenIMISMutation.Input):

    id = graphene.UUID(required=True)


class ReopenAccountingPeriodInputType(OpenIMISMutation.Input):

    id = graphene.UUID(required=True)


class CreateDeploymentConfigurationMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "CreateDeploymentConfigurationMutation"
    _model = DeploymentConfiguration

    class Input(CreateDeploymentConfigurationInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):

        if type(user) is AnonymousUser or not user:
            raise ValidationError(
                _("mutation.authentication_required")
            )

        if not user.has_perms(LedgerConfig.gql_mutation_ledger_admin_perms):
            raise PermissionDenied(_("unauthorized"))

        operating_mode = data.get("operating_mode", None)
        external_system = data.get("external_system", None)
        currency_code = data.get("currency_code", None)

        if "client_mutation_id" in data:
            data.pop("client_mutation_id")
        if "client_mutation_label" in data:
            data.pop("client_mutation_label")

        if operating_mode == DeploymentConfiguration.OPERATING_MODE_REPLICATED:
            if not external_system:
                raise ValidationError(
                    _("External system is required when operating_mode is replicated")
                )

        try:
            account = Account.objects.get(uuid=data["retained_earnings_account_id"])
        except Account.DoesNotExist:
            raise ValidationError(
                _("The specified account was not found")
            )

        if account.type in [AccountType.expense, AccountType.income]:
            raise ValidationError(
                _("retained earnings account type should not be income / expense")
            )

        modes = [
            "local_only",
            "replicated"
        ]
        if operating_mode and operating_mode not in modes:
            raise ValidationError(
                _("Operating mode should be either local_only or replicated")
            )

        systems = [
            "odoo",
            "sage"
        ]
        if external_system:
            if external_system not in systems:
                raise ValidationError(
                    _("external_system should be either odoo or sage")
                )

        deployment_config = DeploymentConfiguration(
            operating_mode=operating_mode,
            external_system=external_system,
            currency_code=currency_code,
            retained_earnings_account=account
        )
        deployment_config.save(username=user.username)


class CreateAccountMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "CreateAccountMutation"
    _model = Account

    class Input(CreateAccountInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):

        if type(user) is AnonymousUser or not user:
            raise ValidationError(
                _("mutation.authentication_required")
            )
        if not user.has_perms(LedgerConfig.gql_mutation_ledger_admin_perms):
            raise PermissionDenied(_("unauthorized"))

        name = data.get("name", None)
        parent_id = data.get("parent_id", None)
        full_code = data.get("full_code", None)
        code = data.get("code", None)
        is_bank_account = data.get("is_bank_account", None)
        acc_type = data.get("type", None)
        currencies = data.get("currencies", {})
        logger.debug("currencies %s", currencies)

        if "client_mutation_id" in data:
            data.pop("client_mutation_id")
        if "client_mutation_label" in data:
            data.pop("client_mutation_label")

        parent = None
        if parent_id:
            try:
                parent = Account.objects.get(uuid=parent_id)
            except Account.DoesNotExist:
                raise ValidationError(
                    _("The specified parent account was not found")
                )

        acc_types = [
            AccountType.asset,
            AccountType.liability,
            AccountType.income,
            AccountType.expense,
            AccountType.equity,
            AccountType.trading
        ]
        if acc_type not in acc_types:
            raise ValidationError(
                _("Account type must be either AS, LI, IN, EX, EQ, TR")
            )

        Account.objects.create(
            code=code,
            full_code=full_code,
            name=name,
            is_bank_account=is_bank_account,
            type=acc_type,
            currencies=currencies,
            parent=parent
        )


class OpenAccountingPeriodMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "OpenAccountingPeriodMutation"
    _model = AccountingPeriod

    class Input(OpenAccountingPeriodInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        logger.debug("Locking Period...")

        if type(user) is AnonymousUser or not user:
            raise ValidationError(
                _("mutation.authentication_required")
            )
        if not user.has_perms(LedgerConfig.gql_mutation_ledger_admin_perms):
            raise PermissionDenied(_("unauthorized"))

        PeriodService.open(
            start_date=data["start_date"],
            end_date=data["end_date"],
            name=data["name"],
            code=data["code"],
            user=user,
        )


class LockAccountingPeriodMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "LockAccountingPeriodMutation"
    _model = AccountingPeriod

    class Input(LockAccountingPeriodInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        logger.debug("Locking Period...")

        if type(user) is AnonymousUser or not user:
            raise ValidationError(
                _("mutation.authentication_required")
            )

        if not user.has_perms(LedgerConfig.gql_mutation_ledger_admin_perms):
            raise PermissionDenied(_("unauthorized"))

        period = AccountingPeriod.objects.filter(id=data["id"], is_deleted=False).first()
        if not period:
            raise ValidationError(
                _("The specified accounting period was not found")
            )

        PeriodService.lock(
            period=period,
            user=user
        )


class CloseAccountingPeriodMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "CloseAccountingPeriodMutation"
    _model = AccountingPeriod

    class Input(CloseAccountingPeriodInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        logger.debug("Closing Period...")

        if type(user) is AnonymousUser or not user:
            raise ValidationError(
                _("mutation.authentication_required")
            )

        if not user.has_perms(LedgerConfig.gql_mutation_ledger_admin_perms):
            raise PermissionDenied(_("unauthorized"))

        period = AccountingPeriod.objects.filter(id=data["id"], is_deleted=False).first()
        if not period:
            raise ValidationError(
                _("The specified accounting period was not found")
            )

        PeriodService.close(
            period=period,
            user=user
        )


class ReopenAccountingPeriodMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "ReopenAccountingPeriodMutation"
    _model = AccountingPeriod

    class Input(ReopenAccountingPeriodInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        logger.debug("Reopening Period...")

        if type(user) is AnonymousUser or not user:
            raise ValidationError(
                _("mutation.authentication_required")
            )

        if not user.has_perms(LedgerConfig.gql_mutation_ledger_admin_perms):
            raise PermissionDenied(_("unauthorized"))

        period = AccountingPeriod.objects.filter(id=data["id"], is_deleted=False).first()
        if not period:
            raise ValidationError(
                _("The specified accounting period was not found")
            )

        PeriodService.reopen(
            period=period,
            user=user
        )


class ManualReviewItemMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "ManualReviewItemMutation"
    _model = ManualReviewQueueItem

    class Input(ManualReviewMutationInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):

        if type(user) is AnonymousUser or not user:
            raise ValidationError(
                _("mutation.authentication_required")
            )

        if not user.has_perms(LedgerConfig.gql_mutation_ledger_admin_perms):
            raise PermissionDenied(_("unauthorized"))

        replication_record_id = data.get("replication_record_id", None)
        resolved_at = data.get("resolved_at", None)
        if not resolved_at:
            resolved_at = datetime.now().date()

        now_utc = datetime.now(timezone.utc)
        resolved_at = datetime.combine(resolved_at, now_utc.time(), tzinfo=timezone.utc)
        logger.debug("resolved_at %s", resolved_at)

        resolved_by_transaction_id = data.get("resolved_by_transaction_id", None)
        resolution_note = data.get("resolution_note", None)

        if "client_mutation_id" in data:
            data.pop("client_mutation_id")
        if "client_mutation_label" in data:
            data.pop("client_mutation_label")

        replication_record_id =\
            ExternalReplicationRecord.objects.filter(
                id=data["replication_record_id"], is_deleted=False
            ).first()
        if not replication_record_id:
            raise ValidationError(
                _("The specified replication record was not found")
            )

        if resolved_by_transaction_id:
            try:
                resolved_by_transaction_id =\
                    Transaction.objects.get(uuid=resolved_by_transaction_id)
            except Transaction.DoesNotExist:
                raise ValidationError(
                    _("The specified transaction resolved by was not found")
                )

        manual_review = ManualReviewQueueItem(
            replication_record=replication_record_id,
            resolved_at=resolved_at,
            resolved_by_transaction=resolved_by_transaction_id,
            resolution_note=resolution_note
        )
        manual_review.save(username=user.username)
