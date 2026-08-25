import logging
from decimal import Decimal

from ledger.models import (
    AccountingPeriod,
    LedgerJournal,
    UnmappedFinancialEvent,
    DeploymentConfiguration,
    AnalyticAxis,
    AnalyticValue
)
from core.signals import bind_service_signal
from ledger.services import LedgerEntryService
from core.service_signals import ServiceSignalBindType
from claim.models import Claim
from policyholder.models import PolicyHolder
from django.db.models import Q
from datetime import datetime as py_datetime
logger = logging.getLogger(__name__)


def resolve_accounts(journal):
    return {
        "debit": journal.default_debit_account_id,
        "credit": journal.default_credit_account_id,
    }


def resolve_party_tag(external_reference, party_type):
    return (
        AnalyticValue.objects
        .filter(
            axis__code=AnalyticAxis.PARTY,
            external_reference=external_reference,
            party_type=party_type,
        )
        .first()
    )


def resolve_funder_tag(funder_code):
    return (
        AnalyticValue.objects
        .filter(
            axis__code=AnalyticAxis.FUNDER,
            funder_code=funder_code,
        )
        .first()
    )


def raise_unmapped(
    event_type,
    source_reference,
    payload,
    user
):
    payload.pop("user", None)
    unmaped = UnmappedFinancialEvent(
        event_type=event_type,
        source_reference=source_reference,
        payload=payload,
    )
    unmaped.save(username=user.username)

    logger.warning(
        "Unmapped financial event",
        extra={
            "event_type": event_type,
            "reference": source_reference,
        },
    )


def get_open_period(transaction_date):

    return (
        AccountingPeriod.objects
        .filter(
            status=AccountingPeriod.STATUS_OPEN,
            start_date__lte=transaction_date,
            end_date__gte=transaction_date,
        )
        .first()
    )


def resolve_mapping(event_type, payload):
    """
    Placeholder until deployment configuration
    provides dynamic mappings.
    """

    mapping = {
        "claim_valuated": {
            "journal": "Claims",
        },
        "invoice_issued": {
            "journal": "Sales",
        },
        "payroll_disbursement": {
            "journal": "Payroll",
        },
        "payment_point_reconciliation": {
            "journal": "Bank",
        }
    }

    journal = LedgerJournal.objects.get(
        code=mapping.get(event_type)["journal"]
    )
    accounts = resolve_accounts(journal)

    mapping.get(event_type).update({
        "credit_account": accounts["credit"],
        "debit_account": accounts["debit"]
    })
    return mapping.get(event_type)


def on_claim_valuated(
    sender,
    claim,
    user,
    **kwargs,
):
    if claim.status != Claim.STATUS_VALUATED:
        logger.info("Skipped Claim because its not valuated")
        return
    logger.info("Claim valuated received")

    amount = Decimal(str(
        claim.valuated or claim.approved or 0
    ))

    if amount == Decimal("0"):
        logger.info("Skipped zero claim valuation")
        return None

    mapping = resolve_mapping(
        "claim_valuated",
        kwargs,
    )

    if not mapping:
        return raise_unmapped(
            "claim_valuated",
            str(claim.uuid),
            kwargs,
            user,
        )

    journal = LedgerJournal.objects.get(
        code=mapping["journal"]
    )

    period = get_open_period(claim.date_claimed)
    if not period:
        return raise_unmapped(
            "claim_valuated",
            str(claim.uuid),
            kwargs,
            user,
        )

    logger.info(
        "Financial event received",
        extra={
            "event_type": "claim_valuated",
            "reference": claim.uuid,
        },
    )

    tags = {}

    party_tag = resolve_party_tag(
        claim.health_facility.uuid,
        AnalyticValue.PARTY_HEALTH_FACILITY,
    )

    resolved_tags = []

    if party_tag:
        resolved_tags.append(party_tag)

    today = py_datetime.now()
    policy_holder = PolicyHolder.objects.filter(
        is_deleted=False
    ).filter(
        Q(date_valid_to__isnull=True) | Q(date_valid_to__date__gte=today.date())
    ).first()

    if policy_holder:
        funder_tag = resolve_funder_tag(policy_holder.code)
        if funder_tag:
            resolved_tags.append(funder_tag)

    if resolved_tags:
        tags = {
            0: resolved_tags,
            1: resolved_tags,
        }

    result = LedgerEntryService.post(
        journal=journal,
        accounting_period=period,
        source_event_type="claim_payment",
        source_event_reference=str(claim.uuid),
        user=user,
        tags=tags,
        legs=[
            {
                "account": mapping["credit_account"],
                "amount": amount,
            },
            {
                "account": mapping["debit_account"],
                "amount": -amount,
            },
        ],
    )

    logger.info(
        "Entry for claim_valuated posted with result %s",
        result,
    )

    return result


def on_invoice_issued(
    sender,
    result,
    **kwargs
):
    invoice = result["data"]

    logger.info(
        "Financial event received",
        extra={
            "event_type": "invoice_issued",
            "reference": invoice["id"]
        }
    )

    amount = Decimal(
        str(invoice["amount_total"])
    )

    if amount == 0:
        logger.info(
            "Skipped zero for event invoice_issued"
        )
        return

    mapping = resolve_mapping(
        "invoice_issued",
        kwargs,
    )

    user = kwargs.get("user", None)

    if not mapping:
        return raise_unmapped(
            "invoice_issued",
            str(invoice["id"]),
            kwargs,
            user
        )

    journal = LedgerJournal.objects.get(
        code=mapping["journal"]
    )

    period = get_open_period(
        invoice["invoice_date"]
    )

    if not period:
        return raise_unmapped(
            "invoice_issued",
            str(invoice["id"]),
            kwargs,
            user
        )

    party_tag = resolve_party_tag(
        invoice["health_facility_id"],
        AnalyticValue.PARTY_HEALTH_FACILITY,
    )

    tags = {}

    if party_tag:
        tags = {
            0: [party_tag],
            1: [party_tag],
        }

    result = LedgerEntryService.post(
        journal=journal,
        accounting_period=period,
        source_event_type="invoice",
        source_event_reference=str(
            invoice["id"]
        ),
        user=kwargs["user"],
        tags=tags,
        legs=[
            {
                "account": mapping["credit_account"],
                "amount": amount,
            },
            {
                "account": mapping["debit_account"],
                "amount": -amount,
            }
        ],
    )

    logger.info(
        "Entry for invoice_issued posted with result %s",
        result
    )


def on_payroll_disbursed(
    sender,
    benefits,
    user,
    **kwargs
):

    amount = sum(
        Decimal(str(b.amount))
        for b in benefits
    )

    if amount == 0:
        logger.info("Skipped zero for event payroll_disbursement")
        return

    mapping = resolve_mapping(
        "payroll_disbursement",
        kwargs,
    )

    if not mapping:
        return raise_unmapped(
            "payroll_disbursement",
            str(kwargs.get("payroll_id")),
            kwargs,
            user
        )

    journal = LedgerJournal.objects.get(
        code=mapping["journal"]
    )

    period = get_open_period(kwargs["payroll_date"])
    if not period:
        return raise_unmapped(
            "payroll_disbursement",
            str(kwargs.get("payroll_id")),
            kwargs,
            user
        )

    logger.info(
        "Financial event received",
        extra={
            "event_type": "payroll_disbursement",
            "reference": kwargs.get("payroll_id")
        }
    )
    party_tag = resolve_party_tag(
        kwargs["payment_point_manager_id"],
        AnalyticValue.PARTY_PAYMENT_POINT_MANAGER,
    )

    tags = {}

    if party_tag:
        tags = {
            0: [party_tag],
            1: [party_tag],
        }
    result = LedgerEntryService.post(
        journal=journal,
        accounting_period=period,
        source_event_type="payroll_disbursement",
        source_event_reference=str(
            kwargs.get("payroll_id")
        ),
        user=user,
        tags=tags,
        legs=[
            {
                "account": mapping["credit_account"],
                "amount": amount,
            },
            {
                "account": mapping["debit_account"],
                "amount": -amount,
            }
        ],
    )
    logger.info("Entry for payroll_disbursed posted with result %s", result)


def on_payment_point_reconciled(
    sender,
    benefits,
    variance=Decimal("0"),
    user=None,
    **kwargs
):

    logger.info(
        "Financial event received",
        extra={
            "event_type": "payment_point_reconciliation",
            "reference": kwargs.get("payroll_id")
        }
    )
    amount = sum(
        Decimal(str(b.amount))
        for b in benefits
    )

    if amount == 0:
        logger.info("Skipped zero for event payment_point_reconciliation")
        return

    mapping = resolve_mapping(
        "payment_point_reconciliation",
        kwargs,
    )

    if not mapping:
        return raise_unmapped(
            "payment_point_reconciliation",
            str(kwargs.get("payroll_id")),
            kwargs,
            user
        )

    journal = LedgerJournal.objects.get(
        code=mapping["journal"]
    )

    period = get_open_period(kwargs["payroll_date"])
    if not period:
        return raise_unmapped(
            "payment_point_reconciliation",
            str(kwargs.get("payroll_id")),
            kwargs,
            user
        )

    legs = [
        {
            "account": mapping["credit_account"],
            "amount": amount,
        },
        {
            "account": mapping["debit_account"],
            "amount": -amount,
        }
    ]

    if variance:
        variance_account = DeploymentConfiguration.objects.first().retained_earnings_account

        legs.append(
            {
                "account": variance_account,
                "amount": -variance,
            }
        )

        legs.append(
            {
                "account": variance_account,
                "amount": variance,
            }
        )

    party_tag = resolve_party_tag(
        kwargs["payment_point_manager_id"],
        AnalyticValue.PARTY_PAYMENT_POINT_MANAGER
    )

    tags = {}

    if party_tag:
        tags = {
            0: [party_tag],
            1: [party_tag],
        }

    result = LedgerEntryService.post(
        journal=journal,
        accounting_period=period,
        source_event_type="payment_point_reconciliation",
        source_event_reference=str(
            kwargs.get("payroll_id")
        ),
        user=user,
        legs=legs,
        tags=tags
    )
    logger.info("Entry for payment_point_reconciliation posted with result %s", result)


def bind_service_signals():

    bind_service_signal(
        'signal_after_invoice_module_invoice_create_service',
        on_invoice_issued,
        bind_type=ServiceSignalBindType.AFTER
    )

    bind_service_signal(
        'claim.claim_valuated',
        on_claim_valuated,
        bind_type=ServiceSignalBindType.AFTER
    )

    bind_service_signal(
        'payroll.disbursed',
        on_payroll_disbursed,
        bind_type=ServiceSignalBindType.AFTER
    )

    bind_service_signal(
        'payroll.payment_point_reconciled',
        on_payment_point_reconciled,
        bind_type=ServiceSignalBindType.AFTER
    )
