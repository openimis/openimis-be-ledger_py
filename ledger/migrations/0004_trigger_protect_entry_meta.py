from django.db import migrations


SQL = """
CREATE OR REPLACE FUNCTION ledger_prevent_closed_period_meta_write()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_status smallint;
BEGIN

    SELECT ap."Status"
      INTO v_status
      FROM "tblAccountingPeriod" ap
     WHERE ap."UUID" =
        COALESCE(
            NEW."AccountingPeriodID",
            OLD."AccountingPeriodID"
        );

    IF v_status = 3 THEN
        RAISE EXCEPTION
        'Cannot modify ledger entries belonging to a closed accounting period';
    END IF;

    RETURN COALESCE(NEW, OLD);
END;
$$;


DROP TRIGGER IF EXISTS trg_closed_period_meta
ON "tblLedgerEntryMeta";


CREATE TRIGGER trg_closed_period_meta
BEFORE INSERT OR UPDATE OR DELETE
ON "tblLedgerEntryMeta"
FOR EACH ROW
EXECUTE FUNCTION ledger_prevent_closed_period_meta_write();
"""


SQL_DROP = """
DROP TRIGGER IF EXISTS trg_closed_period_meta
ON "tblLedgerEntryMeta";

DROP FUNCTION IF EXISTS
ledger_prevent_closed_period_meta_write();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0003_unmappedfinancialevent_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=SQL,
            reverse_sql=SQL_DROP,
        )
    ]
