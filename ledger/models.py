from core import fields
from core import models as core_models
from django.db import models
import logging
from django.utils import timezone as django_tz
from hordak.models import Account, Leg, Transaction
from hordak.defaults import (
    DECIMAL_PLACES,
    MAX_DIGITS
)
from django.core.exceptions import ValidationError
logger = logging.getLogger(__name__)


class Sequence(core_models.HistoryModel):
    """
    This is Sequence class it all the fields needed
    """
    name = models.CharField(db_column='Name', max_length=100, blank=True, null=True, unique=True)
    code = models.CharField(db_column='Code', max_length=50, blank=True, null=True, unique=True)
    prefix = models.CharField(db_column='Prefix', max_length=50, blank=True, null=True)
    suffix = models.CharField(db_column='Suffix', max_length=50, blank=True, null=True)
    padding = models.SmallIntegerField(db_column='Padding', blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'tblSequence'


class AccountingPeriod(core_models.HistoryModel):
    """
    Accounting period lifecycle management
    """

    STATUS_OPEN = 1
    STATUS_LOCKED = 2
    STATUS_CLOSED = 3

    STATUS_CHOICES = (
        (STATUS_OPEN, "Open"),
        (STATUS_LOCKED, "Locked"),
        (STATUS_CLOSED, "Closed"),
    )

    start_date = fields.DateField(
        db_column='StartDate',
        null=True,
        blank=True
    )

    end_date = fields.DateField(
        db_column='EndDate',
        null=True,
        blank=True
    )

    name = models.CharField(
        db_column='Name',
        max_length=100,
        blank=True,
        null=True,
        unique=True
    )

    code = models.CharField(
        db_column='Code',
        max_length=50,
        blank=True,
        null=True,
        unique=True
    )

    status = models.SmallIntegerField(
        db_column='Status',
        choices=STATUS_CHOICES,
        default=STATUS_OPEN
    )

    audit_user_id = models.IntegerField(
        db_column='AuditCreateUser',
        null=True,
        blank=True
    )

    audit_user_id_closed = models.IntegerField(
        db_column='AuditCloseUser',
        null=True,
        blank=True
    )

    closing_transaction = models.ForeignKey(
        Transaction,
        # Preserve historical audit records by not cascading deletions;
        # use DO_NOTHING to retain the foreign key value even if the referenced row is removed.
        models.DO_NOTHING,
        db_column='ClosingTransactionID',
        null=True,
        blank=True,
        related_name='closed_account_periods'
    )

    locked_at = models.DateTimeField(
        db_column='LockedAt',
        null=True,
        blank=True
    )

    closed_at = models.DateTimeField(
        db_column='ClosedAt',
        null=True,
        blank=True
    )

    closed_by = models.IntegerField(
        db_column='ClosedBy',
        null=True,
        blank=True
    )

    @property
    def is_open(self):
        return self.status == self.STATUS_OPEN

    @property
    def is_locked(self):
        return self.status == self.STATUS_LOCKED

    @property
    def is_closed(self):
        return self.status == self.STATUS_CLOSED

    class Meta:
        managed = True
        db_table = 'tblAccountingPeriod'


class LedgerJournal(core_models.HistoryModel):
    """
    This is Journal class it all the fields needed
    """
    name = models.CharField(db_column='Name', max_length=100, blank=True, null=True, unique=True)
    code = models.CharField(db_column='Code', max_length=50, blank=True, null=True, unique=True)
    type = models.CharField(db_column='Type', max_length=50, blank=True, null=True)
    # Preserve historical audit records by not cascading deletions;
    # use DO_NOTHING to retain the foreign key value even if the referenced row is removed.
    sequence_id = models.ForeignKey(Sequence, models.DO_NOTHING, db_column='SequenceID', related_name="sequencies")
    default_credit_account_id = models.ForeignKey(
        Account, models.DO_NOTHING, db_column='DefaultCreditAccountId', related_name="defaultcreditaccounts")
    default_debit_account_id = models.ForeignKey(
        Account, models.DO_NOTHING, db_column='DefaultDebitAccountId', related_name="defaultdebitaccounts")

    class Meta:
        managed = True
        db_table = 'tblLedgerJournal'

    def __str__(self):
        return self.code or self.name or str(self.id)


class AnalyticAxis(core_models.HistoryModel):
    PARTY = "party"
    FUNDER = "funder"

    AXIS_CHOICES = (
        (PARTY, "Party"),
        (FUNDER, "Funder"),
    )

    code = models.CharField(
        db_column='Code',
        max_length=50,
        unique=True,
        choices=AXIS_CHOICES,
    )
    name = models.CharField(
        db_column='Name',
        max_length=100,
    )

    class Meta:
        db_table = 'tblAnalyticAxis'


class AnalyticValue(core_models.HistoryModel):
    PARTY_INSUREE_FAMILY = "insuree_family"
    PARTY_HEALTH_FACILITY = "health_facility"
    PARTY_PAYMENT_POINT_MANAGER = "payment_point_manager"

    PARTY_TYPES = (
        (PARTY_INSUREE_FAMILY, "Insuree/Family"),
        (PARTY_HEALTH_FACILITY, "Health Facility"),
        (PARTY_PAYMENT_POINT_MANAGER, "Payment Point Manager"),
    )

    # Preserve historical audit records by not cascading deletions;
    # use DO_NOTHING to retain the foreign key value even if the referenced row is removed.
    axis = models.ForeignKey(
        AnalyticAxis,
        models.DO_NOTHING,
        db_column='AnalyticAxisID',
        related_name='values'
    )

    party_type = models.CharField(
        db_column='PartyType',
        max_length=50,
        choices=PARTY_TYPES,
        blank=True,
        null=True,
    )

    funder_code = models.CharField(
        db_column='FunderCode',
        max_length=100,
        blank=True,
        null=True,
    )

    external_reference = models.CharField(
        db_column='ExternalReference',
        max_length=255,
    )

    display_name = models.CharField(
        db_column='DisplayName',
        max_length=255,
    )

    def clean(self):
        if self.axis.code == AnalyticAxis.PARTY:
            if not self.party_type:
                raise ValidationError(
                    "party_type is required for party axis"
                )

        if self.axis.code == AnalyticAxis.FUNDER:
            if not self.funder_code:
                raise ValidationError(
                    "funder_code is required for funder axis"
                )

    class Meta:
        db_table = 'tblAnalyticValue'


class LegTag(core_models.HistoryModel):

    # Preserve historical audit records by not cascading deletions;
    # use DO_NOTHING to retain the foreign key value even if the referenced row is removed.
    leg = models.ForeignKey(
        Leg,
        models.DO_NOTHING,
        db_column='LegID',
        related_name='analytic_tags'
    )

    analytic_value = models.ForeignKey(
        AnalyticValue,
        models.DO_NOTHING,
        db_column='AnalyticValueID',
        related_name='leg_tags'
    )

    axis = models.ForeignKey(
        AnalyticAxis,
        models.DO_NOTHING,
        db_column='AxisID',
        editable=False,  # empêche modif manuelle en dehors de save()
    )

    # Dénormalisé depuis hordak_leg.accounting_period_id. Nécessaire pour
    # la contrainte FK composite (leg_id, accounting_period_id) vers
    # hordak_leg, désormais partitionnée par LIST sur accounting_period_id
    # (cf. migration ledger/migrations/0002_partition_leg.py). Ce n'est
    # PAS un ForeignKey Django classique : Leg (Hordak) n'expose pas ce
    # champ côté ORM projet, la valeur est lue en SQL brut à la sauvegarde.
    accounting_period_id = models.UUIDField(
        db_column='AccountingPeriodID',
        editable=False,
    )

    def save(self, *args, **kwargs):
        # Toujours resynchroniser axis depuis analytic_value avant de sauver
        self.axis = self.analytic_value.axis
        self.clean()

        super().save(*args, **kwargs)

    def clean(self):
        existing = LegTag.objects.filter(
            leg=self.leg,
            analytic_value__axis=self.analytic_value.axis
        )
        if self.pk:
            existing = existing.exclude(pk=self.pk)
        if existing.exists():
            raise ValidationError(
                f"Leg already contains a tag for axis "
                f"{self.analytic_value.axis.code}"
            )

    class Meta:
        db_table = 'tblLegTag'
        constraints = [
            models.UniqueConstraint(fields=["leg", "axis"], name="uniq_legtag_leg_axis")
        ]
        # NOTE : la FK composite (leg_id, accounting_period_id) ->
        # hordak_leg(id, accounting_period_id) n'est pas exprimable via
        # ForeignKey Django (pas de support natif des FK multi-colonnes).
        # Elle est ajoutée au niveau DB par RunSQL dans la migration
        # ledger/migrations/0003_legtag_period_fk.py.


class LedgerEntryMeta(core_models.HistoryModel):
    SOURCE_EVENT_TYPES = (
        ("claim_payment", "Claim Payment"),
        ("invoice", "Invoice"),
        ("payroll_disbursement", "Payroll"),
        ("payment_point_reconciliation", "Payment Point"),
        ("closing_entry", "Closing Entry"),
        ("correction", "Correction"),
    )

    # Preserve historical audit records by not cascading deletions;
    # use DO_NOTHING to retain the foreign key value even if the referenced row is removed.
    transaction = models.OneToOneField(
        Transaction,
        models.DO_NOTHING,
        db_column='TransactionID',
        related_name='ledger_meta'
    )

    journal = models.ForeignKey(
        LedgerJournal,
        models.DO_NOTHING,
        db_column='LedgerJournalID'
    )

    accounting_period = models.ForeignKey(
        AccountingPeriod,
        models.DO_NOTHING,
        db_column='AccountingPeriodID'
    )

    source_event_type = models.CharField(
        db_column='SourceEventType',
        max_length=50,
        choices=SOURCE_EVENT_TYPES,
    )

    source_event_reference = models.CharField(
        db_column='SourceEventReference',
        max_length=255,
    )

    posted_at = models.DateTimeField(
        db_column='PostedAt',
        auto_now_add=True,
    )

    def clean(self):
        if self.accounting_period.status != AccountingPeriod.STATUS_OPEN:
            raise ValidationError(
                "Posting allowed only in open period"
            )

    class Meta:
        db_table = 'tblLedgerEntryMeta'


class DeploymentConfiguration(core_models.HistoryModel):

    OPERATING_MODE_LOCAL = "local_only"
    OPERATING_MODE_REPLICATED = "replicated"

    MODES = (
        (OPERATING_MODE_LOCAL, "Local Only"),
        (OPERATING_MODE_REPLICATED, "Replicated"),
    )

    EXTERNAL_SYSTEMS = (
        ("odoo", "Odoo"),
        ("sage", "Sage"),
    )

    operating_mode = models.CharField(
        db_column='OperatingMode',
        max_length=30,
        choices=MODES,
        default=OPERATING_MODE_LOCAL,
    )

    external_system = models.CharField(
        db_column='ExternalSystem',
        max_length=30,
        choices=EXTERNAL_SYSTEMS,
        null=True,
        blank=True,
    )

    currency_code = models.CharField(
        db_column='CurrencyCode',
        max_length=10,
    )

    # Preserve historical audit records by not cascading deletions;
    # use DO_NOTHING to retain the foreign key value even if the referenced row is removed.
    retained_earnings_account = models.ForeignKey(
        Account,
        models.DO_NOTHING,
        db_column='RetainedEarningsAccountID'
    )

    class Meta:
        db_table = 'tblDeploymentConfiguration'


class UnmappedFinancialEvent(core_models.HistoryModel):

    EVENT_STATUS_PENDING = "PENDING"
    EVENT_STATUS_RESOLVED = "RESOLVED"

    event_type = models.CharField(
        max_length=100
    )

    source_reference = models.CharField(
        max_length=255
    )

    payload = models.JSONField(
        default=dict
    )

    status = models.CharField(
        max_length=20,
        default=EVENT_STATUS_PENDING
    )

    class Meta:
        db_table = "ledger_unmapped_event"


class PartyLedgerBalance(core_models.HistoryModel):
    # Preserve historical audit records by not cascading deletions;
    # use DO_NOTHING to retain the foreign key value even if the referenced row is removed.
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        models.DO_NOTHING,
        db_column="AccountingPeriodID",
        related_name="party_balances"
    )

    analytic_value = models.ForeignKey(
        AnalyticValue,
        models.DO_NOTHING,
        db_column="AnalyticValueID",
        related_name="party_balances"
    )

    debit_amount = models.DecimalField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0
    )

    credit_amount = models.DecimalField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0
    )

    balance_amount = models.DecimalField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0
    )

    class Meta:
        db_table = "tblPartyLedgerBalance"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "accounting_period",
                    "analytic_value"
                ],
                name="uniq_party_balance"
            )
        ]


class AccountBalanceSnapshot(core_models.HistoryModel):

    # Preserve historical audit records by not cascading deletions;
    # use DO_NOTHING to retain the foreign key value even if the referenced row is removed.
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        models.DO_NOTHING,
        db_column="AccountingPeriodID"
    )

    account = models.ForeignKey(
        Account,
        models.DO_NOTHING,
        db_column="AccountID"
    )

    debit_amount = models.DecimalField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0
    )

    credit_amount = models.DecimalField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0
    )

    balance_amount = models.DecimalField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0
    )

    class Meta:
        db_table = "tblAccountBalanceSnapshot"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "accounting_period",
                    "account"
                ],
                name="uniq_account_snapshot"
            )
        ]


class ExternalReplicationRecord(core_models.HistoryModel):

    STATUS_PENDING = "pending"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_REJECTED = "rejected"
    STATUS_UNCONFIRMED = "unconfirmed"

    STATUS_CHOICES = [
        (STATUS_PENDING, STATUS_PENDING),
        (STATUS_SUCCEEDED, STATUS_SUCCEEDED),
        (STATUS_REJECTED, STATUS_REJECTED),
        (STATUS_UNCONFIRMED, STATUS_UNCONFIRMED),
    ]

    TARGET_ODOO = "odoo"
    TARGET_SAGE = "sage"

    TARGET_CHOICES = [
        (TARGET_ODOO, TARGET_ODOO),
        (TARGET_SAGE, TARGET_SAGE),
    ]

    # Preserve historical audit records by not cascading deletions;
    # use DO_NOTHING to retain the foreign key value even if the referenced row is removed.
    ledger_entry = models.ForeignKey(
        LedgerEntryMeta,
        on_delete=models.DO_NOTHING,
        related_name="replication_records",
    )

    target_system = models.CharField(
        max_length=20,
        choices=TARGET_CHOICES,
    )

    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    external_reference = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    rejection_reason = models.TextField(
        null=True,
        blank=True,
    )

    attempt_count = models.IntegerField(default=0)

    last_attempted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "tblExternalReplicationRecord"


class ManualReviewQueueItem(core_models.HistoryModel):

    # Preserve historical audit records by not cascading deletions;
    # use DO_NOTHING to retain the foreign key value even if the referenced row is removed.
    replication_record = models.OneToOneField(
        ExternalReplicationRecord,
        on_delete=models.DO_NOTHING,
        related_name="review_item",
    )

    created_at = models.DateTimeField(
        default=django_tz.now
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    resolved_by_transaction = models.ForeignKey(
        Transaction,
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
    )

    resolution_note = models.TextField(
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "tblManualReviewQueueItem"
