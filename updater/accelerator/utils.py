
# TODO: LICENSED

from random import random

from orchestrator_utils.bfrt_proto import bfruntime_pb2


def create_path_bf_rt(base_path):
    return base_path  + "/bf-rt.json"


def create_path_context(base_path, profile_name):
    return base_path  + "/" + profile_name + "/context.json"


def create_path_tofino(base_path, profile_name, binary_name):
    return base_path  + "/" + profile_name + "/" + binary_name + ".bin"


# def get_internal_port_from_external(ext_port):
#     pipe_local_port = port_to_local_port(ext_port)
#     int_pipe = internal_pipes[external_pipes.index(port_to_pipe(ext_port))]

#     if arch == "tofino":
#         # For Tofino-1 we are currently using a 1-to-1 mapping from external
#         # port to internal port so just replace the pipe-id.
#         return make_port(int_pipe, pipe_local_port)
#     elif arch == "tofino2":
#         # For Tofino-2 we are currently using internal ports in 400g mode so up
#         # to eight external ports (if maximum break out is configured) can map
#         # to the same internal port.
#         return make_port(int_pipe, pipe_local_port & 0x1F8)
#     else:
#         assert (arch == "tofino" or arch == "tofino2")

# def make_port(pipe, local_port):
#     """ Given a pipe and a port within that pipe construct the full port number. """
#     return (pipe << 7) | local_port

# def port_to_local_port(port):
#     """ Given a port return its ID within a pipe. """
#     local_port = port & 0x7F
#     assert (local_port < 72)
#     return local_port

# def port_to_pipe(port):
#     """ Given a port return the pipe it belongs to. """
#     local_port = port_to_local_port(port)
#     pipe = (port >> 7) & 0x3
#     assert (port == make_port(pipe, local_port))
#     return pipe

# def get_port_from_pipes(pipes):
#     ports = list()
#     for pipe in pipes:
#         ports = ports + swports_by_pipe[pipe]
#     return random.choice(ports)


# num_pipes = 4
# pipes = list(range(num_pipes))

# swports = []
# swports_by_pipe = {p:list() for p in pipes}
# for device, port, ifname in config["interfaces"]:
#     swports.append(port)
# swports.sort()
# for port in swports:
#     pipe = port_to_pipe(port)
#     swports_by_pipe[pipe].append(port)


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