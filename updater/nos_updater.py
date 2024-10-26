

from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from multiprocessing import Process
import threading
import time
import yaml

import grpc

from orchestrator_utils.tools.persistence import Persistor
from orchestrator_utils.til import til_msg_pb2, til_msg_pb2_grpc
from orchestrator_utils.til import orchestrator_msg_pb2
from orchestrator_utils.til import orchestrator_msg_pb2_grpc
from orchestrator_utils.til import time_measurement_pb2
from orchestrator_utils.til.orchestrator_msg_pb2_grpc import add_NOSUpdaterCommunicatorServicer_to_server, NOSUpdaterCommunicatorServicer
from orchestrator_utils.til.orchestrator_msg_pb2 import UPDATE_ACTION_CREATE, UPDATE_ACTION_DELETE, UPDATE_ACTION_UPDATE, UPDATE_STATUS_DELETED_FAILURE, UPDATE_STATUS_DELETED_SUCCESS, UPDATE_STATUS_UNSPECIFIED, UPDATE_STATUS_UPDATED_FAILURE, UPDATE_STATUS_UPDATED_SUCCESS, UPDATE_STATUS_UPDATING, NOSUpdateResponse

from conf.grpc_settings import NOSUPDATER_ADDRESS, TCC_ADDRESS
from conf.time_measurement_settings import CURRENT_TIMEMEASUREMENT_TIMESCALE
from kube_handler.podman_kube_handler import PodmanKubeHandler
from updater.updater import UpdateException, Updater
from kube_handler.kube_handler import KubeBackendHandler

class KubernetesBackend(Enum):
    """
    Possible Backends for Kubernetes usage in the NOS.
    """
    PODMAN = "podman"
    KUBERNETES = "kubernetes"

# Param Options for Podman Kubernetes Handling
pkh_params = {
    'kube_file': "",            # required
    'state': "",                # required
    'username': "",
    'password': "",
    'network': "",
    'configmap': "",            # optional
    'authfile': "",             # optional
    'cert_dir': "",             # optional
    'log_driver': "",           # optional
    'seccomp_profile_root': "", # optional
    'tls_verify': "",           # optional
    'log_level': "",            # optional
    'quiet': "",                # optional

}

class NOSUpdater(Process, Updater, Persistor, NOSUpdaterCommunicatorServicer):
    """
    Orchestrators NOSUpdater component which handles the deployment and management of tenant CNFs of the submitted TDCs.
    """
    backend_obj = None
    tenants_definitions = {}
    tenants_defintions_lock = threading.Lock()

    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}, daemon=None, params={'kube_file': '','state': 'absent'}, backend=KubernetesBackend.KUBERNETES, persistence_path="./data/persistence/") -> None:
        Process.__init__(self, group, target, name, args, kwargs, daemon=daemon)
        Persistor.__init__(self, persistence_path, "nosupdater_tenant_cnfs.dat")
        Updater.__init__(self)
        try:
            channel = grpc.insecure_channel(TCC_ADDRESS)
            self.tc_stub = til_msg_pb2_grpc.TCCommunicatorStub(channel)
            channel = grpc.insecure_channel(NOSUPDATER_ADDRESS)
            self.rs_stub = orchestrator_msg_pb2_grpc.SchedulerCommunicatorStub(channel)
        except grpc.RpcError as err:
            self.logger.error(err)
        try:
            KubernetesBackend(backend)
            if backend.value == KubernetesBackend.PODMAN.value:
                self.backend_obj = PodmanKubeHandler(params, KubernetesBackend.PODMAN.value)
            elif backend.value == KubernetesBackend.KUBERNETES.value:
                self.backend_obj = KubeBackendHandler(params, persistence_path)
                
        except ValueError:
            self.logger.error("Unsupported Backend Type!")

    @staticmethod
    def _build_tenant_cnf_id(tenantId, tenantFuncName):
        return "t" + str(tenantId) + "-" + tenantFuncName

    def Update(self, request, context):
        """
        GPRC Update implementation for NOSUpdaterCommunicator which is used for NOS update requests.
        """
        tenantId = request.tenantMetadata.tenantId
        tenantFuncName = request.tenantMetadata.tenantFuncName
        updateStatus = UPDATE_STATUS_UNSPECIFIED
        status = 200
        message = ""

        nos_preprocess_time = 0 # No Preprocessing needed so skipping

        nos_update_start = time.time()

        tenant_cnf_id = self._build_tenant_cnf_id(tenantId, tenantFuncName)
        try: 
            if tenant_cnf_id not in self.tenants_definitions.keys():
                with self.tenants_defintions_lock:
                    self.tenants_definitions.update({tenant_cnf_id: {"status": UPDATE_STATUS_UPDATING}})
            else:
                with self.tenants_defintions_lock:
                    self.tenants_definitions[tenant_cnf_id]["status"] = UPDATE_STATUS_UPDATING
            if request.updateAction == orchestrator_msg_pb2.UPDATE_ACTION_UPDATE or request.updateAction == UPDATE_ACTION_CREATE:
                if request.updateAction == orchestrator_msg_pb2.UPDATE_ACTION_CREATE:
                    resp : til_msg_pb2.TenantConfigResponse = self.tc_stub.CreateTenantConfig(til_msg_pb2.TenantConfigRequest(
                        tenantMetadata=til_msg_pb2.TenantMetadata(tenantId=tenantId, tenantFuncName=tenantFuncName),
                        tConfig=request.tConfig
                    ))
                    self.tc_resp = resp
                elif request.updateAction == orchestrator_msg_pb2.UPDATE_ACTION_UPDATE:
                    resp : til_msg_pb2.TenantConfigResponse = self.tc_stub.UpdateTenantConfig(til_msg_pb2.TenantConfigRequest(
                        tenantMetadata=til_msg_pb2.TenantMetadata(tenantId=tenantId, tenantFuncName=tenantFuncName),
                        tConfig=request.tConfig
                    ))
                    self.tc_resp = resp
                if resp.status == 200: 
                    message = "Updated Tenant Config"
                else:
                    message = "Error while updating Tenant Config: {}".format(resp.message)
                    self.logger.error(message)
                    return NOSUpdateResponse(
                        status = resp.status,
                        message = message,
                        updateStatus = UPDATE_STATUS_UPDATED_FAILURE
                    )
                updated, stdout, stderr, deployment = self.update(tenantId, tenantFuncName, request.tConfig, yaml.safe_load(request.tConfig.deployment))
                updateStatus = UPDATE_STATUS_UPDATED_SUCCESS
                if updated:
                    with self.tenants_defintions_lock:
                        self.store_to_persistence(self.tenants_definitions)
                    message = "Changed Deployment."
                else:
                    message = "No changes neccessary!"
            elif request.updateAction == orchestrator_msg_pb2.UPDATE_ACTION_DELETE:
                if tenant_cnf_id not in self.tenants_definitions.keys():
                    updateStatus = UPDATE_STATUS_DELETED_FAILURE
                    message = "Error while deleting NOS deployment: {} does not exist!".format(tenant_cnf_id)
                else:
                    updated, stdout, stderr = self.delete(tenantId, tenantFuncName, yaml.safe_load(self.tenants_definitions[tenant_cnf_id]["deployment"]) if isinstance(self.tenants_definitions[tenant_cnf_id]["deployment"], str) else self.tenants_definitions[tenant_cnf_id]["deployment"])
                    updateStatus = UPDATE_STATUS_DELETED_SUCCESS
        
            else:
                updated = False
                stdout = ""
                message = stderr = "Unknown or unspecified Update Action used"
                self.tenants_definitions[tenant_cnf_id]["status"] = UPDATE_STATUS_DELETED_FAILURE if request.updateAction == orchestrator_msg_pb2.UPDATE_ACTION_DELETE else UPDATE_STATUS_UPDATED_FAILURE
                self.store_to_persistence(self.tenants_definitions)
                self.logger.error(message)
            self.logger.debug((updated, stdout, stderr))
            self.logger.info(message)
        
            self.logger.debug(self.tenants_definitions)
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            status = 500
            if request.updateAction == UPDATE_ACTION_CREATE or request.updateAction == UPDATE_ACTION_UPDATE:
                updateStatus = UPDATE_STATUS_UPDATED_FAILURE
            elif request.updateAction == UPDATE_ACTION_DELETE:
                updateStatus = UPDATE_STATUS_DELETED_FAILURE
        finally:
            self.tenants_definitions[tenant_cnf_id]["status"] = updateStatus
            self.store_to_persistence(self.tenants_definitions)
            nos_update_stop = time.time()
            nos_update_time = (nos_update_stop - nos_update_start) * CURRENT_TIMEMEASUREMENT_TIMESCALE.value
        
        return NOSUpdateResponse(
            status = status,
            message= message,
            updateStatus = updateStatus,
            nosUpdateTimeMeasurement = time_measurement_pb2.NOSUpdateTimeMeasurement(
                nosPreprocessTime = int(nos_preprocess_time),
                nosUpdateTime = int(nos_update_time)
            ),
        )

    def GetUpdateStatus(self, request, context):
        """
        GPRC GetUpdateStatus implementation for NOSUpdaterCommunicator which is used for NOS update status requests.
        """
        tenantId = request.tenantMetadata.tenantId
        tenantFuncName = request.tenantMetadata.tenantFuncName

        tenant_cnf_id = self._build_tenant_cnf_id(tenantId, tenantFuncName)
        if tenant_cnf_id in self.tenants_definitions.keys():
            updateStatus = self.tenants_definitions[tenant_cnf_id]["status"]
            return NOSUpdateResponse(
                status = 200,
                message = "",
                tConfigs = [til_msg_pb2.TenantConfig(
                    tenantMetadata = til_msg_pb2.TenantMetadata(
                        tenantId = tenantId,
                        tenantFuncName = tenantFuncName
                    ),
                )],
                updateStatus = updateStatus
            )
        else:
            return NOSUpdateResponse(
                status = 404,
                message = "{} not found in NOSUpdater".format(tenant_cnf_id),
            )
        
    def SetUpdateStatus(self, request, context):
        """
        GPRC SetUpdateStatus implementation for NOSUpdaterCommunicator which is used for NOS update status requests.
        """
        tenantId = request.tenantMetadata.tenantId
        tenantFuncName = request.tenantMetadata.tenantFuncName

        tenant_cnf_id = self._build_tenant_cnf_id(tenantId, tenantFuncName)
        if tenant_cnf_id in self.tenants_definitions.keys():
            self.tenants_definitions[tenant_cnf_id]["status"] = request.updateStatus
            return NOSUpdateResponse(
                status = 200,
                message = "Updated {} from Tenant ID {} to {}".format(tenantFuncName, tenantId, request.updateStatus),
                tConfigs = [til_msg_pb2.TenantConfig(
                    tenantMetadata = til_msg_pb2.TenantMetadata(
                        tenantId = tenantId,
                        tenantFuncName = tenantFuncName
                    ),
                    # updateStatus = request.updateStatus
                )],
                updateStatus = request.updateStatus
            )
        else:
            return NOSUpdateResponse(
                status = 404,
                message = "{} not found in NOSUpdater".format(tenant_cnf_id),
            )
        
    def update_pkh_params(self, params):
        """
        Update params for Podman Kubernetes Handler
        """
        tenant_cnfs_tmp = self.backend_obj.tenant_cnfs
        self.backend_obj.update_params(params)
        self.backend_obj.tenant_cnfs = tenant_cnfs_tmp

    def run(self) -> None:
        super().run()
        self.grpc_server = grpc.server(ThreadPoolExecutor(max_workers=10))
        add_NOSUpdaterCommunicatorServicer_to_server(self, self.grpc_server)
        self.grpc_server.add_insecure_port(NOSUPDATER_ADDRESS)
        self.grpc_server.start()

    def update(self, tenantId, tenantFuncName : str, til : til_msg_pb2.TenantConfig, deployment=None):
        """
        Update given tenant CNF deployment. If the given tenant CNF deployment does not exist, it will be created

        Parameters:
        -----------
        tenantId : int | str
            ID of the tenant who has submitted the TDC
        tenantFuncName : str
            Function name provided in the TDC
        til : TenantConfig
            Tenant Isolation Logic which should be used for the communication between tenant CNF and Accelerator.
        deployment : str | None
            Kubernetes deployment which should be updated or created.
        """
        deployment = self.backend_obj._add_tenant_communication_unix_socket_volume("t" + str(tenantId) + "-" + tenantFuncName.lower(), deployment)
        deployment = self.backend_obj._add_tenantMetadata_to_deployment(tenantFuncName, tenantId, deployment)
        deployment = self.backend_obj._add_annotations_to_deployment(deployment)
            
        # tc_resp: til_msg_pb2.TenantConfigResponse = self.tc_stub.UpdateTenantConfig(til_msg_pb2.TenantConfigRequest(
        #     tenantMetadata=til_msg_pb2.TenantMetadata(tenantId=tenantId, tenantFuncName=tenantFuncName),
        #     tConfig=til
        #     )
        # )
        cnf_changed, stdout, stderr = self.backend_obj.apply(tenantId, deployment)
        updateStatus = UPDATE_STATUS_UPDATED_SUCCESS if self.tc_resp.status == 200 and stderr == "" else UPDATE_STATUS_UPDATED_FAILURE
        changed = self.tc_resp.status == 200 or cnf_changed
        with self.tenants_defintions_lock:
            self.tenants_definitions.update({self._build_tenant_cnf_id(tenantId, tenantFuncName) : {"deployment": deployment, "status": updateStatus}})
            self.store_to_persistence(self.tenants_definitions)
        return changed, stdout, stderr, deployment

    def Cleanup(self, request, context):
        """
        GPRC Cleanup implementation for NOSUpdaterCommunicator which is used for NOS update requests.
        """
        try:
            self.cleanup()
            return NOSUpdateResponse(
                status = 200,
                message = "NOSUpdater successfully cleaned Kubernetes"
            )
        except Exception as ex:
            self.logger.exception(ex)
            return NOSUpdateResponse(
                status = 500,
                message = "Error while cleanup: {}".format(str(ex))
            )
    
    def terminate(self) -> None:
        self.logger.info("Got Terminate. Stopping GRPC Server.")
        self.grpc_server.stop(10)

    def cleanup(self):
        """
        Cleanup all deployed tenant CNF deployed by the orchestrator. 
        """
        self.logger.debug("Get list of deployments used of orchestrator")
        deployments = self.backend_obj.get_all_deployments_of_orchestrator()
        stdouts = []
        stderrs = []
        changed = []
        self.logger.debug("Deleting deployments of orchestrator")
        for deployment in deployments:
            tenantId = deployment.metadata.labels["tenantId"]
            tenantFuncName = deployment.metadata.labels["tenantFuncName"]
            change, stdout, stderr =  self.delete(tenantId, tenantFuncName, deployment)
            changed.append(change)
            stdouts.append(stdout)
            stderrs.append(stderr)
        self.logger.info("Cleanup complete")
        return any(changed), "\n".join(stdouts), "\n".join(stderrs)

    def delete(self, tenantId, tenantFuncName, deployment = None):
        """
        Delete given tenant CNF deployment.

        Parameters:
        -----------
        tenantId : int | str
            ID of the tenant who has submitted the TDC
        tenantFuncName : str
            Function name provided in the TDC
        deployment : str | None
            Kubernetes deployment which should be deleted.
        """
        cnf_deleted, stdout, stderr = self.backend_obj.delete(tenantId, tenantFuncName, deployment)
        resp : til_msg_pb2.TenantConfigResponse = self.tc_stub.DeleteTenantConfig(til_msg_pb2.TenantConfigRequest(
            tenantMetadata=til_msg_pb2.TenantMetadata(
                tenantId = int(tenantId),
                tenantFuncName = tenantFuncName
            )
        ))
        changed = resp.status == 200 or cnf_deleted
        updateStatus = UPDATE_STATUS_DELETED_SUCCESS if resp.status == 200 and stderr == "" else UPDATE_STATUS_DELETED_FAILURE
        if self._build_tenant_cnf_id(tenantId, tenantFuncName) in self.tenants_definitions.keys():
            with self.tenants_defintions_lock:
                self.tenants_definitions[self._build_tenant_cnf_id(tenantId, tenantFuncName)]["status"] =  updateStatus
                self.store_to_persistence(self.tenants_definitions)
        else:
            stderr += "\n tenant_cnf_id {} does not exists!".format(self._build_tenant_cnf_id(tenantId, tenantFuncName))
        return changed, stdout, stderr