from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('invoice', '0016_remove_historicalpaymentinvoice_party_and_more'),
        ('ledger', '0011_add_journal_types'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE "tblPaymentInvoice"
                ADD COLUMN IF NOT EXISTS "PaymentDestinationID" uuid NULL;

                CREATE INDEX IF NOT EXISTS idx_tblPaymentInvoice_paymentdestinationid
                ON "tblPaymentInvoice" ("PaymentDestinationID");

                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'fk_tblPaymentInvoice_paymentdestination'
                    ) THEN
                        ALTER TABLE "tblPaymentInvoice"
                        ADD CONSTRAINT fk_tblPaymentInvoice_paymentdestination
                        FOREIGN KEY ("PaymentDestinationID")
                        REFERENCES "tblLedgerJournal" ("UUID")
                        ON DELETE NO ACTION;
                    END IF;
                END $$;
            """,
            reverse_sql="""
                ALTER TABLE "tblPaymentInvoice"
                DROP CONSTRAINT IF EXISTS fk_tblPaymentInvoice_paymentdestination;

                DROP INDEX IF EXISTS idx_tblPaymentInvoice_paymentdestinationid;

                ALTER TABLE "tblPaymentInvoice"
                DROP COLUMN IF EXISTS "PaymentDestinationID";
            """
        )
    ]
