from .base import (
    ExternalLedgerAdapter
)


class OdooAdapter(ExternalLedgerAdapter):

    def send(
        self,
        ledger_entry,
        idempotency_key,
    ):
        raise NotImplementedError()
