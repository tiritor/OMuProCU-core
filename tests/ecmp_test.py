
import subprocess

import grpc
import jinja2

from orchestrator_utils.logger.logger import init_logger
from orchestrator_utils.bfrt_proto import bfruntime_pb2, bfruntime_pb2_grpc
from orchestrator_utils.third_party.licensed.sal import sal_services_pb2, sal_services_pb2_grpc

from updater.otf_management.otf_generator import OTFGenerator
from updater.accelerator.accelerator import Tofino

logger = init_logger("Template Test")
tofino_grpc_address = "localhost:50052"
tofino_sal_address = "localhost:50054"

OTFGenerator("inc_template/{}/".format("tofino-edge"), "inc_template/{}/".format("tofino-edge"), "hdr, meta, ig_intr_md").generate()
tofino : Tofino = Tofino("inc_template/tofino-edge/")
tofino.compile("")

tif_request = tofino.buildTIFRequest()
with open('tif_request.log', "w") as f:
    f.write(str(tif_request))


with grpc.insecure_channel(tofino_grpc_address) as channel:
    stub = bfruntime_pb2_grpc.BfRuntimeStub(channel)
    try:
        logger.info("Applying TIF...")
        resp : bfruntime_pb2.SetForwardingPipelineConfigResponse = stub.SetForwardingPipelineConfig(tif_request.bfFwdPipelineConfigRequest)
        logger.info("TIF applied")
    except grpc.RpcError as e:
        logger.exception(e, exc_info=True)


bfrt_python_config_file = "/home/tiritor/working_space/orchestrator/" + "conf/initializaton_files/tofino-edge.py" 
PATH_PREFIX = "/home/netlabadmin/"
BF_SDE_PATH = PATH_PREFIX + "BF/bf-sde-9.7.0/"
COMMAND = "run_bfshell.sh"
PARAMS = "-b"

logger.info("Initialize the hardware...")

logger.info("Sending Setup configuration to device...")
command = "{} {} {}".format(BF_SDE_PATH + COMMAND, PARAMS, bfrt_python_config_file)
logger.debug(command)
process : subprocess.CompletedProcess = subprocess.run(command, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
if process.returncode != 0:
    logger.error("Error while initialization hardware: {}".format(process.stderr))
    exit(-1)
else:
    logger.debug(process.stdout)
    logger.info("initialzation successful") 

logger.info("Initialize Ports")

ports_to_init = (17, 33, 34)

with grpc.insecure_channel(tofino_sal_address) as channel:
    sal_stub = sal_services_pb2_grpc.SwitchServiceStub(channel)
    for port in ports_to_init:
        resp : sal_services_pb2.Response =  sal_stub.AddPort(
            sal_services_pb2.PortInfo(
                portId = sal_services_pb2.PortId(
                    portNum = port,
                    lane = 0,
                ),
                portConf = sal_services_pb2.PortConfig(
                    speed = 6,
                    fec = 3,
                    an = 2,
                    enable = 1
                )
            )
        )
        logger.debug("InitHardware - Response : {}".format(resp.resp))

ecmp_link_test = {
    "lagGroups": {
        "lag_1": {
            "id": 2000,
            "memberbase": 200000,
            "dp_ports": [
                {
                    "portId": 44,  # SDE-Switch 1
                    # "portId": 45,  # SDE-Switch 3
                    "active": False
                },
                {
                    "portId": 144, # SDE-Switch 1 + 3
                    # "portId": 44, # SDE-Switch 3
                    "active": True
                }
            ]
        },
        "lag_2": {
            "id": 2001,
            "memberbase": 100000,
            "dp_ports": [
                {
                    "portId": 145,
                    "active": True
                }
            ]
        }
    },
    "nexthop_map": {
        "default" : 100,
        "lag_1" : 100,
        "lag_2" : 101
    },
    "ipv4_host_entries":[
        {
            "ip": "10.100.0.102",
            "nexthop_id": 101
        }                
    ],
    "arp_table_host_entries": [
        {
            "ip": "10.100.0.102",
            "nexthop_id": 101
        }
    ],
    "connections": [
        {
            "src_port": 17,
            "dest_port": 18,
            "src_dp_port": 44,
            "dest_dp_port": 45,
            "weight": 1,
            "enabled": True,
            "dest_device": "s2"
        },
        {
            "src_port": 18,
            "dest_port": 18,
            "src_dp_port": 45,
            "dest_dp_port": 45,
            "weight": 1,
            "enabled": False,
            "dest_device": "s4"
        },
        {
            "src_port": 33,
            "dest_port": 34,
            "src_dp_port": 144,
            "dest_dp_port": 145,
            "weight": 1,
            "enabled": True,
            "dest_device": "s4"
        },
        {
            "src_port": 34,
            "dest_port": 1,
            "src_dp_port": 144,
            "dest_dp_port": None,
            "weight": 1,
            "dest_device": "endpoint1"
        }
    ]
}

python_template_code = """
p4 = bfrt.tenant_inc.pipe
lag_ecmp = p4.TenantINCFrameworkIngress.lag_ecmp
lag_ecmp_sel = p4.TenantINCFrameworkIngress.lag_ecmp_sel
{% for lag in lagGroups.values() %}
mbr_base = {{ lag.memberbase }}
memb_port_ids = []
memb_port_active = []
{% for port in lag.dp_ports %}
port_{{ loop.index }} = mbr_base + {{ loop.index }}
lag_ecmp.entry_with_send(port_{{ loop.index }}, port={{ port["portId"] }}).push()
memb_port_ids.append(port_{{ loop.index }})
memb_port_active.append({{ port["active"] }})
{% endfor %}
lag_{{ loop.index }} = {{ lag.id }}
lag_ecmp_sel.entry(SELECTOR_GROUP_ID=lag_{{ loop.index }}, MAX_GROUP_SIZE=8, ACTION_MEMBER_ID=memb_port_ids, ACTION_MEMBER_STATUS=memb_port_active).push()
    
{% endfor %}
"""

environment = jinja2.Environment()
template = environment.from_string(python_template_code)
python_code = template.render(lagGroups=ecmp_link_test["lagGroups"])

with open("test_lag_change.py", "w") as f:
    f.write(python_code)