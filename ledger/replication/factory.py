from ledger.replication.odoo import OdooAdapter
from ledger.replication.sage import SageAdapter


def get_adapter(target_system):

    if target_system == "odoo":
        return OdooAdapter()

    if target_system == "sage":
        return SageAdapter()

    raise ValueError(
        f"Unsupported target system {target_system}"
    )
