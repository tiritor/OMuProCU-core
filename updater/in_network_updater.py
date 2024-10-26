

from concurrent import futures
import hashlib
from multiprocessing import Process
import os
import random
import threading
import time

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict

from orchestrator_utils.tools.persistence import Persistor
from orchestrator_utils.tools.accelerator_type import AcceleratorType, find_python_acceleratorTypeEnum, find_protobuf_acceleratorTypeEnum
from orchestrator_utils.til import orchestrator_msg_pb2, til_msg_pb2
from orchestrator_utils.til import orchestrator_msg_pb2_grpc, til_msg_pb2_grpc
from orchestrator_utils.til import time_measurement_pb2
from orchestrator_utils.til.orchestrator_msg_pb2 import UPDATE_ACTION_CREATE, UPDATE_ACTION_UPDATE, UPDATE_ACTION_DELETE, UPDATE_STATUS_UNSPECIFIED, UPDATE_STATUS_WAIT_FOR_UPDATE, UPDATE_STATUS_UPDATING, UPDATE_STATUS_UPDATED_SUCCESS, UPDATE_STATUS_UPDATED_FAILURE, UPDATE_STATUS_DELETED_SUCCESS, UPDATE_STATUS_DELETED_FAILURE, ACCELERATOR_TYPE_UNSPECIFIED, INUpdateResponse, INUpdateRequest
from orchestrator_utils.til.orchestrator_msg_pb2_grpc import INUpdaterCommunicatorServicer
from orchestrator_utils.til.til_msg_pb2 import TenantConfig, TenantConfigRequest, TenantMetadata, TenantFuncDescription

from conf.grpc_settings import INUPDATER_ADDRESS, RULESUPDATER_ADDRESS, TCC_ADDRESS, TIF_ADDRESS, maxMsgLength
from conf.in_updater_settings import ACCELERATOR_CONFIGURATION, DevInitModes
from conf.time_measurement_settings import CURRENT_TIMEMEASUREMENT_TIMESCALE
from updater.accelerator.accelerator import Accelerator, AcceleratorCompilerException, BMv2, acceleratorClasses
from updater.otf_management.otf_generator import OTFGenerator
from updater.updater import Updater, UpdateException

"""
tenants = { 
    tenant_cnf_id: {
        "hash_compiled_code": "",
        "compiled_code: "",
        "code": "",
        "status": "",
        "mainIngressName": "",
        "accessRules": [
            VNI, VNI, ...
        ]
    }
}
"""


class INUpdater(Process, Updater, Persistor, INUpdaterCommunicatorServicer):
    """
    Orchestrators INUpdater component which handles the deployment of the in-network accelerator configurations of the submitted TDCs.
    """
    tenants_code_definitions = {}
    tenants_cnf_name_id = {}
    tenant_otfs_path = "./data/inupdater/tenant_otfs/"
    persistence_lock = threading.Lock
    MANAGEMENT_TENANT_ID = 1
    MANAGEMENT_TENANT_FUNC_NAME = "OMuProCU-management"

    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}, daemon=None, persistence_path="./data/persistence/", dev_init_mode=None):
        Process.__init__(self, group, target, name, args, kwargs, daemon=daemon)
        Persistor.__init__(self, persistence_path, "inupdater_tenant_cnfs.dat")
        Updater.__init__(self)
        self.tenants_code_definitions = self.read_from_persistence()
        
        if not os.path.exists(self.tenant_otfs_path):
            os.makedirs(self.tenant_otfs_path)
        
        self.otf_generators = {}
        self.accelerator_compilers = {}
        self.tenant_cnf_accelerator_map = {}
        self.old_tenant_cnf_accelerator_map = {}
        self.rules_to_apply = {}
        self.rules_to_delete = {}
        self.tenant_functions_description = {
            "CREATE" : [],
            "UPDATE" : [],
            "DELETE" : []
        }
        for accelerator in AcceleratorType:
            if accelerator == AcceleratorType.NONE:
                continue
            if ACCELERATOR_CONFIGURATION[accelerator.value]["enabled"]:
                if accelerator.value not in self.tenants_code_definitions.keys():
                    self.tenants_code_definitions[accelerator.value] = {}
                if accelerator.value not in self.tenants_cnf_name_id.keys():
                    self.tenants_cnf_name_id[accelerator.value] = {}
                if "general" not in self.tenants_code_definitions[accelerator.value].keys():
                        self.tenants_code_definitions.update({ accelerator.value: {
                            "general": {
                                "compiled_code" : "",
                                "hash_compiled_code": hashlib.sha256(b""),
                                "compiled_p4runtime_code": "",
                                "hash_compiled_p4runtime_code": hashlib.sha256(b""),
                                "status": UPDATE_STATUS_UNSPECIFIED,
                                }
                            }
                        })
                if dev_init_mode is None:
                    self.accelerator_compilers.update({accelerator.value: acceleratorClasses[accelerator.value]("inc_template/{}/".format(ACCELERATOR_CONFIGURATION[accelerator.value]["template"].value))})
                else:
                    self.accelerator_compilers.update({accelerator.value: acceleratorClasses[accelerator.value]("inc_template/{}/".format(ACCELERATOR_CONFIGURATION[accelerator.value]["template"].value), dev_init_mode)})
                
                self.otf_generators.update({accelerator.value: OTFGenerator("inc_template/{}/".format(ACCELERATOR_CONFIGURATION[accelerator.value]["template"].value), "inc_template/{}/".format(ACCELERATOR_CONFIGURATION[accelerator.value]["template"].value), self.accelerator_compilers[accelerator.value].otf_apply_parameter)})
        
                for name, tenant_code_defintion in self.tenants_code_definitions[accelerator.value].items():
                    if name != "general":
                        tenant_cnf_id = self._build_tenant_cnf_id(tenant_code_defintion["tenantId"], tenant_code_defintion["tenantFuncName"])
                        # Duplicates are not possible, but since the tenant_cnf_id must be unique, this should not be a problem. ;)
                        self.tenant_cnf_accelerator_map[tenant_cnf_id] = accelerator.value

        try:
            self.grpc_server = grpc.server(futures.ThreadPoolExecutor(10))
            orchestrator_msg_pb2_grpc.add_INUpdaterCommunicatorServicer_to_server(self, self.grpc_server)
            self.grpc_server.add_insecure_port(INUPDATER_ADDRESS)
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)

    @staticmethod
    def _build_tenant_cnf_id(tenantId, tenantFuncName):
        return "t" + str(tenantId) + "-" + tenantFuncName
    
    @staticmethod
    def split_tenant_cnf_id(tenant_cnf_id):
        tenant_id = tenant_cnf_id.split("-")[0][1:]
        tenant_func_name = tenant_cnf_id.split("-")[1]
        return int(tenant_id), tenant_func_name

    def _create_tenant_definition(self, tenantId, tenantFuncName, hash_compiled_code = None, compiled_code = "", compiled_p4runtime_code= "", hash_compiled_p4runtime_code = None, code = "", status = UPDATE_STATUS_UPDATING, mainIngressName: str = "", accessRules: list = [], acceleratorType = ACCELERATOR_TYPE_UNSPECIFIED, updateAction = UPDATE_ACTION_CREATE):
        """
        Helper method to create a in-network tenant function definition (or also called OTF). This maintains the state for a specific OTF. 

        Parameters:
        -----------
        tenantId : int | str
            ID of the tenant who has submitted the TDC
        tenantFuncName : str
            Function name provided in the TDC
        hash_compiled_code : str
            String representation of the hash of the compiled code
        compiled_code : str
            String representation of the compiled code
        compiled_p4runtime_code : str
            String representation of the compiled code
        hash_compiled_p4runtime_code : str
            String representation of the hash of the compiled p4runtime code
        code : str
            OTF code which should added to TIF
        status : UpdateStatus
            enum value of the update status which the OTF has.
        mainIngressName: str
            main ingress name for the OTF 
        accessRules: list
            access rules of the TDC
        acceleratorType : AcceleratorType
            accelerator type where this OTF should be deployed
        updateAction : UpdateAction
            update action what should happen with the submitted OTF
        """
        if hash_compiled_p4runtime_code is None:
            hash_compiled_p4runtime_code = hashlib.sha256(b"")
        if hash_compiled_code is None:
            hash_compiled_code = hashlib.sha256(b"")

        tenant_cnf_id = self._build_tenant_cnf_id(tenantId, tenantFuncName)
        if tenant_cnf_id not in self.tenants_cnf_name_id.keys():
            tenant_func_id_num = random.randint(0, 128)
            while tenant_func_id_num in self.tenants_cnf_name_id.values():
                tenant_func_id_num = random.randint(0, 128)
            self.tenants_cnf_name_id[find_python_acceleratorTypeEnum(acceleratorType).value].update({tenant_cnf_id: tenant_func_id_num})
        self.tenant_cnf_accelerator_map[tenant_cnf_id] = find_python_acceleratorTypeEnum(acceleratorType)
        if tenant_cnf_id in self.old_tenant_cnf_accelerator_map.keys():
            self.old_tenant_cnf_accelerator_map.pop(tenant_cnf_id)
        self.tenants_code_definitions[find_python_acceleratorTypeEnum(acceleratorType).value].update({tenant_cnf_id: {
            "tenantId" : tenantId,
            "tenantFuncName": tenantFuncName,
            "tenant_func_id_num": tenant_func_id_num,
            "accelerator_type": acceleratorType,
            "hash_compiled_code" : hash_compiled_code,
            "compiled_code" : compiled_code,
            "compiled_p4runtime_code": compiled_p4runtime_code,
            "hash_compiled_p4runtime_code": hash_compiled_p4runtime_code,
            "code" : code,
            "mainIngressName" : mainIngressName,
            "updateAction": updateAction,
            "status" : status,
            "accessRules" : accessRules
        }})

    def run(self) -> None:
        super().run()
        self.running = True
        self.grpc_server.start()
        self.logger.info("INUpdater started.")

    def SetDevInitModeForAccelerator(self, request, context):
        """
        GRPC SetDevInitModeForAccelerator implementation for INUpdaterCommunicator which is used to set a specified device init mode for a specified accelerator.
        """
        acceleratorType = find_python_acceleratorTypeEnum(request.acceleratorType)
        devInitMode = DevInitModes(request.devInitMode)
        self.accelerator_compilers[acceleratorType.value].dev_init_mode = devInitMode
        return orchestrator_msg_pb2.INUpdateResponse(
            status= 200,
            message = "Updated dev_init_mode to {} for accelerator {}".format(devInitMode.name, acceleratorType.value)
        )

    def terminate(self) -> None:
        self.running = False
        self.logger.info("Got Terminate. Stopping GRPC server.")
        self.grpc_server.stop(10)
        self.logger.info("INUpdater stopped")

    def _update_til_in_tcc(self):
        """
        Helper method to update the TIL in the TCC
        """
        with grpc.insecure_channel(TCC_ADDRESS) as channel:
            tcc_updater_stub = til_msg_pb2_grpc.TCCommunicatorStub(channel)
            for tenant in self.tenant_functions_description["CREATE"]:
                resp : til_msg_pb2.TenantConfigResponse = tcc_updater_stub.CreateTenantConfig(
                    TenantConfigRequest(
                        tenantMetadata = TenantMetadata(
                            tenantId = tenant.tenantMetadata.tenantId,
                            tenantFuncName = tenant.tenantMetadata.tenantFuncName
                        ),
                        tConfig=TenantConfig(
                            tenantMetadata=tenant.tenantMetadata,
                            tFunctionDescription=tenant,
                        )
                    )
                )
                if resp.status == 200:
                    self.tenant_functions_description["CREATE"] = []
                else:
                    raise UpdateException("Error while applying Tenant Func Descriptions to TCC: {} (Code: {})".format(resp.message, resp.status))
            for tenant in self.tenant_functions_description["UPDATE"]:
                resp : til_msg_pb2.TenantConfigResponse = tcc_updater_stub.UpdateTenantConfig(
                    TenantConfigRequest(
                        tenantMetadata = TenantMetadata(
                            tenantId = tenant.tenantMetadata.tenantId,
                            tenantFuncName = tenant.tenantMetadata.tenantFuncName
                        ),
                        tConfig=TenantConfig(
                            tenantMetadata=tenant.tenantMetadata,
                            tFunctionDescription=tenant,
                        )
                    )
                )
                if resp.status == 200:
                    self.tenant_functions_description["UPDATE"] = []
                else:
                    raise UpdateException("Error while applying Tenant Func Descriptions to TCC: {} (Code: {})".format(resp.message, resp.status))
            for tenant in self.tenant_functions_description["DELETE"]:
                resp : til_msg_pb2.TenantConfigResponse = tcc_updater_stub.DeleteTenantConfig(
                    TenantConfigRequest(
                        tenantMetadata = TenantMetadata(
                            tenantId = tenant.tenantMetadata.tenantId,
                            tenantFuncName = tenant.tenantMetadata.tenantFuncName
                        ),
                        tConfig=TenantConfig(
                            tenantMetadata=tenant.tenantMetadata,
                            tFunctionDescription=tenant,
                        )

                    )
                )
                if resp.status == 200:
                    self.tenant_functions_description["DELETE"] = []
                else:
                    raise UpdateException("Error while applying Tenant Func Descriptions to TCC: {} (Code: {})".format(resp.message, resp.status))

    def _update_code(self, accelerator_name, force = False):
        """
        Helper method to trigger the TIF code updates. 

        Parameters:
        -----------
        accelerator_name : str
            Name of the accelerator where the code update should be done.
        force : bool
            Force the code update, also if it is not neccessary
        """
        message = ""
        resp = None
        status = 200
        tif_time_message = None
        try:
            acc_type_num = find_protobuf_acceleratorTypeEnum(accelerator_name)
            resp_dict = None
            code_parts = None
            with grpc.insecure_channel(TIF_ADDRESS, options=[
        ('grpc.max_send_message_length', maxMsgLength),
        ('grpc.max_receive_message_length', maxMsgLength),
        ('grpc.max_message_length', maxMsgLength)]) as channel:
                inc_updater_stub = orchestrator_msg_pb2_grpc.TIFUpdateCommunicatorStub(channel)
                resp : orchestrator_msg_pb2.TIFResponse = inc_updater_stub.GetTIFCode(
                    orchestrator_msg_pb2.TIFRequest(
                        tenantMetadata=til_msg_pb2.TenantMetadata(
                            tenantId = self.MANAGEMENT_TENANT_ID,
                            tenantFuncName = self.MANAGEMENT_TENANT_FUNC_NAME
                        ),
                        acceleratorType = acc_type_num,
                    )
                )
                if resp.status == 200:
                    resp_dict = MessageToDict(resp)
                    code_parts = self.accelerator_compilers[accelerator_name].extract_code_parts(resp_dict)
                elif resp.status == 404:
                    code_parts = self.accelerator_compilers[accelerator_name].construct_code_parts_struct()
                else: 
                    raise UpdateException("Error while pulling TIF code from {} (Code: {}): {}".format(accelerator_name, resp.status, resp.message))
            hashes = self.accelerator_compilers[accelerator_name].generate_hashes(code_parts)
            if force or \
               not self.accelerator_compilers[accelerator_name].compare_hashes(hashes):
                # Update TIL in TCC first before applying the new code
                self._update_til_in_tcc()
                # The rules of the tenant functions that will be deleted must be deleted first!
                for tenant_cnf_id, runtime_rules in self.rules_to_delete.items():
                    self._delete_rules(tenant_cnf_id, runtime_rules)
                self.rules_to_delete.clear()
                # Apply the new code to the accelerator
                with grpc.insecure_channel(TIF_ADDRESS) as channel:
                    tif_update_init_start = time.time()
                    tif_updater_stub = orchestrator_msg_pb2_grpc.TIFUpdateCommunicatorStub(channel)
                    request = self.accelerator_compilers[accelerator_name].buildTIFRequest()
                    tif_update_start = time.time()
                    resp : orchestrator_msg_pb2.TIFResponse = tif_updater_stub.UpdateTIFCode(request)
                    tif_update_stop = time.time()
                    status = resp.status
                    if resp.status == 200:
                        tif_post_update_init_start = time.time() 
                        resp_init : orchestrator_msg_pb2.TIFResponse = tif_updater_stub.InitializeHardware(
                            orchestrator_msg_pb2.TIFRequest(
                                acceleratorType = acc_type_num,
                            )
                        )
                        tif_post_update_init_stop = time.time()
                        self.tenants_code_definitions[accelerator_name]["general"]["status"] = UPDATE_STATUS_UPDATED_SUCCESS
                        self._change_update_status_of_deployments(accelerator_name, UPDATE_STATUS_UPDATED_SUCCESS)
                        message = "Updated (offline) in-network code for {}!".format(accelerator_name)
                    else:
                        self.tenants_code_definitions[accelerator_name]["general"]["status"] = UPDATE_STATUS_UPDATED_FAILURE
                        self._change_update_status_of_deployments(accelerator_name, UPDATE_STATUS_UPDATED_FAILURE)
                        raise UpdateException("Error while applying {} Code: {} (Code: {})".format(accelerator_name, resp.message, resp.status))

                    tif_update_preprocess_time = (tif_update_start - tif_update_init_start) * CURRENT_TIMEMEASUREMENT_TIMESCALE.value
                    tif_update_time = (tif_update_stop - tif_update_start) * CURRENT_TIMEMEASUREMENT_TIMESCALE.value
                    tif_post_update_init_time = (tif_post_update_init_stop - tif_post_update_init_start) * CURRENT_TIMEMEASUREMENT_TIMESCALE.value
                    tif_time_message = self._build_tif_time_measurement_message(tif_update_preprocess_time, tif_update_time, tif_post_update_init_time)
            else:
                # Apply only the needed part if only one part is changed
                self.tenants_code_definitions[accelerator_name]["general"]["status"] = UPDATE_STATUS_UPDATED_SUCCESS
                message = "No (offline) update needed!"
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            status = 500
            if hasattr(ex, 'message'):
                message = ex.message
            else:
                message = str(ex)
        return status, message, tif_time_message

    def _change_update_status_of_deployments(self, accelerator_type, update_status):
        """
        Helper method to change update status for all deployments of a given accelerator type to given update status

        Parameters:
        -----------
        accelerator_type : str
            Name of the accelerator where the update status should be changed.
        update_status : UpdateStatus
            Update status which should be set for the given accelerator.
        """
        for tenant_cnf_id in self.tenants_code_definitions[accelerator_type].keys():
            if self.tenants_code_definitions[accelerator_type][tenant_cnf_id]["status"] == UPDATE_STATUS_UPDATING:
                self.tenants_code_definitions[accelerator_type][tenant_cnf_id]["status"] = update_status

    def _preprocess(self, request):
        """
        Helper method to preprocess the in-network tenant configurations given in the GRPC request. These will be sorted for their respective accelerator and creates a tenant definition if not available

        Parameters:
        -----------
        request : INUpdateRequest
            GRPC request which should be processed in the INUpdater.
        """
        message = ""
        for inTConfig in request.inTConfig:
            tenantId = inTConfig.tenantMetadata.tenantId
            tenantFuncName = inTConfig.tenantMetadata.tenantFuncName
            p4Code = inTConfig.p4Code
            mainIngressName = inTConfig.mainIngressName
            accessRules = inTConfig.accessRules.vnis 
            updateAction = inTConfig.updateAction
            tenant_cnf_id = self._build_tenant_cnf_id(tenantId, tenantFuncName)
            acceleratorType = find_python_acceleratorTypeEnum(inTConfig.acceleratorType)
            if tenant_cnf_id not in self.tenants_code_definitions[acceleratorType.value].keys():
                self._create_tenant_definition(tenantId, tenantFuncName, code=p4Code, mainIngressName=mainIngressName, accessRules=accessRules, updateAction=updateAction, acceleratorType=inTConfig.acceleratorType)
            else:
                self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["code"] = p4Code
                self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["mainIngressName"] = mainIngressName
                self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["accessRules"] = accessRules
                self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["updateAction"] = updateAction
                # self.tenant_cnf_accelerator_map[tenant_cnf_id] = find_python_acceleratorTypeEnum(acceleratorType)
                if tenant_cnf_id in self.old_tenant_cnf_accelerator_map.keys():
                    self.tenant_cnf_accelerator_map[tenant_cnf_id] = self.old_tenant_cnf_accelerator_map.pop(tenant_cnf_id)
            if inTConfig.acceleratorType == ACCELERATOR_TYPE_UNSPECIFIED:
                message += "Accelerator type is unspecified!"
                self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["status"] = UPDATE_STATUS_UPDATED_FAILURE
                raise UpdateException(message)
            if inTConfig.updateAction == UPDATE_ACTION_CREATE:
                self.otf_generators[acceleratorType.value].add_otf_by_code(tenant_cnf_id, self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["tenant_func_id_num"], accessRules, mainIngressName, p4Code)
                self.rules_to_apply[tenant_cnf_id] = [MessageToDict(rule) for rule in inTConfig.runtimeRules]
                with grpc.insecure_channel(TCC_ADDRESS) as channel:
                    tcc_updater_stub = til_msg_pb2_grpc.TCCommunicatorStub(channel)
                    resp : til_msg_pb2.TenantConfigResponse = tcc_updater_stub.GetTenantConfig(
                        TenantConfigRequest(
                            tenantMetadata = TenantMetadata(
                                tenantId = tenantId,
                                tenantFuncName = tenantFuncName
                            )
                        )
                    )
                    if resp.status == 200:
                        self.tenant_functions_description["UPDATE"].append(TenantFuncDescription(
                            tenantMetadata=til_msg_pb2.TenantMetadata(
                                tenantId=tenantId,
                                tenantFuncName=tenantFuncName
                            ),
                            tenantFuncId=self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["tenant_func_id_num"])
                        )
                    elif resp.status == 404:
                        self.tenant_functions_description["CREATE"].append(TenantFuncDescription(
                            tenantMetadata=til_msg_pb2.TenantMetadata(
                                tenantId=tenantId,
                                tenantFuncName=tenantFuncName
                            ),
                            tenantFuncId=self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["tenant_func_id_num"]) 
                        )
                    else:
                        raise UpdateException("Error while checking if tenant function exists: {} (Code: {})".format(resp.message, resp.status))
            elif inTConfig.updateAction == UPDATE_ACTION_UPDATE:
                try: 
                    self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["status"] = UPDATE_STATUS_UPDATING
                    self.otf_generators[acceleratorType.value].update_otf_by_code(tenant_cnf_id, self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["tenant_func_id_num"], accessRules, mainIngressName, p4Code)
                    self.rules_to_apply[tenant_cnf_id] = [MessageToDict(rule) for rule in inTConfig.runtimeRules]
                    self.tenant_functions_description["UPDATE"].append(TenantFuncDescription(
                        tenantMetadata=til_msg_pb2.TenantMetadata(
                            tenantId=tenantId,
                            tenantFuncName=tenantFuncName
                        ),
                        tenantFuncId=self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["tenant_func_id_num"])
                    )
                except KeyError as err:
                    self.logger.warning("Tenant CNF ID not found! Creating OTF part.")
                    self.otf_generators[acceleratorType.value].add_otf_by_code(tenant_cnf_id, self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["tenant_func_id_num"], accessRules, mainIngressName, p4Code)
            elif inTConfig.updateAction == UPDATE_ACTION_DELETE:
                self.otf_generators[acceleratorType.value].delete_otf(tenant_cnf_id)
                # Keep the mapping for the status access.
                self.old_tenant_cnf_accelerator_map[tenant_cnf_id] = self.tenant_cnf_accelerator_map.pop(tenant_cnf_id)
                self.rules_to_delete[tenant_cnf_id] = [MessageToDict(rule) for rule in inTConfig.runtimeRules]
                with grpc.insecure_channel(TCC_ADDRESS) as channel:
                    tcc_updater_stub = til_msg_pb2_grpc.TCCommunicatorStub(channel)
                    resp : til_msg_pb2.TenantConfigResponse = tcc_updater_stub.GetTenantConfig(
                        TenantConfigRequest(
                            tenantMetadata = TenantMetadata(
                                tenantId = tenantId,
                                tenantFuncName = tenantFuncName
                            )
                        )
                    )
                if resp.status == 200:
                    self.tenant_functions_description["DELETE"].append(TenantFuncDescription(
                        tenantMetadata=til_msg_pb2.TenantMetadata(
                            tenantId=tenantId,
                            tenantFuncName=tenantFuncName
                        ),
                        tenantFuncId=self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["tenant_func_id_num"])
                    )
                elif resp.status == 404:
                    self.logger.debug(f"Tenant function {tenant_cnf_id} not found in TCC. No need to delete.")
            else:
                raise UpdateException("Update Action was unspecified or not recognized!") 
        for name, otf_generator in self.otf_generators.items():
            otf_generator.generate()

    def _postprocess(self):
        """
        Helper method to postprocess the deployment in general.
        """
        try:
            for tenant_cnf_id, runtime_rules in self.rules_to_apply.items():
                self._synchronize_rules(tenant_cnf_id, runtime_rules)
            self.rules_to_apply.clear()
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            # raise UpdateException("Error while postprocessing: {}".format(str(ex)))

    def _delete_rules(self, tenant_cnf_id, runtime_rules):
        """
        Helper method to delete the rules for a given tenant configuration ID.

        Parameters:
        -----------
        tenant_cnf_id : str
            Tenant configuration ID
        runtime_rules : list
            List of runtime rules which should be deleted
        """
        tenant_id, tenant_func_name = self.split_tenant_cnf_id(tenant_cnf_id)
        try:
            with grpc.insecure_channel(RULESUPDATER_ADDRESS) as channel:
                rule_updater_stub = orchestrator_msg_pb2_grpc.RulesUpdaterCommunicatorStub(channel)
                resp : orchestrator_msg_pb2.TIFControlResponse = rule_updater_stub.DeleteRules(
                    orchestrator_msg_pb2.TIFControlRequest(
                        tenantMetadata = til_msg_pb2.TenantMetadata(
                            tenantId = tenant_id,
                            tenantFuncName = tenant_func_name
                        ),
                        runtimeRules = runtime_rules
                    )
                )
                if resp.status == 200:
                    resp : orchestrator_msg_pb2.TIFControlResponse = rule_updater_stub.GetRules(
                        orchestrator_msg_pb2.TIFControlRequest(
                            tenantMetadata = til_msg_pb2.TenantMetadata(
                                tenantId = tenant_id,
                                tenantFuncName = tenant_func_name
                            )
                        )
                    )
                    if resp.status == 404:
                        self.logger.info("Rules for {} deleted successfully!".format(tenant_cnf_id))
                    else:
                        raise UpdateException("Error while deleting rules: {}".format(resp.message))
                else:
                    raise UpdateException("Error while deleting rules: {} (status: {})".format(resp.message, resp.status))
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            # raise UpdateException("Error while deleting rules: {}".format(str(ex)))

    def _synchronize_rules(self, tenant_cnf_id, runtime_rules):
        """
        Helper method to synchronize the rules for a given tenant configuration ID.

        Parameters:
        -----------
        tenant_cnf_id : str
            Tenant configuration ID
        runtime_rules : list
            List of runtime rules which should be synchronized
        """
        def equal_complete_rule_dict(rules1 : list, rules2 : list):
            """
            Check if two rule dictionaries are equal.
            """
            for rule1 in rules1:
                if not complete_rule_in_runtime_rules(rule1, rules2):
                    return False
            return True
        
        def complete_rule_in_runtime_rules(rule : dict, runtime_rules : list):
            """
            Check if a rule is in the runtime rules.
            """
            for runtime_rule in runtime_rules:
                if equals_complete_rule(rule, runtime_rule):
                    return True
            return False
        
        def rule_in_runtime_rules(rule : dict, runtime_rules : list):
            """
            Check if a rule is in the runtime rules.
            """
            for runtime_rule in runtime_rules:
                if equals_rule(rule, runtime_rule):
                    return True
            return False
        
        def equals_complete_rule(rule : dict, runtime_rule : dict):
            """
            A rule must have the same table, matches and action to be the same.
            """
            return rule["table"] == runtime_rule["table"] and rule["matches"] == runtime_rule["matches"] and rule["actionName"] == runtime_rule["actionName"] and rule["actionParams"] == runtime_rule["actionParams"]

        def equals_rule(rule : dict, runtime_rule : dict):
            """
            A rule must have the same table and matches to be the same.
            """
            return rule["table"] == runtime_rule["table"] and rule["matches"] == runtime_rule["matches"]

        scheduled_create_rules = []
        scheduled_delete_rules = []
        scheduled_update_rules = []
        tenant_id, tenant_func_name = self.split_tenant_cnf_id(tenant_cnf_id)
        try:
            with grpc.insecure_channel(RULESUPDATER_ADDRESS) as channel:
                rule_updater_stub = orchestrator_msg_pb2_grpc.RulesUpdaterCommunicatorStub(channel)
                resp : orchestrator_msg_pb2.TIFControlResponse = rule_updater_stub.GetRules(
                    orchestrator_msg_pb2.TIFControlRequest(
                        tenantMetadata = til_msg_pb2.TenantMetadata(
                            tenantId = tenant_id,
                            tenantFuncName = tenant_func_name
                        )
                    )
                )
                if resp.status == 200:
                    # Check if the rules are the same
                    applied_runtime_rules = [MessageToDict(rule) for rule in resp.runtimeRules]
                    if equal_complete_rule_dict(runtime_rules, applied_runtime_rules):
                        return
                    else:
                        # Check which rules are different and create/delete them
                        for rule in runtime_rules:
                            if not rule_in_runtime_rules(rule, applied_runtime_rules):
                                scheduled_create_rules.append(rule)
                            else:
                                scheduled_update_rules.append(rule)
                        for rule in applied_runtime_rules:
                            if not rule_in_runtime_rules(rule, runtime_rules):
                                scheduled_delete_rules.append(rule)
                            elif rule not in scheduled_update_rules:
                                # scheduled_update_rules.append(rule)
                                pass
                            else:
                                scheduled_create_rules.append(rule)
                elif resp.status == 404:
                    scheduled_create_rules = runtime_rules
                if len(scheduled_update_rules) > 0:
                    resp : orchestrator_msg_pb2.TIFControlResponse = rule_updater_stub.UpdateRules(
                        orchestrator_msg_pb2.TIFControlRequest(
                            tenantMetadata = til_msg_pb2.TenantMetadata(
                                tenantId = tenant_id,
                                tenantFuncName = tenant_func_name
                            ),
                        runtimeRules = [ParseDict(rule, til_msg_pb2.RuntimeRule()) for rule in scheduled_update_rules]
                        )
                    )
                if len(scheduled_create_rules) > 0:
                    resp : orchestrator_msg_pb2.TIFControlResponse = rule_updater_stub.CreateRules(
                        orchestrator_msg_pb2.TIFControlRequest(
                            tenantMetadata = til_msg_pb2.TenantMetadata(
                                tenantId = tenant_id,
                                tenantFuncName = tenant_func_name
                            ),
                            runtimeRules = [ParseDict(rule, til_msg_pb2.RuntimeRule()) for rule in scheduled_create_rules]
                        )
                    )
                if len(scheduled_delete_rules) > 0:
                    resp : orchestrator_msg_pb2.TIFControlResponse = rule_updater_stub.DeleteRules(
                        orchestrator_msg_pb2.TIFControlRequest(
                            tenantMetadata = til_msg_pb2.TenantMetadata(
                                tenantId = tenant_id,
                                tenantFuncName = tenant_func_name
                            ),
                            runtimeRules = [ParseDict(rule, til_msg_pb2.RuntimeRule()) for rule in scheduled_delete_rules]
                        )
                    )
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            # raise UpdateException("Error while synchronizing rules: {}".format(str(ex)))

    def _build_inupdate_time_measurement_message(self, preprocessTime, compileTime, updateTime, postProcessTime):
        """
        Helper method to build the Protobuf INUpdate time measurement message.

        Parameters:
        -----------
        preprocessTime : int | float
            Duration of the preprocessing step
        compileTime : int | float
            Duration of the compile step
        updateTime : int | float
            Duration of the update step
        postProcessTime : int | float
            Duration of the postprocess step (at the moment, not neccessary in this setup)
        """
        return time_measurement_pb2.INUpdateTimeMeasurement(
            inPreprocessTime = int(preprocessTime),
            inCompileTime = int(compileTime),
            inUpdateTime = int(updateTime),
            inPostProcessTime = int(postProcessTime),
        )

    def _build_tif_time_measurement_message(self, preProcessTime, updateTime, postUpdateTime):
        """
        Helper method to build the Protobuf TIF time measurement message.

        Parameters:
        -----------
        preProcessTime : int | float
            Duration of the TIF preprocess step
        updateTime : int | float
            Duration of the TIF update step
        postUpdateTime : int | float
            Duration of the TIF postprocess step (e.g., initialize hardware again)
        """
        return time_measurement_pb2.TIFTimeMeasurement(
            tifPreprocessTime = int(preProcessTime),
            tifUpdateTime = int(updateTime),
            tifPostUpdateTime = int(postUpdateTime),
        )

    def Update(self, request, context):
        status = 500
        message = "Error while deploying in-network code: "
        try:
            preprocess_start = time.time()
            self._preprocess(request)
            preprocess_stop = time.time()
            # Accelerator compilation 
            for name, accelerator in self.accelerator_compilers.items():
                code_compile_start = time.time()
                accelerator.compile("")
                code_compile_stop = time.time()
                
                # Apply to accelerator 
                code_update_process_start = time.time()
                status, message, tif_time_measurement_message = self._update_code(name, force=request.forceUpdate)
                code_update_process_stop = time.time()
                self.logger.info(message)

                postprocess_start = time.time()
                self._postprocess()
                postprocess_stop = time.time()

                preprocess_time = (preprocess_stop - preprocess_start) * CURRENT_TIMEMEASUREMENT_TIMESCALE.value
                code_compile_time = (code_compile_stop - code_compile_start) * CURRENT_TIMEMEASUREMENT_TIMESCALE.value
                code_update_process_time = (code_update_process_stop - code_update_process_start) * CURRENT_TIMEMEASUREMENT_TIMESCALE.value
                postprocess_time = (postprocess_stop - postprocess_start) * CURRENT_TIMEMEASUREMENT_TIMESCALE.value

                time_measurement_message = self._build_inupdate_time_measurement_message(preprocess_time, code_compile_time, code_update_process_time, postprocess_time)
                
            status = 200
        except AcceleratorCompilerException as ex:
            self.logger.exception(ex, exc_info=True)
            message += "There was an error while compiling the code."
        except UpdateException as ex:
            self.logger.exception(ex, exc_info=True)
            message += "There was an error while updating the code."
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            message += "There was an error while updating the code."

        return orchestrator_msg_pb2.INUpdateResponse(
            status = status,
            message = message,
            inUpdateTimeMeasurement = time_measurement_message,
            tifTimeMeasurement = tif_time_measurement_message,
        )
    
    def GetUpdateConfigs(self, request, context):
        """
        GRPC GetUpdateConfigs implementation for INUpdaterCommunicator which is used to get the update configs of all deployed TDC.
        """
        return super().GetUpdateConfigs(request, context)

    def GetUpdateStatus(self, request, context):
        """
        GRPC GetUpdateStatus implementation for INUpdaterCommunicator which is used to get the update status for a specified TDC.
        """
        tenant_cnf_id = self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)
        try:
            acceleratorType = None
            if tenant_cnf_id in self.tenant_cnf_accelerator_map.keys():
                acceleratorType = self.tenant_cnf_accelerator_map[tenant_cnf_id]
            else:
                acceleratorType = self.old_tenant_cnf_accelerator_map[tenant_cnf_id]
            if tenant_cnf_id in self.tenants_code_definitions[acceleratorType.value].keys():
                updateStatus = self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["status"]
                return INUpdateResponse(
                    status = 200,
                    message = "IN-Update Status of {} (applied @ Accelerator {}) is {}".format(tenant_cnf_id, acceleratorType, updateStatus),
                    updateStatus = updateStatus,
                )
        except KeyError as ex:
            return INUpdateResponse(
                status = 404,
                message = "IN-Update Status of {} @ all available accelerators not found!".format(tenant_cnf_id),
            )

    def SetUpdateStatus(self, request, context):
        """
        GRPC SetUpdateStatus implementation for INUpdaterCommunicator which is used to set the update status for a specified TDC.
        """
        tenant_cnf_id = self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)
        acceleratorType = self.tenant_cnf_accelerator_map[tenant_cnf_id]
        self.tenants_code_definitions[acceleratorType.value][tenant_cnf_id]["status"] = request.updateStatus
        
        if request.updateStatus == UPDATE_STATUS_WAIT_FOR_UPDATE:
            self.tenants_code_definitions[acceleratorType.value]["general"]["status"] = UPDATE_STATUS_WAIT_FOR_UPDATE

        return INUpdateResponse(
            message = "IN-Update Status of {} is set {}".format(tenant_cnf_id, request.updateStatus),
            updateStatus = request.updateStatus,
        )
    
    def cleanup_build_directories(self, accelerator_name):
        """
        Delete the build directories for a given accelerator.

        Parameters:
        -----------
        accelerator_name : str
            Name of the accelerator 
        """
        self.accelerator_compilers[accelerator_name].cleanup_build()

    def Cleanup(self, request, context):
        """
        GRPC Cleanup implementation for INUpdaterCommunicator which is used to cleanup the updater and accelerators as well as deploy the initial TIF to it again.
        """
        try:
            for accelerator in AcceleratorType:
                if accelerator == AcceleratorType.NONE:
                    continue
                if not ACCELERATOR_CONFIGURATION[accelerator.value]["enabled"]:
                    continue
                tenants_code_definitions_keys = list(self.tenants_code_definitions[accelerator.value].keys())
                for key in tenants_code_definitions_keys:
                    try:
                        if key != "general":
                            self.tenants_code_definitions[accelerator.value].pop(key)
                            self.tenants_cnf_name_id[accelerator.value].pop(key)
                            if self.otf_generators[accelerator.value].is_otf_in_generator(key):
                                self.otf_generators[accelerator.value].delete_otf(key)
                    except KeyError as err:
                        self.logger.error("{} in {} does not exist!".format(key, accelerator.value))
                # Cleanup of all applied tenant_rules
                try:
                    with grpc.insecure_channel(RULESUPDATER_ADDRESS) as channel:
                        rule_updater_stub = orchestrator_msg_pb2_grpc.RulesUpdaterCommunicatorStub(channel)
                        resp : orchestrator_msg_pb2.TIFControlResponse = rule_updater_stub.Cleanup(
                            orchestrator_msg_pb2.TIFControlRequest()
                        )
                        if resp.status == 200:
                            self.logger.info("Cleanup of {} rules was successful.".format(accelerator.value))
                        else:
                            raise Exception("Custom error while cleaning up rules")
                except Exception as ex:
                    self.logger.exception(ex, exc_info=True)
                # Call update once to reset the applied in-network
                with grpc.insecure_channel(INUPDATER_ADDRESS) as channel:
                    stub = orchestrator_msg_pb2_grpc.INUpdaterCommunicatorStub(channel)
                    resp: INUpdateResponse = stub.Update(
                        INUpdateRequest(
                            tenantMetadata = til_msg_pb2.TenantMetadata(
                                tenantId = self.MANAGEMENT_TENANT_ID,
                                tenantFuncName = self.MANAGEMENT_TENANT_FUNC_NAME
                            ),
                            inTConfig= [],
                            forceUpdate=True
                        )
                    )
                    self.cleanup_build_directories(accelerator.value)
                    if resp.status == 200:
                        return INUpdateResponse(
                            status = 200,
                            message = "Cleanup successful."
                        )
                    else:
                        raise Exception("Custom error while cleaning up in-network code")
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            return INUpdateResponse(
                status = 500,
                message = "Error while cleanup OTFs: {}".format(str(ex))
            )
