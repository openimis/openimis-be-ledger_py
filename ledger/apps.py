from django.apps import AppConfig
import importlib
import inspect

MODULE_NAME = "ledger"

DEFAULT_CFG = {
    "gql_query_ledger_perms": ["131000"],
    "gql_mutation_post_entry_perms": ["131001"],
    "gql_mutation_manage_periods_perms": ["131002"],
}

CALCULATION_RULES = []


def read_all_calculation_rules():
    """function to read all calculation rules"""
    result = inspect.getmembers(
        importlib.import_module(
            "calculation_comores.calculation_rule"
        ),
        inspect.isclass,
    )

    for name, cls in result:
        if "calculation" in cls.__module__.split(".")[0]:
            CALCULATION_RULES.append(cls)
            cls.ready()


class LedgerConfig(AppConfig):
    name = MODULE_NAME

    gql_query_ledger_perms = []
    gql_mutation_post_entry_perms = []
    gql_mutation_manage_periods_perms = []

    def __load_config(self, cfg):
        for field in cfg:
            if hasattr(LedgerConfig, field):
                setattr(LedgerConfig, field, cfg[field])

    def ready(self):
        from core.models import ModuleConfiguration
        cfg = ModuleConfiguration.get_or_default(MODULE_NAME, DEFAULT_CFG)
        self.__load_config(cfg)
        # read_all_calculation_rules()
