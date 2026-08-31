import graphene
from django.test import TestCase
from ledger.replication.base import AdapterResult
from unittest.mock import patch
from ledger.replication.tasks import (
    replicate_entry
)
import core
from hordak.models import Transaction, Account
from ledger.models import (
    ExternalReplicationRecord,
    ManualReviewQueueItem,
    DeploymentConfiguration,
    Sequence,
    AccountingPeriod,
    LedgerJournal,
    LedgerEntryMeta
)
from ledger.services import ManualReviewService
from core.test_helpers import create_test_interactive_user
from ledger.schema import Query, Mutation
from types import SimpleNamespace


class PostingSignalsTest(TestCase):

    def setUp(self):
        self.user = create_test_interactive_user()
        self.context = SimpleNamespace(
            user=self.user
        )

        self.account = Account.objects.create(
            code="4002",
            full_code="4002",
            name="Cash 2"
        )

        # Create sequence
        self.sequence = Sequence(
            code="GLMETA",
            name="General Ledger Meta",
        )
        self.sequence.save(username=self.user.username)

        # Create accounts
        self.cash_account = Account.objects.create(
            code="1002",
            full_code="1002",
            name="Cash",
        )
        self.expense_account = Account.objects.create(
            code="6002",
            full_code="6002",
            name="Expense",
        )

        # Create journal
        self.journal = LedgerJournal(
            code="GENERAL_META",
            name="General Journal Meta",
            sequence_id=self.sequence,
            default_credit_account_id=self.cash_account,
            default_debit_account_id=self.expense_account,
        )
        self.journal.save(username=self.user.username)

        self.period = AccountingPeriod(
            name="2026-02",
            code="2026-02",
            status=AccountingPeriod.STATUS_OPEN,
        )
        self.period.save(username=self.user.username)

        transaction = Transaction.objects.create()
        self.ledger_entry = LedgerEntryMeta(
            transaction=transaction,
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="claim_payment",
            source_event_reference="META-001",
        )

        self.ledger_entry.save(username=self.user.username)

        transaction2 = Transaction.objects.create()
        self.correcting_entry = LedgerEntryMeta(
            transaction=transaction2,
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="claim_payment",
            source_event_reference="META-002",
        )
        self.correcting_entry.save(username=self.user.username)

        transaction3 = Transaction.objects.create()
        self.ledger_entry2 = LedgerEntryMeta(
            transaction=transaction3,
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="claim_payment",
            source_event_reference="META-003",
        )
        self.ledger_entry2.save(username=self.user.username)

        transaction4 = Transaction.objects.create()
        self.ledger_entry3 = LedgerEntryMeta(
            transaction=transaction4,
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="claim_payment",
            source_event_reference="META-004",
        )
        self.ledger_entry3.save(username=self.user.username)

        transaction5 = Transaction.objects.create()
        self.ledger_entry4 = LedgerEntryMeta(
            transaction=transaction5,
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="claim_payment",
            source_event_reference="META-005",
        )
        self.ledger_entry4.save(username=self.user.username)

        transaction6 = Transaction.objects.create()
        self.ledger_entry5 = LedgerEntryMeta(
            transaction=transaction6,
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="claim_payment",
            source_event_reference="META-006",
        )
        self.ledger_entry5.save(username=self.user.username)

        transaction6 = Transaction.objects.create()
        self.ledger_entry6 = LedgerEntryMeta(
            transaction=transaction6,
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="claim_payment",
            source_event_reference="META-006",
        )
        self.ledger_entry6.save(username=self.user.username)

    def test_adapter_success_shape(self):

        result = AdapterResult(
            status="success",
            external_reference="ODOO-123"
        )

        self.assertEqual(
            result.status,
            "success"
        )
        self.assertEqual(
            result.external_reference,
            "ODOO-123"
        )
        self.assertTrue(
            result.rejection_reason is None
        )

    def test_adapter_rejected_shape(self):

        result = AdapterResult(
            status="rejected",
            rejection_reason="Account not found"
        )

        self.assertEqual(
            result.status,
            "rejected"
        )

        self.assertEqual(
            result.rejection_reason,
            "Account not found"
        )

        self.assertTrue(
            result.external_reference is None
        )

    def test_adapter_timeout_shape(self):

        result = AdapterResult(
            status="timeout"
        )

        self.assertEqual(
            result.status,
            "timeout"
        )
        self.assertTrue(
            result.external_reference is None
        )

        self.assertTrue(
            result.rejection_reason is None
        )

    @patch("ledger.replication.tasks.get_adapter")
    def test_successful_replication_marks_record_succeeded(
        self,
        mock_get_adapter,
    ):

        adapter = mock_get_adapter.return_value

        adapter.send.return_value = AdapterResult(
            status="success",
            external_reference="ODOO-999"
        )

        replicate_entry(
            ledger_entry_id=self.ledger_entry.id,
            target_system="odoo",
            username=self.user.username
        )

        record = ExternalReplicationRecord.objects.filter(
            ledger_entry=self.ledger_entry,
            is_deleted=False
        ).first()

        self.assertEqual(
            record.status,
            ExternalReplicationRecord.STATUS_SUCCEEDED
        )

        self.assertEqual(
            record.external_reference,
            "ODOO-999"
        )

        self.assertEqual(
            record.attempt_count,
            1
        )

    @patch("ledger.replication.tasks.get_adapter")
    def test_rejected_replication_creates_review_queue_item(
        self,
        mock_get_adapter,
    ):

        adapter = mock_get_adapter.return_value

        adapter.send.return_value = AdapterResult(
            status="rejected",
            rejection_reason="Account does not exist"
        )

        replicate_entry(
            ledger_entry_id=self.ledger_entry4.id,
            target_system="odoo",
            username=self.user.username
        )

        record = ExternalReplicationRecord.objects.filter(
            ledger_entry=self.ledger_entry4,
            is_deleted=False
        ).first()

        review_item = ManualReviewQueueItem.objects.filter(
            replication_record=record
        ).first()

        self.assertEqual(
            record.status,
            ExternalReplicationRecord.STATUS_REJECTED
        )

        self.assertEqual(
            record.rejection_reason,
            "Account does not exist"
        )

        self.assertIsNotNone(
            review_item.pk
        )

        self.assertIsNone(
            review_item.resolved_at
        )

        self.assertIsNone(
            review_item.resolved_by_transaction
        )

    def test_resolve_review_item_links_correcting_transaction(
        self,
    ):
        record = ExternalReplicationRecord(
            ledger_entry=self.ledger_entry,
            target_system="odoo",
            idempotency_key="abc",
            status=ExternalReplicationRecord.STATUS_REJECTED,
            rejection_reason="Bad account"
        )
        record.save(username=self.user.username)

        review_item = ManualReviewQueueItem(
            replication_record=record
        )
        review_item.save(username=self.user.username)

        ManualReviewService.resolve(
            review_item=review_item,
            correcting_entry=self.correcting_entry,
            note="Fixed account mapping",
            user=self.user,
        )

        review_item.refresh_from_db()

        self.assertIsNotNone(
            review_item.resolved_at
        )

        self.assertEqual(
            review_item.resolved_by_transaction,
            self.correcting_entry.transaction
        )

        self.assertEqual(
            review_item.resolution_note,
            "Fixed account mapping"
        )

        query = """
        query {
        manualReviewQueue {
            edges {
            node {
                id
                resolutionNote
            }
            }
        }
        }
        """
        schema = graphene.Schema(
            query=Query,
        )

        result = schema.execute(
            query,
            context_value=self.context
        )

        assert result.errors is None

        edges = result.data["manualReviewQueue"]["edges"]

        assert len(edges) == 1

    def test_create_deployment_config(self):
        core.async_mutations = False
        mutation = """
            mutation createDeploymentConfiguration($input: CreateDeploymentConfigurationMutationInput!) {
                createDeploymentConfiguration(input: $input) {
                    clientMutationId
                    internalId
                }
            }
        """

        variables = {
            "input": {
                "clientMutationId": "ca18e62f-5f29-4158-bec8-042b9b935727",
                "clientMutationLabel": "Créer une configuration",
                "operatingMode": "local_only",
                "currencyCode": "XAF",
                "retainedEarningsAccountId": str(self.account.uuid)
            }
        }

        schema = graphene.Schema(
            query=Query,
            mutation=Mutation,
        )

        result = schema.execute(
            mutation,
            variable_values=variables,
            context_value=self.context
        )

        assert result.errors is None
        config = DeploymentConfiguration.objects.filter(
            retained_earnings_account=self.account).order_by("-id").first()

        assert config.operating_mode == "local_only"

    def test_create_manual_review(self):
        core.async_mutations = False
        transaction2 = Transaction.objects.create()
        ledger_entry = LedgerEntryMeta(
            transaction=transaction2,
            journal=self.journal,
            accounting_period=self.period,
            source_event_type="claim_payment",
            source_event_reference="META-002",
        )
        ledger_entry.save(username=self.user.username)

        record = ExternalReplicationRecord(
            ledger_entry=ledger_entry,
            target_system="odoo",
            idempotency_key="abc",
            status=ExternalReplicationRecord.STATUS_REJECTED,
            rejection_reason="Bad account"
        )
        record.save(username=self.user.username)
        mutation = """
            mutation ManualReviewItemMutation($input: ManualReviewItemMutationInput!) {
                resolveManualReview(input: $input) {
                    clientMutationId
                    internalId
                }
            }
        """

        variables = {
            "input": {
                "clientMutationId": "cb18e62f-5f29-4158-bec8-042b9b935727",
                "clientMutationLabel": "Créer une revue manuelle",
                "replicationRecordId": str(record.id),
                "resolvedByTransactionId": str(transaction2.uuid),
                "resolutionNote": "Test"
            }
        }

        schema = graphene.Schema(
            query=Query,
            mutation=Mutation,
        )

        result = schema.execute(
            mutation,
            variable_values=variables,
            context_value=self.context
        )

        assert result.errors is None
        item = ManualReviewQueueItem.objects.get(replication_record=record.id)

        assert item.resolution_note == "Test"

    @patch("ledger.replication.tasks.get_adapter")
    def test_timeout_after_max_attempts_marks_unconfirmed(
        self,
        mock_get_adapter,
    ):

        adapter = mock_get_adapter.return_value

        adapter.send.return_value = AdapterResult(
            status="timeout"
        )

        record = ExternalReplicationRecord(
            ledger_entry=self.ledger_entry,
            target_system="odoo",
            idempotency_key=f"odoo:{self.ledger_entry.transaction.uuid}",
            attempt_count=3,
        )
        record.save(username=self.user.username)

        replicate_entry(
            ledger_entry_id=self.ledger_entry.id,
            target_system="odoo",
            username=self.user.username,
        )

        record.refresh_from_db()

        self.assertEqual(
            record.status,
            ExternalReplicationRecord.STATUS_UNCONFIRMED,
        )

        self.assertEqual(
            record.attempt_count,
            3,
        )

        review = ManualReviewQueueItem.objects.filter(
            replication_record=record,
            is_deleted=False,
        ).first()

        self.assertIsNotNone(review)

        self.assertNotEqual(
            record.status,
            ExternalReplicationRecord.STATUS_REJECTED,
        )

    @patch("ledger.replication.tasks.get_adapter")
    def test_idempotency_prevents_duplicate_external_posting(
        self,
        mock_get_adapter,
    ):

        adapter = mock_get_adapter.return_value

        adapter.send.return_value = AdapterResult(
            status="success",
            external_reference="ODOO-123"
        )

        replicate_entry(
            ledger_entry_id=self.ledger_entry.id,
            target_system="odoo",
            username=self.user.username,
        )

        replicate_entry(
            ledger_entry_id=self.ledger_entry.id,
            target_system="odoo",
            username=self.user.username,
        )

        record = ExternalReplicationRecord.objects.get(
            ledger_entry=self.ledger_entry,
            target_system="odoo",
        )

        self.assertEqual(
            record.status,
            ExternalReplicationRecord.STATUS_SUCCEEDED,
        )

        self.assertEqual(
            adapter.send.call_count,
            1,
        )

        self.assertEqual(
            ExternalReplicationRecord.objects.filter(
                ledger_entry=self.ledger_entry,
                target_system="odoo",
                is_deleted=False,
            ).count(),
            1,
        )
        self.assertEqual(
            record.idempotency_key,
            f"odoo:{self.ledger_entry.transaction.uuid}",
        )
