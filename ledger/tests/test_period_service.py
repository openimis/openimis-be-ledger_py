from decimal import Decimal
from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.test_helpers import create_test_interactive_user

from hordak.models import Transaction

from ledger.models import (
    AccountingPeriod,
    Account,
    LedgerJournal,
    Sequence,
    DeploymentConfiguration,
    AccountBalanceSnapshot,
)

from ledger.services import (
    PeriodService,
)


class PeriodServiceTest(TestCase):

    def setUp(self):
        self.user = create_test_interactive_user()

        self.cash_account = Account.objects.create(
            code="1001",
            full_code="1001",
            name="Cash",
            type="AS",
        )

        self.income_account = Account.objects.create(
            code="7001",
            full_code="7001",
            name="Income",
            type="IN",
        )

        self.expense_account = Account.objects.create(
            code="6001",
            full_code="6001",
            name="Expense",
            type="EX",
        )

        self.sequence = Sequence(
            code="PERIOD",
            name="Period Sequence",
        )
        self.sequence.save(username=self.user.username)

        self.journal = LedgerJournal(
            code="GENERAL",
            name="General Journal",
            sequence_id=self.sequence,
            default_credit_account_id=self.cash_account,
            default_debit_account_id=self.expense_account,
        )
        self.journal.save(username=self.user.username)

        self.config = DeploymentConfiguration(
            currency_code="EUR",
            retained_earnings_account=self.cash_account,
        )
        self.config.save(username=self.user.username)

    # ------------------------------------------------------------------
    # open()
    # ------------------------------------------------------------------

    def test_open_period_creates_open_period(self):
        period = PeriodService.open(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            name="January 2026",
            code="2026-01",
            user=self.user,
        )

        self.assertIsNotNone(period.pk)
        self.assertEqual(
            period.status,
            AccountingPeriod.STATUS_OPEN,
        )
        self.assertEqual(
            period.start_date,
            date(2026, 1, 1),
        )
        self.assertEqual(
            period.end_date,
            date(2026, 1, 31),
        )

    def test_open_period_requires_start_date(self):
        with self.assertRaises(ValidationError):
            PeriodService.open(
                start_date=None,
                end_date=date(2026, 1, 31),
                user=self.user,
            )

    def test_open_period_requires_end_date(self):
        with self.assertRaises(ValidationError):
            PeriodService.open(
                start_date=date(2026, 1, 1),
                end_date=None,
                user=self.user,
            )

    def test_open_period_rejects_invalid_dates(self):
        with self.assertRaises(ValidationError):
            PeriodService.open(
                start_date=date(2026, 2, 1),
                end_date=date(2026, 1, 31),
                user=self.user,
            )

    def test_open_period_rejects_overlap(self):
        PeriodService.open(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            code="2026-01",
            user=self.user,
        )

        with self.assertRaises(ValidationError):
            PeriodService.open(
                start_date=date(2026, 1, 15),
                end_date=date(2026, 2, 15),
                code="2026-02",
                user=self.user,
            )

    def test_open_period_must_follow_latest_period(self):
        PeriodService.open(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
            code="2026-02",
            user=self.user,
        )

        with self.assertRaises(ValidationError):
            PeriodService.open(
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
                code="2026-01",
                user=self.user,
            )

    # ------------------------------------------------------------------
    # lock()
    # ------------------------------------------------------------------

    def test_lock_open_period(self):
        period = PeriodService.open(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            code="2026-01",
            user=self.user,
        )

        result = PeriodService.lock(
            period,
            user=self.user,
        )

        self.assertEqual(
            result.status,
            AccountingPeriod.STATUS_LOCKED,
        )

        self.assertIsNotNone(
            result.locked_at,
        )

    def test_lock_rejects_non_open_period(self):
        period = AccountingPeriod(
            name="Locked",
            status=AccountingPeriod.STATUS_LOCKED,
        )
        period.save(username=self.user.username)

        with self.assertRaises(ValidationError):
            PeriodService.lock(
                period,
                user=self.user,
            )

    def test_periods_must_be_locked_chronologically(self):
        first = PeriodService.open(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            code="2026-01",
            user=self.user,
        )

        second = PeriodService.open(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
            code="2026-02",
            user=self.user,
        )

        with self.assertRaises(ValidationError):
            PeriodService.lock(
                second,
                user=self.user,
            )

        PeriodService.lock(
            first,
            user=self.user,
        )

        # Le second peut maintenant être verrouillé.
        result = PeriodService.lock(
            second,
            user=self.user,
        )

        self.assertEqual(
            result.status,
            AccountingPeriod.STATUS_LOCKED,
        )

    # ------------------------------------------------------------------
    # reopen()
    # ------------------------------------------------------------------

    def test_reopen_locked_period(self):
        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_LOCKED,
        )
        period.save(username=self.user.username)

        result = PeriodService.reopen(
            period,
            user=self.user,
        )

        self.assertEqual(
            result.status,
            AccountingPeriod.STATUS_OPEN,
        )
        self.assertIsNone(
            result.locked_at,
        )

    def test_reopen_closed_period_rejected(self):
        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_CLOSED,
        )
        period.save(username=self.user.username)

        with self.assertRaises(ValidationError):
            PeriodService.reopen(
                period,
                user=self.user,
            )

    def test_reopen_open_period_rejected(self):
        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_OPEN,
        )
        period.save(username=self.user.username)

        with self.assertRaises(ValidationError):
            PeriodService.reopen(
                period,
                user=self.user,
            )

    # ------------------------------------------------------------------
    # close()
    # ------------------------------------------------------------------

    def test_close_locked_period_creates_closing_transaction(self):
        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_LOCKED,
        )
        period.save(username=self.user.username)

        acc_bal_sn = AccountBalanceSnapshot(
            accounting_period=period,
            account=self.income_account,
            debit_amount=Decimal("0"),
            credit_amount=Decimal("1000"),
            balance_amount=Decimal("-1000"),
        )
        acc_bal_sn.save(username=self.user.username)

        result = PeriodService.close(
            period,
            user=self.user,
        )

        result.refresh_from_db()

        self.assertEqual(
            result.status,
            AccountingPeriod.STATUS_CLOSED,
        )

        self.assertIsNotNone(
            result.closing_transaction_id,
        )

        self.assertIsNotNone(
            result.closed_at,
        )

        closing_transaction = Transaction.objects.get(
            pk=result.closing_transaction_id
        )

        self.assertEqual(
            closing_transaction.legs.count(),
            2,
        )

    def test_close_reverses_income_expense_balances(self):
        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_LOCKED,
        )
        period.save(username=self.user.username)

        # Income has a credit balance of 1000.
        acc_bal_sn2 = AccountBalanceSnapshot(
            accounting_period=period,
            account=self.income_account,
            debit_amount=Decimal("0"),
            credit_amount=Decimal("1000"),
            balance_amount=Decimal("-1000"),
        )
        acc_bal_sn2.save(username=self.user.username)

        result = PeriodService.close(
            period,
            user=self.user,
        )

        closing_transaction = Transaction.objects.get(
            pk=result.closing_transaction_id
        )

        legs = list(
            closing_transaction.legs.all()
        )

        income_leg = next(
            leg
            for leg in legs
            if leg.account_id == self.income_account.id
        )

        retained_earnings_leg = next(
            leg
            for leg in legs
            if leg.account_id == self.cash_account.id
        )

        self.assertEqual(
            income_leg.amount.amount,
            Decimal("1000"),
        )

        self.assertEqual(
            retained_earnings_leg.amount.amount,
            Decimal("1000"),
            # Normalement -100 mais hordak gere tout en positif
        )

    def test_close_reverses_multiple_income_expense_balances(self):
        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_LOCKED,
        )
        period.save(username=self.user.username)

        acc_bal_sn3 = AccountBalanceSnapshot(
            accounting_period=period,
            account=self.income_account,
            debit_amount=Decimal("0"),
            credit_amount=Decimal("1500"),
            balance_amount=Decimal("-1500"),
        )
        acc_bal_sn3.save(username=self.user.username)

        acc_bal_sn4 = AccountBalanceSnapshot(
            accounting_period=period,
            account=self.expense_account,
            debit_amount=Decimal("500"),
            credit_amount=Decimal("0"),
            balance_amount=Decimal("500"),
        )
        acc_bal_sn4.save(username=self.user.username)

        result = PeriodService.close(
            period,
            user=self.user,
        )

        transaction = Transaction.objects.get(
            pk=result.closing_transaction_id
        )

        self.assertEqual(
            transaction.legs.count(),
            3,
        )

        total = sum(
            leg.amount.amount
            for leg in transaction.legs.all()
        )

        total = sum(
            (
                leg.debit.amount
                if leg.debit
                else -leg.credit.amount
            )
            for leg in transaction.legs.all()
        )

        self.assertEqual(
            total,
            Decimal("0"),
        )

    def test_close_skips_zero_balances(self):
        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_LOCKED,
        )
        period.save(username=self.user.username)

        acc_bal_sn5 = AccountBalanceSnapshot(
            accounting_period=period,
            account=self.income_account,
            debit_amount=Decimal("0"),
            credit_amount=Decimal("0"),
            balance_amount=Decimal("0"),
        )
        acc_bal_sn5.save(username=self.user.username)

        with self.assertRaises(ValidationError):
            PeriodService.close(
                period,
                user=self.user,
            )

    def test_close_requires_locked_period(self):
        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_OPEN,
        )
        period.save(username=self.user.username)

        with self.assertRaises(ValidationError):
            PeriodService.close(
                period,
                user=self.user,
            )

    def test_close_cannot_be_called_twice(self):
        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_LOCKED,
        )
        period.save(username=self.user.username)

        acc_bal_sn6 = AccountBalanceSnapshot(
            accounting_period=period,
            account=self.income_account,
            debit_amount=Decimal("0"),
            credit_amount=Decimal("1000"),
            balance_amount=Decimal("-1000"),
        )
        acc_bal_sn6.save(username=self.user.username)

        PeriodService.close(
            period,
            user=self.user,
        )

        period.refresh_from_db()

        with self.assertRaises(ValidationError):
            PeriodService.close(
                period,
                user=self.user,
            )

    def test_close_rejects_income_expense_retained_earnings_account(self):
        self.config.retained_earnings_account = self.income_account
        self.config.save(username=self.user.username)

        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_LOCKED,
        )
        period.save(username=self.user.username)

        with self.assertRaises(ValidationError):
            PeriodService.close(
                period,
                user=self.user,
            )

    def test_close_requires_deployment_configuration(self):
        DeploymentConfiguration.objects.all().delete()

        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_LOCKED,
        )
        period.save(username=self.user.username)

        with self.assertRaises(ValidationError):
            PeriodService.close(
                period,
                user=self.user,
            )

    def test_close_retained_earnings_account_type(self):

        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_LOCKED,
        )
        period.save(username=self.user.username)

        with self.assertRaises(ValidationError):
            PeriodService.close(
                period,
                user=self.user,
            )

    def test_no_deployment_config(self):
        DeploymentConfiguration.objects.all().delete()

        period = AccountingPeriod(
            name="2026-01",
            status=AccountingPeriod.STATUS_LOCKED,
        )
        period.save(username=self.user.username)

        with self.assertRaises(ValidationError):
            PeriodService.close(
                period,
                user=self.user,
            )
