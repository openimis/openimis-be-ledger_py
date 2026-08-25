from django.db import migrations


SQL = """
CREATE OR REPLACE FUNCTION ledger_prevent_closed_period_legtag_write()
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
        'Cannot modify analytic tags belonging to a closed accounting period';
    END IF;

    RETURN COALESCE(NEW, OLD);
END;
$$;


DROP TRIGGER IF EXISTS trg_closed_period_legtag
ON "tblLegTag";


CREATE TRIGGER trg_closed_period_legtag
BEFORE INSERT OR UPDATE OR DELETE
ON "tblLegTag"
FOR EACH ROW
EXECUTE FUNCTION ledger_prevent_closed_period_legtag_write();
"""


SQL_DROP = """
DROP TRIGGER IF EXISTS trg_closed_period_legtag
ON "tblLegTag";

DROP FUNCTION IF EXISTS
ledger_prevent_closed_period_legtag_write();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0004_trigger_protect_entry_meta"),
    ]

    operations = [
        migrations.RunSQL(
            sql=SQL,
            reverse_sql=SQL_DROP,
        )
    ]