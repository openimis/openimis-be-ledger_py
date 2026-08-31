from .base import (
    ExternalLedgerAdapter
)


class SageAdapter(ExternalLedgerAdapter):

    def send(
        self,
        ledger_entry,
        idempotency_key,
    ):
        raise NotImplementedError()
