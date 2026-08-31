from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class AdapterResult:

    status: str

    external_reference: str = None

    rejection_reason: str = None


class ExternalLedgerAdapter(ABC):

    STATUS_SUCCESS = "success"
    STATUS_REJECTED = "rejected"
    STATUS_TIMEOUT = "timeout"

    @abstractmethod
    def send(
        self,
        ledger_entry,
        idempotency_key,
    ) -> AdapterResult:
        pass
