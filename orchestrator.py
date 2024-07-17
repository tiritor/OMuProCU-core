

from concurrent import futures
from enum import Enum
import logging
import os
import signal
import socket
from sys import argv
import threading
import time
import pandas as pd
import json

import grpc
from google.protobuf.json_format import MessageToDict

from orchestrator_utils.logger.logger import init_logger
from orchestrator_utils.tcc.tenant_communication_controller import TenantCommunicationController
from orchestrator_utils.tools.accelerator_type import find_protobuf_acceleratorTypeEnum, AcceleratorType
from orchestrator_utils.tools.countermeasure_action import CountermeasureAction
from orchestrator_utils.tools.persistence import Persistor
from orchestrator_utils.til import orchestrator_msg_pb2, orchestrator_msg_pb2_grpc, til_msg_pb2, til_msg_pb2_grpc, time_measurement_pb2_grpc, time_measurement_pb2
from orchestrator_utils.states import DeploymentStatus
from orchestrator_utils.validator import TDCValidationException, TDCValidator, ValidationException

from conf.grpc_settings import INUPDATER_ADDRESS, NOSUPDATER_ADDRESS, ORCHESTRATOR_ADDRESS, SCHEDULE_ADDRESS, TCC_ADDRESS
from conf.in_updater_settings import ACCELERATOR_CONFIGURATION
from conf.time_measurement_settings import CURRENT_TIMEMEASUREMENT_TIMESCALE
from reconfig_scheduler import ReconfigScheduler
from updater.nos_updater import NOSUpdater
from updater.in_network_updater import INUpdater
from updater.rules_updater import RulesUpdater
from updater.tif_updater import TIFUpdater

INTERACTIVE = False
CLEANUP_BY_TERMINATE = True
running = False


class Orchestrator(til_msg_pb2_grpc.DeploymentCommunicatorServicer, Persistor):
    """
    Management Process of OMuProCU. This covers the whole monitoring and TDC deployment submission process. 
    """

    def __init__(self, log_level=logging.INFO):
        self.logger = init_logger(self.__class__.__name__, log_level)
        Persistor.__init__(self, "./data/persistence/", "main.dat", self.__class__.__name__)
        self.MANAGEMENT_TENANT_ID = 1
        self.MANAGEMENT_TENANT_FUNC_NAME = "OMuProCU-management"
        self.codeValidator = TDCValidator()
        self.tenants_status = {}
        self.tenants_previous_status = {}
        self.orchestrator_timemeasurement = {}
        self.orchestrator_timemeasurement_fetched = {}
        self.orchestrator_timemeasurement_df = pd.DataFrame(columns=[
            "tenantId", "submissionId",
            "action", 
            "deploymentTime", "validationTime",
            "scheduledTime", "processingTime", 
            "nosPreprocessTime", "nosUpdateTime", 
            "inPreprocessTime", "inCompileTime", "inUpdateTime", "inPostProcessTime", 
            "tifPreprocessTime", "tifUpdateTime", "tifPostUpdateTime"
        ])
        self.OMuProCU_status_thread = None
        self.running = False
        if not self.create_persistence_paths():
            # Persisted data available, loading it.
            self.tenants = self.read_from_persistence()
        else:
            # This must be initialized since there is no data available!
            self.tenants = {}
        self.grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        til_msg_pb2_grpc.add_DeploymentCommunicatorServicer_to_server(self, self.grpc_server)
        self.grpc_server.add_insecure_port(ORCHESTRATOR_ADDRESS)

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()

    def start(self):
        """
        Start the Management Process
        """
        self.tenants = self.read_from_persistence()
        self.OMuProCU_status_thread = threading.Thread(target=self.status_loop, args=())
        self.OMuProCU_timemeasurement_thread = threading.Thread(target=self.timemeasurement_loop, args=())
        self.running = True
        self.OMuProCU_status_thread.daemon = True
        self.OMuProCU_timemeasurement_thread.daemon = True
        self.OMuProCU_status_thread.start()
        self.OMuProCU_timemeasurement_thread.start()
        self.grpc_server.start()

    def stop(self):
        """
        Stop the Orchestrator Management.

        IMPORTANT: To persist the latest state this should be called before terminating the orchestrator!
        """
        self.logger.info("Stopping Orchestrator.")
        self.running = False
        self.grpc_server.stop(10)
        self.store_to_persistence(self.tenants)
        self.logger.info("Orchestrator stopped.")

    def Create(self, request, context):
        """"
        GPRC Create implementation for DeploymentCommunicator which is used for submitting TDC create requests.
        """
        raw_deployment = request.deploymentMessage.deploymentRaw
        status, message = self.create(raw_deployment)
        return til_msg_pb2.DeploymentResponse(
            status = status, 
            message = message
        )
    
    def Update(self, request, context):
        """
        GPRC Update implementation for DeploymentCommunicator which is used for submitting TDC update requests.
        """
        raw_deployment = request.deploymentMessage.deploymentRaw
        status, message = self.update(raw_deployment)
        return til_msg_pb2.DeploymentResponse(
            status = status, 
            message = message
        )
    
    def Delete(self, request, context):
        """
        GPRC Delete implementation for DeploymentCommunicator which is used for submitting TDC delete requests.
        """
        try: 
            tenantId = request.tenantMetadata.tenantId
            tenantFuncName = request.tenantMetadata.tenantFuncName
            if tenantFuncName is None: 
                self.remove_tenant(tenantId)
            else:
                acceleratorType = AcceleratorType(self.tenants[tenantId][tenantFuncName]["TDC"]["TCD"]["acceleratorType"])
                self.remove(tenantId, tenantFuncName, acceleratorType)
            return til_msg_pb2.DeploymentResponse(
                status = 200,
                message = "Function {} of tenant {} deleted successfully.".format(tenantFuncName, tenantId)
            )
        except KeyError as err:
            self.logger.error("Function {} of Tenant {} does not exist!".format(tenantFuncName, tenantId))
            return til_msg_pb2.DeploymentResponse(
                status = 404,
                message = "Error while deleting {} of Tenant {}: does not exist!".format((tenantFuncName, tenantId))
            )
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            return til_msg_pb2.DeploymentResponse(
                status = 400, 
                message = "Error while Deleting: {}".format(ex.__str__())
            )
    
    def Cleanup(self, request, context):
        """
        GPRC Cleanup implementation for DeploymentCommunicator which is used for submissions
        """
        status, message = self.cleanup()
        return til_msg_pb2.DeploymentResponse(
            status = status,
            message = message
        )

    def CheckHealth(self, request, context):
        """
        Check the health of the orchestrator.

        Returns:
            A DeploymentResponse object with the status and message.
        """
        return til_msg_pb2.DeploymentResponse(status=200, message="OMuProCU healthy.")

    def GetDeploymentMonitorStatus(self, request, context):
        """
        Get the deployment monitor status for a specific tenant.

        Returns:
            A DeploymentResponse object containing the deployment status and message.
        """
        tenantId = request.tenantMetadata.tenantId
        tenantFuncName = request.tenantMetadata.tenantFuncName
        if tenantId in self.tenants_status:
            if tenantFuncName in self.tenants_status[tenantId]:
                return til_msg_pb2.DeploymentResponse(status=200, message="Deployment Status for {} of Tenant ID {} is {}".format(tenantFuncName, tenantId, self.tenants_status[tenantId][tenantFuncName].name), deploymentStatus=self.tenants_status[tenantId][tenantFuncName].value)
            else:
                return til_msg_pb2.DeploymentResponse(status=404, message="Tenant Function Name {} for Tenant ID {} not found".format(tenantId, tenantFuncName))
        else:
            return til_msg_pb2.DeploymentResponse(status=404, message="Tenant ID {} not found".format(tenantId), deploymentStatus=til_msg_pb2.DEPLOYMENT_STATUS_UNSPECIFIED)

    def RestartSchedulerLoop(self, request, context):
        """
        GPRC implementation to restart the reconfiguration scheduler loop.
        """
        try:
            with grpc.insecure_channel(SCHEDULE_ADDRESS) as channel:
                stub = orchestrator_msg_pb2_grpc.SchedulerCommunicatorStub(channel)
                resp: orchestrator_msg_pb2.ScheduleResponse = stub.RestartSchedulerLoop(
                    orchestrator_msg_pb2.ScheduleRequest(

                    )
                )
            if resp.status == 200:
                return til_msg_pb2.DeploymentResponse(status=200, message="ReconfigScheduler Loop restarted.")
            else:
                return til_msg_pb2.DeploymentResponse(status=500, message="ReconfigScheduler has thrown an error.")
        except Exception as ex:
            self.logger.exception(ex)
            return til_msg_pb2.DeploymentResponse(status=500, message="Error occured while trying to restart ReconfigScheduler Loop: {}".format(ex.__str__()))

    @staticmethod
    def _build_tenant_cnf_id(tenantId, tenantFuncName):
        return "t" + str(tenantId) + "-" + tenantFuncName

    @staticmethod
    def _split_tenant_cnf_id(tenant_cnf_id : str):
        return tenant_cnf_id.split("-")[0][1:], "-".join(tenant_cnf_id.split("-")[1:])

    @staticmethod
    def _get_til_msg_action(action: CountermeasureAction):
        """
        Get the corresponding Protobuf Enum from the given Python Countermeasure Action.

        Parameters:
        -----------
        action : CountermeasureAction
            Python CountermeasureAction enum object.
        """
        return til_msg_pb2.COUNTERMEASURE_ACTION_ACCEPT if action == CountermeasureAction.ACCEPT else til_msg_pb2.COUNTERMEASURE_ACTION_DROP if action == CountermeasureAction.DROP else til_msg_pb2.COUNTERMEASURE_ACTION_HARD if action == CountermeasureAction.HARD else til_msg_pb2.COUNTERMEASURE_ACTION_SOFT if action == CountermeasureAction.SOFT else til_msg_pb2.COUNTERMEASURE_ACTION_UNSPECIFIED

    def convert_til_to_tenantConfig_msg(self, tdc : dict):
        """
        Converting TIL from TDC to Protobuf tenant config struct.

        Parameters:
        -----------
        tdc : dict
            TDC from where the TIL should be converted to a tenant config message struct.
        """
        vnis = [tdc["TIL"]["accessRules"]["VNI"]] if isinstance(tdc["TIL"]["accessRules"]["VNI"], int) else tdc["TIL"]["accessRules"]["VNI"]
        tenantConfig = til_msg_pb2.TenantConfig(
            tenantMetadata = til_msg_pb2.TenantMetadata(tenantId=tdc["id"], tenantFuncName=tdc["name"]),
            accessRules = til_msg_pb2.AccessRules(vnis=vnis if isinstance(vnis, list) else [vnis]),
            rRules = [
                til_msg_pb2.TenantConfig.RuntimeRule(
                    table = rule["table"],
                    actionName = rule["actionName"],
                    matches = [rule["match"]],
                    actionParams = [rule["actionParams"]],
                ) for rule in tdc["TIL"]["runtimeRules"]
            ],
            deployment=tdc["TCD"]["kubernetesDeployment"].__str__()
        )
        return tenantConfig
    
    def preprocess(self, deployment=None, path=None, update_action=orchestrator_msg_pb2.UPDATE_ACTION_UNSPECIFIED):
        """
        Preprocess a TDC. TDC can be a path to a TDC or string. If both are given, the deployment parameter is prefered.

        Parameters:
        -----------
        deployment : str
            TDC deployment string which should be validated.
        path : str
            path to the TDC deployment which should be loaded and validated.
        update_action : UpdateAction
            update action enum value with which the deployment should be handled.
        """
        validation_start = time.time()
        tenantId = None
        tenantFuncName = None
        valid = False
        # FIXME: This must be backported for the OMUProCU paper release.
        update_request = update_action == orchestrator_msg_pb2.UPDATE_ACTION_UPDATE
        delete_request = update_action == orchestrator_msg_pb2.UPDATE_ACTION_DELETE
        if deployment is not None:
            valid = self.codeValidator.validate(deployment=deployment, update_request=update_request, delete_request=delete_request)
        elif path is not None: 
            valid = self.codeValidator.validate(path=path, update_request=update_request, delete_request=delete_request)
        else:
            raise ValidationException("Preprocess needs deployment or path to be set!")
        if valid:
            tenantId = self.codeValidator.tdc["id"] 
            tenantFuncName = self.codeValidator.tdc["name"] 
            if tenantId in self.tenants_status:
                if tenantFuncName in self.tenants_status[tenantId]:
                    if tenantId not in self.tenants_previous_status:
                        self.tenants_previous_status[tenantId] = {}
                    self.tenants_previous_status[tenantId][tenantFuncName] = self.tenants_status[tenantId][tenantFuncName]
            self.tenants_status.update({tenantId: {tenantFuncName: DeploymentStatus.VALIDATING}}) 
            params = {
                "kube_file": self.codeValidator.tcd["kubernetesDeploymentFile"] if "kubernetesDeploymentFile" in self.codeValidator.tcd.keys() else "",
                "state": "started"
            }
            validation_end = time.time()
            return tenantId, tenantFuncName, params, (validation_end - validation_start) * CURRENT_TIMEMEASUREMENT_TIMESCALE.value
        else:
            tenantId = self.codeValidator.tdc["id"] 
            tenantFuncName = self.codeValidator.tdc["name"] 
            tenantId_exist = tenantId in self.tenants.keys()
            tenantFuncName_exist = tenantFuncName in self.tenants[tenantId].keys() if tenantId_exist else False
            if update_action == orchestrator_msg_pb2.UPDATE_ACTION_CREATE and (not tenantId_exist and not tenantFuncName_exist):
                self.tenants_status.update({tenantId: {tenantFuncName: DeploymentStatus.FAILED}})
            raise TDCValidationException("Error while validating provided TDC!")

    def _check_nos_update(self, tenantId, tenantFuncName, scheduleStatus=orchestrator_msg_pb2.SCHEDULE_STATUS_UNSPECIFIED):
        """
        Helper method to check the update status of the NOS deployment.

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who has submitted the TDC
        tenantFuncName : str
            Function name provided in the TDC
        scheduleStatus : ScheduleStatus
            the actual schedule status from the to be checked TDC deployment
        """
        with grpc.insecure_channel(NOSUPDATER_ADDRESS) as channel:
            stub = orchestrator_msg_pb2_grpc.NOSUpdaterCommunicatorStub(channel)
            resp: orchestrator_msg_pb2.NOSUpdateResponse = stub.GetUpdateStatus(orchestrator_msg_pb2.NOSUpdateRequest(
                tenantMetadata = til_msg_pb2.TenantMetadata(
                    tenantId = tenantId,
                    tenantFuncName = tenantFuncName
                )
            ))
            self._handle_nos_update_status(tenantId, tenantFuncName, resp, scheduleStatus)
            return resp

    def _handle_nos_update_status(self, tenantId, tenantFuncName, resp, scheduleStatus):
        """
        Helper method to handle the update status of the NOS deployment.

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who has submitted the TDC
        tenantFuncName : str
            Function name provided in the TDC
        resp : NOSUpdateResponse
            Protobuf message from the NOSUpdater
        scheduleStatus : ScheduleStatus
            the actual schedule status from the to be checked TDC deployment
        """
        if resp.status == 200:
            if resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_UPDATING:
                self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.UPDATING
            elif resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_UPDATED_SUCCESS:
                self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.NOS_UPDATED
            elif resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_UPDATED_FAILURE:
                self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.FAILED
            elif resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_DELETED_SUCCESS:
                self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.NOS_UPDATED
            elif resp.updateStatus== orchestrator_msg_pb2.UPDATE_STATUS_DELETED_FAILURE:
                self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.FAILED
        elif resp.status == 404 and scheduleStatus == orchestrator_msg_pb2.SCHEDULE_STATUS_DELETED:
            # Deployment was aborted before the TDC was deployed by the scheduler. Set status to DELETED
            self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.DELETED
        elif resp.status == 404:
                self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.UNSPECIFIED

    def _handle_schedule_status(self, tenantId, tenantFuncName, resp):
        """
        Helper method to handle the schedule status of the TDC deployment.

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who has submitted the TDC
        tenantFuncName : str
            Function name provided in the TDC
        resp : ScheduleResponse
            Protobuf message from the Reconfiguration Scheduler
        """
        if resp.scheduleStatus == orchestrator_msg_pb2.SCHEDULE_STATUS_UNSPECIFIED:
            self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.UNSPECIFIED
        elif resp.scheduleStatus == orchestrator_msg_pb2.SCHEDULE_STATUS_SCHEDULED:
            self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.SCHEDULED
        elif resp.scheduleStatus == orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSING:
            self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.UPDATING
            self._check_nos_update(tenantId, tenantFuncName)
        elif resp.scheduleStatus == orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSING_FAILED:
            self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.FAILED
        elif resp.scheduleStatus == orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSED:
            self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.RUNNING
        elif resp.scheduleStatus == orchestrator_msg_pb2.SCHEDULE_STATUS_DELETED:
            # self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.DELETED
            self._check_nos_update(tenantId, tenantFuncName)

    def _check_scheduler_update(self, tenantId, tenantFuncName):
        """
        Helper method to check the schedule status of the TDC deployment.

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who has submitted the TDC
        tenantFuncName : str
            Function name provided in the TDC
        """
        with grpc.insecure_channel(SCHEDULE_ADDRESS) as channel:
            stub = orchestrator_msg_pb2_grpc.SchedulerCommunicatorStub(channel)
            resp: orchestrator_msg_pb2.ScheduleResponse = stub.GetScheduleStatus(
                orchestrator_msg_pb2.ScheduleRequest(
                    tenantMetadata = til_msg_pb2.TenantMetadata(
                        tenantId = tenantId,
                        tenantFuncName = tenantFuncName
                    )
                )
            )
            self._handle_schedule_status(tenantId, tenantFuncName, resp)
            return resp

    def _check_in_update(self, tenantId, tenantFuncName):
        """
        Helper method to check the in-network update status of the TDC deployment.

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who has submitted the TDC
        tenantFuncName : str
            Function name provided in the TDC
        """
        with grpc.insecure_channel(INUPDATER_ADDRESS) as channel:
            stub = orchestrator_msg_pb2_grpc.INUpdaterCommunicatorStub(channel)
            resp: orchestrator_msg_pb2.INUpdateResponse = stub.GetUpdateStatus(
                orchestrator_msg_pb2.INUpdateRequest(
                    tenantMetadata = til_msg_pb2.TenantMetadata(
                        tenantId = tenantId,
                        tenantFuncName = tenantFuncName
                    )
                )
            )
            if resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_UPDATED_SUCCESS:
                self.tenants_status.update({tenantId: {tenantFuncName: DeploymentStatus.IN_UPDATED}})
            elif resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_UPDATED_FAILURE or resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_DELETED_FAILURE:
                self.tenants_status.update({tenantId: {tenantFuncName: DeploymentStatus.FAILED}})
            elif resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_DELETED_SUCCESS:
                self.tenants_status.update({tenantId: {tenantFuncName: DeploymentStatus.IN_UPDATED}})
            else:
                pass
            return resp

    def timemeasurement_loop(self):
        """
        Loop to fetch and save timemeasurement data from different pipeline steps.
        """
        def cleanup_fetched_timemeasurement():
            """
            Helper method to cleanup the collected timemeasurement data structs.
            """
            tenant_cnf_ids = list(self.orchestrator_timemeasurement.keys())
            for tenant_cnf_id in tenant_cnf_ids:
                if isinstance(self.orchestrator_timemeasurement[tenant_cnf_id], dict):
                    tenant_submitted_deployments = list(self.orchestrator_timemeasurement[tenant_cnf_id].keys())
                    for deploymentSubmissionId in tenant_submitted_deployments:
                        if self.orchestrator_timemeasurement_fetched[tenant_cnf_id][deploymentSubmissionId]:
                            self.orchestrator_timemeasurement[tenant_cnf_id].pop(deploymentSubmissionId)
                            self.orchestrator_timemeasurement_fetched[tenant_cnf_id].pop(deploymentSubmissionId)
                            with grpc.insecure_channel(SCHEDULE_ADDRESS) as channel:
                                stub = time_measurement_pb2_grpc.TimeMeasurementCommunicatorStub(channel)
                                tenantId, tenantFuncName = self._split_tenant_cnf_id(tenant_cnf_id)
                                stub.RemoveTimeMeasurementFromTenant(
                                    time_measurement_pb2.TimeMeasurementRequest(
                                        tenantMetadata=til_msg_pb2.TenantMetadata(
                                            tenantId=int(tenantId),
                                            tenantFuncName=tenantFuncName,
                                            deploymentSubmissionId=deploymentSubmissionId
                                        )
                                    )
                                )
                        if len(self.orchestrator_timemeasurement[tenant_cnf_id].values()) < 1:
                            self.orchestrator_timemeasurement.pop(tenant_cnf_id)
                            self.orchestrator_timemeasurement_fetched.pop(tenant_cnf_id)
        
        def save_fetched_timemeasurement():
            """
            Helper method to save the collected timemeasurement data to csv file. 
            """
            finished_timemeasurement = {}
            for tenant_cnf_id, value in self.orchestrator_timemeasurement.items():
                if isinstance(value, dict):
                    for deploymentSubmissionId, tm in self.orchestrator_timemeasurement[tenant_cnf_id].items():
                        if self.orchestrator_timemeasurement_fetched[tenant_cnf_id][deploymentSubmissionId]:
                            finished_timemeasurement[tenant_cnf_id] = self.orchestrator_timemeasurement[tenant_cnf_id][deploymentSubmissionId]
                            finished_timemeasurement[tenant_cnf_id]["submissionId"] = deploymentSubmissionId
                            # finished_timemeasurement[tenant_cnf_id]["deploymentTime"] = 0
            df = pd.DataFrame.from_dict(finished_timemeasurement, orient="index", columns=self.orchestrator_timemeasurement_df.columns[1:])
            df.index.name = "tenantId"
            df.reset_index(inplace=True)
            self.orchestrator_timemeasurement_df = pd.concat([self.orchestrator_timemeasurement_df, df], ignore_index=True)
            self.orchestrator_timemeasurement_df.fillna(0, inplace=True)
            self.orchestrator_timemeasurement_df.to_csv("orchestrator_timemeasurement.csv", index=False)
            finished_timemeasurement.clear()
        
        while self.running:
            with grpc.insecure_channel(SCHEDULE_ADDRESS) as channel:
                stub = time_measurement_pb2_grpc.TimeMeasurementCommunicatorStub(channel)
                timemeasurements = stub.GetTimeMeasurementForMultipleTenants(
                    time_measurement_pb2.TimeMeasurementRequest()
                )
                for tm_msg in timemeasurements:
                    tm_dict = MessageToDict(tm_msg)
                    tm_tm = tm_dict["tenantMetadata"]
                    tm_timemeasurement = tm_dict["timeMeasurement"]
                    tenant_cnf_id = self._build_tenant_cnf_id(tm_tm["tenantId"], tm_tm["tenantFuncName"])
                    for key, part in tm_timemeasurement.items():
                        if isinstance(part, dict):
                            for key, value in part.items():
                                self.orchestrator_timemeasurement[tenant_cnf_id][int(tm_tm["deploymentSubmissionId"])][key] = value
                        self.orchestrator_timemeasurement_fetched[tenant_cnf_id][int(tm_tm["deploymentSubmissionId"])] = True
            save_fetched_timemeasurement()
            cleanup_fetched_timemeasurement()
            time.sleep(5)

    def status_loop(self):
        """
        Status loop for health check of scheduled and commissioned deployments.
        """
        while self.running:
            tenantIds = list(self.tenants_status.keys())
            for tenantId in tenantIds:
                tenantFuncNames = list(self.tenants_status[tenantId].keys())
                for tenantFuncName in tenantFuncNames:
                    if self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.UNSPECIFIED:
                        # Status lost --> Find the status again.
                        self.logger.warn("Lost status of {} of tenant id {}... Trying to find it again.".format(tenantFuncName, tenantId))
                        resp = self._check_scheduler_update(tenantId, tenantFuncName)
                    elif self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.SCHEDULING or self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.SCHEDULED:
                        resp = self._check_scheduler_update(tenantId, tenantFuncName)
                    elif self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.UPDATING:
                        resp = self._check_nos_update(tenantId, tenantFuncName)
                    elif self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.NOS_UPDATED:
                        resp = self._check_in_update(tenantId, tenantFuncName)
                    elif self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.IN_UPDATED:
                        if self.tenants[tenantId][tenantFuncName]["lastAction"] == orchestrator_msg_pb2.UPDATE_ACTION_DELETE:
                            self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.DELETED
                        elif self.tenants[tenantId][tenantFuncName]["lastAction"] == orchestrator_msg_pb2.UPDATE_ACTION_CREATE or self.tenants[tenantId][tenantFuncName]["lastAction"] == orchestrator_msg_pb2.UPDATE_ACTION_UPDATE:
                            self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.RUNNING
                    elif self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.RUNNING:
                        ### First, here will be the performance monitoring to check if the deployed TIF drops the performance of the processing. 
                        ### Afterwards: Health check of deployed and running TDCs
                        pass
                    elif self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.FAILED:
                        tenant_security_config = None
                        with open("conf/tenant_security_config.json", "r") as f:
                            tenant_security_config = json.load(f)
                        if self.tenants and tenantId in self.tenants.keys():
                            if self.tenants[tenantId][tenantFuncName]["TDC"]["INC"]["mainIngressName"] in tenant_security_config[str(tenantId)]["devices"]["default"]["mainIngressNames"]:
                                tenant_security_config[str(tenantId)]["devices"]["default"]["mainIngressNames"].remove(self.tenants[tenantId][tenantFuncName]["TDC"]["INC"]["mainIngressName"])
                        with open("conf/tenant_security_config.json", "w") as f:
                            f.write("")
                            json.dump(tenant_security_config, f, indent=2)
                        ### Rollback to old deployment if available, depending also used accelerator and its TIF besides the NOS deployment.
                    elif self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.REQUEST_DELETE:
                        resp = self._check_scheduler_update(tenantId, tenantFuncName)
                        if resp.status == 200: 
                            if resp.scheduleStatus == orchestrator_msg_pb2.SCHEDULE_STATUS_DELETED:
                                self.tenants.pop(tenantId)
                                self.store_to_persistence(self.tenants)
                                self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.DELETED
                        else:
                            self.logger.error("An error occured while check scheduling status: {}".format(resp.message))
                    elif self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.DELETED:
                        tenant_security_config = None
                        with open("conf/tenant_security_config.json", "r") as f:
                            tenant_security_config = json.load(f)
                        if self.tenants and tenantId in self.tenants.keys():
                            if self.tenants[tenantId][tenantFuncName]["TDC"]["INC"]["mainIngressName"] in tenant_security_config[str(tenantId)]["devices"]["default"]["mainIngressNames"]:
                                tenant_security_config[str(tenantId)]["devices"]["default"]["mainIngressNames"].remove(self.tenants[tenantId][tenantFuncName]["TDC"]["INC"]["mainIngressName"])
                        with open("conf/tenant_security_config.json", "w") as f:
                            f.write("")
                            json.dump(tenant_security_config, f, indent=2)
                        ### Here can be introduce a Garbage Collection System to clean up very old deleted TDCs.
            self.logger.info(self.tenants_status)
            time.sleep(5)

    def _check_for_update_states(self, tenantId, tenantFuncName):
        """
        Get the update state for a TDC. 

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who has submitted the TDC
        tenantFuncName : str
            Function name provided in the TDC
        """
        if tenantId in self.tenants_status.keys():
            if tenantFuncName in self.tenants_status[tenantId].keys():
                return self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.NOS_UPDATED or self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.IN_UPDATED or self.tenants_status[tenantId][tenantFuncName] == DeploymentStatus.UPDATING
            # return False
        return False

    def set_status_of_tenant_cnf(self, tenantId, tenantFuncName, status : DeploymentStatus):
        """
        Set the status of a tenant CNF.

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who has submitted the TDC
        tenantFuncName : str
            Function name provided in the TDC
        """
        if tenantId in self.tenants_status.keys():
            if tenantFuncName in self.tenants_status[tenantId].keys():
                self.tenants_status[tenantId][tenantFuncName] = status
                return
            raise KeyError("Tenant Function Name not found")
        raise KeyError("Tenant ID not found")

    def create(self, deployment = None, tdc_path = None):
        """
         Helper method for creating a TDC deployment. If the deployment exists, it will return an error message.

        Parameters:
        -----------
        deployment : str
            String with the whole manifest which should be parsed and deployed.

        tdc_path : str
            Local path to a TDC which should be loaded, parsed and deployed.
        """
        try:
            if deployment is not None and not os.path.exists(deployment): 
                tenantId, tenantFuncName, params, validation_time = self.preprocess(deployment=deployment, update_action=orchestrator_msg_pb2.UPDATE_ACTION_CREATE)
            elif tdc_path is not None:
                tenantId, tenantFuncName, params, validation_time = self.preprocess(path=tdc_path, update_action=orchestrator_msg_pb2.UPDATE_ACTION_CREATE)
            elif os.path.exists(deployment):
                tenantId, tenantFuncName, params, validation_time = self.preprocess(path=deployment, update_action=orchestrator_msg_pb2.UPDATE_ACTION_CREATE)
            else: 
                raise ValidationException("Deployment or Path to TDC must be set!")
        except ValidationException as tdc_ex:
            self.logger.exception(tdc_ex, exc_info=True)
            self.set_status_of_tenant_cnf(tenantId, tenantFuncName, DeploymentStatus.FAILED)
            return 500, tdc_ex.__str__()

        tenant_cnf_id = self._build_tenant_cnf_id(tenantId, tenantFuncName)
        if tenantId in self.tenants.keys():
            if tenantFuncName in self.tenants[tenantId].keys():
                if self.tenants_previous_status[tenantId][tenantFuncName] != DeploymentStatus.DELETED:
                    self.logger.error("Failed to create tenant function: {} does already exists!".format(tenantFuncName))
                    return 500, "Failed to create tenant function: {} does already exists!".format(tenantFuncName)
        try:
            self.logger.debug(self.tenants)
            self.tenants.update({self.codeValidator.tdc_id: {tenantFuncName: {"params": params, "TDC": self.codeValidator.tdc, "lastAction" : orchestrator_msg_pb2.UPDATE_ACTION_CREATE}}}) 
            self.logger.debug(self.tenants)
            til_config_msg = self.convert_til_to_tenantConfig_msg(self.codeValidator.tdc)
            with grpc.insecure_channel(SCHEDULE_ADDRESS) as channel:
                self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.SCHEDULING
                stub = orchestrator_msg_pb2_grpc.SchedulerCommunicatorStub(channel)
                deployment_submission_time = time.time()
                resp = stub.Schedule(
                    orchestrator_msg_pb2.ScheduleRequest(
                        tenantMetadata = til_msg_pb2.TenantMetadata(
                            tenantId=tenantId,
                            tenantFuncName=tenantFuncName,
                            deploymentSubmissionId = int(deployment_submission_time)
                        ),
                        scheduleMessage = orchestrator_msg_pb2.ScheduleMessage(
                            tConfig = til_config_msg,
                            updateAction = orchestrator_msg_pb2.UPDATE_ACTION_CREATE,
                            inTConfig = orchestrator_msg_pb2.INTenantConfig(
                                tenantMetadata = til_msg_pb2.TenantMetadata(
                                    tenantId=tenantId,
                                    tenantFuncName=tenantFuncName
                                ),
                                p4Code=self.codeValidator.inc["p4Code"],
                                mainIngressName=self.codeValidator.inc["mainIngressName"],
                                acceleratorType=find_protobuf_acceleratorTypeEnum(self.codeValidator.tcd["acceleratorType"]),
                                accessRules=til_msg_pb2.AccessRules(
                                    vnis = self.codeValidator.til["accessRules"]["VNI"] if isinstance(self.codeValidator.til["accessRules"]["VNI"], list) else [self.codeValidator.til["accessRules"]["VNI"]]
                                ),
                                updateAction = orchestrator_msg_pb2.UPDATE_ACTION_CREATE,
                                runtimeRules=[
                                    til_msg_pb2.RuntimeRule(
                                        table=rule["table"],
                                        actionName=rule["actionName"],
                                        matches=[rule["match"]],
                                        actionParams=[rule["actionParams"]]
                                    ) for rule in self.codeValidator.til["runtimeRules"]
                                ]
                            )
                        )
                    )
                )
                if resp.status == 200:
                    self.logger.info("Added Deployment.")
                    self.logger.debug("Debug Information: (status code: 200, message: {})".format(resp.message))
                    if tenant_cnf_id not in self.orchestrator_timemeasurement.keys():
                            self.orchestrator_timemeasurement[tenant_cnf_id] = {}
                            self.orchestrator_timemeasurement_fetched[tenant_cnf_id] = {}
                    self.orchestrator_timemeasurement[tenant_cnf_id][int(deployment_submission_time)] = {
                            "action": orchestrator_msg_pb2.UPDATE_ACTION_CREATE,
                            "deploymentSubmissionTimestamp": deployment_submission_time,
                            "validationTime" : validation_time,
                        }
                    self.orchestrator_timemeasurement_fetched[tenant_cnf_id][int(deployment_submission_time)] = False
                    self.store_to_persistence(self.tenants)
                else:
                    self.logger.error("An error (status code: {}) occured while scheduling the update of {}: {}".format(resp.status, tenant_cnf_id, resp.message))
                return resp.status, resp.message
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            self.set_status_of_tenant_cnf(tenantId, tenantFuncName, DeploymentStatus.FAILED)
            return 500, ex.__str__()

    def update(self, deployment=None, tdc_path = None):
        """
        Helper method for creating or updating a TDC deployment.

        Parameters:
        -----------
        deployment : str
            String with the whole manifest which should be parsed and deployed.

        tdc_path : str
            Local path to a TDC which should be loaded, parsed and deployed.
        """
        try:
            if deployment is not None: 
                tenantId, tenantFuncName, params, validation_time = self.preprocess(deployment=deployment, update_action = orchestrator_msg_pb2.UPDATE_ACTION_UPDATE)
            elif tdc_path is not None:
                tenantId, tenantFuncName, params, validation_time = self.preprocess(path=tdc_path, update_action = orchestrator_msg_pb2.UPDATE_ACTION_UPDATE)
            elif os.path.exists(deployment):
                tenantId, tenantFuncName, params, validation_time = self.preprocess(path=deployment, update_action = orchestrator_msg_pb2.UPDATE_ACTION_UPDATE)
            else: 
                raise ValidationException("Deployment or Path to TDC must be set!")
        except ValidationException as tdc_ex:
            self.logger.exception(tdc_ex, exc_info=True)
            return tdc_ex

        tenant_cnf_id = self._build_tenant_cnf_id(tenantId, tenantFuncName)

        try:
            self.logger.debug(self.tenants)
            # {"tenantId": {"tenantFuncName": {"params": {"kube_file": "", "state": "started"}, "TDC": TDC}}}
            self.tenants.update({self.codeValidator.tdc_id: {tenantFuncName: {"params": params, "TDC": self.codeValidator.tdc, "lastAction" : orchestrator_msg_pb2.UPDATE_ACTION_UPDATE}}}) 
            self.logger.debug(self.tenants)
            til_config_msg = self.convert_til_to_tenantConfig_msg(self.codeValidator.tdc)
            if self._check_for_update_states(tenantId, tenantFuncName):
                self.logger.error("A previous submitted TDC is applied. Please wait, until the process is done before submitted a new one!")
                return
            with grpc.insecure_channel(SCHEDULE_ADDRESS) as channel:
                self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.SCHEDULING
                stub = orchestrator_msg_pb2_grpc.SchedulerCommunicatorStub(channel)
                deployment_submission_time = time.time()
                resp = stub.Schedule(
                    orchestrator_msg_pb2.ScheduleRequest(
                        tenantMetadata = til_msg_pb2.TenantMetadata(
                            tenantId=tenantId,
                            tenantFuncName=tenantFuncName,
                            deploymentSubmissionId=int(deployment_submission_time)
                        ),
                        scheduleMessage = orchestrator_msg_pb2.ScheduleMessage(
                            tConfig = til_config_msg,
                            updateAction = orchestrator_msg_pb2.UPDATE_ACTION_UPDATE,
                            inTConfig = orchestrator_msg_pb2.INTenantConfig(
                                tenantMetadata = til_msg_pb2.TenantMetadata(
                                    tenantId=tenantId,
                                    tenantFuncName=tenantFuncName
                                ),
                                p4Code=self.codeValidator.inc["p4Code"],
                                mainIngressName=self.codeValidator.inc["mainIngressName"],
                                acceleratorType=find_protobuf_acceleratorTypeEnum(self.codeValidator.tcd["acceleratorType"]),
                                accessRules=til_msg_pb2.AccessRules(
                                    vnis = self.codeValidator.til["accessRules"]["VNI"] if isinstance(self.codeValidator.til["accessRules"]["VNI"], list) else [self.codeValidator.til["accessRules"]["VNI"]]
                                ),
                                updateAction = orchestrator_msg_pb2.UPDATE_ACTION_UPDATE,
                                runtimeRules=[
                                    til_msg_pb2.RuntimeRule(
                                        table=rule["table"],
                                        actionName=rule["actionName"],
                                        matches=[rule["match"]],
                                        actionParams=[rule["actionParams"]]
                                    ) for rule in self.codeValidator.til["runtimeRules"]
                                ]
                            )
                        )
                    )
                )
                if resp.status == 200:
                    self.logger.info("Added/Changed Deployment.")
                    self.logger.debug("Debug Information: (status code: 200, message: {})".format(resp.message))
                    if tenant_cnf_id not in self.orchestrator_timemeasurement.keys():
                        self.orchestrator_timemeasurement[tenant_cnf_id] = {}
                        self.orchestrator_timemeasurement_fetched[tenant_cnf_id] = {}
                    self.orchestrator_timemeasurement[tenant_cnf_id][int(deployment_submission_time)] = {
                                "action": orchestrator_msg_pb2.UPDATE_ACTION_UPDATE,
                                "deploymentSubmissionTimestamp": deployment_submission_time,
                                "validationTime" : validation_time,
                        }
                    self.orchestrator_timemeasurement_fetched[tenant_cnf_id][int(deployment_submission_time)] = False
                    self.store_to_persistence(self.tenants)
                else:
                    self.logger.error("An error (status code: {}) occured while scheduling the update of {}: {}".format(resp.status, tenant_cnf_id, resp.message))
                    raise Exception("An error (status code: {}) occured while scheduling the update of {}: {}".format(resp.status, tenant_cnf_id, resp.message))
                return resp.status, resp.message
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            self.set_status_of_tenant_cnf(tenantId, tenantFuncName, DeploymentStatus.FAILED)
            return 500, ex.__str__()

    def get_tenant_by_id(self, tenantId):
        """
        Returns the deployments of a tenant.
        
        Parameters:
        -----------
        tenantId : int
            ID of the tenant who has submitted the TDC
        """
        return self.tenants[tenantId]

    def get_tenants(self):
        """
        Get the struct of all submitted and deployed deployments of all tenants.
        """
        return self.tenants

    def remove_tenant(self, tenantId):
        """
        Remove all submitted and deployed functions of a tenant. 

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who has submitted the TDC
        """
        self.logger.info("Removing tenant id {}".format(tenantId))
        for tenantFuncName, tenant_func_config in self.tenants[tenantId].items():
            acceleratorType = AcceleratorType(self.tenants[tenantId][tenantFuncName]["TDC"]["TCD"]["acceleratorType"])
            self.remove(tenantId, tenantFuncName, acceleratorType)

    def remove(self, tenantId, tenantFuncName, acceleratorType : AcceleratorType):
        """
        Helper method for removing a TDC deployment.

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who has submitted the TDC
        tenantFuncName : str
            Function name provided in the TDC
        acceleratorType : AcceleratorType (Enum)
            Used Accelerator for TDC deployment marked for deletion
        """
        if tenantId in self.tenants.keys():
            if tenantFuncName in self.tenants[tenantId].keys():
                self.logger.debug("Removing tenant function {} of tenant id {}".format(tenantFuncName, tenantId))
                self.logger.debug("Tenant state before deleting: {:s}".format(self.tenants.__str__()))
                self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.REQUEST_DELETE
                self.logger.info("Request delete of tenant function {} of tenant id {}".format(tenantFuncName, tenantId))
                # til_config_msg = self.convert_til_to_tenantConfig_msg(self.tenants[tenantId][tenantFuncName]["TDC"])
                self.tenants[tenantId][tenantFuncName]["lastAction"] = orchestrator_msg_pb2.UPDATE_ACTION_DELETE
                acceleratorType = find_protobuf_acceleratorTypeEnum(acceleratorType.value)
                with grpc.insecure_channel(SCHEDULE_ADDRESS) as channel:
                    self.tenants_status[tenantId][tenantFuncName] = DeploymentStatus.SCHEDULING
                    stub = orchestrator_msg_pb2_grpc.SchedulerCommunicatorStub(channel)
                    deployment_submission_time = time.time()
                    resp : orchestrator_msg_pb2.ScheduleResponse = stub.Schedule(
                        orchestrator_msg_pb2.ScheduleRequest(
                            tenantMetadata = til_msg_pb2.TenantMetadata(
                                tenantId = tenantId,
                                tenantFuncName = tenantFuncName,
                                deploymentSubmissionId = int(deployment_submission_time)
                            ),
                            scheduleMessage = orchestrator_msg_pb2.ScheduleMessage(
                                updateAction = orchestrator_msg_pb2.UPDATE_ACTION_DELETE,
                                inTConfig = orchestrator_msg_pb2.INTenantConfig(
                                    tenantMetadata = til_msg_pb2.TenantMetadata(
                                        tenantId=tenantId,
                                        tenantFuncName=tenantFuncName
                                    ),
                                    acceleratorType = acceleratorType,
                                    updateAction= orchestrator_msg_pb2.UPDATE_ACTION_DELETE,
                                    runtimeRules=[
                                        til_msg_pb2.RuntimeRule(
                                            table=rule["table"],
                                            actionName=rule["actionName"],
                                            matches=[rule["match"]],
                                            actionParams=[rule["actionParams"]]
                                        ) for rule in self.tenants[tenantId][tenantFuncName]["TDC"]["TIL"]["runtimeRules"]
                                    ]
                                )
                            )
                            )
                        )
                    if resp.status == 200:
                        self.logger.info("Added/Changed Deployment.")
                        self.logger.debug("Debug Information: (status code: 200, message: {})".format(resp.message))
                        tenant_cnf_id  = self._build_tenant_cnf_id(tenantId, tenantFuncName)
                        if tenant_cnf_id not in self.orchestrator_timemeasurement.keys():
                            self.orchestrator_timemeasurement[tenant_cnf_id] = {}
                            self.orchestrator_timemeasurement_fetched[tenant_cnf_id] = {}
                        self.orchestrator_timemeasurement[tenant_cnf_id][int(deployment_submission_time)] = {
                            "action": orchestrator_msg_pb2.UPDATE_ACTION_DELETE,
                            "deploymentSubmissionTime": deployment_submission_time,
                        }
                        self.orchestrator_timemeasurement_fetched[tenant_cnf_id][int(deployment_submission_time)] = False
                        self.store_to_persistence(self.tenants)
                    else:
                        self.logger.error("An error (status code: {}) occured while scheduling the update of {}: {}".format(resp.status, tenantFuncName, resp.message))
               
                return False, "", ""
            else: 
                self.logger.error("Failed to delete function {} of tenant id {}: Tenant function {} does not exist".format(tenantFuncName, tenantId, tenantFuncName))
                return False, "", "Failed to delete function {} of tenant id {}: Tenant function {} does not exist".format(tenantFuncName, tenantId, tenantFuncName) 
        else: 
            self.logger.error("Failed to delete function {} of tenant id {}: Tenant id {} does not exist".format(tenantFuncName, tenantId, tenantId))
            return False, "", "Failed to delete function {} of tenant id {}: Tenant id {} does not exist".format(tenantFuncName, tenantId, tenantId) 

    # def synchronize_tenants_of_cluster(self):
    #     """
    #     Synchronize
    #     """
    #     self.logger.info("Synchronizing tenants existing in kubernetes cluster.")
    #     deployments : V1DeploymentList = self.nosUpdater.backend_obj.get_all_deployments_of_orchestrator()
    #     if deployments is not None:
    #         for deployment in deployments:
    #             if "OMuProCU-managed-by" in deployment.metadata.annotations:
    #                 if deployment.metadata.annotations["OMuProCU-managed-by"] == "orchestrator":
    #                     tenantId = deployment.metadata.labels["tenantId"]
    #                     tenantFuncName = deployment.metadata.labels["tenantFuncName"]
    #                     self.tenants.update({deployment.metadata.labels[tenantId]: { tenantFuncName : None }})
    #     self.logger.debug("Synchronized tenants: {}".format(deployments.__str__()))
    #     self.logger.info("Synchronized with kubernetes cluster")

    def apply_initial_tif_deployment(self):
        """
        Applies the initial TIF without any deployed OTFs. 
        Useful to reset the accelerator to the default state. 
        """
        try:
            # Call update once to reset the applied in-network
            with grpc.insecure_channel(INUPDATER_ADDRESS) as channel:
                stub = orchestrator_msg_pb2_grpc.INUpdaterCommunicatorStub(channel)
                resp: orchestrator_msg_pb2.INUpdateResponse = stub.Update(
                    orchestrator_msg_pb2.INUpdateRequest(
                        tenantMetadata = til_msg_pb2.TenantMetadata(
                            tenantId = self.MANAGEMENT_TENANT_ID,
                            tenantFuncName = self.MANAGEMENT_TENANT_FUNC_NAME
                        ),
                        inTConfig= [],
                        forceUpdate = True
                    )
                )
                if resp.status == 200:
                    return orchestrator_msg_pb2.INUpdateResponse(
                        status = 200,
                        message = "Apply of initial TIF code successful."
                    )
                else:
                    self.logger.error("Applying Initial TIF caused an error: {} (Status: {})".format(resp.message, resp.status))
                    raise Exception("Custom error while applying initial TIF code")
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
            return orchestrator_msg_pb2.INUpdateResponse(
                status = 500,
                message = "Error while apply initial TIF code: {}".format(str(ex))
            )

    def cleanup(self):
        """
        Cleanup and remove all deployed TDCs, apply the initial TIF and reset the Orchestrator to the initial state.
        """
        self.logger.info("Cleanup all tenant functions in kubernetes")
        msg = ""
        try:
            with grpc.insecure_channel(SCHEDULE_ADDRESS) as channel:
                stub = orchestrator_msg_pb2_grpc.SchedulerCommunicatorStub(channel)
                resp : orchestrator_msg_pb2.ScheduleRequest = stub.Cleanup(
                    orchestrator_msg_pb2.ScheduleRequest()
                )
            changed = resp.status == 200
            if len(self.tenants) >= 1:
                self.logger.info("Cleanup all tenant definitions")
                tenant_security_config = None
                with open("conf/tenant_security_config.json", "r") as f:
                    tenant_security_config = json.load(f)
                for tenantId in self.tenants.keys():
                    for tenantFuncName in self.tenants[tenantId].keys():
                        if self.tenants[tenantId][tenantFuncName]["TDC"]["INC"]["mainIngressName"] in tenant_security_config[str(tenantId)]["devices"]["default"]["mainIngressNames"]:
                            tenant_security_config[str(tenantId)]["devices"]["default"]["mainIngressNames"].remove(self.tenants[tenantId][tenantFuncName]["TDC"]["INC"]["mainIngressName"])
                with open("conf/tenant_security_config.json", "w") as f:
                    f.write("")
                    json.dump(tenant_security_config, f, indent=2)
                self.tenants = {}
                self.tenants_status = {}
                self.store_to_persistence(self.tenants)
                changed = changed or True
        except Exception as ex:
            self.logger.exception(ex)
            changed = False
            msg = ex.__str__()
        if changed:
            self.logger.info("Cleanup complete.")
            return 200, "Cleanup complete."
        elif resp is not None: 
            self.logger.error("Error occured while cleaning up: {}".format(resp.message))
            return 500, "Error occured while cleaning up: {}".format(resp.message)
        elif msg != "": 
            return 500, msg
    
    def set_dev_init_mode(self, dev_init_mode, accelerator_names=None):
        """
        Change the device initialization mode for a accelerator. 

        Parameters:
        -----------
        dev_init_mode : str | int
            Device init mode as number (can be mostly 0 or 1)
        accelerator_names : str | list
            Accelerator where the mode should be set. If no accelerator given, it will be set to all supported accelerators. If a list of accelerator is provided, it will applied to the provided list of accelerators.
        """
        if isinstance(dev_init_mode, str):
            dev_init_mode = int(dev_init_mode)
        self.dev_init_mode = dev_init_mode
        self.logger.debug("Apply DEV_INIT_MODE to supported accelerators: {}".format(dev_init_mode))
        if accelerator_names is not None and not isinstance(accelerator_names, list):
            with grpc.insecure_channel(INUPDATER_ADDRESS) as channel:
                inupdater_stub = orchestrator_msg_pb2_grpc.INUpdaterCommunicatorStub(channel)
                inupdater_stub.SetDevInitModeForAccelerator(orchestrator_msg_pb2.INUpdateRequest(
                    tenantMetadata = til_msg_pb2.TenantMetadata(),
                    devInitMode = dev_init_mode,
                    acceleratorType = find_protobuf_acceleratorTypeEnum(accelerator_names)
                ))
        else:
            if accelerator_names is None:
                accelerator_names = ACCELERATOR_CONFIGURATION.keys()
            for accelerator_name in accelerator_names:
                if not ACCELERATOR_CONFIGURATION[accelerator_name]["enabled"]:
                    continue
                with grpc.insecure_channel(INUPDATER_ADDRESS) as channel:
                    inupdater_stub = orchestrator_msg_pb2_grpc.INUpdaterCommunicatorStub(channel)
                    inupdater_stub.SetDevInitModeForAccelerator(orchestrator_msg_pb2.INUpdateRequest(
                        tenantMetadata = til_msg_pb2.TenantMetadata(),
                        devInitMode = dev_init_mode,
                        acceleratorType = find_protobuf_acceleratorTypeEnum(accelerator_name)
                    ))


def set_stop_state(signum, frame):
    global running
    running = False

def main_loop():
    global running
    while running:
        time.sleep(1)

if __name__ == "__main__":
    dev_init_mode = 0
    experiment_protocol = ""
    device_id = socket.gethostname()
    if len(argv) > 1:
        if "--no-cleanup" in argv:
            CLEANUP_BY_TERMINATE = False
        if "--dev-init-mode" in argv:
            index = argv.index("--dev-init-mode")
            if int(argv[index + 1]) == 0 or int(argv[index + 1]) == 1:
                dev_init_mode = argv[index + 1]
            else:
                raise Exception("No valid dev_init_mode parameter option!")
        if "--experiment-protocol" in argv:
            index = argv.index("--experiment-protocol")
            experiment_protocol = argv[index + 1]
        if "--device-id" in argv:
            index = argv.index("--device-id")
            device_id = argv[index + 1]
    try:
        logger = init_logger("Orchestrator")
        logger.info("Starting ReconfigScheduler")
        reconf_sched = ReconfigScheduler(auto_start_scheduler=False)
        reconf_sched.run()
        logger.info("ReconfigScheduler started")
        logger.info("Starting NOSUpdater")
        nosUpdater = NOSUpdater()
        nosUpdater.run()
        logger.info("NOSUpdater started")
        logger.info("Starting INUpdater")
        inUpdater = INUpdater()
        inUpdater.run()
        logger.info("INUpdater started")
        logger.info("Starting TIFUpdater Process")
        tifUpdater = TIFUpdater(device_id)
        tifUpdater.run()
        logger.info("TIFUpdater started")
        logger.info("Starting TCC...")
        tcc = TenantCommunicationController(address=TCC_ADDRESS)
        tcc.run()
        logger.info("TCC started.")
        logger.info("Starting RulesUpdater...")
        rulesUpdater = RulesUpdater()
        rulesUpdater.run()
        logger.info("RulesUpdater started.")
        logger.info("Starting Management Process")
        orchestrator = Orchestrator()
        orchestrator.experiment_protocol = experiment_protocol
        orchestrator.start()
        logger.info("Management Process started")
        logger.info("Setting dev_init_mode for supported devices...")
        orchestrator.set_dev_init_mode(dev_init_mode)
        logger.info("Set dev_init_mode successfully.")
        logger.info("Apply initial TIF Code...")
        orchestrator.apply_initial_tif_deployment()
        logger.info("Applying TIF successful.")
        logger.info("Starting ReconfigScheduler Loop")
        reconf_sched.start_scheduler_loop()
        logger.info("ReconfigScheduler Loop started")
        logger.info("To end the Orchestrator, type <Control-C>.")
        signal.signal(signal.SIGTERM, set_stop_state)
        running = True
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Got Interrupt. Terminating.")
        running = False
    except Exception as ex:
        logger.exception(ex, exc_info=True)
    finally:
        if CLEANUP_BY_TERMINATE:
            orchestrator.cleanup()
        orchestrator.stop()
        reconf_sched.terminate()
        nosUpdater.terminate()
        inUpdater.terminate()
        tcc.terminate()
        tifUpdater.terminate()