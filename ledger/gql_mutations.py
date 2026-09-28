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
    ExternalReplicationRecord,
    JournalTypes,
    LedgerJournal,
    AccountBalanceSnapshot,
    LedgerEntryMeta,
    PartyLedgerBalance
)
from .services import PeriodService
from datetime import datetime, timezone
from .apps import LedgerConfig
from django.db.models import Q
logger = logging.getLogger(__name__)


class CreateDeploymentConfigurationInputType(OpenIMISMutation.Input):

    operating_mode = graphene.String(required=True)

    external_system = graphene.String(required=False)

    currency_code = graphene.String(required=True)

    retained_earnings_account_id = graphene.UUID(required=True)


class CreateJournalTypeInputType(OpenIMISMutation.Input):

    code = graphene.String(required=True)

    type = graphene.String(required=True)

    alt_language = graphene.String(required=True)


class CreateAccountInputType(OpenIMISMutation.Input):

    name = graphene.String(required=True)

    parent_id = graphene.UUID(required=False)

    code = graphene.String(required=True)

    type = graphene.String(required=True)

    is_bank_account = graphene.Boolean(required=True)

    currencies = graphene.JSONString(required=False)


class UpdateAccountInputType(CreateAccountInputType, OpenIMISMutation.Input):
    """
    Update Account GQL
    """
    account_uuid = graphene.UUID(required=True)


class DeleteAccountInputType(OpenIMISMutation.Input):
    """
    Delete Account GQL
    """
    account_uuid = graphene.UUID(required=True)


class CreateJournalInputType(OpenIMISMutation.Input):

    name = graphene.String(required=True)

    code = graphene.String(required=True)

    type = graphene.UUID(required=True)

    default_credit_account_id = graphene.UUID(required=True)

    default_debit_account_id = graphene.UUID(required=True)


class UpdateJournalInputType(CreateJournalInputType, OpenIMISMutation.Input):

    journal_uuid = graphene.UUID(required=True)


class DeleteJournalInputType(OpenIMISMutation.Input):

    journal_uuid = graphene.UUID(required=True)


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


class DeleteAccountingPeriodInputType(OpenIMISMutation.Input):

    id = graphene.UUID(required=True)


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
                return [
                    {
                        'message': _("ledger.mutation.failed_to_create_deployconfig"),
                        'detail': _("External system is required when operating_mode is replicated")
                    }
                ]

        try:
            account = Account.objects.get(uuid=data["retained_earnings_account_id"])
        except Account.DoesNotExist:
            return [
                {
                    'message': _("ledger.mutation.failed_to_create_deployconfig"),
                    'detail': _("The specified retained earnings account account was not found")
                }
            ]

        if account.type in [AccountType.expense, AccountType.income]:
            return [
                {
                    'message': _("ledger.mutation.failed_to_create_deployconfig"),
                    'detail': _("retained earnings account type should not be income / expense")
                }
            ]

        modes = [
            "local_only",
            "replicated"
        ]
        if operating_mode and operating_mode not in modes:
            return [
                {
                    'message': _("ledger.mutation.failed_to_create_deployconfig"),
                    'detail': _("Operating mode should be either local_only or replicated")
                }
            ]

        systems = [
            "odoo",
            "sage"
        ]
        if external_system:
            if external_system not in systems:
                return [
                    {
                        'message': _("ledger.mutation.failed_to_create_deployconfig"),
                        'detail': _("external_system should be either odoo or sage")
                    }
                ]

        deployment_config = DeploymentConfiguration(
            operating_mode=operating_mode,
            external_system=external_system,
            currency_code=currency_code,
            retained_earnings_account=account
        )
        deployment_config.save(username=user.username)


class CreateJournalMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "CreateJournalMutation"
    _model = Account

    class Input(CreateJournalInputType):
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
        code = data.get("code", None)
        journal_id = data.get("type", None)
        default_credit_account_id = data.get("default_credit_account_id", None)
        default_debit_account_id = data.get("default_debit_account_id", None)

        if "client_mutation_id" in data:
            data.pop("client_mutation_id")
        if "client_mutation_label" in data:
            data.pop("client_mutation_label")

        journal_type = None
        if journal_id:
            try:
                journal_type = JournalTypes.objects.get(id=journal_id)
            except JournalTypes.DoesNotExist:
                return [
                    {
                        'message': _("ledger.mutation.failed_to_create_journal"),
                        'detail': _("The specified journal type was not found")
                    }
                ]

        default_credit_account = None
        if default_credit_account_id:
            try:
                default_credit_account = Account.objects.get(uuid=default_credit_account_id)
            except Account.DoesNotExist:
                return [
                    {
                        'message': _("ledger.mutation.failed_to_create_journal"),
                        'detail': _("The specified default credit account was not found")
                    }
                ]

        default_debit_account = None
        if default_debit_account_id:
            try:
                default_debit_account = Account.objects.get(uuid=default_debit_account_id)
            except Account.DoesNotExist:
                return [
                    {
                        'message': _("ledger.mutation.failed_to_create_journal"),
                        'detail': _("The specified default debit account was not found")
                    }
                ]

        journal = LedgerJournal(
            code=code,
            name=name,
            type=journal_type,
            default_credit_account_id=default_credit_account,
            default_debit_account_id=default_debit_account
        )
        journal.save(username=user.username)


class DeleteJournalMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "DeleteJournalMutation"
    _model = LedgerJournal

    class Input(DeleteJournalInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):

        if type(user) is AnonymousUser or not user:
            raise ValidationError(
                _("mutation.authentication_required")
            )
        if not user.has_perms(LedgerConfig.gql_mutation_ledger_admin_perms):
            raise PermissionDenied(_("unauthorized"))

        journal_uuid = data.get("journal_uuid", None)
        journal = LedgerJournal.objects.filter(id=journal_uuid).first()
        if not journal:
            return [
                {
                    'message': _("ledger.mutation.failed_to_delete_journal"),
                    'detail': _("The specified journal to delete was not found")
                }
            ]

        journal.is_deleted = True
        journal.save(username=user.username)


class UpdateJournalMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "UpdateJournalMutation"
    _model = LedgerJournal

    class Input(UpdateJournalInputType):
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
        code = data.get("code", None)
        journal_type_id = data.get("type", None)
        journal_uuid = data.get("journal_uuid", None)
        default_credit_account_id = data.get("default_credit_account_id", None)
        default_debit_account_id = data.get("default_debit_account_id", None)

        if "client_mutation_id" in data:
            data.pop("client_mutation_id")
        if "client_mutation_label" in data:
            data.pop("client_mutation_label")

        journal_type = None
        if journal_type_id:
            try:
                journal_type = JournalTypes.objects.get(id=journal_type_id)
            except JournalTypes.DoesNotExist:
                return [
                    {
                        'message': _("ledger.mutation.failed_to_update_journal"),
                        'detail': _("The specified journal type was not found")
                    }
                ]

        default_credit_account = None
        if default_credit_account_id:
            try:
                default_credit_account = Account.objects.get(uuid=default_credit_account_id)
            except Account.DoesNotExist:
                return [
                    {
                        'message': _("ledger.mutation.failed_to_update_journal"),
                        'detail': _("The specified default credit account was not found")
                    }
                ]

        default_debit_account = None
        if default_debit_account_id:
            try:
                default_debit_account = Account.objects.get(uuid=default_debit_account_id)
            except Account.DoesNotExist:
                return [
                    {
                        'message': _("ledger.mutation.failed_to_update_journal"),
                        'detail': _("The specified default debit account was not found")
                    }
                ]

        journal_to_update = LedgerJournal.objects.filter(id=journal_uuid).first()
        if not journal_to_update:
            return [
                {
                    'message': _("ledger.mutation.failed_to_update_journal"),
                    'detail': _("The specified journal to update was not found")
                }
            ]

        journal_to_update.code = code
        journal_to_update.name = name
        journal_to_update.type = journal_type
        journal_to_update.default_credit_account_id = default_credit_account
        journal_to_update.default_debit_account_id = default_debit_account
        journal_to_update.save(username=user.username)


class CreateJournalTypeMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "CreateJournalTypeMutation"
    _model = JournalTypes

    class Input(CreateJournalTypeInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):

        if type(user) is AnonymousUser or not user:
            raise ValidationError(
                _("mutation.authentication_required")
            )
        if not user.has_perms(LedgerConfig.gql_mutation_ledger_admin_perms):
            raise PermissionDenied(_("unauthorized"))

        code = data.get("code", None)
        j_type = data.get("type", None)
        alt_language = data.get("alt_language", None)

        if "client_mutation_id" in data:
            data.pop("client_mutation_id")
        if "client_mutation_label" in data:
            data.pop("client_mutation_label")

        sequence = JournalTypes(
            code=code,
            type=j_type,
            alt_language=alt_language
        )
        sequence.save(username=user.username)


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
                return [
                    {
                        'message': _("ledger.mutation.failed_to_create_account"),
                        'detail': _("The specified parent account was not found")
                    }
                ]

        acc_types = [
            AccountType.asset,
            AccountType.liability,
            AccountType.income,
            AccountType.expense,
            AccountType.equity,
            AccountType.trading
        ]
        if acc_type not in acc_types:
            return [
                {
                    'message': _("ledger.mutation.failed_to_create_account"),
                    'detail': _("Account type must be either AS, LI, IN, EX, EQ, TR")
                }
            ]

        Account.objects.create(
            code=code,
            name=name,
            is_bank_account=is_bank_account,
            type=acc_type,
            currencies=currencies,
            parent=parent
        )


class DeleteAccountMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "DeleteAccountMutation"
    _model = Account

    class Input(DeleteAccountInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):

        if type(user) is AnonymousUser or not user:
            raise ValidationError(
                _("mutation.authentication_required")
            )
        if not user.has_perms(LedgerConfig.gql_mutation_ledger_admin_perms):
            raise PermissionDenied(_("unauthorized"))

        account_uuid = data.get("account_uuid", None)
        account = Account.objects.filter(uuid=account_uuid).first()
        if not account:
            return [
                {
                    'message': _("ledger.mutation.failed_to_delete_account"),
                    'detail': _("The Account you are trying to delete was not found")
                }
            ]
        childrens = account.get_children()
        if childrens:
            return [
                {
                    'message': _("ledger.mutation.failed_to_delete_account"),
                    'detail': _("The account you are trying to delete has childrens,"
                                " please first  delete those children")
                }
            ]
        journals = LedgerJournal.objects.filter(
            Q(default_credit_account_id=account) | Q(default_debit_account_id=account)
        ).filter(is_deleted=False)
        if journals:
            return [
                {
                    'message': _("ledger.mutation.failed_to_delete_account"),
                    'detail': _("The account you are trying to delete is used by one or "
                                "more journals, please first  delete those journals")
                }
            ]
        account.delete()


class UpdateAccountMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "UpdateAccountMutation"
    _model = Account

    class Input(UpdateAccountInputType):
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
        code = data.get("code", None)
        is_bank_account = data.get("is_bank_account", None)
        acc_type = data.get("type", None)
        currencies = data.get("currencies", {})
        logger.debug("currencies %s", currencies)
        account_uuid = data.get("account_uuid", None)

        if "client_mutation_id" in data:
            data.pop("client_mutation_id")
        if "client_mutation_label" in data:
            data.pop("client_mutation_label")

        parent = None
        if parent_id:
            try:
                parent = Account.objects.get(uuid=parent_id)
            except Account.DoesNotExist:
                return [
                    {
                        'message': _("ledger.mutation.failed_to_update_account"),
                        'detail': _("The specified parent account was not found")
                    }
                ]

        acc_types = [
            AccountType.asset,
            AccountType.liability,
            AccountType.income,
            AccountType.expense,
            AccountType.equity,
            AccountType.trading
        ]
        if acc_type not in acc_types:
            return [
                {
                    'message': _("ledger.mutation.failed_to_update_account"),
                    'detail': _("Account type must be either AS, LI, IN, EX, EQ, TR")
                }
            ]

        account = Account.objects.filter(uuid=account_uuid)
        if not account.exists():
            return [
                {
                    'message': _("ledger.mutation.failed_to_update_account"),
                    'detail': _("The Account you are trying to update was not found")
                }
            ]

        account.update(
            code=code,
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
            return [
                {
                    'message': _("ledger.mutation.failed_to_lock_account"),
                    'detail': _("The specified accounting period was not found")
                }
            ]

        PeriodService.lock(
            period=period,
            user=user
        )


class DeleteAccountingPeriodMutation(OpenIMISMutation):

    _mutation_module = "ledger"

    _mutation_class = "DeleteAccountingPeriodMutation"
    _model = AccountingPeriod

    class Input(DeleteAccountingPeriodInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        logger.debug("Deleting Period...")

        if type(user) is AnonymousUser or not user:
            raise ValidationError(
                _("mutation.authentication_required")
            )

        if not user.has_perms(LedgerConfig.gql_mutation_ledger_admin_perms):
            raise PermissionDenied(_("unauthorized"))

        period = AccountingPeriod.objects.filter(id=data["id"], is_deleted=False).first()
        if not period:
            return [
                {
                    'message': _("ledger.mutation.failed_to_delete_period"),
                    'detail': _("The specified accounting period was not found")
                }
            ]

        balance = AccountBalanceSnapshot.objects.filter(accounting_period__id=data["id"])
        if balance:
            return [
                {
                    'message': _("ledger.mutation.failed_to_delete_period"),
                    'detail': _("Cannot delete a period linked to one or more balances")
                }
            ]

        meta = LedgerEntryMeta.objects.filter(accounting_period__id=data["id"])
        if meta:
            return [
                {
                    'message': _("ledger.mutation.failed_to_delete_period"),
                    'detail': _("Cannot delete a period linked to one or more entries")
                }
            ]

        ledger_balance = PartyLedgerBalance.objects.filter(accounting_period__id=data["id"])
        if ledger_balance:
            return [
                {
                    'message': _("ledger.mutation.failed_to_delete_period"),
                    'detail': _("Cannot delete a period linked to one or more party balances")
                }
            ]
        period.delete()


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
            return [
                {
                    'message': _("ledger.mutation.failed_to_close_account"),
                    'detail': _("The specified accounting period was not found")
                }
            ]

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
            return [
                {
                    'message': _("ledger.mutation.failed_to_reopen_account"),
                    'detail': _("The specified accounting period was not found")
                }
            ]

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
            return [
                {
                    'message': _("ledger.mutation.failed_to_create_manual_review"),
                    'detail': _("The specified replication record was not found")
                }
            ]

        if resolved_by_transaction_id:
            try:
                resolved_by_transaction_id =\
                    Transaction.objects.get(uuid=resolved_by_transaction_id)
            except Transaction.DoesNotExist:
                return [
                    {
                        'message': _("ledger.mutation.failed_to_create_manual_review"),
                        'detail': _("The specified transaction resolved by was not found")
                    }
                ]

        manual_review = ManualReviewQueueItem(
            replication_record=replication_record_id,
            resolved_at=resolved_at,
            resolved_by_transaction=resolved_by_transaction_id,
            resolution_note=resolution_note
        )
        manual_review.save(username=user.username)
