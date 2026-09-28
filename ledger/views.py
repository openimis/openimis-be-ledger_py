import csv

from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes

from .apps import LedgerConfig
from core.security import checkUserWithRights

from .models import (
    AccountingPeriod,
    LedgerEntryMeta,
)

STANDARD = "standard"
FEC = "fec"


@api_view(["GET"])
@permission_classes([
    checkUserWithRights(
        LedgerConfig.gql_query_ledger_perms,
    )
])
def download_period(request, period_id, export_type):

    period = AccountingPeriod.objects.filter(id=period_id)
    if not period.exists():
        return HttpResponse(
            "This period does not exist",
            status=400
        )

    if export_type == STANDARD:
        return export_standard_gl(period.first())

    if export_type == FEC:
        return export_fec_ohada(period.first())

    return HttpResponse(
        "Invalid export type",
        status=400
    )


def export_standard_gl(period):

    response = HttpResponse(
        content_type="text/csv"
    )

    response[
        "Content-Disposition"
    ] = (
        f'attachment; filename="grand_livre_{period.code}.csv"'
    )

    writer = csv.writer(
        response,
        delimiter=";"
    )

    writer.writerow([
        "Date",
        "Journal",
        "Reference",
        "Compte",
        "LibelleCompte",
        "Debit",
        "Credit",
        "Description",
    ])

    entries = (
        LedgerEntryMeta.objects
        .filter(accounting_period=period)
        .select_related(
            "transaction",
            "journal"
        )
        .prefetch_related(
            "transaction__legs__account"
        )
        .order_by(
            "transaction__date",
            "transaction_id"
        )
    )

    for entry in entries:

        for leg in entry.transaction.legs.all():

            writer.writerow([
                entry.transaction.date,
                entry.journal.code,
                entry.source_event_reference,
                leg.account.full_code,
                leg.account.name,
                leg.debit.amount if leg.debit else "",
                leg.credit.amount if leg.credit else "",
                entry.transaction.description,
            ])

    return response


def export_fec_ohada(period):

    response = HttpResponse(
        content_type="text/csv"
    )

    response[
        "Content-Disposition"
    ] = (
        f'attachment; filename="FEC_{period.code}.csv"'
    )

    writer = csv.writer(
        response,
        delimiter=";"
    )

    writer.writerow([
        "JournalCode",
        "JournalLib",
        "EcritureNum",
        "EcritureDate",
        "CompteNum",
        "CompteLib",
        "PieceRef",
        "PieceDate",
        "EcritureLib",
        "Debit",
        "Credit",
    ])

    entries = (
        LedgerEntryMeta.objects
        .filter(
            accounting_period=period
        )
        .select_related(
            "transaction",
            "journal"
        )
        .prefetch_related(
            "transaction__legs__account"
        )
        .order_by(
            "transaction__date",
            "transaction_id"
        )
    )

    for entry in entries:

        ecriture_num = str(
            entry.transaction_id
        )

        for leg in entry.transaction.legs.all():

            writer.writerow([
                entry.journal.code,
                entry.journal.name,
                ecriture_num,
                entry.transaction.date.strftime("%Y%m%d"),
                leg.account.full_code,
                leg.account.name,
                entry.source_event_reference,
                entry.transaction.date.strftime("%Y%m%d"),
                entry.transaction.description,
                leg.debit.amount if leg.debit else 0,
                leg.credit.amount if leg.credit else 0,
            ])

    return response
