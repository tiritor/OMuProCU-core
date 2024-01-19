

from concurrent import futures
from datetime import datetime, timedelta
import logging
from multiprocessing import Process
import threading
import time

import grpc

from google.protobuf.json_format import MessageToDict, ParseDict
import pandas as pd

from orchestrator_utils.logger.logger import init_logger
from orchestrator_utils.tools.persistence import Persistor, ReconfigSchedulerStorage
from orchestrator_utils.til import orchestrator_msg_pb2, orchestrator_msg_pb2_grpc, til_msg_pb2, time_measurement_pb2_grpc, time_measurement_pb2

from conf.grpc_settings import INUPDATER_ADDRESS, NOSUPDATER_ADDRESS, SCHEDULE_ADDRESS, SCHEDULE_TIME_WINDOW_SIZE
from conf.time_measurement_settings import CURRENT_TIMEMEASUREMENT_TIMESCALE


class ReconfigScheduler(Process, orchestrator_msg_pb2_grpc.SchedulerCommunicatorServicer, time_measurement_pb2_grpc.TimeMeasurementCommunicatorServicer, Persistor):
    """
    Reconfiguration Scheduler is a core component which handles the main part of the OMuProCU deployment pipeline.
    """
    MANAGEMENT_TENANT_ID = 1
    MANAGEMENT_TENANT_FUNC_NAME = "OMuProCU-management"
    TIME_FRAME_SIZE = 10
    MAX_TENANT_COUNT = 5
    tenant_count = 0
    SLEEP_TIME = 5
    last_apply_timestamp = None
    RSS = ReconfigSchedulerStorage()
    rss_lock = threading.Lock()
    deployment_lock = threading.Lock()
    
    def __init__(self, time_frame_size=SCHEDULE_TIME_WINDOW_SIZE, auto_start_scheduler=True, max_tenant_count=5, group=None, target=None, name=None, args=(), kwargs={},
                 *, daemon=None, persistence_path="./data/persistence/", persistence_file="scheduler.dat", log_level=logging.INFO) -> None:
        super().__init__(group, target, name, args, kwargs, daemon=daemon)
        Persistor.__init__(self, persistence_path, persistence_file)
        self.logger = init_logger(self.__class__.__name__, log_level)
        if self.create_persistence_paths():
            self.RSS = self.read_from_persistence(ReconfigSchedulerStorage)
        self.auto_start_scheduler = auto_start_scheduler
        self.MAX_TENANT_COUNT = max_tenant_count
        self.TIME_FRAME_SIZE = time_frame_size
        self.inTConfigs = []
        self.scheduler_thread = None
        self.scheduler_monitoring_thread = None
        self.grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        orchestrator_msg_pb2_grpc.add_SchedulerCommunicatorServicer_to_server(self, self.grpc_server)
        time_measurement_pb2_grpc.add_TimeMeasurementCommunicatorServicer_to_server(self, self.grpc_server)
        self.grpc_server.add_insecure_port(SCHEDULE_ADDRESS)

        self.time_measurement_structure = {}
        self.time_measurement_structure_df = pd.DataFrame(columns=[
            "tenantId", "deploymentSubmissionId",
            "action", 
            "scheduledTime", "processingTime", 
            "nosPreprocessTime", "nosUpdateTime", 
            "inPreprocessTime", "inCompileTime", "inUpdateTime", "inPostProcessTime", 
            "tifPreprocessTime", "tifUpdateTime", "tifPostUpdateTime"])

    @staticmethod
    def _build_tenant_cnf_id(tenantId, tenantFuncName):
        return "t" + str(tenantId) + "-" + tenantFuncName

    @staticmethod
    def _split_tenant_cnf_id(tenant_cnf_id : str):
        return tenant_cnf_id.split("-")[0][1:], "-".join(tenant_cnf_id.split("-")[1:])

    def scheduler_monitor_loop(self):
        """
        The main monitoring loop for the scheduler. 
        """
        while self.monitoring_running: 
            running_timestamp = datetime.now()
            scheduled_tenants = None
            with self.rss_lock:
                assert self.RSS.in_scheduled_configs.keys() == self.RSS.nos_scheduled_configs.keys()
                self.tenant_count = len(self.RSS.in_scheduled_configs)
                scheduled_tenants = list(self.RSS.nos_scheduled_configs.keys())
            for t_id in scheduled_tenants:
                try:
                    # Check now the scheduled tenant configs in NOS
                    with self.rss_lock:
                        deployment_status = self.RSS.scheduled_deployment_status.get(t_id)
                        if deployment_status == orchestrator_msg_pb2.SCHEDULE_STATUS_SCHEDULED or deployment_status == orchestrator_msg_pb2.SCHEDULE_STATUS_DELETED:
                            continue

                        nos_config = self.RSS.nos_scheduled_configs.get(t_id)
                        if nos_config is None:
                            continue
                        with grpc.insecure_channel(NOSUPDATER_ADDRESS) as channel:
                            stub = orchestrator_msg_pb2_grpc.NOSUpdaterCommunicatorStub(channel)
                            resp = stub.GetUpdateStatus(orchestrator_msg_pb2.NOSUpdateRequest(
                                tenantMetadata = til_msg_pb2.TenantMetadata(
                                    tenantId = nos_config["tenantMetadata"]["tenantId"],
                                    tenantFuncName = nos_config["tenantMetadata"]["tenantFuncName"]
                                ),
                            ))
                            if resp.status == 200:
                                if resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_UPDATING:
                                    continue
                                elif resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_DELETED_FAILURE or resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_UPDATED_FAILURE:
                                        self.RSS.add(t_id, None, None, None, orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSING_FAILED)
                                elif (resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_UPDATED_SUCCESS and self.RSS.scheduled_deployment_status[t_id] != orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSED) or resp.updateStatus != orchestrator_msg_pb2.UPDATE_STATUS_DELETED_SUCCESS:
                                    with grpc.insecure_channel(INUPDATER_ADDRESS) as channel_2:
                                        stub = orchestrator_msg_pb2_grpc.INUpdaterCommunicatorStub(channel_2)
                                        resp = stub.GetUpdateStatus(orchestrator_msg_pb2.INUpdateRequest(
                                            tenantMetadata = til_msg_pb2.TenantMetadata(
                                                tenantId = nos_config["tenantMetadata"]["tenantId"],
                                                tenantFuncName = nos_config["tenantMetadata"]["tenantFuncName"]
                                            ),
                                        ))
                                        if resp.status == 200:
                                            if resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_UPDATED_SUCCESS:
                                                self.RSS.add(t_id, None, None, None, orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSED)
                                            elif resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_UPDATED_FAILURE or resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_DELETED_FAILURE:
                                                self.RSS.add(t_id, None, None, None, orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSING_FAILED)
                                            elif resp.updateStatus == orchestrator_msg_pb2.UPDATE_STATUS_DELETED_SUCCESS:
                                                self.RSS.add(t_id, None, None, None, orchestrator_msg_pb2.SCHEDULE_STATUS_DELETED)
                                        elif resp.status == 404:
                                            if deployment_status == orchestrator_msg_pb2.SCHEDULE_STATUS_SCHEDULED or deployment_status == orchestrator_msg_pb2.SCHEDULE_STATUS_UNSPECIFIED:
                                                self.logger.debug("Deployment {} is scheduled (or waiting to be scheduled) and not yet processed.".format(t_id))
                                                continue
                                            else:
                                                raise Exception("Error in INUPDATER: {} (status: {})".format(resp.message, resp.status))
                                        else:
                                            raise Exception("Error in INUPDATER: {} (status: {})".format(resp.message, resp.status))
                            elif resp.status == 404:
                                if deployment_status == orchestrator_msg_pb2.SCHEDULE_STATUS_SCHEDULED or deployment_status == orchestrator_msg_pb2.SCHEDULE_STATUS_UNSPECIFIED:
                                    self.logger.debug("Deployment {} is scheduled (or waiting to be scheduled) and not yet processed.".format(t_id))
                                    continue
                                else:
                                    raise Exception("Error in NOSUPDATER: {} (status: {})".format(resp.message, resp.status))
                            else:
                                raise Exception("Error in NOSUPDATER: {} (status: {})".format(resp.message, resp.status))
                except Exception as ex:
                    with self.rss_lock:
                        self.RSS.add(t_id, None, None, None, orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSING_FAILED)
                    self.logger.exception(ex)
                finally:
                    with self.rss_lock:
                        self.store_to_persistence(self.RSS)
            self.logger.info(self.RSS.scheduled_deployment_status)
            sleep_time = self.SLEEP_TIME - (datetime.now() - running_timestamp).seconds if self.SLEEP_TIME - (datetime.now() - running_timestamp).seconds > 0 else 0
            time.sleep(sleep_time) 

    def _collect_inTConfigs(self, inTConfig : dict):
        """
        Helper method to collect in-network tenant configurations which should be deployed to accelerators.

        Parameters:
        -----------
        inTConfig : dict
            in-network tenant configuration for a specific accelerator given from a submitted and scheduled TDC.
        """
        if self.inTConfigs is None:
            self.inTConfigs = []
        with self.rss_lock:
            self.inTConfigs.append(inTConfig)

    def _is_scheduled(self, tenant_cnf_id):
        """
        Helper method to check if a TDC is scheduled. 

        Parameters:
        -----------
        tenant_cnf_id : str
            Unique tenant cnf identifier for the deployment to be checked.
        """
        exist = False
        status = 0
        message = ""
        try:
            exist = self.RSS.checkKey(tenant_cnf_id)
        except Exception as ex:
            self.logger.error("Key does not exist in all dictionaries, Cleaning up")
            self.RSS.delete(tenant_cnf_id)
        if exist:
            status = 200
            if self.RSS.scheduled_deployment_status == orchestrator_msg_pb2.SCHEDULE_STATUS_SCHEDULED:
                message = "{} is scheduled for deployment".format(tenant_cnf_id)
                scheduled = True
            else:
                message = "{} is not scheduled for deployment".format(tenant_cnf_id)
                scheduled = False
        else:
            status = 404
            message = "{} does not exist and is not scheduled for deployment".format(tenant_cnf_id)
            scheduled = False
            
        return status, message, exist, scheduled
    
    def _delete_scheduled_config(self, tenant_cnf_id):
        """
        Helper method to delete existing, but scheduled TDC configs. 

        Parameters:
        -----------
        tenant_cnf_id : str
            Unique tenant cnf identifier for the one to be deleted scheduled TDC.
        """
        exist = False
        status = 0
        message = ""
        try:
            exist = self.RSS.checkKey(tenant_cnf_id)
        except Exception as ex:
            self.logger.warning("Key does not exist in all dictionaries, Cleaning up")
        if exist:
            status = 200
            with self.rss_lock:
                self.RSS.add(tenant_cnf_id, None, None, None, orchestrator_msg_pb2.SCHEDULE_STATUS_DELETED)
                self.store_to_persistence(self.RSS)
            message = "Scheduled deployment {} removed".format(tenant_cnf_id)
        else:
            status = 404
            message = "Cannot delete deployment {}: This was not scheduled for deployment".format(tenant_cnf_id)
        
        self.logger.debug(self.RSS.scheduled_deployment_status)
        return status, message
    
    def scheduler_loop(self):
        """
        The main scheduler part. This is where deployment pipeline is processed.
        """
        self.last_apply_timestamp = datetime.now()
        while self.running:
            running_timestamp = datetime.now()
            self.deployment_lock.acquire()
            assert self.RSS.in_scheduled_configs.keys() == self.RSS.nos_scheduled_configs.keys()
            self.tenant_count = len(self.RSS.in_scheduled_configs)
            scheduled_tenants = [tenant for tenant in list(self.RSS.nos_scheduled_configs.keys()) if self.RSS.scheduled_deployment_status[tenant] == orchestrator_msg_pb2.SCHEDULE_STATUS_SCHEDULED]
            if (self.last_apply_timestamp + timedelta(0, self.TIME_FRAME_SIZE) < datetime.now() or self.tenant_count >= self.MAX_TENANT_COUNT) and self.tenant_count > 0:
                try:
                    for t_id in scheduled_tenants:
                        try:
                            # Apply now the scheduled tenant configs in NOS
                            self.time_measurement_structure[t_id].update({"rolloutStarted" : time.time()})
                            config = None
                            inTConfig = None
                            with self.rss_lock:
                                self.RSS.add(t_id, None, None, None, orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSING)
                                config = self.RSS.nos_scheduled_configs.get(t_id)
                                inTConfig = self.RSS.in_scheduled_configs.get(t_id)
                            tenantId = config["tenantMetadata"]["tenantId"]
                            tenantFuncName = config["tenantMetadata"]["tenantFuncName"]
                            config = ParseDict(config, til_msg_pb2.TenantConfig())
                            with grpc.insecure_channel(NOSUPDATER_ADDRESS) as channel:
                                stub = orchestrator_msg_pb2_grpc.NOSUpdaterCommunicatorStub(channel)
                                resp : orchestrator_msg_pb2.NOSUpdateResponse = stub.Update(orchestrator_msg_pb2.NOSUpdateRequest(
                                    tenantMetadata = til_msg_pb2.TenantMetadata(
                                        tenantId = tenantId,
                                        tenantFuncName = tenantFuncName
                                    ),
                                    tConfig = config,
                                    updateAction = self.RSS.scheduled_updateActions.get(t_id)
                                ))
                                if resp.status != 200:
                                    raise Exception("Error while Updating NOS Deployment for {}: {}".format(t_id, resp.message))
                                else: 
                                    self.logger.info("Updated NOS deployment for {}".format(t_id))
                                    self.time_measurement_structure[t_id].update(self._create_nos_update_timemeasurement_struct(resp))
                            self._collect_inTConfigs(inTConfig)
                        except Exception as ex:
                            # Set state to failed for the current TDC 
                            with self.rss_lock:
                                self.RSS.add(t_id, None, None, None, orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSING_FAILED)
                            self.logger.exception(ex, exc_info=True)
                    if len(self.inTConfigs) > 0:
                        # Apply now the scheduled INC config/config updates in IN-Layer
                        with grpc.insecure_channel(INUPDATER_ADDRESS) as channel:
                            stub = orchestrator_msg_pb2_grpc.INUpdaterCommunicatorStub(channel)
                            resp : orchestrator_msg_pb2.INUpdateResponse = stub.Update(orchestrator_msg_pb2.INUpdateRequest(
                                tenantMetadata=til_msg_pb2.TenantMetadata(
                                    tenantId = self.MANAGEMENT_TENANT_ID,
                                    tenantFuncName = self.MANAGEMENT_TENANT_FUNC_NAME
                                ),
                                inTConfig=[
                                    ParseDict(inTConfig, orchestrator_msg_pb2.INTenantConfig()) for inTConfig in self.inTConfigs
                                ]
                            ))
                            if resp.status != 200:
                                with self.rss_lock:
                                    for t_id in scheduled_tenants:
                                        self.RSS.add(t_id, None, None, None, orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSING_FAILED)
                                    self.inTConfigs.clear()
                                self.logger.error("Error while updating IN deployment: {}".format(resp.message))
                                raise Exception("Error while IN Deployment for {}: {}".format(t_id, resp.message))
                            else:
                                with self.rss_lock:
                                    for t_id in scheduled_tenants:
                                        self.RSS.add(t_id, None, None, None, orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSED)
                                        self.time_measurement_structure[t_id].update(self._create_in_update_timemeasurement_struct(resp))
                                        self.time_measurement_structure[t_id].update({"rolloutFinished" : time.time()})
                                    self.inTConfigs.clear()
                                    self._postprocess_timemeasurement_struct()
                                self.logger.info("Updated IN deployment".format())
                                ### Apply existing runtime rules again and new ones also 
                                
                except Exception as ex:
                    with self.rss_lock:
                        self.RSS.add(t_id, None, None, None, orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSING_FAILED)
                    self.logger.exception(ex)
                self.last_apply_timestamp = datetime.now()
            self.deployment_lock.release()
            sleep_time = self.SLEEP_TIME - (datetime.now() - running_timestamp).seconds
            time.sleep(sleep_time if sleep_time > 0 else 0)

    def run(self) -> None:
        super().run()
        self.grpc_server.start()
        self.start_scheduler_monitoring_loop()
        if self.auto_start_scheduler:
            self.start_scheduler_loop()

    def start_scheduler_loop(self):
        """
        Start the scheduler loop.
        """
        self.running = True
        self.scheduler_thread = threading.Thread(target=self.scheduler_loop, args=())
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()

    def stop_scheduler_loop(self):
        """
        Stop the scheduler loop.
        """
        self.running = False
        self.scheduler_thread.join()

    def start_scheduler_monitoring_loop(self):
        """
        Start the scheduler monitoring loop.
        """
        self.monitoring_running = True
        self.scheduler_monitoring_thread = threading.Thread(target=self.scheduler_monitor_loop, args=())
        self.scheduler_monitoring_thread.start()

    def stop_scheduler_monitoring_loop(self):
        """
        Stop the scheduler monitoring loop.
        """
        self.monitoring_running = False
        self.scheduler_monitoring_thread.join()
        
    def terminate(self) -> None:
        self.running = False
        self.monitoring_running = False
        self.logger.info("Got Terminate. Stopping GRPC server.")
        self.grpc_server.stop(10)

    def _set_wait_for_update_status_for_TDC(self, tConfig, inTConfig):
        """
        Set the state of the given TDC parts to WAITING_FOR_UPDATE in the updaters. 

        Parameters:
        -----------
        tConfig : dict
            tenant isolation and deployment config which should be set to WAITING_FOR_UPDATE state.
        inTConfig : dict
            tenant isolation and deployment config which should be set to WAITING_FOR_UPDATE state.
        """
        with grpc.insecure_channel(NOSUPDATER_ADDRESS) as channel:
            stub = orchestrator_msg_pb2_grpc.NOSUpdaterCommunicatorStub(channel)
            resp: orchestrator_msg_pb2.NOSUpdateResponse = stub.SetUpdateStatus(orchestrator_msg_pb2.NOSUpdateRequest(
                tenantMetadata= til_msg_pb2.TenantMetadata(
                    tenantId= tConfig["tenantMetadata"]["tenantId"],
                    tenantFuncName= tConfig["tenantMetadata"]["tenantFuncName"]
                ),
                updateStatus = orchestrator_msg_pb2.UPDATE_STATUS_WAIT_FOR_UPDATE
            ))
        with grpc.insecure_channel(INUPDATER_ADDRESS) as channel:
            stub = orchestrator_msg_pb2_grpc.INUpdaterCommunicatorStub(channel)
            resp: orchestrator_msg_pb2.INUpdateResponse = stub.SetUpdateStatus(orchestrator_msg_pb2.INUpdateRequest(
                tenantMetadata= til_msg_pb2.TenantMetadata(
                    tenantId= inTConfig["tenantMetadata"]["tenantId"],
                    tenantFuncName= inTConfig["tenantMetadata"]["tenantFuncName"]
                ),
                updateStatus = orchestrator_msg_pb2.UPDATE_STATUS_WAIT_FOR_UPDATE
            ))
        
    def GetTimeMeasurementForMultipleTenants(self, request, context):
        """
        GRPC GetTimeMeasurementForMultipleTenants implementation for SchedulerCommunicator which is used to collect the timemeasurement for multiple tenants.
        """
        try:
            for label, row in self.time_measurement_structure_df.iterrows():
                tenantId, tenantFuncName = self._split_tenant_cnf_id(row["tenantId"])
                yield time_measurement_pb2.TimeMeasurementResponse(
                    tenantMetadata = til_msg_pb2.TenantMetadata(
                        tenantId = int(tenantId),
                        tenantFuncName = tenantFuncName,
                        deploymentSubmissionId = int(row["deploymentSubmissionId"])
                    ),
                    timeMeasurement = time_measurement_pb2.TimeMeasurement(
                        scheduleTimeMeasurement = time_measurement_pb2.ScheduleTimeMeasurement(
                            scheduledTime = int(row["scheduledTime"]),
                            processingTime= int(row["processingTime"]),
                        ),
                        nosUpdateTimeMeasurement = time_measurement_pb2.NOSUpdateTimeMeasurement(
                            nosPreprocessTime = int(row["nosPreprocessTime"]),
                            nosUpdateTime = int(row["nosUpdateTime"]),
                        ),
                        inUpdateTimeMeasurement = time_measurement_pb2.INUpdateTimeMeasurement(
                            inPreprocessTime = int(row["inPreprocessTime"]),
                            inCompileTime = int(row["inCompileTime"]),
                            inUpdateTime = int(row["inUpdateTime"]),
                            inPostProcessTime = int(row["inPostProcessTime"]),
                        ),
                        tifTimeMeasurement = time_measurement_pb2.TIFTimeMeasurement(
                            tifPreprocessTime = int(row["tifPreprocessTime"]),
                            tifUpdateTime = int(row["tifUpdateTime"]),
                            tifPostUpdateTime = int(row["tifPostUpdateTime"]),
                        )
                    )
                )
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)

    def RemoveTimeMeasurementFromTenant(self, request, context):
        """
        GRPC RemoveTimeMeasurementFromTenant implementation for SchedulerCommunicator which is used to remove the timemeasurement data for a tenant deployment.
        """
        try:
            tenant_cnf_id = self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)
            self.time_measurement_structure_df = self.time_measurement_structure_df.loc[~((self.time_measurement_structure_df["tenantId"] == tenant_cnf_id) & (self.time_measurement_structure_df["deploymentSubmissionId"] == request.tenantMetadata.deploymentSubmissionId))]
            return time_measurement_pb2.TimeMeasurementResponse(
                status=200,
                message= "TimeMeasurement removed"
            )
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)

    def RestartSchedulerLoop(self, request, context):
        """
        GRPC RestartSchedulerLoop implementation for SchedulerCommunicator which is used to trigger a restart the scheduler loop.
        """
        try:
            self.stop_scheduler_loop()
            time.sleep(0.33)
            self.start_scheduler_loop()
            self.logger.info("Restarted SchedulerLoop as requested.")
            return orchestrator_msg_pb2.ScheduleResponse(status = 200, message="Restarted ReconfigScheduler Loop.")
        except Exception as ex:
            self.logger.exception(ex)
            return orchestrator_msg_pb2.ScheduleResponse(status= 500, message= "Error while restarting Reconfig Scheduler.")

    def Schedule(self, request, context):
        """
        GRPC Schedule implementation for SchedulerCommunicator which is one of the core methods used to schedule a given TDC.
        """
        try:
            tenant_cnf_id = self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)
            if tenant_cnf_id in self.RSS.scheduled_deployment_status.keys():
                deployment_status  = self.RSS.scheduled_deployment_status.get(tenant_cnf_id)

                if deployment_status == orchestrator_msg_pb2.SCHEDULE_STATUS_PROCESSING or self.deployment_lock.locked():
                    raise Exception("The previous scheduled deployment of {} is processing at the moment. Please wait for deployment of this until scheduling an updated version.".format(tenant_cnf_id))
                elif deployment_status == orchestrator_msg_pb2.SCHEDULE_STATUS_SCHEDULED:
                    if request.scheduleMessage.updateAction == orchestrator_msg_pb2.UPDATE_ACTION_DELETE:
                        with self.deployment_lock:
                            self._delete_scheduled_config(tenant_cnf_id)
                            return orchestrator_msg_pb2.ScheduleResponse(
                                    status = 200,
                                    message= "Removed scheduled deployment of {}".format(tenant_cnf_id)
                                )
                elif deployment_status == orchestrator_msg_pb2.SCHEDULE_STATUS_UNSPECIFIED:
                    raise Exception("The previous deployment {} is in unspecified state. Please delete it first and reschedule.".format(tenant_cnf_id))

            tConfig = MessageToDict(request.scheduleMessage.tConfig)
            inTConfig = MessageToDict(request.scheduleMessage.inTConfig)
            tConfig = tConfig if len(tConfig) > 0 else None
            inTConfig = inTConfig if len(inTConfig) > 0 else None
            try:
                self.deployment_lock.acquire(timeout=10)
                if tConfig is not None and inTConfig is not None:
                    if isinstance(tConfig, list) or isinstance(inTConfig, list):
                        assert len(tConfig) == len(inTConfig)
                        for i in range(len(tConfig)):
                            if inTConfig[i]["updateAction"] == "UPDATE_ACTION_UPDATE":
                                self._set_wait_for_update_status_for_TDC(tConfig[i], inTConfig[i])
                    else:
                        if tenant_cnf_id in self.RSS.nos_scheduled_configs.keys():
                            if inTConfig["updateAction"] == "UPDATE_ACTION_UPDATE":
                                self._set_wait_for_update_status_for_TDC(tConfig, inTConfig)
                    
                with self.rss_lock:
                    self.RSS.add(tenant_cnf_id, request.scheduleMessage.updateAction, tConfig, inTConfig, orchestrator_msg_pb2.SCHEDULE_STATUS_SCHEDULED)
                    if tenant_cnf_id not in self.time_measurement_structure.keys():
                        self.time_measurement_structure[tenant_cnf_id]  = {}
                        self.time_measurement_structure[tenant_cnf_id]["deploymentSubmissionId"] = request.tenantMetadata.deploymentSubmissionId
                    self.time_measurement_structure[tenant_cnf_id]["action"] = request.scheduleMessage.updateAction
                    self.time_measurement_structure[tenant_cnf_id]["deploymentScheduled"] = time.time()
                    self.store_to_persistence(self.RSS)
                    self.logger.info(self.RSS.__str__())
            finally:
                self.deployment_lock.release()
                
            return orchestrator_msg_pb2.ScheduleResponse(
                status = 200,
                message= "Scheduled {}".format(tenant_cnf_id)
            )
            
        except Exception as ex:
            self.logger.exception("Error while scheduling {}: {}".format(tenant_cnf_id, ex), exc_info=True)
            return orchestrator_msg_pb2.ScheduleResponse(
                status = 400,
                message = "Error while scheduling {}: {}".format(tenant_cnf_id, ex.__str__())
            )

    def IsScheduled(self, request, context):
        """
        GRPC IsScheduled implementation for SchedulerCommunicator which is used to check if a TDC is scheduled at the moment or not.
        """
        tenant_cnf_id = self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)
        status, message, _, _ = self._is_scheduled(tenant_cnf_id)

        return orchestrator_msg_pb2.ScheduleResponse(
            status=status,
            message = message,
            tConfigs = []
        )

    def SetScheduleStatus(self, request, context):
        """
        GRPC SetScheduleStatus implementation for SchedulerCommunicator which is used to update the schedule status for a specific TDC deplyment.
        """
        tenant_cnf_id = self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)
        exist = False
        try:
            exist = self.RSS.checkKey(tenant_cnf_id)
        except Exception as ex:
            self.logger.error("Key does not exist in all dictionaries, Cleaning up")
            self.RSS.delete(tenant_cnf_id)
        if exist:
            status = 200
            with self.rss_lock:
                self.RSS.scheduled_deployment_status[tenant_cnf_id] = request.scheduleStatus
                self.store_to_persistence(self.RSS)
            message = "Status of deployment {} updated to {}.".format(tenant_cnf_id, request.scheduleStatus)
        else:
            status = 404
            message = "Cannot update status of {}: This is not scheduled for deployment".format(tenant_cnf_id)
        
        self.logger.info(self.RSS.scheduled_deployment_status)

        return orchestrator_msg_pb2.ScheduleResponse(
            status=status,
            message = message,
            scheduleStatus = request.scheduleStatus,
        )
    
    def GetScheduleStatus(self, request, context):
        """
        GRPC GetScheduleStatus implementation for SchedulerCommunicator which is used to get the schedule status for a specific TDC deplyment.
        """
        tenant_cnf_id = self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)
        # self.RSS = self.read_from_persistence(ReconfigSchedulerStorage)
        exist = False
        try:
            exist = self.RSS.checkKey(tenant_cnf_id)
        except Exception as ex:
            self.logger.exception("Error while checking key:", ex,exc_info=True)
            self.logger.error("Key does not exist in all dictionaries, Cleaning up")
            with self.rss_lock:
                self.RSS.delete(tenant_cnf_id)
        scheduleStatus = orchestrator_msg_pb2.SCHEDULE_STATUS_UNSPECIFIED
        if exist:
            status = 200
            with self.rss_lock:
                scheduleStatus = self.RSS.scheduled_deployment_status[tenant_cnf_id]
                self.store_to_persistence(self.RSS)
            message = "Status of deployment {} updated to {}.".format(tenant_cnf_id, request.scheduleStatus)
        else:
            status = 404
            message = "Cannot get schedule status of {}: This is not scheduled for deployment".format(tenant_cnf_id)
        
        self.logger.info(self.RSS.scheduled_deployment_status)

        return orchestrator_msg_pb2.ScheduleResponse(
            status=status,
            message = message,
            scheduleStatus = scheduleStatus,
        )
    
    def DeleteScheduledConfig(self, request, context):
        """
        GRPC DeleteScheduledConfig implementation for SchedulerCommunicator which is used to delete a specific scheduled TDC deplyment.
        """
        tenant_cnf_id = self._build_tenant_cnf_id(request.tenantMetadata.tenantId, request.tenantMetadata.tenantFuncName)
        with self.deployment_lock:
            status, message = self._delete_scheduled_config(tenant_cnf_id)

        return orchestrator_msg_pb2.ScheduleResponse(
            status=status,
            message = message,
        )

    def Cleanup(self, request, context):
        """
        GRPC DeleteScheduledConfig implementation for SchedulerCommunicator which is used to cleanup all TDC deplyments in NOS and all accelerators.
        """
        try:
            self.deployment_lock.acquire()
            scheduled_tenants = [tenant for tenant in list(self.RSS.nos_scheduled_configs.keys()) if self.RSS.scheduled_deployment_status[tenant] == orchestrator_msg_pb2.SCHEDULE_STATUS_SCHEDULED]
            for t_id in scheduled_tenants:
                self.RSS.scheduled_deployment_status[t_id] = orchestrator_msg_pb2.SCHEDULE_STATUS_DELETED
            with grpc.insecure_channel(NOSUPDATER_ADDRESS) as channel:
                stub = orchestrator_msg_pb2_grpc.NOSUpdaterCommunicatorStub(channel)
                resp: orchestrator_msg_pb2.NOSUpdateResponse = stub.Cleanup(
                    orchestrator_msg_pb2.NOSUpdateRequest(

                    )
                )
                if resp.status == 200:
                    with grpc.insecure_channel(INUPDATER_ADDRESS) as channel:
                        stub = orchestrator_msg_pb2_grpc.INUpdaterCommunicatorStub(channel)
                        resp: orchestrator_msg_pb2.INUpdateResponse = stub.Cleanup(
                            orchestrator_msg_pb2.INUpdateRequest(

                            )
                        )
                        if resp.status == 200:
                            tenants = list(self.RSS.nos_scheduled_configs.keys())
                            for t_id in tenants:
                                with self.rss_lock:
                                    self.RSS.delete(t_id)
                                    self.store_to_persistence(self.RSS)
                            self.deployment_lock.release()
                            return orchestrator_msg_pb2.ScheduleResponse(
                                status = 200,
                                message = "Scheduled cleanup was successful."
                            )
                        else:
                            raise Exception("Scheduled cleanup failed: Error while cleaning up IN-Code.")
                else: 
                    raise Exception("Scheduled cleanup failed: Error while cleaning up NOS.")
        except Exception as ex:
            self.deployment_lock.release()
            self.logger.exception(ex, exc_info=True)
            return orchestrator_msg_pb2.ScheduleResponse(
                status = 500,
                message = "Error while cleanup"
            )
    
    def GetScheduledConfigs(self, request, context):
        """
        GRPC GetScheduledConfigs implementation for SchedulerCommunicator which is used to get all scheduled TDC deplyment.
        """
        return orchestrator_msg_pb2.ScheduleResponse(
            status=200,
            message="These deployments are scheduled",
            tConfigs = self.RSS.values()
        )
    
    def _create_in_update_timemeasurement_struct(self, response: orchestrator_msg_pb2.INUpdateResponse):
        """
        Converting INUpdate and TIFUpdate timemeasurement protobuf messages to dictionaries

        Parameters:
        -----------
        response : INUpdateResponse
            The response from the In-Network Updater with the timemeasurement data from the update process of the TIF and the general IN-Update.
        """
        inUpdateTimeMeasurementDict = MessageToDict(response.inUpdateTimeMeasurement)
        tifUpdateTimeMeasurementDict = MessageToDict(response.tifTimeMeasurement)
        # Python 3.9: inUpdateTimeMeasurementDict | tifUpdateTimeMeasurementDict
        return {**inUpdateTimeMeasurementDict, **tifUpdateTimeMeasurementDict}

    def _create_nos_update_timemeasurement_struct(self, response : orchestrator_msg_pb2.NOSUpdateResponse):
        """
        Converting NOSUpdate timemeasurement protobuf message to dictionary

        Parameters:
        -----------
        response : NOSUpdateResponse
            The response from the NOS Updater with the timemeasurement data from the update process of the NOS for the deployed TDCs
        """
        return MessageToDict(response.nosUpdateTimeMeasurement)
        
    def _postprocess_timemeasurement_struct(self):
        """
        Collect the timemeasurements, construct and save the data.
        """
        for tenant_cnf_id in self.time_measurement_structure.keys():
                self.time_measurement_structure[tenant_cnf_id]["processingTime"] = int((self.time_measurement_structure[tenant_cnf_id]["rolloutFinished"] - self.time_measurement_structure[tenant_cnf_id]["rolloutStarted"]) * CURRENT_TIMEMEASUREMENT_TIMESCALE.value)
                self.time_measurement_structure[tenant_cnf_id]["scheduledTime"] = int((self.time_measurement_structure[tenant_cnf_id]["rolloutStarted"] - self.time_measurement_structure[tenant_cnf_id]["deploymentScheduled"]) * CURRENT_TIMEMEASUREMENT_TIMESCALE.value)
                
                self.time_measurement_structure[tenant_cnf_id].pop("rolloutStarted") 
                self.time_measurement_structure[tenant_cnf_id].pop("rolloutFinished")
                self.time_measurement_structure[tenant_cnf_id].pop("deploymentScheduled")
        
        df = pd.DataFrame.from_dict(self.time_measurement_structure, orient="index", columns=self.time_measurement_structure_df.columns[1:])
        df.index.name = "tenantId"
        df.reset_index(inplace=True)
        self.time_measurement_structure_df = pd.concat([self.time_measurement_structure_df, df], ignore_index=True)
        self.time_measurement_structure_df.fillna(0, inplace=True)
        self.time_measurement_structure_df.to_csv("reconfig_timemeasurement.csv", index=False)
        self.time_measurement_structure.clear()

if __name__ == "__main__":
    test = ReconfigScheduler()
    test.run()