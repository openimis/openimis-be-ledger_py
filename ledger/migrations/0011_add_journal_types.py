from django.db import migrations
import uuid

def create_journal_types(apps, schema_editor):
    JournalTypes = apps.get_model("ledger", "JournalTypes")
    user = apps.get_model("core", "User")

    user = (
        user.objects
        .order_by("id")
        .first()
    )

    if not user:
        return

    journal_types = [
        {
            "code": "sales",
            "type": "Sales",
            "alt_language": "Vente",
        },
        {
            "code": "sales_credit_note",
            "type": "Sales Credit Note / Sales Returns",
            "alt_language": "Avoir de vente",
        },
        {
            "code": "purchase",
            "type": "Purchases Journal",
            "alt_language": "Achat",
        },
        {
            "code": "purchase_credit_note",
            "type": "Purchase Credit Note / Purchase Returns",
            "alt_language": "Avoir fournisseur",
        },
        {
            "code": "cash",
            "type": "Cash Journal",
            "alt_language": "Liquidités",
        },
        {
            "code": "bank",
            "type": "Bank & Checks Journal",
            "alt_language": "Journal de banque et chèque",
        },
        {
            "code": "general",
            "type": "General Journal",
            "alt_language": "Journal général",
        },
        {
            "code": "close",
            "type": "Opening/Closing journal",
            "alt_language": "Journal de situation ouverture / clôture",
        },
        {
            "code": "treasury",
            "type": "Treasury journal",
            "alt_language": "Journal de trésorerie",
        },
    ]

    for item in journal_types:
        JournalTypes.objects.get_or_create(
            code=item["code"],
            defaults={
                "id": uuid.uuid4(),
                "type": item["type"],
                "alt_language": item["alt_language"],
                "user_created": user,
                "user_updated": user,
                "version": 1,
                "is_deleted": False,
            },
        )


def reverse_create_journal_types(apps, schema_editor):
    JournalTypes = apps.get_model("ledger", "JournalTypes")

    JournalTypes.objects.filter(
        code__in=[
            "sales",
            "sales_credit_note",
            "purchase",
            "cash",
            "bank",
            "general",
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0010_alter_journaltypes_options_alter_journaltypes_table"),
    ]

    operations = [
        migrations.RunPython(
            create_journal_types,
            reverse_create_journal_types,
        ),
    ]
