

from orchestrator_utils.bfrt_proto import bfruntime_pb2


def create_path_bf_rt(base_path):
    return base_path  + "/bf-rt.json"


def create_path_context(base_path, profile_name):
    return base_path  + "/" + profile_name + "/context.json"


def create_path_tofino(base_path, profile_name, binary_name):
    return base_path  + "/" + profile_name + "/" + binary_name + ".bin"


# Tofino-1 uses pipes 0 and 2 as the external pipes while 1 and 3 are
# the internal pipes.
# Tofino-2 uses pipes 0 and 1 as the external pipes while 2 and 3 are
# the internal pipes.
arch = "tofino"
external_pipes = []
if arch == "tofino":
    external_pipes = [0,2]
    internal_pipes = [1,3]
elif arch == "tofino2":
    external_pipes = [0,1]
    internal_pipes = [2,3]
else:
    assert (arch == "tofino" or arch == "tofino2")


def generate_BFForwardingPipelineConfig_dict(name : str, bfruntime_info : str, profile_info_list: list):
    """
    Generate BFForwarding Pipeline configuration dictionary.
    """
    return {
        "p4_name" : name,
        "bfruntime_info": bfruntime_info,
        "profiles": profile_info_list
    }

def generate_BFForwardingPipelineConfig_proto_msg(name: str, bfruntime_info  : str, profile_info_list: list):
    """
    Generate BF Forwarding Pipeline configuration protobuf message.
    """
    config = bfruntime_pb2.ForwardingPipelineConfig(
        p4_name = name, 
        bfruntime_info = bfruntime_info,
    )
    for raw_profile in profile_info_list:
        profile = config.profiles.add()
        if isinstance(raw_profile, dict):
            profile.profile_name = raw_profile["profile_name"]
            profile.context = raw_profile["context"]
            profile.binary = raw_profile["binary"]
            profile.pipe_scope.extend(raw_profile["pipe_scope"])
        else:
            profile.profile_name = raw_profile.profile_name
            profile.context = raw_profile.context
            profile.binary = raw_profile.binary
            profile.pipe_scope.extend(raw_profile.pipe_scope)
    return config

def generate_BFProfileInfo_dict(profile_name, context, binary, pipe_scope: list):
    """
    Generate BF Profile Info configuration dictionary.
    """
    return {
        "profile_name" : profile_name,
        "context": context,
        "binary": binary,
        "pipe_scope" : pipe_scope
    }