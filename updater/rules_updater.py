

from concurrent import futures
from enum import Enum
from multiprocessing import Process

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict

from orchestrator_utils.logger.logger import init_logger
from orchestrator_utils.til import orchestrator_msg_pb2, til_msg_pb2, til_msg_pb2_grpc
from orchestrator_utils.til.orchestrator_msg_pb2 import TIFControlRequest, TIFControlResponse
from orchestrator_utils.til.tif_control_pb2 import RoutingTableConfiguration
from orchestrator_utils.tools.persistence import Persistor
from orchestrator_utils.til.orchestrator_msg_pb2_grpc import TIFControlCommunicatorStub, add_RulesUpdaterCommunicatorServicer_to_server, RulesUpdaterCommunicatorServicer

from conf.grpc_settings import RULESUPDATER_ADDRESS, TIF_ADDRESS
from updater.updater import Updater

class RulesOperation(Enum):
    UNKNOWN = 0
    CREATE = 1
    UPDATE = 2
    DELETE = 3


class RulesUpdater(Process, Updater, Persistor, RulesUpdaterCommunicatorServicer):
    """
    RulesUpdater is responsible for managing the rules in the applied TIF.
    """
    provider_tables = {}
    tenant_tables = {}
    management_tenant_id = 0
    management_tenant_name = "management"

    @staticmethod
    def _build_tenant_cnf_id(tenantId, tenantFuncName):
        """
        Build a tenant configuration ID.

        Args:
            tenant_id : int
                The tenant ID.
            tenant_func_name : str
                The tenant function name.

        Returns:
            str: The tenant configuration ID.
        """
        return "t" + str(tenantId) + "-" + tenantFuncName

    @staticmethod
    def _split_tenant_cnf_id(tenant_cnf_id : str):
        """
        Split the tenant configuration ID into tenant ID and tenant function name.

        Args:
            tenant_cnf_id : str
                The tenant configuration ID.

        Returns:
            Tuple[int, str]: The tenant ID and tenant function name.
        """
        return tenant_cnf_id.split("-")[0][1:], "-".join(tenant_cnf_id.split("-")[1:])

    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}, daemon=None, persistence_path="./data/persistence"):
        Process.__init__(self, group, target, name, args, kwargs, daemon=daemon)
        Persistor.__init__(self, persistence_path, "rules_updater.dat")
        Updater.__init__(self)
        try:
            self.grpc_server = grpc.server(futures.ThreadPoolExecutor(10))
            add_RulesUpdaterCommunicatorServicer_to_server(self, self.grpc_server)
            self.grpc_server.add_insecure_port(RULESUPDATER_ADDRESS)
            self.logger = init_logger("RulesUpdater")
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
        self.tenant_tables = {}
        self.provider_tables = {}

    def run(self):
        """
        Starts the RulesUpdater process.
        
        Raises:
            Exception: If an error occurs during the process startup.
        """
        try:
            super().run()
            self.running = True
            self.grpc_server.start()
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
    
    def terminate(self) -> None:
        """
        Stops the RulesUpdater process.
        """
        self.running = False
        self.logger.info("Got Terminate. Stopping GRPC Server.")
        self.grpc_server.stop(10)
        self.logger.info("RulesUpdater stopped.")

    def _rule_in_table(self, rule, table):
        """
        Check if a rule is in the table.

        Args:
            rule : dict
                The rule to check.
            table : list
                The table to check the rule in.

        Returns:
            bool: True if the rule is in the table, False otherwise
        """
        for r in table:
            if rule["table"] == r["table"] and rule["matches"] == r["matches"]:
                return True
        return False

    def _rule_in_provider_table(self, rule, table):
        """
        Check if a rule is in the provider table.
        
        Args:
            rule : dict
                The rule to check.
            table : list
                The table to check the rule in.

        Returns:
            bool: True if the rule is in the table, False otherwise
        """
        for r in table:
            if rule["key"] == r["key"] and rule["nextHopId"] == r["nextHopId"]:
                return True
        return False
    
    def _search_rule_in_table(self, rule, table):
        """
        Search for a rule in the table.

        Args:
            rule : dict
                The rule to search.
            table : list
                The table to search the rule in.

        Returns:
            dict: The rule if found, None otherwise
        """
        for r in table:
            if rule["table"] == r["table"] and rule["matches"] == r["matches"]:
                return r
        return None
    
    def _get_index_of_rule(self, rule, table):
        """
        Get the index of a rule in the table.

        Args:
            rule : dict
                The rule to search.
            table : list
                The table to search the rule in.

        Returns:
            int: The index of the rule if found, -1 otherwise
        """
        for i, r in enumerate(table):
            if rule["table"] == r["table"] and rule["matches"] == r["matches"]:
                return i
        return -1

    def CreateRules(self, request, context):
        """
        Creates rules based on the provided request.

        Args:
            request: The request object containing the rules to be created.
            context: The context object for the gRPC communication.

        Returns:
            An instance of `orchestrator_msg_pb2.TIFControlResponse` indicating the status of the rule creation.

        Raises:
            Exception: If an error occurs during the rule creation process.
        """
        scheduled_tables = {}
        scheduled_tables["rules"] = []
        scheduled_tables["nexthopMapEntries"] = []
        scheduled_tables["ipv4HostEntries"] = []
        scheduled_tables["arpHostEntries"] = []
        try:
            tenant_id = request.tenantMetadata.tenantId
            tenant_name = request.tenantMetadata.tenantFuncName
            tenant_cnf_id = self._build_tenant_cnf_id(tenant_id, tenant_name)
            if request.runtimeRules:
                if self.tenant_tables.get(tenant_cnf_id) is None:
                    self.tenant_tables[tenant_cnf_id] = []
                    for rule in request.runtimeRules:
                        if MessageToDict(rule) in self.tenant_tables[tenant_cnf_id]:
                            self.logger.warning("Rule {} already exists in tenant table. Skipping.".format(rule))
                            continue
                        self.tenant_tables[tenant_cnf_id].extend([MessageToDict(rule)])
                        scheduled_tables["rules"] = [MessageToDict(rule) for rule in request.runtimeRules]
                else:
                    for rule in request.runtimeRules:
                        if MessageToDict(rule) in self.tenant_tables[tenant_cnf_id]:
                            self.logger.warning("Rule {} already exists in tenant table. Skipping.".format(rule))
                            continue
                        self.tenant_tables[tenant_cnf_id].extend([MessageToDict(rule)])
                        scheduled_tables["rules"] = [MessageToDict(rule) for rule in request.runtimeRules]
            if request.nexthopMapEntries:
                if self.provider_tables.get("nextHopEntries") is None:
                    self.provider_tables["nextHopEntries"] = [MessageToDict(rule) for rule in request.nextHopMapEntries]
                    scheduled_tables["nextHopEntries"] = [MessageToDict(rule) for rule in request.nextHopMapEntries]
                else:
                    # Add only the new rules
                    if len(self.provider_tables["nextHopEntries"]) == 0:
                        self.provider_tables["nextHopEntries"] = [MessageToDict(rule) for rule in request.nextHopMapEntries]
                        scheduled_tables["nextHopEntries"] = [MessageToDict(rule) for rule in request.nextHopMapEntries]
                    else:
                        # Check if the rule already exists by matching the table and matches
                        for rule in request.nextHopMapEntries:
                            if not self._rule_in_provider_table(MessageToDict(rule), self.provider_tables["nextHopEntries"]):
                                self.provider_tables["nextHopEntries"].extend([MessageToDict(rule)])
                                scheduled_tables["nextHopEntries"].extend([MessageToDict(rule)])
                            else:
                                self.logger.warning("Rule {} already exists in provider table. Skipping.".format(rule))
            if request.ipv4HostEntries:
                if self.provider_tables.get("ipv4HostEntries") is None:
                    self.provider_tables["ipv4HostEntries"] = [MessageToDict(rule) for rule in request.ipv4HostEntries]
                    scheduled_tables["ipv4HostEntries"] = [MessageToDict(rule) for rule in request.ipv4HostEntries]
                else:
                    # Add only the new rules
                    if len(self.provider_tables["ipv4HostEntries"]) == 0:
                        self.provider_tables["ipv4HostEntries"] = [MessageToDict(rule) for rule in request.ipv4HostEntries]
                        scheduled_tables["ipv4HostEntries"] = [MessageToDict(rule) for rule in request.ipv4HostEntries]
                    else:
                        # Check if the rule already exists by matching the table and matches
                        for rule in request.ipv4HostEntries:
                            if not self._rule_in_provider_table(MessageToDict(rule), self.provider_tables["ipv4HostEntries"]):
                                self.provider_tables["ipv4HostEntries"].extend([MessageToDict(rule)])
                                scheduled_tables["ipv4HostEntries"].extend([MessageToDict(rule)])
                            else:
                                self.logger.warning("Rule {} already exists in provider table. Skipping.".format(rule))
                # self.provider_tables["ipv4HostEntries"] = [MessageToDict(rule) for rule in request.ipv4HostEntries]
            if request.arpHostEntries:
                if self.provider_tables.get("arpHostEntries") is None:
                    self.provider_tables["arpHostEntries"] = [MessageToDict(rule) for rule in request.arpHostEntries]
                    scheduled_tables["arpHostEntries"] = [MessageToDict(rule) for rule in request.arpHostEntries]
                else:
                    # Add only the new rules
                    if len(self.provider_tables["arpHostEntries"]) == 0:
                        self.provider_tables["arpHostEntries"] = [MessageToDict(rule) for rule in request.arpHostEntries]
                        scheduled_tables["arpHostEntries"] = [MessageToDict(rule) for rule in request.arpHostEntries]
                    else:
                        # Check if the rule already exists by matching the table and matches
                        for rule in request.arpHostEntries:
                            if not self._rule_in_provider_table(MessageToDict(rule), self.provider_tables["arpHostEntries"]):
                                self.provider_tables["arpHostEntries"].extend([MessageToDict(rule)])
                                scheduled_tables["arpHostEntries"].extend([MessageToDict(rule)])
                            else:
                                self.logger.warning("Rule {} already exists in provider table. Skipping.".format(rule))
            if len(scheduled_tables["rules"]) == 0 and len(scheduled_tables["nexthopMapEntries"]) == 0 and len(scheduled_tables["ipv4HostEntries"]) == 0 and len(scheduled_tables["arpHostEntries"]) == 0:
                return orchestrator_msg_pb2.TIFControlResponse(
                    tenantMetadata=request.tenantMetadata,
                    status=404,
                    message="No rules found to create"
                )
            next_hop_entries = []
            ipv4_host_entries = []
            arp_host_entries = []
            runtime_rules = []
            if scheduled_tables.get("nextHopEntries") is not None:
                next_hop_entries =[ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_tables.get("nextHopEntries") if scheduled_tables.get("nextHopEntries") is not None]
            if scheduled_tables.get("ipv4HostEntries") is not None:
                ipv4_host_entries = [ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_tables.get("ipv4HostEntries") if scheduled_tables.get("ipv4HostEntries") is not None]
            if scheduled_tables.get("arpHostEntries") is not None:
                arp_host_entries = [ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_tables.get("arpHostEntries") if scheduled_tables.get("arpHostEntries") is not None]
            if scheduled_tables.get("rules") is not None:
                runtime_rules = [ParseDict(rule, til_msg_pb2.RuntimeRule()) for rule in scheduled_tables["rules"] if scheduled_tables.get("rules") is not None]
            with grpc.insecure_channel(TIF_ADDRESS) as channel:
                stub : TIFControlCommunicatorStub = TIFControlCommunicatorStub(channel)
                stub.AddTableEntries(orchestrator_msg_pb2.TIFControlRequest(
                    tenantMetadata = request.tenantMetadata,
                    nexthopMapEntries=next_hop_entries,
                    ipv4HostEntries=ipv4_host_entries,
                    arpHostEntries=arp_host_entries,
                    runtimeRules = runtime_rules
                    )
                )
            return orchestrator_msg_pb2.TIFControlResponse(
                tenantMetadata=request.tenantMetadata,
                status=200,
                message="Rules created successfully"
            )
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            return orchestrator_msg_pb2.TIFControlResponse(
                tenantMetadata=request.tenantMetadata,
                status=500,
                message="Error creating rules: " + str(ex)
            )

    def UpdateRules(self, request, context):
        """
        Updates rules based on the provided request.

        Args:
            request: The request object containing the rules to be updated.
            context: The context object for the gRPC communication.

        Returns:
            An instance of `orchestrator_msg_pb2.TIFControlResponse` indicating the status of the rule update.
        
        Raises:
            Exception: If an error occurs during the rule update process.
        """
        scheduled_tables = {}
        scheduled_to_create_tables = {}
        try:
            tenant_id = request.tenantMetadata.tenantId
            tenant_name = request.tenantMetadata.tenantFuncName
            tenant_cnf_id = self._build_tenant_cnf_id(tenant_id, tenant_name)
            scheduled_tables["rules"] = []
            scheduled_tables["nexthopMapEntries"] = []
            scheduled_tables["ipv4HostEntries"] = []
            scheduled_tables["arpHostEntries"] = []
            scheduled_to_create_tables["rules"] = []
            if request.runtimeRules: 
                if self.tenant_tables.get(tenant_cnf_id) is None:
                    self.tenant_tables[tenant_cnf_id] = []
                    for rule in request.runtimeRules:
                        if not self._rule_in_table(MessageToDict(rule), self.tenant_tables[tenant_cnf_id]):
                            self.logger.warning("Rule {} not found in tenant table. Schedule for Creation.".format(rule))
                            self.tenant_tables[tenant_cnf_id].extend([MessageToDict(rule)])
                            scheduled_to_create_tables["rules"].extend([MessageToDict(rule)])
                            continue
                        else:
                            index = self.tenant_tables[tenant_cnf_id].index(MessageToDict(rule))
                            self.tenant_tables[tenant_cnf_id][index] = MessageToDict(rule)
                            scheduled_tables["rules"].extend([MessageToDict(rule)])
                else:
                    for rule in request.runtimeRules:
                        if not self._rule_in_table(MessageToDict(rule), self.tenant_tables[tenant_cnf_id]):
                            self.logger.warning("Rule {} not found in tenant table. Skipping.".format(rule))
                            continue
                        else:
                            index = self._get_index_of_rule(MessageToDict(rule), self.tenant_tables[tenant_cnf_id])
                            self.tenant_tables[tenant_cnf_id][index] = MessageToDict(rule)
                            scheduled_tables["rules"].extend([MessageToDict(rule)])

            if request.nexthopMapEntries:
                if self.provider_tables.get("nextHopEntries") is None:
                    self.provider_tables["nextHopEntries"] = [MessageToDict(rule) for rule in request.nexthopMapEntries]
                    scheduled_tables["nextHopEntries"] = [MessageToDict(rule) for rule in request.nexthopMapEntries]
                else:
                    for rule in request.nexthopMapEntries:
                        if not self._rule_in_provider_table(MessageToDict(rule), self.provider_tables["nextHopEntries"]):
                            self.provider_tables["nextHopEntries"].extend([MessageToDict(rule)])
                            scheduled_tables["nextHopEntries"].extend([MessageToDict(rule)])
                        else:
                            self.logger.warning("Rule {} not found in provider table. Skipping.".format(rule))
            if request.ipv4HostEntries:
                if self.provider_tables.get("ipv4HostEntries") is None:
                    self.provider_tables["ipv4HostEntries"] = [MessageToDict(rule) for rule in request.ipv4HostEntries]
                    scheduled_tables["ipv4HostEntries"] = [MessageToDict(rule) for rule in request.ipv4HostEntries]
                else:
                    for rule in request.ipv4HostEntries:
                        if not self._rule_in_provider_table(MessageToDict(rule), self.provider_tables["ipv4HostEntries"]):
                            self.provider_tables["ipv4HostEntries"].extend([MessageToDict(rule)])
                            scheduled_tables["ipv4HostEntries"].extend([MessageToDict(rule)])
                        else:
                            self.logger.warning("Rule {} not found in provider table. Skipping.".format(rule))
            if request.arpHostEntries:
                if self.provider_tables.get("arpHostEntries") is None:
                    self.provider_tables["arpHostEntries"] = [MessageToDict(rule) for rule in request.arpHostEntries]
                    scheduled_tables["arpHostEntries"] = [MessageToDict(rule) for rule in request.arpHostEntries]
                else:
                    for rule in request.arpHostEntries:
                        if not self._rule_in_provider_table(MessageToDict(rule), self.provider_tables["arpHostEntries"]):
                            self.provider_tables["arpHostEntries"].extend([MessageToDict(rule)])
                            scheduled_tables["arpHostEntries"].extend([MessageToDict(rule)])
                        else:
                            self.logger.warning("Rule {} not found in provider table. Skipping.".format(rule))
            if len(scheduled_tables["rules"]) == 0 and len(scheduled_tables["nexthopMapEntries"]) == 0 and len(scheduled_tables["ipv4HostEntries"]) == 0 and len(scheduled_tables["arpHostEntries"]) == 0:
                self.logger.debug("No rules found to update")
                return orchestrator_msg_pb2.TIFControlResponse(
                    tenantMetadata=request.tenantMetadata,
                    status=404,
                    message="No rules found to update"
                )
            # Update rules in TIF
            with grpc.insecure_channel(TIF_ADDRESS) as channel:
                stub : TIFControlCommunicatorStub = TIFControlCommunicatorStub(channel)
                stub.UpdateTableEntries(orchestrator_msg_pb2.TIFControlRequest(
                    tenantMetadata = request.tenantMetadata,
                    runtimeRules = [ParseDict(rule, til_msg_pb2.RuntimeRule()) for rule in scheduled_tables["rules"]],
                    nexthopMapEntries = [ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_tables["nexthopMapEntries"]],
                    ipv4HostEntries = [ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_tables["ipv4HostEntries"]],
                    arpHostEntries = [ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_tables["arpHostEntries"]]
                    )
                )
            if len(scheduled_to_create_tables["rules"]) > 0:
                self.logger.debug("Rules not found in tenant table. Scheduling for creation.")
                # Create the rules that were not found in the tenant table
                with grpc.insecure_channel(TIF_ADDRESS) as channel:
                    stub : TIFControlCommunicatorStub = TIFControlCommunicatorStub(channel)
                    stub.AddTableEntries(orchestrator_msg_pb2.TIFControlRequest(
                        tenantMetadata = request.tenantMetadata,
                        runtimeRules = [ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_to_create_tables["rules"]],
                        nexthopMapEntries = [ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_to_create_tables["nexthopMapEntries"]],
                        ipv4HostEntries = [ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_to_create_tables["ipv4HostEntries"]],
                        arpHostEntries = [ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_to_create_tables["arpHostEntries"]]
                        )
                    )
            return orchestrator_msg_pb2.TIFControlResponse(
                tenantMetadata=request.tenantMetadata,
                status=200,
                message="Rules updated successfully"
            )
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            return orchestrator_msg_pb2.TIFControlResponse(
                tenantMetadata=request.tenantMetadata,
                status=500,
                message="Error updating rules: " + str(ex)
            )
    
    def DeleteRules(self, request, context):
        """
        Deletes rules based on the provided request.

        Args:
            request: The request object containing the rules to be deleted.
            context: The context object for the gRPC communication.

        Returns:
            An instance of `orchestrator_msg_pb2.TIFControlResponse` indicating the status of the rule deletion.

        Raises:
            Exception: If an error occurs during the rule deletion process.
        """
        scheduled_tables = {}
        try:
            tenant_id = request.tenantMetadata.tenantId
            tenant_name = request.tenantMetadata.tenantFuncName
            tenant_cnf_id = self._build_tenant_cnf_id(tenant_id, tenant_name)
            scheduled_tables["rules"] = []
            scheduled_tables["nextHopEntries"] = []
            scheduled_tables["ipv4HostEntries"] = []
            scheduled_tables["arpHostEntries"] = []
            if request.runtimeRules:
                for rule in request.runtimeRules:
                    if MessageToDict(rule) in self.tenant_tables[tenant_cnf_id]:
                        self.tenant_tables[tenant_cnf_id].remove(MessageToDict(rule))
                        if len(self.tenant_tables[tenant_cnf_id]) == 0:
                            del self.tenant_tables[tenant_cnf_id]
                        scheduled_tables["rules"].append(MessageToDict(rule))
                    else:
                        self.logger.error("Rule {} not found in tenant table".format(rule))
                        raise Exception("Rule {} not found in tenant table".format(rule))
            if request.nexthopMapEntries:
                if self.provider_tables.get("nextHopEntries") is None:
                    self.logger.error("No rules found in provider table {}".format("nextHopMapEntries"))
                    raise Exception("No rules found in provider table {}".format("nextHopMapEntries"))
                else:
                    for rule in request.nexthopMapEntries:
                        if not self._rule_in_provider_table(MessageToDict(rule), self.provider_tables["nextHopEntries"]):
                            self.logger.warning("Rule {} not found in provider table. Skipping.".format(rule))
                            continue
                        else:
                            self.provider_tables["nextHopEntries"].remove(MessageToDict(rule))
                            scheduled_tables["nextHopEntries"].append(MessageToDict(rule))
            if request.ipv4HostEntries:
                if self.provider_tables.get("ipv4HostEntries") is None:
                    self.logger.error("No rules found in provider table {}".format("ipv4HostEntries"))
                    raise Exception("No rules found in provider table {}".format("ipv4HostEntries"))
                else:
                    for rule in request.ipv4HostEntries:
                        if not self._rule_in_provider_table(MessageToDict(rule), self.provider_tables["ipv4HostEntries"]):
                            self.logger.warning("Rule {} not found in provider table. Skipping.".format(rule))
                            continue
                        else:
                            self.provider_tables["ipv4HostEntries"].remove(MessageToDict(rule))
                            scheduled_tables["ipv4HostEntries"].append(MessageToDict(rule))
                # self.provider_tables["ipv4HostEntries"] = [MessageToDict(rule) for rule in request.ipv4HostEntries]
            if request.arpHostEntries:
                if self.provider_tables.get("arpHostEntries") is None:
                    self.logger.error("No rules found in provider table {}".format("arpHostEntries"))
                    raise Exception("No rules found in provider table {}".format("arpHostEntries"))
                else:
                    for rule in request.arpHostEntries:
                        if not self._rule_in_provider_table(MessageToDict(rule), self.provider_tables["arpHostEntries"]):
                            self.logger.warning("Rule {} not found in provider table. Skipping.".format(rule))
                            continue
                        self.provider_tables["arpHostEntries"].remove([MessageToDict(rule) for rule in request.arpHostEntries])
                        scheduled_tables["arpHostEntries"] = [MessageToDict(rule) for rule in request.arpHostEntries]
            if len(scheduled_tables["rules"]) == 0 and len(scheduled_tables["nextHopEntries"]) == 0 and len(scheduled_tables["ipv4HostEntries"]) == 0 and len(scheduled_tables["arpHostEntries"]) == 0:
                return orchestrator_msg_pb2.TIFControlResponse(
                    tenantMetadata=request.tenantMetadata,
                    status=404,
                    message="No rules found to delete"
                )
            with grpc.insecure_channel(TIF_ADDRESS) as channel:
                stub : TIFControlCommunicatorStub = TIFControlCommunicatorStub(channel)
                stub.DeleteTableEntries(orchestrator_msg_pb2.TIFControlRequest(
                    tenantMetadata = request.tenantMetadata,
                    nexthopMapEntries=[ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_tables.get("nextHopEntries") if scheduled_tables.get("nextHopEntries") is not None],
                    ipv4HostEntries=[ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_tables.get("ipv4HostEntries") if scheduled_tables.get("ipv4HostEntries") is not None],
                    arpHostEntries=[ParseDict(rule, RoutingTableConfiguration()) for rule in scheduled_tables.get("arpHostEntries") if scheduled_tables.get("arpHostEntries") is not None],
                    runtimeRules = [ParseDict(rule, til_msg_pb2.RuntimeRule()) for rule in scheduled_tables["rules"] if scheduled_tables.get("rules") is not None]
                    )
                )
            return orchestrator_msg_pb2.TIFControlResponse(
                tenantMetadata=request.tenantMetadata,
                status=200,
                message="Rules deleted successfully"
            )
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            return orchestrator_msg_pb2.TIFControlResponse(
                tenantMetadata=request.tenantMetadata,
                status=500,
                message="Error deleting rules: " + str(ex)
            )
    
    def Cleanup(self, request, context):
        """
        Cleans up the rules in the applied TIF.

        Args:
            request: The request object containing the rules to be cleaned up.
            context: The context object for the gRPC communication.

        Returns:
            An instance of `orchestrator_msg_pb2.TIFControlResponse` indicating the status of the rule cleanup.

        Raises:
            Exception: If an error occurs during the rule cleanup process.
        """
        self.logger.info("Cleaning up rules")
        try: 
            for tenant_cnf_id in self.tenant_tables.keys():
                tenant_id, tenant_func_name = self._split_tenant_cnf_id(tenant_cnf_id)
                with grpc.insecure_channel(TIF_ADDRESS) as channel:
                    stub : TIFControlCommunicatorStub = TIFControlCommunicatorStub(channel)
                    stub.DeleteTableEntries(orchestrator_msg_pb2.TIFControlRequest(
                        tenantMetadata = til_msg_pb2.TenantMetadata(
                            tenantId=int(tenant_id),
                            tenantFuncName=tenant_func_name),
                        runtimeRules = [ParseDict(rule, til_msg_pb2.RuntimeRule()) for rule in self.tenant_tables[tenant_cnf_id]]
                        )
                    )
            self.logger.debug("Clear tenant tables in rules updater.")
            self.tenant_tables.clear()
            self.logger.info("Rules cleaned up successfully")
            return orchestrator_msg_pb2.TIFControlResponse(
                status=200,
                message="Rules cleaned up successfully"
            )
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            return orchestrator_msg_pb2.TIFControlResponse(
                tenantMetadata=request.tenantMetadata,
                status=500,
                message="Error cleaning up rules: " + str(ex)
            )

    def GetRules(self, request, context):
        """
        Gets the rules in the applied TIF.
        
        Args:
            request: The request object containing the rules to be retrieved.
            context: The context object for the gRPC communication.
            
        Returns:
            An instance of `orchestrator_msg_pb2.TIFControlResponse` containing the rules in the applied TIF.
            
        Raises:
            Exception: If an error occurs during the rule retrieval process.
        """
        try:
            tenant_id = request.tenantMetadata.tenantId
            tenant_name = request.tenantMetadata.tenantFuncName
            tenant_cnf_id = self._build_tenant_cnf_id(tenant_id, tenant_name)
            if self.tenant_tables.get(tenant_cnf_id) is not None:
                return orchestrator_msg_pb2.TIFControlResponse(
                    tenantMetadata=request.tenantMetadata,
                    status=200,
                    message="Rules found",
                    runtimeRules=[ParseDict(rule, til_msg_pb2.RuntimeRule()) for rule in self.tenant_tables[tenant_cnf_id]],
                    nexthopMapEntries=[ParseDict(rule, orchestrator_msg_pb2.RoutingTableConfiguration()) for rule in self.provider_tables["nextHopEntries"]],
                    ipv4HostEntries=[ParseDict(rule, orchestrator_msg_pb2.RoutingTableConfiguration()) for rule in self.provider_tables["ipv4HostEntries"]],
                    arpHostEntries=[ParseDict(rule, orchestrator_msg_pb2.RoutingTableConfiguration()) for rule in self.provider_tables["arpHostEntries"]]
                )
            else:
                return orchestrator_msg_pb2.TIFControlResponse(
                    tenantMetadata=request.tenantMetadata,
                    status=404,
                    message="No rules found"
                )
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            return orchestrator_msg_pb2.TIFControlResponse(
                tenantMetadata=request.tenantMetadata,
                status=500,
                message="Error getting rules: " + str(ex)
            )

    def ListRules(self, request, context):
        """
        Lists the rules in the applied TIF.

        Args:
            request: The request object containing the rules to be listed.
            context: The context object for the gRPC communication.

        Returns:
            An instance of `orchestrator_msg_pb2.TIFControlResponse` containing the rules in the applied TIF.

        Raises:
            Exception: If an error occurs during the rule listing process.
        """
        try:
            tenant_id = request.tenantMetadata.tenantId
            tenant_name = request.tenantMetadata.tenantFuncName
            tenant_cnf_id = self._build_tenant_cnf_id(tenant_id, tenant_name)
            tenant_table_rules = []
            for tenant_cnf_id in self.tenant_tables.keys():
                for rule in self.tenant_tables[tenant_cnf_id]:
                    tenant_table_rules.append(rule)
                return orchestrator_msg_pb2.TIFControlResponse(
                    tenantMetadata=request.tenantMetadata,
                    status=200,
                    message="Rules found",
                    runtimeRules=[ParseDict(rule, til_msg_pb2.RuntimeRule()) for rule in tenant_table_rules],
                    nexthopMapEntries=[ParseDict(rule, orchestrator_msg_pb2.RoutingTableConfiguration()) for rule in self.provider_tables["nextHopEntries"]],
                    ipv4HostEntries=[ParseDict(rule, orchestrator_msg_pb2.RoutingTableConfiguration()) for rule in self.provider_tables["ipv4HostEntries"]],
                    arpHostEntries=[ParseDict(rule, orchestrator_msg_pb2.RoutingTableConfiguration()) for rule in self.provider_tables["arpHostEntries"]]
                )
            else:
                return orchestrator_msg_pb2.TIFControlResponse(
                    tenantMetadata=request.tenantMetadata,
                    status=404,
                    message="No rules found"
                )
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            return orchestrator_msg_pb2.TIFControlResponse(
                tenantMetadata=request.tenantMetadata,
                status=500,
                message="Error getting rules: " + str(ex)
            )


