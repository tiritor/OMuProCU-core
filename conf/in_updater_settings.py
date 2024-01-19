from enum import Enum
from conf.grpc_settings import TCC_ADDRESS

from orchestrator_utils.third_party.licensed.sde_versions import SDEVersion


class AcceleratorTemplates(Enum):
    TOFINO_CENTER = "tofino"
    TOFINO_EDGE = "tofino-edge"
    BMv2 = "bmv2"


class DevInitModes(Enum):
    """
    Available device init modes which can be set to an accelerator.
    """
    FAST_RECONFIG = 0 # Default
    HITLESS = 1


ACCELERATOR_CONFIGURATION = {
    "tofino" : {
        "template": AcceleratorTemplates.TOFINO_EDGE,
        "enabled" : True,
        "address" : "localhost:50054",
        "dev_init_mode" : DevInitModes.FAST_RECONFIG,
        "initialization_method": SDEVersion.SDE_WITHOUT_SAL
        },
    "bmv2": {
        "template": AcceleratorTemplates.BMv2,
        "enabled" : False,
        "address" : TCC_ADDRESS,
        "dev_init_mode" : DevInitModes.FAST_RECONFIG,
        }
}
