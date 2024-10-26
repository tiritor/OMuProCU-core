
import ast
from concurrent import futures
import ipaddress
import json
from multiprocessing import Process
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Union

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
import jinja2

from orchestrator_utils.til import orchestrator_msg_pb2_grpc, orchestrator_msg_pb2
from orchestrator_utils.til.orchestrator_msg_pb2 import TIFControlRequest, TIFControlResponse
from orchestrator_utils.til.tif_control_pb2 import DpPort, Lag, RoutingTableConfiguration
from orchestrator_utils.bfrt_proto import bfruntime_pb2, bfruntime_pb2_grpc
from orchestrator_utils.logger.logger import init_logger
from orchestrator_utils.tools.accelerator_type import find_python_acceleratorTypeEnum
from orchestrator_utils.third_party.licensed.sde_versions import SDEVersion
from orchestrator_utils.p4.v1 import p4runtime_pb2, p4runtime_pb2_grpc
from orchestrator_utils.p4.tmp import p4config_pb2
from orchestrator_utils.p4.bmv2 import helper as p4info_help

from conf.grpc_settings import TIF_ADDRESS, maxMsgLength
from conf.in_updater_settings import ACCELERATOR_CONFIGURATION, AcceleratorTemplates
from conf.initializaton_files.port_conf import DEFAULT_PORTS

class TIFUpdateException(Exception):
    """Exception raised for errors during TIF update.

    Attributes:
        message -- explanation of the error
    """
    pass

class TIFControlException(Exception):
    """
    Exception raised for TIF control errors.

    Attributes:
        message -- explanation of the error
    """
    pass

def is_valid_mac(address):
    """
    Check if the provided string is a valid MAC address.
    """
    # Regular expression to match the MAC address
    mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')
    return bool(mac_pattern.match(address))

def is_valid_ipv4(address):
    try:
        ipaddress.IPv4Address(address)
        return True
    except ValueError:
        return False


class TIFUpdater(Process, orchestrator_msg_pb2_grpc.TIFUpdateCommunicatorServicer, orchestrator_msg_pb2_grpc.TIFControlCommunicatorServicer):
    """
    The Tenant INC Framework Updater process. This handles the accelerator code and configuration update as well as the management of the accelerator.
    """
    tofino_grpc_address = "localhost:50052"
    bmv2_grpc_address = "localhost:9000" # If using BMv2, the GRPC port must be set to this or change properly!
    applied_forwarding_pipeline_configs = {}
    applied_table_entries = {}
    scheduled_table_entries = {}
    management_tenant_id = 0

    def __init__(self, device_name, group=None, target=None, name=None, args=(), kwargs={}, daemon=None, bfrt_template_path = "conf/initializaton_files/templates/") -> None:
        super().__init__(group, target, name, args, kwargs, daemon=daemon)
        self.grpc_server = grpc.server(futures.ThreadPoolExecutor(10), options=[('grpc.max_send_message_length', maxMsgLength), ('grpc.max_receive_message_length', maxMsgLength)])
        orchestrator_msg_pb2_grpc.add_TIFUpdateCommunicatorServicer_to_server(self, self.grpc_server)
        orchestrator_msg_pb2_grpc.add_TIFControlCommunicatorServicer_to_server(self, self.grpc_server)
        self.grpc_server.add_insecure_port(TIF_ADDRESS)
        self.logger = init_logger(self.__class__.__name__)
        for accelerator, configuration in ACCELERATOR_CONFIGURATION.items():
            if configuration["enabled"] :
                self.applied_forwarding_pipeline_configs[accelerator] = None
        
        self.bfrt_templates_location = bfrt_template_path
        self.switch_config_path = "conf/switch-configuration.json"
        if os.path.exists(self.switch_config_path):
            self.load_switch_configuration()
        else:
            self.switch_configuration = {
                "lag_ecmp_groups" : {},
                "nexthop_map": {},
                "ipv4_host_entries": {},
                "arp_table_host_entries": {},
                "tenant_rules": {},
            }
        if device_name is not None and self.switch_configuration["initialized_ports"] is None:
            self.switch_configuration["initialized_ports"] = DEFAULT_PORTS[device_name]

    @staticmethod
    def _build_tenant_cnf_id(tenant_id, tenant_func_name):
        """
        Build a tenant configuration ID.

        Parameters:
        -----------
        tenant_id : int
            The tenant ID.
        tenant_func_name : str
            The tenant function name.

        Returns:
        --------
        str: The tenant configuration ID.
        """
        return str(tenant_id) + "_" + tenant_func_name

    def run(self) -> None:
        super().run()
        self.running = True
        self.grpc_server.start()
        self.logger.info("TIFUpdater started")
    
    def terminate(self) -> None:
        self.running = False
        self.grpc_server.stop(10)
        self.logger.info("Got Terminate. Stopping GRPC server.")

    def save_switch_configuration(self):
        """
        Save the switch configuration to a file.
        """
        with open(self.switch_config_path, "w") as f:
            json.dump(self.switch_configuration, f, indent=2)

    def load_switch_configuration(self):
        """
        Load the switch configuration from a file.
        """
        with open(self.switch_config_path, "r") as f:
            self.switch_configuration = json.load(f)

    def pull_config(self, acceleratorType : orchestrator_msg_pb2.AcceleratorType, address = None):
            """
            Pull Forwarding Pipeline Config from the given accelerator.

            Parameters:
            -----------
            acceleratorType : AcceleratorType
                accelerator type from where the config should be pulled
            address : str, optional
                GRPC address from where configuration should be pulled.

            Raises:
            -------
            TIFUpdateException:
                If no valid accelerator type is specified.
            """
            if acceleratorType == orchestrator_msg_pb2.ACCELERATOR_TYPE_TNA:
                fwd_pipeline_conf = self.pull_ForwardingPipelineConfig_from_tofino(address)
                self.applied_forwarding_pipeline_configs[find_python_acceleratorTypeEnum(acceleratorType).value] = fwd_pipeline_conf
            elif acceleratorType == orchestrator_msg_pb2.ACCELERATOR_TYPE_BMV2:
                fwd_pipeline_conf = self.pull_ForwardingPipelineConfig_from_bmv2(address)
                self.applied_forwarding_pipeline_configs[find_python_acceleratorTypeEnum(acceleratorType).value] = fwd_pipeline_conf
            else:
                raise TIFUpdateException("No valid accelerator type specified!")

    def GetTIFCode(self, request, context):
        """
        GPRC GetTIFCode implementation for TIFUpdateCommunicator which is used for returning applied TIF for a specified accelerator hardware.
        """
        if request.acceleratorType == orchestrator_msg_pb2.ACCELERATOR_TYPE_TNA:
            try:
                fwd_pipeline_confs = self.pull_ForwardingPipelineConfig_from_tofino()
                self.applied_forwarding_pipeline_configs[find_python_acceleratorTypeEnum(request.acceleratorType).value] = fwd_pipeline_confs
                # TODO: Multiple Forwarding Pipeline Config are not supported
                return orchestrator_msg_pb2.TIFResponse(
                    status= 200,
                    message = "TIF pulled successfully",
                    bfFwdPipelineConfig = self.convert_to_bfruntime_fwd_pipeline_conf_message(fwd_pipeline_confs)
                )
            except KeyError as err:
                return orchestrator_msg_pb2.TIFResponse(
                    status = 404,
                    message = "TIF is not available on Chip"
                )
            except Exception as ex:
                return orchestrator_msg_pb2.TIFResponse(
                    status = 500,
                    message = "Error while pulling TIF:" + ex.__str__()
                )
        elif request.acceleratorType == orchestrator_msg_pb2.ACCELERATOR_TYPE_BMV2:
            try:
                fwd_pipeline_confs = self.pull_ForwardingPipelineConfig_from_bmv2()
                self.applied_forwarding_pipeline_configs[find_python_acceleratorTypeEnum(request.acceleratorType).value] = fwd_pipeline_confs
                # TODO: Multiple Forwarding Pipeline Config are not supported
                return orchestrator_msg_pb2.TIFResponse(
                    status= 200,
                    message = "TIF pulled successfully",
                    bmv2ForwardingPipelineConfig = self.convert_to_bfruntime_fwd_pipeline_conf_message(fwd_pipeline_confs)
                )
            except KeyError as err:
                return orchestrator_msg_pb2.TIFResponse(
                    status = 404,
                    message = "TIF is not available on Chip"
                )
            except Exception as ex:
                return orchestrator_msg_pb2.TIFResponse(
                    status = 500,
                    message = "Error while pulling TIF:" + ex.__str__()
                )
        else:
            return orchestrator_msg_pb2.TIFResponse(
                status = 400,
                message = "Accelerator Type was unspecified or invalid! Please provide a valid type!"
            )

    def UpdateTIFCode(self, request, context):
        """
        GPRC UpdateTIFCode implementation for TIFUpdateCommunicator which is used for updating or applying TIF to a accelerator hardware.
        """
        try:
            acc_type = ""
            if request.acceleratorType == orchestrator_msg_pb2.ACCELERATOR_TYPE_TNA:
                acc_type = "TNA"
                self.send_SetForwardingPipelineConfig_request_to_tofino(request.bfFwdPipelineConfigRequest)
            elif request.acceleratorType == orchestrator_msg_pb2.ACCELERATOR_TYPE_BMV2:
                acc_type = "BMv2"
                self.send_SetForwardingPipelineConfig_request_to_bmv2(request)
            else:
                return orchestrator_msg_pb2.TIFResponse(
                    status = 404,
                    message = "Accelerator type unknown or specified."
                )
            return orchestrator_msg_pb2.TIFResponse(
                status = 200,
                message= "TIF to {} applied.".format(acc_type)
            )
            
        except Exception as ex:
            return orchestrator_msg_pb2.TIFResponse(
                status=500,
                message= "Error while updating TIF: {}".format(ex.__str__())
            )

    def InitializeHardware(self, request, context):
        """
        GPRC InitializeHardware implementation for TIFUpdateCommunicator which is used for initializing the hardware after TIF was applied or updated.
        """
        if request.acceleratorType == orchestrator_msg_pb2.ACCELERATOR_TYPE_TNA:
            ### Hardware initialization must be done (e.g., using SAL or similar frameworks), since it will reset if the config is changed.
            ### Due to the software license of the abstraction layer this is omitted.
            if SDEVersion.SDE_WITH_SAL == ACCELERATOR_CONFIGURATION["tofino"]["initialization_method"]: 
               return orchestrator_msg_pb2.TIFResponse(
                    status=200,
                    message="Hardware initialized."
                )
            elif SDEVersion.SDE_WITHOUT_SAL == ACCELERATOR_CONFIGURATION["tofino"]["initialization_method"]:
                try:
                    self._run_port_setup()
                    self._run_tif_initialization_setup_script()
                except Exception as ex:
                    self.logger.exception(ex)
                    return TIFControlResponse(
                        status=500,
                        message="Error while initialize ports: {}".format(str(ex))
                    )
                self.logger.debug("Initialized ports successful.")
                return TIFControlResponse(
                    status=200,
                    message="Initialized ports successful."
                )
            else:
                return TIFControlResponse(
                    status=500,
                    message="Unsupported Hardware initialization method."
                )
        elif request.acceleratorType == orchestrator_msg_pb2.ACCELERATOR_TYPE_BMV2:
            # No need to initialize hardware if using BMv2
            pass
        else:
            return orchestrator_msg_pb2.TIFControlResponse(
                status = 404,
                message =  "Accelerator type unkmown or unspecified."
            )

    def GetTableEntries(self, request: TIFControlRequest, context):
        """
        Get the table entries from the switch configuration.

        Parameters:
        -----------
        request (TIFControlRequest): 
            The control request object.
        context: 
            The context object.

        Returns:
        --------
        TIFControlResponse: The control response object containing the table entries.
        """
        try:
            if request.tenantMetadata.tenantId != self.management_tenant_id:
                tenant_cnf_id = self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)
                if tenant_cnf_id in self.switch_configuration["tenant_rules"].keys():
                    return TIFControlResponse(
                        status=200,
                        message="Got Table Entries successfully",
                        runtimeRules=[ParseDict(rule, RoutingTableConfiguration()) for rule in self.switch_configuration["tenant_rules"][tenant_cnf_id]]
                    )
            else:   
                return TIFControlResponse(
                    status=200,
                    message="Got Table Entries successfully",
                    arpHostEntries=[ParseDict({"key": entry["ip"], "nextHopId": entry["nexthop_id"]}, RoutingTableConfiguration()) for entry in self.switch_configuration["arp_table_host_entries"]],
                    ipv4HostEntries=[ParseDict({"key": entry["ip"], "nextHopId": entry["nexthop_id"]}, RoutingTableConfiguration()) for entry in self.switch_configuration["ipv4_host_entries"]],
                    nexthopMapEntries=[ParseDict({"key": key, "nextHopId": value}, RoutingTableConfiguration()) for key, value in self.switch_configuration["nexthop_map"].items()],
                )
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status=500,
                message="Error while getting table entries: {}".format(str(ex))
            )

    def AddTableEntries(self, request : TIFControlRequest, context):
        """
        Add table entries to the switch configuration.

        Parameters:
        -----------
        request (TIFControlRequest): 
            The request object containing the table entries.
        context: 
            The context object for the gRPC request.

        Returns:
        --------
        TIFControlResponse: The response object indicating the status of the operation.
        """
        def find_ip_in_entries(entry_list, value):
            """
            Find the index of an IP address in a list of entries.

            Parameters:
            -----------
            entry_list (list): 
                The list of entries to search.
            value: 
                The IP address to find.

            Returns:
            --------
            int: The index of the IP address in the list, or -1 if not found.
            """
            for i, entry in enumerate(entry_list):
                if entry["ip"] == value:
                    return i
            return -1

        try:
            tables = {}
            # The method assumes the checks against access control are done before this point.
            if request.runtimeRules:
                if self.switch_configuration["tenant_rules"].get(self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)) is None:
                    self.switch_configuration["tenant_rules"][self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)] = []
                for rule in request.runtimeRules:
                    rule = MessageToDict(rule)
                    rule["matches"] = ast.literal_eval(rule["matches"][0])
                    if isinstance(rule["matches"], str):
                        rule["matches"] = ast.literal_eval(rule["matches"])
                    if len(rule["matches"]) != 0:
                        for key_name, key in rule["matches"].items():
                            if is_valid_mac(str(key)):
                                rule["matches"][key_name] = "'{}'".format(key)
                            elif is_valid_ipv4(str(key)):
                                rule["matches"][key_name] = "'{}'".format(key)
                    rule["actionParams"] = ast.literal_eval(rule["actionParams"][0])
                    if isinstance(rule["actionParams"], str):
                        rule["actionParams"] = ast.literal_eval(rule["actionParams"])
                    if len(rule["actionParams"]) != 0:
                        for key_name, key in rule["actionParams"].items():
                            if is_valid_mac(str(key)):
                                rule["actionParams"][key_name] = "'{}'".format(key)
                            elif is_valid_ipv4(str(key)):
                                rule["actionParams"][key_name] = "'{}'".format(key)
                    self.switch_configuration["tenant_rules"][self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)].append(rule)
                    if self.applied_table_entries.get("tenant_rules") is not None:
                        if rule not in self.applied_table_entries["tenant_rules"]:
                            tables["tenant_rules"].append(rule)
                    else:
                        self.applied_table_entries["tenant_rules"] = []
                        tables["tenant_rules"] = [rule]
            if request.arpHostEntries:
                for entry in request.arpHostEntries:
                    index = find_ip_in_entries(self.switch_configuration["arp_table_host_entries"], entry.key)
                    if index == -1 :
                        self.switch_configuration["arp_table_host_entries"].append({"ip": entry.key, "nexthop_id": entry.nextHopId})
                        if self.applied_table_entries.get("arp_table_host_entries") is not None:
                            if {"ip": entry.key, "nexthop_id": entry.nextHopId} not in self.applied_table_entries["arp_table_host_entries"]:
                                tables["arp_table"].append((f'"{entry.key}"', entry.nextHopId))
                        else:
                            tables["arp_table"] = [(f'"{entry.key}"', entry.nextHopId)]
                    else:
                        return TIFControlResponse(
                            status= 400
                        )
            if request.ipv4HostEntries:
                for entry in request.ipv4HostEntries:
                    index = find_ip_in_entries(self.switch_configuration["ipv4_host_entries"], entry.key)
                    if index == -1 :
                        self.switch_configuration["ipv4_host_entries"].append({"ip": entry.key, "nexthop_id": entry.nextHopId})
                        if self.applied_table_entries.get("ipv4_host_entries") is not None:
                            if {"ip": entry.key, "nexthop_id": entry.nextHopId} not in self.applied_table_entries["ipv4_host_entries"]:
                                tables["ipv4_host"].append((f'"{entry.key}"', entry.nextHopId))
                        else:
                            tables["ipv4_host"] = [(f'"{entry.key}"', entry.nextHopId)]
                    else:
                        return TIFControlResponse(
                            status= 400
                        )
            if request.nexthopMapEntries:
                for entry in request.nexthopMapEntries:
                    if entry.key not in self.switch_configuration["nexthop_map"].keys():
                        self.switch_configuration["nexthop_map"][entry.key] = entry.nextHopId
                        if self.applied_table_entries.get("nexthop_map") is not None:
                            if entry.key not in self.applied_table_entries["nexthop_map"]:
                                tables["nexthop"].append((f'"{entry.key}"', entry.nextHopId))
                        else:
                            tables["nexthop"] = [(f'"{entry.key}"', entry.nextHopId)]
                    else:
                        return TIFControlResponse(
                            status= 400
                        )
            bfrt_python_code = self._build_table_entry_bfrt_python_code("add", tables)
            self.logger.debug("BFRuntime Python Code: {}".format(bfrt_python_code))
            self._run_bfshell_bfrt_python(bfrt_python_code)
            if request.runtimeRules:
                self.applied_table_entries.update({"tenant_rules": {self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName): tables["tenant_rules"]},}) # Add the applied tenant table entries to the applied table entries list.
            if "tenant_rules" in tables.keys():
                tables.pop("tenant_rules")
            self.applied_table_entries.update(tables) # Add the other applied table entries to the applied table entries list.
            self.save_switch_configuration()
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status= 500,
                message="Error while adding table entries: {}".format(str(ex))
            )
        return TIFControlResponse(
            status =  200,
        )
    
    def UpdateTableEntries(self, request : TIFControlRequest, context):
        """
        Updates the table entries in the switch configuration based on the provided request.

        Parameters:
        -----------
        request (TIFControlRequest): 
            The request containing the table entries to be updated.
        context: 
            The context of the request.

        Returns:
        --------
        TIFControlResponse: The response indicating the status of the update operation.
        """
        def check_if_equal(rule1, rule2):
            """
            Check if two rules are equal.

            Parameters:
            -----------
            rule1 (dict): 
                The first rule to compare.
            rule2 (dict): 
                The second rule to compare.

            Returns:
            --------
            bool: True if the rules are equal, False otherwise.
            """
            return rule1["ip"] == rule2["ip"] and rule1["nexthop_id"] == rule2["nexthop_id"]
        
        def find_ip_in_entries(entry_list, value):
            """
            Finds the index of an IP address in a list of entries.

            Parameters:
            -----------
            entry_list (list): 
                The list of entries to search in.
            value: 
                The IP address to find.

            Returns:
            --------
            int: The index of the IP address in the list, or -1 if not found.
            """
            for i, entry in enumerate(entry_list):
                if entry["ip"] == value:
                    return i
            return -1

        def get_index_of_rule(rule, table):
            """
            Get the index of a rule in a table.

            Parameters:
            -----------
            rule (dict): 
                The rule to find.
            table (list): 
                The table to search in.

            Returns:
            --------
            int: The index of the rule in the table, or -1 if not found.
            """
            for i, r in enumerate(table):
                if r["table"] == rule["table"] and r["matches"] == rule["matches"] :
                    return i
            return -1

        def search_rule(rule, table):
            """
            Search for a rule in a table.

            Parameters:
            -----------
            rule (dict): 
                The rule to search for.
            table (list): 
                The table to search in.

            Returns:
            --------
            dict: The rule found in the table, or None if not found.
            """
            for r in table:
                if r["table"] == rule["table"] and r["matches"] == rule["matches"]:
                    return r
            return None

        tables = {}
        try:
            if request.runtimeRules:
                for rule in request.runtimeRules:
                    rule = MessageToDict(rule)
                    rule["matches"] = ast.literal_eval(rule["matches"][0])
                    if isinstance(rule["matches"], str):
                        rule["matches"] = ast.literal_eval(rule["matches"])
                    if len(rule["matches"]) != 0:
                        for key_name, key in rule["matches"].items():
                            if is_valid_mac(str(key)):
                                rule["matches"][key_name] = "'{}'".format(key)
                            elif is_valid_ipv4(str(key)):
                                rule["matches"][key_name] = "'{}'".format(key)
                    rule["actionParams"] = ast.literal_eval(rule["actionParams"][0])
                    if isinstance(rule["actionParams"], str):
                        rule["actionParams"] = ast.literal_eval(rule["actionParams"])
                    if len(rule["actionParams"]) != 0:
                        for key_name, key in rule["actionParams"].items():
                            if is_valid_mac(str(key)):
                                rule["actionParams"][key_name] = "'{}'".format(key)
                            elif is_valid_ipv4(str(key)):
                                rule["actionParams"][key_name] = "'{}'".format(key)
                    tenant_cnf_id = self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)
                    if tenant_cnf_id in self.switch_configuration["tenant_rules"].keys():
                        index = get_index_of_rule(rule, self.switch_configuration["tenant_rules"][tenant_cnf_id])
                        if index == -1:
                            return TIFControlResponse(
                                status= 400,
                                message="Error while updating table entries: Entry {} in table {} does not exist!".format(rule, "tenant_rules")
                            )
                        else:
                            self.switch_configuration["tenant_rules"][tenant_cnf_id][index] = rule
                            if self.applied_table_entries.get("tenant_rules") is not None:
                                if search_rule(rule, self.applied_table_entries["tenant_rules"][tenant_cnf_id]) is not None:
                                    if tables.get("tenant_rules") is not None:
                                        tables["tenant_rules"].append(rule)
                                    else:
                                        tables["tenant_rules"] = [rule]
                            else:
                                tables["tenant_rules"] = [rule]
            if request.arpHostEntries:
                for entry in request.arpHostEntries:
                    index = find_ip_in_entries(self.switch_configuration["arp_table_host_entries"], entry.key)
                    if index == -1 :
                        self.switch_configuration["arp_table_host_entries"].append({"ip": entry.key, "nexthop_id": entry.nextHopId})
                        if self.applied_table_entries.get("arp_table") is not None:
                            if {"ip": entry.key, "nexthop_id": entry.nextHopId} not in self.applied_table_entries["arp_table"]:
                                # tables["arp_table"].append((entry.key, entry.nextHopId))
                                return TIFControlResponse(
                                    status= 404,
                                    message="Error while updating table entries: Entry {} in table {} does not exist!".format(entry.key, "arp_table")
                                )
                            else: 
                                tables["arp_table"].append((f'"{entry.key}"', entry.nextHopId))
                        else:
                            tables["arp_table"] = [(f'"{entry.key}"', entry.nextHopId)]
                    else:
                        if not check_if_equal(self.switch_configuration["arp_table_host_entries"][index], {"ip": entry.key, "nexthop_id": entry.nextHopId}):
                            self.switch_configuration["arp_table_host_entries"][index] = {"ip": entry.key, "nexthop_id": entry.nextHopId}
                            if not isinstance(self.applied_table_entries.get("arp_table"), list):
                                tables["arp_table"] = [(f'"{entry.key}"', entry.nextHopId)]
                            else:
                                if "arp_table" not in tables.keys():
                                    tables["arp_table"] = [(f'"{entry.key}"', entry.nextHopId)]
                                else:
                                    tables["arp_table"].append((f'"{entry.key}"', entry.nextHopId))
            if request.ipv4HostEntries:
                for entry in request.ipv4HostEntries:
                    index = find_ip_in_entries(self.switch_configuration["ipv4_host_entries"], entry.key)
                    if index == -1 :
                        # We can only update existing entries since Tofino support atomic operations!
                        return TIFControlResponse(
                            status= 400,
                            message="Error while updating table entries: Entry {} in table {} does not exist!".format(entry.key, "ipv4_host_entries")
                        )
                    else:
                        self.switch_configuration["ipv4_host_entries"][index] = {"ip": entry.key, "nexthop_id": entry.nextHopId}
                        if not isinstance(self.applied_table_entries.get("ipv4_host_entries"), list):
                            tables["ipv4_host"] = [(f'"{entry.key}"', entry.nextHopId)]
                        else:
                            if "ipv4_host" not in tables.keys():
                                    tables["ipv4_host"] = [(f'"{entry.key}"', entry.nextHopId)]
                            else:
                                tables["ipv4_host"].append((f'"{entry.key}"', entry.nextHopId))
            if request.nexthopMapEntries:
                for entry in request.nexthopMapEntries:
                        self.switch_configuration["nexthop_map"][entry.key] = entry.nextHopId
                        if self.applied_table_entries.get("nexthop_map") is not None:
                            if entry.key in self.applied_table_entries["nexthop_map"]:
                                tables["nexthop"].append((f'"{entry.key}"', entry.nextHopId))
                            else:
                                return TIFControlResponse(
                                    status= 400,
                                    message="Error while updating table entries: Entry {} in table {} does not exist!".format(entry.key, "nexthop_map")
                                )
                        else:
                            if "nexthop" not in tables.keys():
                                tables["nexthop"] = [(f'"{entry.key}"', entry.nextHopId)]
                            else:
                                tables["nexthop"].append((f'"{entry.key}"', entry.nextHopId))
            bfrt_python_code = self._build_table_entry_bfrt_python_code("update", tables)
            self._run_bfshell_bfrt_python(bfrt_python_code)
            self.applied_table_entries.update(tables)
            self.save_switch_configuration()
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status= 500,
                message="Error while updating table entries: {}".format(str(ex))
            )
        return TIFControlResponse(
            status =  200,
        )
    
    def DeleteTableEntries(self, request : TIFControlRequest, context):
        """
        Deletes table entries based on the provided request.

        Parameters:
        -----------
        request (TIFControlRequest): 
            The request object containing the entries to be deleted.
        context: 
            The context object for the gRPC request.

        Returns:
        --------
        TIFControlResponse: The response object indicating the status of the operation.
        """
        def find_ip_in_entries(entry_list, value):
            """
            Helper function to find the index of an IP address in a list of entries.

            Parameters:
            -----------
            entry_list (list): 
                The list of entries to search in.
            value: 
                The IP address to search for.

            Returns:
            --------
            int: The index of the IP address in the list, or -1 if not found.
            """
            for i, entry in enumerate(entry_list):
                if entry["ip"] == value:
                    return i
            return -1
        
        try:
            tables = {}
            tables["arp_table"] = []
            tables["ipv4_host"] = []
            tables["nexthop"] = []
            tables["tenant_rules"] = []
            if request.runtimeRules:
                tables["tenant_rules"] = []
                for rule in request.runtimeRules:
                    tenant_cnf_id = self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)
                    rule = MessageToDict(rule)
                    rule["matches"] = ast.literal_eval(rule["matches"][0])
                    rule["actionParams"] = ast.literal_eval(rule["actionParams"][0])
                    if isinstance(rule["matches"], str):
                        rule["matches"] = ast.literal_eval(rule["matches"])
                    if isinstance(rule["actionParams"], str):
                        rule["actionParams"] = ast.literal_eval(rule["actionParams"])
                    if len(rule["matches"]) != 0:
                        for key_name, key in rule["matches"].items():
                            if is_valid_mac(str(key)):
                                rule["matches"][key_name] = "'{}'".format(key)
                            elif is_valid_ipv4(str(key)):
                                rule["matches"][key_name] = "'{}'".format(key)
                    if isinstance(rule["actionParams"], list):
                        rule["actionParams"] = ast.literal_eval(rule["actionParams"][0])
                    if len(rule["actionParams"]) != 0:
                        for key_name, key in rule["actionParams"].items():
                            if is_valid_mac(str(key)):
                                rule["actionParams"][key_name] = "'{}'".format(key)
                            elif is_valid_ipv4(str(key)):
                                rule["actionParams"][key_name] = "'{}'".format(key)
                    if tenant_cnf_id in self.switch_configuration["tenant_rules"].keys():
                        index = self.switch_configuration["tenant_rules"][tenant_cnf_id].index(rule)
                        if index == -1:
                            return TIFControlResponse(
                                status = 404,
                                message="Error while deleting table entries: Entry {} in table {} does not exist!".format(rule, "tenant_rules")
                            )
                        else:
                            rule = self.switch_configuration["tenant_rules"][tenant_cnf_id].pop(index)
                            if len(self.switch_configuration["tenant_rules"][tenant_cnf_id]) == 0:
                                del self.switch_configuration["tenant_rules"][tenant_cnf_id]
                            if self.applied_table_entries.get("tenant_rules") is not None:
                                if rule in self.applied_table_entries["tenant_rules"][tenant_cnf_id]:
                                    index = self.applied_table_entries["tenant_rules"][tenant_cnf_id].index(rule)
                                    if index != -1:
                                        tables["tenant_rules"].append(rule)
                                    else:
                                        return TIFControlResponse(
                                            status = 404,
                                            message="Error while deleting table entries: Entry {} in table {} does not exist!".format(rule, "tenant_rules")
                                        )
                                else:
                                    return TIFControlResponse(
                                            status = 404,
                                            message="Error while deleting table entries: Entry {} in table {} does not exist!".format(rule, "tenant_rules")
                                        )
                    else:
                        return TIFControlResponse(
                            status = 404,
                            message="Error while deleting table entries: Entry {} in table {} does not exist!".format(rule, "tenant_rules")
                        )
            if request.arpHostEntries:
                for entry in request.arpHostEntries:
                    index = find_ip_in_entries(self.switch_configuration["arp_table_host_entries"], entry.key)
                    if index == -1 :
                        return TIFControlResponse(
                            status = 404
                        )
                    else:
                        rule = self.switch_configuration["arp_table_host_entries"].pop(index)
                        if self.applied_table_entries.get("arp_table") is not None:
                            if rule in self.applied_table_entries["arp_table"]:
                                tables["arp_table"].append((f'"{rule["ip"]}"', rule["nexthop_id"]))
                            else:
                                return TIFControlResponse(
                                    status = 404
                                )
            if request.ipv4HostEntries:
                for entry in request.ipv4HostEntries:
                    index = find_ip_in_entries(self.switch_configuration["ipv4_host_entries"], entry.key)
                    if index == -1 :
                        return TIFControlResponse(
                            status = 404
                        )
                    else:
                        rule = self.switch_configuration["ipv4_host_entries"].pop(index)
                        if self.applied_table_entries.get("ipv4_host") is not None:
                            if rule not in self.applied_table_entries["ipv4_host"]:
                                tables["ipv4_host"].append((f'"{rule["ip"]}"', rule["nexthop_id"]))
            if request.nexthopMapEntries:
                for entry in request.nexthopMapEntries:
                        self.switch_configuration["nexthop_map"].pop(entry.key)
                        if self.applied_table_entries.get("nexthop") is not None:
                            if entry.key not in self.applied_table_entries["nexthop"]:
                                tables["nexthop"].append(entry.key)
            bfrt_python_code = self._build_table_entry_bfrt_python_code("delete", tables)
            self._run_bfshell_bfrt_python(bfrt_python_code)
            # Remove the deleted table entries from the applied table entries list.
            for table in self.applied_table_entries.keys():
                if table in tables.keys():
                    if table == "tenant_rules":
                        for rule in tables[table]:
                            self.applied_table_entries[table][self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)].remove(rule)
                    else:
                        self.applied_table_entries[table].remove(tables[table])
            self.save_switch_configuration()
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status= 500,
                message="Error while deleting table entries: {}".format(str(ex))
            )
        return TIFControlResponse(
            status =  200,
        )
    
    def GetLAGConfiguration(self, request : TIFControlRequest, context):
        """
        Retrieves the LAG (Link Aggregation Group) configuration.

        Parameters:
        ----------
        request (TIFControlRequest): 
            The request object containing the LAG groups.
        context: 
            The context object for the gRPC request.

        Returns:
        --------
        TIFControlResponse: The response object containing the LAG configuration.

        Raises:
        -------
        Exception: If there is an error while getting the LAG configuration.
        """
        try:
            if len(request.lagGroups) > 0:
                return TIFControlResponse(
                    status = 200,
                    message = "",
                    lagGroups = [ParseDict(self.switch_configuration["lag_ecmp_groups"][self._get_lag_name(lag.id)], Lag()) for lag in request.lagGroups if self._get_lag_name(lag.id) is not None]
                )
            else:
                return TIFControlResponse(
                    status = 200,
                    message = "",
                    lagGroups = [ParseDict(lag, Lag()) for name, lag in self.switch_configuration["lag_ecmp_groups"].items()]
                )
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status= 500,
                message="Error while getting LAG configuration: {}".format(str(ex))
            )
 
    def AddLAG(self, request: TIFControlRequest, context):
        """
        Adds a Link Aggregation Group (LAG) to the switch configuration.

        Parameters:
        ----------
        request (TIFControlRequest): 
            The request object containing the LAG information.
        context: 
            The context object for the gRPC request.

        Returns:
        --------
        TIFControlResponse: The response object indicating the status of the LAG addition.

        Raises:
        -------
        Exception: If an error occurs while adding the LAG(s).
        """
        try:
            for lag in request.lagGroups:
                if self._get_lag_name(lag.id) is not None:
                    return TIFControlResponse(
                        status=400,
                        message="Adding LAG(s) failed: LAG already exists!"
                    )
                else:
                    lag_num = len(self.switch_configuration["lag_ecmp_groups"]) + 1
                    self.switch_configuration["lag_ecmp_groups"]["lag_" + str(lag_num)] = {
                        "id": lag.id,
                        "memberbase": lag.memberbase,
                        "dp_ports": [{"portId": port.portId, "active": port.active} for port in lag.dp_ports]
                    }
            self._run_tif_initialization_setup_script()
            self.save_switch_configuration()
            return TIFControlResponse(
                status=200,
                message="Adding LAG(s) successful"
            )
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status=500,
                message="Error while adding LAG(s): {}".format(str(ex))
            )
        
    def UpdateLAG(self, request : TIFControlRequest, context):
        """
        Update the Link Aggregation Groups (LAGs) based on the provided request.

        Parameters:
        ----------
        request (TIFControlRequest): 
            The request object containing the LAG groups to be updated.
        context: 
            The context object for the gRPC request.

        Returns:
        --------
        TIFControlResponse: The response object indicating the status of the LAG update operation.
        """
        try:
            for lag in request.lagGroups:
                lag_name = self._get_lag_name(lag.id) 
                if lag_name is not None:
                    self.switch_configuration["lag_ecmp_groups"][lag_name] = {
                        "id" : lag.id,
                        "memberbase": lag.memberbase,
                        "dp_ports" : [{"portId": port.portId, "active": port.active} for port in lag.dp_ports]
                    }
                else:
                    return TIFControlResponse(
                        status=400,
                        message="Updating LAG(s) failed: Does not exist!"
                    )
            
            self._run_tif_initialization_setup_script()
            self.save_switch_configuration()
            return TIFControlResponse(
                status=200,
                message="Updating LAG(s) successful"
            )
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status=500,
                message="Error while updating LAG(s): {}".format(str(ex))
            )
        
    def DeleteLAG(self, request : TIFControlRequest, context):
        """
        Deletes the specified LAG(s) from the switch configuration.

        Parameters:
        ----------
        request (TIFControlRequest): 
            The request object containing the LAG(s) to be deleted.
        context: 
            The context object for the gRPC request.

        Returns:
        --------
        TIFControlResponse: The response object indicating the status of the LAG deletion operation.
        """
        try:
            for lag in request.lagGroups:
                lag_name = self._get_lag_name(lag.id)
                if lag_name is not None:
                    self.switch_configuration["lag_ecmp_groups"].pop(lag_name)
                else:
                    return TIFControlResponse(
                        status=400,
                        message="Deleting LAG(s) failed: Does not exist!"
                    )
            self._run_tif_initialization_setup_script()
            self.save_switch_configuration()
            return TIFControlResponse(
                    status=200,
                    message="Deleting LAG(s) successful"
                )
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status=500,
                message="Error while deleting LAG(s): {}".format(str(ex))
            )

    def GetLAGMemberState(self, request: TIFControlRequest, context):
        """
        Get the member state of the LAG groups.

        Parameters:
        ----------
        request (TIFControlRequest): 
            The request object containing the LAG groups.
        context: 
            The context object.

        Returns:
        --------
        TIFControlResponse: The response object containing the member state of the LAG groups.
        """
        try:
            if len(request.lagGroups) > 0:
                lagGroups = []
                for lag in request.lagGroups:
                    lag_name = self._get_lag_name(lag.id)
                    dp_ports = self.switch_configuration["lag_ecmp_groups"][lag_name]
                    dp_ports = [ParseDict({"portId": dp.portId, "enabled": dp_ports.active}, DpPort()) for dp in dp_ports]
                    lagGroups.append(ParseDict({"id": lag.id, "memberbase": self.switch_configuration["lag_ecmp_groups"][lag_name]["memberbase"], "dp_ports": dp_ports}))
                return TIFControlResponse(
                    status=200,
                    message="",
                    lagGroups=lagGroups
                )
            else:
                return TIFControlResponse(
                    status=400,
                    message="Error while getting LAG Member State: No LAG is given"
                )
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status=500,
                message="Error while getting LAG member state: {}".format(ex)
            )

    def ChangeLAGMemberState(self, request : TIFControlRequest, context):
        """
        Change the state of LAG (Link Aggregation Group) members.

        Parameters:
        ----------
        request (TIFControlRequest): 
            The control request containing the LAG groups.
        context: 
            The context of the request.

        Returns:
        --------
        TIFControlResponse: The control response indicating the status of the operation.
        """
        try:
            environment = jinja2.Environment(loader=jinja2.FileSystemLoader(Path(self.bfrt_templates_location + "/")))
            template = environment.get_template("changeLAGMemberState.py.j2")
            python_code = template.render(lagGroups=request.lagGroups)
            self._run_bfshell_bfrt_python(python_code)
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status=500,
                message="Error while changing LAG member states: {}".format(str(ex))
            )
        self.logger.debug("Changed LAG member state successful.")
        return TIFControlResponse(
            status=200,
            message="Changing LAG member state successful."
        )

    def GetPortConfiguration(self, request: TIFControlRequest, context): 
        """
        Retrieves the port configuration based on the provided request.

        Parameters:
        ----------
        request (TIFControlRequest): 
            The request object containing the necessary information.
        context: 
            The context object for the gRPC request.

        Returns:
        --------
        TIFControlResponse: The response object containing the port configuration.

        Raises:
        -------
        Exception: If an error occurs while getting the port configuration.
        """
        try:
            if len(request.dpPorts) > 0:
                dpPorts = []
                for port in request.dpPorts:
                    index = self._is_port_in_initialized_ports(port.portId)
                    if index >= 0:
                        port_md = self.switch_configuration["initialized_ports"][index]
                        dpPorts.append(ParseDict({"portId" : port_md["dp"], "slotId": port_md["port"], "speed": port_md["speed"], "fec": port_md["fec"], "an": port_md["an"], "active": port_md["enabled"]}, DpPort()) )
                    else:
                        return TIFControlResponse(
                            status=404,
                            message="Error while getting portmetadata for {}: Port does not exist.".format(port.portId)
                        )
                return TIFControlResponse(
                    status=200,
                    message="",
                    dpPorts=dpPorts
                )
            else: 
                return TIFControlResponse(
                    status=200,
                    message="",
                    dpPorts=[ParseDict({"portId" : port["dp"], "slotId": port["port"], "speed": port["speed"], "fec": port["fec"], "active": port["enabled"]}, DpPort()) for port in self.switch_configuration["initialized_ports"]]
                )
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status=500,
                message="Error while getting port configuration: {}".format(ex)
            )

    def UpdatePortConfiguration(self, request : TIFControlRequest, context):
        """
        Update the port configuration based on the provided TIFControlRequest.

        Parameters:
        ----------
        request (TIFControlRequest): 
            The TIFControlRequest object containing the updated port configuration.
        context: 
            The context object for the gRPC request.

        Returns:
        --------
        TIFControlResponse: The TIFControlResponse object indicating the status of the port configuration update.
        """
        try:
            for port in request.dpPorts:
                index = self._is_port_in_initialized_ports(port.slotId)
                if index >= 0:
                    self.switch_configuration["initialized_ports"][index] = {
                        "port" : port.slotId,
                        "dp" : port.portId,
                        "speed": port.speed,
                        "fec": port.fec,
                        "an": port.an,
                        "enabled": port.active
                    }
                else:
                    self.switch_configuration["initialized_ports"].append(
                        {
                            "port" : port.slotId,
                            "dp" : port.portId,
                            "speed": port.speed,
                            "fec": port.fec,
                            "an": port.an,
                            "enabled": port.active
                        })
            self.logger.debug(self.switch_configuration["initialized_ports"])
            self._run_port_setup()
            self._run_tif_initialization_setup_script()
            self.save_switch_configuration()
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status=500,
                message="Error while updating port configuration: {}".format(str(ex))
            )
        self.logger.info("Updated Port configuration successful")
        return TIFControlResponse(
            status=200,
            message="Updated Port configuration successful"
        )
    
    def DeletePortConfiguration(self, request: TIFControlRequest, context):
        """
        Deletes the port configuration specified in the TIFControlRequest.

        Parameters:
        ----------
        request (TIFControlRequest): 
            The request object containing the port configuration to be deleted.
        context: 
            The context object for the gRPC request.

        Returns:
        --------
        TIFControlResponse: The response object indicating the status and message of the operation.
        """
        try:
            if len(request.dpPorts) > 0:
                for port in request.dpPorts:
                    index = self._is_port_in_initialized_ports(port.slotId)
                    if index >= 0:
                        port_config = self.switch_configuration["initialized_ports"].pop(index)
                        self.logger.debug("Port Configuration {} removed".format(port_config["port"]))
                    else:
                        raise ValueError("Port Configuration {} not found".format(port.slotId))
            else:
                self.switch_configuration["initialized_ports"].clear()
                self.logger.debug("Port Configurations cleared.")
            self._run_port_setup()
            self._run_tif_initialization_setup_script()
            self.save_switch_configuration()
            return TIFControlResponse(
                status=200,
                message="Deleted Port Configuration successful."
            )
        except ValueError as err:
            self.logger.error("Error while deleting Port Configuration: {}".format(str(err)))
            return TIFControlResponse(
                status=404,
                message="Error while deleting Port Configuration: {}".format(str(err))
            )
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status=500,
                message="Error while deleting Port Configuration: {}".format(str(ex))
            )
        
    def RestartPorts(self, request : TIFControlRequest, context):
        """
        Restarts the ports based on the provided request.

        Parameters:
        ----------
        request (TIFControlRequest): 
            The request object containing the control parameters.
        context: 
            The context object for the gRPC communication.

        Returns:
        --------
        TIFControlResponse: The response object indicating the status of the port restart operation.
        """
        try:
            if request.clear:
                self._clear_port_setup()
                self._run_port_setup()
            else:
                self._run_restart_port_setup()
            return TIFControlResponse(
                status=200,
                message="Restarted Ports successful"
            )
        except Exception as ex:
            self.logger.exception(ex)
            return TIFControlResponse(
                status=500,
                message="Error while restarting ports: ".format(str(ex))
            )

    def _is_port_in_initialized_ports(self, port):
            """
            Check if a given port is present in the initialized ports list.

            Parameters:
            ----------
            port (str): 
                The port to check.

            Returns:
            --------
            int: The index of the port in the initialized ports list if found, otherwise -1.
            """
            for index, md in enumerate(self.switch_configuration["initialized_ports"]):
                if md["port"] == port:
                    return index
            return -1

    def _get_lag_name(self, lag_id : int):
            """
            Get the name of the LAG (Link Aggregation Group) based on the provided LAG ID.

            Parameters:
            ----------
            lag_id (int): 
                The ID of the LAG.

            Returns:
            --------
            str: The name of the LAG.
            """
            for lag_name, lag_metadata in self.switch_configuration["lag_ecmp_groups"].items():
                if lag_metadata["id"] == lag_id:
                    return lag_name

    def _apply_known_table_rules(self):
        """
        Apply the known table rules to the switch.

        Parameters:
        ----------
        None

        Returns:
        --------
        None
        """
        bfrt_python_code = ""
        if self.applied_table_entries.get("tenant_rules") is not None:
            bfrt_python_code += self._build_table_entry_bfrt_python_code("add", {"tenant_rules": self.applied_table_entries["tenant_rules"]}) + "\n"
        if self.applied_table_entries.get("arp_table_host_entries") is not None:
            bfrt_python_code += self._build_table_entry_bfrt_python_code("add", {"arp_table_host_entries": self.applied_table_entries["arp_table_host_entries"]}) + "\n"
        if self.applied_table_entries.get("ipv4_host_entries") is not None:
            bfrt_python_code += self._build_table_entry_bfrt_python_code("add", {"ipv4_host_entries": self.applied_table_entries["ipv4_host_entries"]}) + "\n"
        if self.applied_table_entries.get("nexthop_map") is not None:
            bfrt_python_code += self._build_table_entry_bfrt_python_code("add", {"nexthop_map": self.applied_table_entries["nexthop_map"]}) + "\n"
        
        self._run_bfshell_bfrt_python(bfrt_python_code)

    def _apply_known_tenant_table_rules(self):
        # Flatten applied_table_entries dictionary by removing the tenant_cnf_id key
        tables = {}
        for table_category, tenant_tables in self.applied_table_entries.items():
            if isinstance(tenant_tables, dict):
                for tenant_cnf_id, tenant_table in tenant_tables.items():
                    if tables.get(table_category) is not None:
                        tables[table_category].extend(tenant_table)
                    else:
                        tables[table_category] = tenant_table
            else:
                tables[table_category] = tenant_tables
        code = self._build_table_entry_bfrt_python_code("add", tables)
        self.logger.debug(code)
        self._run_bfshell_bfrt_python(code)

    def _run_tif_initialization_setup_script(self):
        """
        Runs the TIF initialization setup script.

        This method generates the configuration code using Jinja2 templates
        and runs the generated code using bfshell_bfrt_python.

        Parameters:
        ----------
        None

        Returns:
        --------
        None
        """
        if ACCELERATOR_CONFIGURATION["tofino"]["template"] == AcceleratorTemplates.TOFINO_EDGE:
            environment = jinja2.Environment(loader=jinja2.FileSystemLoader(Path(self.bfrt_templates_location + "/")))
            template = environment.get_template("config_initialization-{}.py.j2".format(ACCELERATOR_CONFIGURATION["tofino"]["template"].value))
            code = template.render(
                ports=self.switch_configuration["initialized_ports"], 
                lagGroups=self.switch_configuration["lag_ecmp_groups"], 
                nexthop_map=self.switch_configuration["nexthop_map"],
                ipv4_host_entries=self.switch_configuration["ipv4_host_entries"],
                arp_table_entries=self.switch_configuration["arp_table_host_entries"]
            )
            self.logger.debug(code)
            self._run_bfshell_bfrt_python(code)
            self._apply_known_tenant_table_rules()
            self.logger.info("TIF initialization setup successful.")
        else:
            # self.logger.warning("Initialization of TIF on center Tofino devices is not implemented at the moment!")
            self._apply_known_tenant_table_rules()
            self.logger.info("TIF initialization setup successful.")

    def _run_restart_port_setup(self):
        """
        Run the restart port setup process.

        This method generates a shell script using a Jinja2 template and the initialized ports from the switch configuration.
        The generated script is then executed using the `_run_bfshell_ucli` method.

        Parameters:
        ----------
        None

        Returns:
        --------
        None
        """
        environment = jinja2.Environment(loader=jinja2.FileSystemLoader(Path(self.bfrt_templates_location + "/")))
        template = environment.get_template("port_restart.sh.j2")
        code = template.render(ports=self.switch_configuration["initialized_ports"])
        self.logger.debug(code)
        self._run_bfshell_ucli(code)

    def _run_port_setup(self):
        """
        Run the port setup process.

        This method initializes the environment, loads a Jinja2 template, renders the template with the initialized ports,
        and executes the generated code.

        Parameters:
        ----------
        None

        Returns:
        --------
        None
        """
        environment = jinja2.Environment(loader=jinja2.FileSystemLoader(Path(self.bfrt_templates_location + "/")))
        template = environment.get_template("port_initialization.sh.j2")
        code = template.render(ports=self.switch_configuration["initialized_ports"])
        self.logger.debug(code)
        self._run_bfshell_ucli(code)

    def _clear_port_setup(self):
        """
        Clears the port setup.

        Parameters:
        ----------
        None

        Returns:
        --------
        None
        """
        initialization_commands = [
            "ucli",
            "pm",
            "port-del -/-",
            "exit",
            "exit",
            "\n"
        ]
        initialization_commands = [cmd + "\n" for cmd in initialization_commands]
        self.logger.debug(initialization_commands)
        self._run_bfshell_ucli(initialization_commands)

    def _run_bfshell_ucli(self, code: Union[str, list], executable="run_bfshell.sh", executable_path="/home/netlabadmin/"):
        """
        Run the bfshell ucli command with the provided code.

        Parameters:
        ----------
        code (Union[str, list]): 
            The code to be executed. It can be either a string or a list of strings.
        executable (str): 
            The name of the executable script. Default is "run_bfshell.sh".
        executable_path (str): 
            The path to the executable script. Default is "/home/netlabadmin/".

        Raises:
        -------
        ValueError: If the code parameter is neither a string nor a list.

        Returns:
        --------
        None
        """
        if isinstance(code, str):
            code = code.splitlines(True)
        elif isinstance(code, list):
            code = [line + "\n" if line[:-1] != "\n" else line for line in code]
        else:
            raise ValueError

        process = None
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as temp:
            temp.writelines(code)
            temp.flush()
            command = "{}/{} -f {}".format(executable_path, executable, temp.name)
            process: subprocess.CompletedProcess = subprocess.run(command, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)

        if process.returncode != 0:
            self.logger.debug(process.stdout)
            self.logger.error("Error while running script: {} ".format(process.stderr))
            raise TIFControlException("Error while running script: {}".format(process.stderr))
        else:
            self.logger.debug("BFshell script output: {}".format(process.stdout))

    def _run_bfshell_bfrt_python(self, python_code: Union[str, list], executable="run_bfshell.sh", executable_path="/home/netlabadmin/"):
        """
        Run BFShell BFRuntime Python code.

        Parameters:
        ----------
        python_code (Union[str, list]): 
            The Python code to be executed.
        executable (str, optional): 
            The name of the executable script. Defaults to "run_bfshell.sh".
        executable_path (str, optional): 
            The path to the executable script. Defaults to "/home/netlabadmin/".

        Raises:
        -------
        ValueError: If the `python_code` parameter is neither a string nor a list.
        TIFControlException: If there is an error while running the script.

        Returns:
        --------
        None
        """
        if isinstance(python_code, str):
            code = python_code.splitlines(True)
        elif isinstance(python_code, list):
            code = [line + "\n" if line[:-1] != "\n" else line for line in python_code]
        else:
            raise ValueError
        process = None
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as temp:
            temp.writelines(code)
            temp.flush()
            command = "{}/{} -b {}".format(executable_path, executable, temp.name)
            process: subprocess.CompletedProcess = subprocess.run(command, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        if process.returncode != 0:
            self.logger.error("Error while running script: {}".format(process.stderr))
            raise TIFControlException("Error while running script: {}".format(process.stderr))
        else:
            self.logger.debug("BFRT Python script output: {}".format(process.stdout))
            # return TIFControlResponse(
            #     status=200,
            #     message=""
            # )

    def _build_table_entry_bfrt_python_code(self, operation, tables):
        """
        Build the BFRuntime Python code for a table entry.

        Parameters:
        ----------
        table_name (str): 
            The name of the table.
        table_entry (dict): 
            The table entry data.

        Returns:
        --------
        str: The generated BFRuntime Python code.
        """
        environment = jinja2.Environment(loader=jinja2.FileSystemLoader(Path(self.bfrt_templates_location + "/")))
        template = environment.get_template("{:s}_table_entry.py.j2".format(operation))
        return template.render(tables=tables)

    def pull_table_entries_from_tofino(self, tables):
        """
        Pull table entries from the Tofino chip.

        Parameters:
        ----------
        tables (list): 
            The list of tables for which the entries should be pulled.

        Returns:
        --------
        dict: The table entries.
        """
        with grpc.insecure_channel(self.tofino_grpc_address) as channel:
            stub = bfruntime_pb2_grpc.BfRuntimeStub(channel)
            for table in tables:
                request = bfruntime_pb2.ReadTableEntriesRequest()
                request.table_name = table
                response = stub.ReadTableEntries(request)
                yield response


    def pull_ForwardingPipelineConfig_from_tofino(self, address=None):
            """
            Pull the running Forwarding Pipeline Config from the tofino chip 
            and remove unnecessary parts (e.g. NonP4Config part).

            Parameters:
            -----------
            address : str, optional
                GRPC address from where configuration should be pulled.
                If not provided, the default address will be used.

            Returns:
            --------
            dict: The extracted Forwarding Pipeline Config.
            """
            if address is None:
                address = self.tofino_grpc_address
            with grpc.insecure_channel(address, options=[
                    ('grpc.max_send_message_length', maxMsgLength),
                    ('grpc.max_receive_message_length', maxMsgLength),
                    ('grpc.max_message_length', maxMsgLength)
                ]) as channel:
                stub = bfruntime_pb2_grpc.BfRuntimeStub(channel)
                resp : bfruntime_pb2.GetForwardingPipelineConfigResponse = stub.GetForwardingPipelineConfig(bfruntime_pb2.GetForwardingPipelineConfigRequest())
                resp_dict = MessageToDict(resp)
                resp_dict.pop("nonP4Config")
                return resp_dict["config"]
        
    def pull_ForwardingPipelineConfig_from_bmv2(self, address=None):
        """
        Pulls the running Forwarding Pipeline Config from BMv2 and removes unnecessary parts (e.g. NonP4Config part).

        Parameters:
        -----------
        address : str, optional
            GRPC address from where the configuration should be pulled. If not provided, the default address will be used.

        Returns:
        --------
        dict: The pulled Forwarding Pipeline Config as a dictionary.
        """
        if address is None:
            address = self.tofino_grpc_address
        with grpc.insecure_channel(address) as channel:
            stub = p4runtime_pb2_grpc.P4RuntimeStub(channel)
            resp: p4runtime_pb2.GetForwardingPipelineConfigResponse = stub.GetForwardingPipelineConfig(p4runtime_pb2.GetForwardingPipelineConfigRequest())
            resp_dict = MessageToDict(resp)
            return resp_dict["config"]

    def convert_to_bfruntime_fwd_pipeline_conf_message(self, data : Union[dict, list]):
        """
        Converting the data to BFRuntime Forwarding Pipeline Config message.

        Parameters:
        -----------
        data : dict | list
            BFRuntime Forwarding Pipeline Config message data which should be converted.

        Returns:
        --------
        list: List of BFRuntime Forwarding Pipeline Config messages.

        Raises:
        -------
        TypeError : If the data is not of type dict or list.
        """
        if isinstance(data, list):
            return [ParseDict(config, bfruntime_pb2.ForwardingPipelineConfig()) for config in data]
        elif isinstance(data, dict):
            return [ParseDict(config, bfruntime_pb2.ForwardingPipelineConfig()) for config in data["config"]]
        else:
            raise TypeError("data must be one of type: dict or list")

    def send_SetForwardingPipelineConfig_request_to_tofino(self, req):
        """
        Send the ForwardingPipeline config request to the Tofino chip.

        Parameters:
        -----------
        req : BFRuntimeConfigRequest
            BarefootRuntimeConfigRequest object which is already generated previously.

        Returns:
        --------
        resp : bfruntime_pb2.SetForwardingPipelineConfigResponse
            Response received from the Tofino chip after sending the config request.

        Raises:
        -------
        TIFUpdateException:
            If there is an error while sending the config request to the Tofino chip.
        """
        resp = None
        with grpc.insecure_channel(self.tofino_grpc_address) as channel:
            stub = bfruntime_pb2_grpc.BfRuntimeStub(channel)
            try:
                resp : bfruntime_pb2.SetForwardingPipelineConfigResponse = stub.SetForwardingPipelineConfig(req)
            except grpc.RpcError as e:
                raise TIFUpdateException(e)
        return resp
    
    def send_SetForwardingPipelineConfig_request_to_bmv2(self, req):
        """
        Send the ForwardingPipeline config request to bmv2.

        Parameters:
        -----------
        req : TIFUpdateRequest
            TIFUpdateRequest object which should be processed and set to BMv2.

        Returns:
        --------
        p4runtime_pb2.SetForwardingPipelineConfigResponse
            Response from the BMv2 indicating the success or failure of the request.
        """
        def build_device_config(self, bmv2_json_file):
            device_config = p4config_pb2.P4DeviceConfig()
            device_config.reassign = True
            with open(bmv2_json_file) as json_file:
                device_config.device_data = json_file.read().encode("utf-8")
            return device_config

        device_config = build_device_config(req.bmv2ForwardingPipelineConfig.compiledP4InfoCode.code)
        request = p4runtime_pb2.SetForwardingPipelineConfigRequest()
        request.election_id.low = 1
        request.device_id = self.device_id

        config = request.config
        with tempfile.NamedTemporaryFile(prefix="p4info") as tmp_1: 
            tmp_1.write(request.compiledP4InfoCode.code.encode("utf-8"))
            p4info_helper = p4info_help.P4InfoHelper(tmp_1.name)
            config.p4info.CopyFrom(p4info_helper.p4info)
            config.p4_device_config = device_config.SerializeToString()
            request.action = p4runtime_pb2.SetForwardingPipelineConfigRequest.VERIFY_AND_COMMIT

        resp = None
        with grpc.insecure_channel(self.bmv2_grpc_address) as channel:
            stub = p4runtime_pb2_grpc.P4RuntimeStub(channel)
            try:
                resp : p4runtime_pb2.SetForwardingPipelineConfigResponse = stub.SetForwardingPipelineConfig(req)
            except grpc.RpcError as e:
                raise TIFUpdateException(e)
        return resp