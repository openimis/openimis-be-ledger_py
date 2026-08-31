from django.core.exceptions import ValidationError
from core.models import User
from django.db import transaction
from django.utils import timezone
from core.signals import register_service_signal
from hordak.models import Transaction, Leg, AccountType
from datetime import datetime as py_datetime
from ledger.models import (
    AccountingPeriod,
    LedgerEntryMeta,
    LegTag,
    DeploymentConfiguration,
    PartyLedgerBalance,
    AccountBalanceSnapshot,
    AnalyticAxis
)
from decimal import Decimal
from djmoney.money import Money
from ledger.replication.tasks import (
    replicate_entry
)


class MissingAccountMappingException(Exception):
    pass


class MissingDeploymentConfigurationException(Exception):
    pass


class ClosedPeriodException(Exception):
    pass


class ManualReviewService:
    @classmethod
    def resolve(
        cls,
        review_item,
        correcting_entry,
        note,
        user,
    ):
        if review_item.resolved_at:
            raise ValidationError(
                "Already resolved"
            )
        review_item.resolved_at = timezone.now()

        review_item.resolved_by_transaction = (
            correcting_entry.transaction
        )

        review_item.resolution_note = note

        review_item.save(
            username=user.username
        )


class LedgerEntryService:

    @classmethod
    def _update_account_snapshot(
        cls,
        accounting_period,
        leg,
        username
    ):
        """
        Maintient le snapshot de balance par compte/période.
        """

        amount = Decimal(str(leg.amount.amount))

        snapshot = (
            AccountBalanceSnapshot.objects
            .filter(
                accounting_period=accounting_period,
                account=leg.account,
            )
            .first()
        )

        if snapshot is None:
            snapshot = AccountBalanceSnapshot(
                accounting_period=accounting_period,
                account=leg.account,
                debit_amount=Decimal("0"),
                credit_amount=Decimal("0"),
                balance_amount=Decimal("0"),
            )
            snapshot.save(username=username)
        if amount > 0:
            snapshot.debit_amount += amount
        else:
            snapshot.credit_amount += abs(amount)

        snapshot.balance_amount += amount

        snapshot.save(username=username)

    @classmethod
    def _update_party_balance(
        cls,
        accounting_period,
        leg,
        username
    ):
        """
        Maintient les balances PARTY uniquement.
        Les tags FUNDER ne doivent pas être agrégés ici.
        """

        amount = Decimal(str(leg.amount.amount))

        party_tags = (
            LegTag.objects
            .select_related(
                "analytic_value",
                "analytic_value__axis"
            )
            .filter(
                leg=leg,
                analytic_value__axis__code=AnalyticAxis.PARTY,
            )
        )

        for leg_tag in party_tags:

            analytic_value = leg_tag.analytic_value

            balance = (
                PartyLedgerBalance.objects
                .filter(
                    accounting_period=accounting_period,
                    analytic_value=analytic_value,
                )
                .first()
            )

            if not balance:

                balance = PartyLedgerBalance(
                    accounting_period=accounting_period,
                    analytic_value=analytic_value,
                    debit_amount=Decimal("0"),
                    credit_amount=Decimal("0"),
                    balance_amount=Decimal("0"),
                )

                balance.save(username=username)

            if amount > 0:
                balance.debit_amount = (
                    Decimal(str(balance.debit_amount))
                    + amount
                )
            else:
                balance.credit_amount = (
                    Decimal(str(balance.credit_amount))
                    + abs(amount)
                )

            balance.balance_amount = (
                Decimal(str(balance.balance_amount))
                + amount
            )

            balance.save(username=username)

    @classmethod
    @register_service_signal("ledger_service.post_entry")
    def post(
        cls,
        journal,
        accounting_period,
        source_event_type,
        source_event_reference,
        legs,
        tags=None,
        user=None,
    ):

        if not user:
            raise ValidationError(
                "User is required to post ledger entries"
            )

        username = user.username

        if accounting_period.status != AccountingPeriod.STATUS_OPEN:
            raise ClosedPeriodException(
                "Cannot post into a non-open accounting period"
            )

        if len(legs) < 2:
            raise ValidationError(
                "At least two legs required"
            )

        for leg_data in legs:
            if not leg_data.get("account"):
                raise MissingAccountMappingException(
                    "Missing account mapping"
                )

        total = sum(
            Decimal(str(leg["amount"]))
            for leg in legs
        )

        if total != Decimal("0"):
            raise ValidationError(
                "Ledger entry must be balanced"
            )

        deployment_config = DeploymentConfiguration.objects.first()
        if not deployment_config:
            raise MissingDeploymentConfigurationException(
                "DeploymentConfiguration is required before posting ledger entries"
            )
        currency_code = deployment_config.currency_code

        tags = tags or {}

        with transaction.atomic():

            trx = Transaction.objects.create()

            meta = LedgerEntryMeta(
                transaction=trx,
                journal=journal,
                accounting_period=accounting_period,
                source_event_type=source_event_type,
                source_event_reference=source_event_reference,
            )

            meta.save(username=username)

            created_legs = []

            for leg_data in legs:

                leg = Leg.objects.create(
                    transaction=trx,
                    account=leg_data["account"],
                    amount=Money(
                        leg_data["amount"],
                        currency_code,
                    ),
                )

                created_legs.append(leg)

            for leg_index, leg_tags in tags.items():

                if leg_index >= len(created_legs):
                    raise ValidationError(
                        f"Invalid leg index: {leg_index}"
                    )

                for analytic_value in leg_tags:

                    legtag = LegTag(
                        leg=created_legs[leg_index],
                        analytic_value=analytic_value,
                        accounting_period_id=accounting_period.uuid
                    )

                    legtag.save(username=username)

            for leg in created_legs:

                cls._update_account_snapshot(
                    accounting_period=accounting_period,
                    leg=leg,
                    username=username
                )

                cls._update_party_balance(
                    accounting_period=accounting_period,
                    leg=leg,
                    username=username
                )

            deployment_config = DeploymentConfiguration.objects.filter(is_deleted=False).first()

            mode_replicated = DeploymentConfiguration.OPERATING_MODE_REPLICATED
            if deployment_config and deployment_config.operating_mode == mode_replicated:
                transaction.on_commit(
                    lambda: replicate_entry.delay(
                        meta.id,
                        deployment_config.external_system,
                        username
                    )
                )
            return meta


def ensure_period_not_closed(period):
    if period.status == AccountingPeriod.STATUS_CLOSED:
        raise ClosedPeriodException(
            "Entries belonging to a closed accounting period "
            "cannot be modified"
        )


class PeriodService:

    # LOCK
    @classmethod
    def _get_earliest_open_period(cls):
        return (
            AccountingPeriod.objects
            .filter(
                status=AccountingPeriod.STATUS_OPEN,
            )
            .order_by("start_date", "id")
            .first()
        )

    @classmethod
    def _validate_earliest_open_period(cls, period):
        earliest = cls._get_earliest_open_period()

        if not earliest:
            raise ValidationError(
                "No open accounting period exists"
            )

        if earliest.pk != period.pk:
            raise ValidationError(
                "Accounting periods must be processed chronologically."
            )

    # CLOSE
    @classmethod
    def _get_earliest_non_closed_period(cls):
        return (
            AccountingPeriod.objects
            .exclude(
                status=AccountingPeriod.STATUS_CLOSED
            )
            .order_by("start_date", "id")
            .first()
        )

    @classmethod
    def _validate_earliest_non_closed_period(cls, period):
        earliest = cls._get_earliest_non_closed_period()

        if not earliest:
            raise ValidationError(
                "No non-closed accounting period exists"
            )

        if earliest.pk != period.pk:
            raise ValidationError(
                "Accounting periods must be processed chronologically."
            )

    @classmethod
    def _validate_dates(cls, start_date, end_date):
        if not start_date:
            raise ValidationError("Period start date is required")

        if not end_date:
            raise ValidationError("Period end date is required")

        if start_date > end_date:
            raise ValidationError(
                "Period start date must be before or equal to end date"
            )

    @classmethod
    def _validate_no_overlap(cls, start_date, end_date):
        overlapping_period = (
            AccountingPeriod.objects
            .filter(
                start_date__lte=end_date,
                end_date__gte=start_date,
            )
            .exists()
        )

        if overlapping_period:
            raise ValidationError(
                "Accounting period overlaps an existing period"
            )

    @classmethod
    def _validate_chronological_order(cls, start_date):
        latest_period = (
            AccountingPeriod.objects
            .order_by("-end_date", "-id")
            .first()
        )

        if not latest_period:
            return

        if latest_period.end_date and start_date <= latest_period.end_date:
            raise ValidationError(
                "New accounting period must start after the latest "
                "existing accounting period"
            )

    @classmethod
    @register_service_signal("ledger_service.open_period")
    def open(
        cls,
        start_date,
        end_date,
        name=None,
        code=None,
        user=None,
    ):
        """
        Opens a new accounting period.

        Rules:
        - start_date <= end_date
        - no overlap
        - chronological ordering
        """

        cls._validate_dates(start_date, end_date)
        cls._validate_no_overlap(start_date, end_date)
        cls._validate_chronological_order(start_date)

        with transaction.atomic():

            if not user:
                raise ValidationError(
                    "Cannot perfom this action without user specified"
                )
            core_user = User.objects.filter(id=user.id).first()
            if not core_user:
                raise ValidationError(
                    "No core user found for the specified user"
                )
            period = AccountingPeriod(
                start_date=start_date,
                end_date=end_date,
                name=name,
                code=code,
                audit_user_id=core_user.i_user.id,
                status=AccountingPeriod.STATUS_OPEN,
            )

            period.save(username=user.username)

            return period

    @classmethod
    @register_service_signal("ledger_service.lock_period")
    def lock(cls, period, user=None):

        with transaction.atomic():

            period = (
                AccountingPeriod.objects
                .select_for_update()
                .get(pk=period.pk)
            )

            if period.status != AccountingPeriod.STATUS_OPEN:
                raise ValidationError(
                    "Only an open accounting period can be locked"
                )
            cls._validate_earliest_open_period(period)

            period.status = AccountingPeriod.STATUS_LOCKED
            period.locked_at = py_datetime.now()

            if not user:
                raise ValidationError(
                    "Cannot perform this action without user provided"
                )
            core_user = User.objects.filter(id=user.id).first()
            if not core_user:
                raise ValidationError(
                    "No core user found for the specified user"
                )
            period.audit_user_id = core_user.i_user.id

            period.save(
                username=user.username,
                update_fields=[
                    "status",
                    "locked_at",
                    "audit_user_id",
                ]
            )

            return period

    @classmethod
    @register_service_signal("ledger_service.close_period")
    def close(cls, period, user=None):

        deployment_config = (
            DeploymentConfiguration.objects
            .select_related("retained_earnings_account")
            .first()
        )

        if not deployment_config:
            raise ValidationError(
                "DeploymentConfiguration is required to close "
                "an accounting period"
            )

        retained_earnings_account = (
            deployment_config.retained_earnings_account
        )

        if retained_earnings_account.type in [AccountType.income, AccountType.expense]:
            raise ValidationError(
                "Retained earnings account must not be an "
                "Income or Expense account"
            )

        currency_code = deployment_config.currency_code

        with transaction.atomic():

            period = (
                AccountingPeriod.objects
                .select_for_update()
                .get(pk=period.pk)
            )

            if period.status != AccountingPeriod.STATUS_LOCKED:
                raise ValidationError(
                    "Only a locked accounting period can be closed"
                )

            if period.closing_transaction_id:
                raise ValidationError(
                    "Accounting period already has a closing transaction"
                )

            cls._validate_earliest_non_closed_period(period)

            types = [AccountType.income, AccountType.expense]
            snapshots = list(
                AccountBalanceSnapshot.objects
                .select_related("account")
                .filter(
                    accounting_period=period,
                    account__type__in=types,
                )
                .order_by("account_id")
            )

            p_and_l_legs = []

            for snapshot in snapshots:

                balance = Decimal(
                    str(snapshot.balance_amount or 0)
                )

                if balance == Decimal("0"):
                    continue

                p_and_l_legs.append(
                    {
                        "account": snapshot.account,
                        "amount": -balance,
                    }
                )

            if not p_and_l_legs:
                raise ValidationError(
                    "Cannot close a period with no Income/Expense balance"
                )

            total_p_and_l_closing = sum(
                item["amount"]
                for item in p_and_l_legs
            )

            retained_earnings_amount = -total_p_and_l_closing

            closing_transaction = Transaction.objects.create()

            for item in p_and_l_legs:

                Leg.objects.create(
                    transaction=closing_transaction,
                    account=item["account"],
                    amount=Money(
                        item["amount"],
                        currency_code,
                    ),
                )

            Leg.objects.create(
                transaction=closing_transaction,
                account=retained_earnings_account,
                amount=Money(
                    retained_earnings_amount,
                    currency_code,
                ),
            )

            period.status = AccountingPeriod.STATUS_CLOSED
            period.closing_transaction = closing_transaction
            period.closed_at = py_datetime.now()

            if not user:
                raise ValidationError(
                    "Cannot perform this action without user provided"
                )
            core_user = User.objects.filter(id=user.id).first()
            if not core_user:
                raise ValidationError(
                    "No core user found for the specified user"
                )
            period.audit_user_id_closed = core_user.i_user.id
            period.closed_by = core_user.i_user.id

            period.save(
                username=user.username,
                update_fields=[
                    "status",
                    "closing_transaction",
                    "closed_at",
                    "audit_user_id_closed",
                    "closed_by",
                ]
            )

            return period

    @classmethod
    @register_service_signal("ledger_service.reopen_period")
    def reopen(cls, period, user=None):
        """
        Transitions:

            LOCKED -> OPEN

        A closed period can never be reopened through this service.
        """

        if period.status != AccountingPeriod.STATUS_LOCKED:
            raise ValidationError(
                "Only a locked accounting period can be reopened"
            )

        with transaction.atomic():

            period.status = AccountingPeriod.STATUS_OPEN
            period.locked_at = None

            if not user:
                raise ValidationError(
                    "Cannot perform this action without user provided"
                )
            core_user = User.objects.filter(id=user.id).first()
            if not core_user:
                raise ValidationError(
                    "No core user found for the specified user"
                )
            period.audit_user_id = core_user.i_user.id

            period.save(
                username=user.username,
                update_fields=[
                    "status",
                    "locked_at",
                    "audit_user_id",
                ]
            )

            return period
