from enum import Enum
from conf.grpc_settings import TCC_ADDRESS

class DevInitModes(Enum):
    """
    Available device init modes which can be set to an accelerator.
    """
    FAST_RECONFIG = 0 # Default
    HITLESS = 1

ACCELERATOR_CONFIGURATION = {
    "tofino" : {
        "enabled" : True,
        "address" : "localhost:50054",
        "dev_init_mode" : DevInitModes.FAST_RECONFIG,
        },
    "bmv2": {
        "enabled" : False,
        "address" : TCC_ADDRESS,
        "dev_init_mode" : DevInitModes.FAST_RECONFIG,
        }
}
