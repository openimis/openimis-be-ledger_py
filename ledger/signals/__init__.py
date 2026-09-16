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
from payer.models import Payer
from django.db.models import Q
from datetime import datetime as py_datetime
from insuree.models import Insuree
from invoice.models import Invoice
logger = logging.getLogger(__name__)


def resolve_accounts(journal):
    if not journal:
        return {}
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
            "journal": "purchase",
        },
        "invoice_issued": {
            "journal": "sales",
        },
        "invoice_paid": {
            "journal": "treasury",
        },
        "payment_point_reconciliation": {
            "journal": "treasury",
        },
        "payroll_disbursement": {
            "journal": "treasury",
        },
    }

    journal = LedgerJournal.objects.filter(
        type__code=mapping.get(event_type)["journal"]
    ).first()
    if journal:
        accounts = resolve_accounts(journal)

        mapping.get(event_type).update({
            "credit_account": accounts["credit"],
            "debit_account": accounts["debit"],
            "journal": journal.id
        })
    return mapping.get(event_type)


def on_claim_valuated(
    sender,
    **kwargs,
):
    claim, errors = kwargs['result']
    if not isinstance(claim, Claim):
        logger.info("set_claim_processed_or_valuated method has not returned a claim instance")
        return None
    if errors:
        logger.info("Cannot process due to errors on claim processing")

    user = kwargs.get('data', ([], None))[0][1]
    if claim.status != Claim.STATUS_VALUATED:
        logger.info("Skipped Claim because its not valuated")
        return None
    logger.info("Claim valuated received")

    amount = Decimal(str(
        claim.valuated or claim.approved or claim.claimed or 0
    ))

    if amount == Decimal("0"):
        logger.info("Skipped zero claim valuation")
        return None

    mapping = resolve_mapping(
        "claim_valuated",
        kwargs,
    )

    payload = {
        "claim_id": str(claim.id) if claim else None,
        "claim_code": claim.code if claim else None,
        "username": user.username if user else None,
    }

    if not mapping:
        return raise_unmapped(
            "claim_valuated",
            str(claim.uuid),
            payload,
            user,
        )

    journal = LedgerJournal.objects.filter(
        id=mapping["journal"]
    ).first()
    if not journal:
        logger.info("Skipped journal not found on claim valuation")
        return None

    period = get_open_period(claim.date_claimed)
    if not period:
        return raise_unmapped(
            "claim_valuated",
            str(claim.uuid),
            payload,
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
    if not party_tag:
        logger.info("party %s does not exist, we create it", claim.health_facility.uuid)
        axis = AnalyticAxis.objects.filter(code=AnalyticAxis.PARTY).first()
        if not axis:
            axis = AnalyticAxis(
                code=AnalyticAxis.PARTY,
                name="Party",
            )
            axis.save(username=user.username)

        analytic_value = AnalyticValue(
            axis=axis,
            party_type=AnalyticValue.PARTY_HEALTH_FACILITY,
            external_reference=claim.health_facility.code,
            display_name=str(claim.health_facility.name),
        )
        analytic_value.save(
            username=user.username
        )
        party_tag = analytic_value

    resolved_tags = []

    if party_tag:
        resolved_tags.append(party_tag)

    today = py_datetime.now()
    payer = Payer.objects.filter(
        location_id=claim.health_facility.location.id
    ).filter(
        Q(validity_to__isnull=True) | Q(validity_to__date__gte=today.date())
    ).first()

    if payer:
        funder_tag = resolve_funder_tag(payer.uuid)
        if not funder_tag:
            logger.info("party %s does not exist, we create it", payer.name)
            axis = AnalyticAxis.objects.filter(code=AnalyticAxis.FUNDER).first()
            if not axis:
                axis = AnalyticAxis(
                    code=AnalyticAxis.FUNDER,
                    name="Funder",
                )
                axis.save(username=user.username)

            analytic_value = AnalyticValue(
                axis=axis,
                funder_code=payer.uuid,
                party_type=AnalyticValue.PARTY_PAYMENT_POINT_MANAGER,
                external_reference=payer.uuid,
                display_name=str(payer.name),
            )
            analytic_value.save(
                username=user.username
            )
            funder_tag = analytic_value

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
        "Entry for claim_valuated %s posted with result %s",
        claim.uuid,
        result,
    )

    return result


def on_invoice_issued(
    sender,
    result,
    **kwargs
):
    invoice = kwargs['data'][1]['result']
    invoice_code = invoice['invoice_data']['code']
    amount = invoice['invoice_data_line'][0]['amount_total']
    date_invoice = invoice['invoice_data']['date_invoice']
    insuree_id = invoice['invoice_data']['thirdparty_id']
    user = invoice['user']
    payload = {
        "invoice_code": invoice_code,
        "insuree_id": insuree_id,
        "date_invoice": date_invoice,
        "user": user.username
    }

    logger.info(
        "Financial event received",
        extra={
            "event_type": "invoice_issued",
            "reference": invoice_code
        }
    )

    amount = Decimal(
        str(amount)
    )

    if amount == 0:
        logger.info(
            "Skipped zero for event invoice_issued"
        )
        return

    mapping = resolve_mapping(
        "invoice_issued",
        result,
    )

    if not mapping:
        return raise_unmapped(
            "invoice_issued",
            str(invoice_code),
            payload,
            user
        )

    journal = LedgerJournal.objects.filter(
        id=mapping["journal"]
    ).first()
    if not journal:
        logger.info("Skipped journal not found on invoice issued")
        return None

    period = get_open_period(
        date_invoice
    )

    if not period:
        return raise_unmapped(
            "invoice_issued",
            str(invoice_code),
            payload,
            user
        )

    insuree = Insuree.objects.filter(id=insuree_id).first()
    party_tag = None
    if not insuree:
        logger.info("Skipped insuree not found on invoice issued")
        return None

    party_tag = resolve_party_tag(
        insuree.chf_id,
        AnalyticValue.PARTY_INSUREE_FAMILY,
    )

    if not party_tag:
        logger.info("party %s does not exist, we create it", insuree.chf_id)
        axis = AnalyticAxis.objects.filter(code=AnalyticAxis.PARTY).first()
        if not axis:
            axis = AnalyticAxis(
                code=AnalyticAxis.PARTY,
                name="Party",
            )
            axis.save(username=user.username)

        analytic_value = AnalyticValue(
            axis=axis,
            party_type=AnalyticValue.PARTY_INSUREE_FAMILY,
            external_reference=insuree.chf_id,
            display_name=str(insuree.last_name) + " " + str(insuree.other_names),
        )
        analytic_value.save(
            username=user.username
        )
        party_tag = analytic_value

    tags = {
        0: [party_tag],
        1: [party_tag],
    }

    result = LedgerEntryService.post(
        journal=journal,
        accounting_period=period,
        source_event_type="invoice",
        source_event_reference=str(
            invoice_code
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

    journal = LedgerJournal.objects.filter(
        id=mapping["journal"]
    ).first()
    if not journal:
        logger.info("Skipped journal not found on payroll disbursed")
        return None

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


def on_invoice_paid(
    sender,
    result,
    **kwargs
):
    data = kwargs["data"]

    first_item = data[0]
    user = first_item[0]

    input_data = first_item[1]

    payment_invoice = first_item[2]

    status = first_item[3]

    invoice_uuid = first_item[4]
    amount = input_data["amount_received"]
    date_payment = input_data["date_payment"]
    payload = {
        "payment_invoice": payment_invoice.id,
        "status": status,
        "invoice_uuid": invoice_uuid,
        "paymentInvoiceId": payment_invoice.id,
        "user": user.username
    }

    logger.info(
        "Financial event received",
        extra={
            "event_type": "invoice_paid",
            "invoice_uuid": invoice_uuid
        }
    )

    amount = Decimal(
        str(amount)
    )

    if amount == 0:
        logger.info(
            "Skipped zero for event invoice_paid"
        )
        return

    mapping = resolve_mapping(
        "invoice_paid",
        result,
    )

    if not mapping:
        return raise_unmapped(
            "invoice_paid",
            str(payment_invoice.id),
            payload,
            user
        )

    journal = LedgerJournal.objects.filter(
        id=mapping["journal"]
    ).first()
    if not journal:
        logger.info("Skipped journal not found on invoice paid")
        return None

    period = get_open_period(
        date_payment
    )

    if not period:
        return raise_unmapped(
            "invoice_paid",
            str(payment_invoice.id),
            payload,
            user
        )

    invoice = Invoice.objects.filter(id=invoice_uuid).first()
    if not invoice:
        logger.info("Skipped invoice not found on invoice paid")
        return None
    insuree = Insuree.objects.filter(id=invoice.thirdparty_id).first()
    if not insuree:
        logger.info("Skipped insuree not found on invoice paid")
        return None

    party_tag = None
    party_tag = resolve_party_tag(
        insuree.chf_id,
        AnalyticValue.PARTY_INSUREE_FAMILY,
    )

    if not party_tag:
        logger.info("party %s does not exist, we create it", insuree.chf_id)
        axis = AnalyticAxis.objects.filter(code=AnalyticAxis.PARTY).first()
        if not axis:
            axis = AnalyticAxis(
                code=AnalyticAxis.PARTY,
                name="Party",
            )
            axis.save(username=user.username)

        analytic_value = AnalyticValue(
            axis=axis,
            party_type=AnalyticValue.PARTY_INSUREE_FAMILY,
            external_reference=insuree.chf_id,
            display_name=str(insuree.last_name) + " " + str(insuree.other_names),
        )
        analytic_value.save(
            username=user.username
        )
        party_tag = analytic_value

    tags = {
        0: [party_tag],
        1: [party_tag],
    }

    result = LedgerEntryService.post(
        journal=journal,
        accounting_period=period,
        source_event_type="payment_point_reconciliation",
        source_event_reference=str(
            payment_invoice.id
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

    logger.info(
        "Entry for invoice_paid posted with result %s",
        result
    )


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

    journal = LedgerJournal.objects.filter(
        id=mapping["journal"]
    ).first()
    if not journal:
        logger.info("Skipped journal not found on payment_point_reconciliation")
        return None

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

    bind_service_signal(
        'signal_after_payment_detail_received',
        on_invoice_paid,
        bind_type=ServiceSignalBindType.AFTER
    )
