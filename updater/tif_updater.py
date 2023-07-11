
from concurrent import futures
import json
from multiprocessing import Process
import tempfile
from typing import Union

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict

from orchestrator_utils.til import orchestrator_msg_pb2_grpc, orchestrator_msg_pb2
from orchestrator_utils.bfrt_proto import bfruntime_pb2, bfruntime_pb2_grpc
from orchestrator_utils.logger.logger import init_logger
from orchestrator_utils.tools.accelerator_type import find_python_acceleratorTypeEnum
from orchestrator_utils.p4.v1 import p4runtime_pb2, p4runtime_pb2_grpc
from orchestrator_utils.p4.tmp import p4config_pb2
from orchestrator_utils.p4.bmv2 import helper as p4info_help

from conf.grpc_settings import TIF_ADDRESS
from conf.in_updater_settings import ACCELERATOR_CONFIGURATION


class TIFUpdateException(Exception):
    pass

class TIFUpdater(Process, orchestrator_msg_pb2_grpc.TIFUpdateCommunicatorServicer):
    """
    The Tenant INC Framework Updater process. This handles the accelerator code and configuration update as well as the management of the accelerator.
    """
    tofino_grpc_address = "localhost:50052"
    bmv2_grpc_address = "localhost:9000" # If using BMv2, the GRPC port must be set to this or change properly!
    applied_forwarding_pipeline_configs = {}

    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}, daemon=None) -> None:
        super().__init__(group, target, name, args, kwargs, daemon=daemon)
        self.grpc_server = grpc.server(futures.ThreadPoolExecutor(10))
        orchestrator_msg_pb2_grpc.add_TIFUpdateCommunicatorServicer_to_server(self, self.grpc_server)
        self.grpc_server.add_insecure_port(TIF_ADDRESS)
        self.logger = init_logger(self.__class__.__name__)
        for accelerator, configuration in ACCELERATOR_CONFIGURATION.items():
            if configuration["enabled"] :
                self.applied_forwarding_pipeline_configs[accelerator] = None

    def run(self) -> None:
        super().run()
        self.running = True
        self.grpc_server.start()
        self.logger.info("TIFUpdater started")
    
    def terminate(self) -> None:
        self.running = False
        self.grpc_server.stop(10)
        self.logger.info("Got Terminate. Stopping GRPC server.")

    def pull_config(self, acceleratorType : orchestrator_msg_pb2.AcceleratorType, address = None):
        """
        Pull Forwarding Pipeline Config from the given accelerator

        Parameters:
        -----------
        acceleratorType : AcceleratorType
            accelerator type from where the config should be pulled
        address : str
            GRPC address from where configuration should be pulled.
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
            return orchestrator_msg_pb2.TIFResponse(
                status=200,
                message="Hardware initialized."
            )
        elif request.acceleratorType == orchestrator_msg_pb2.ACCELERATOR_TYPE_BMV2:
            # No need to initialize hardware if using BMv2
            pass
        else:
            return orchestrator_msg_pb2.TIFResponse(
                status = 404,
                message =  "Accelerator type unkmown or unspecified."
            )
        return super().InitializeHardware(request, context)

    def pull_ForwardingPipelineConfig_from_tofino(self, address=None):
        """
        Pull the running Forwarding Pipeline Config from the tofino chip 
        and remove unneccessary parts (e.g. NonP4Config part).

        Parameters:
        -----------
        address : str
            GRPC address from where configuration should be pulled.
        """
        if address is None:
            address = self.tofino_grpc_address
        with grpc.insecure_channel(address) as channel:
            stub = bfruntime_pb2_grpc.BfRuntimeStub(channel)
            # try:
            resp : bfruntime_pb2.GetForwardingPipelineConfigResponse = stub.GetForwardingPipelineConfig(bfruntime_pb2.GetForwardingPipelineConfigRequest())
            resp_dict = MessageToDict(resp)
            resp_dict.pop("nonP4Config")
            return resp_dict["config"]
        
    def pull_ForwardingPipelineConfig_from_bmv2(self, address=None):
        """
        Pull the running Forwarding Pipeline Config from BMv2 
        and remove unneccessary parts (e.g. NonP4Config part).

        Parameters:
        -----------
        address : str
            GRPC address from where configuration should be pulled.
        """
        if address is None:
            address = self.tofino_grpc_address
        with grpc.insecure_channel(address) as channel:
            stub = p4runtime_pb2_grpc.P4RuntimeStub(channel)
            resp : p4runtime_pb2.GetForwardingPipelineConfigResponse = stub.GetForwardingPipelineConfig(p4runtime_pb2.GetForwardingPipelineConfigRequest())
            resp_dict = MessageToDict(resp)
            return resp_dict["config"]

    def convert_to_bfruntime_fwd_pipeline_conf_message(self, data : Union[dict, list]):
        """
        Converting the data to BFRuntime Forwarding Pipeline Config message.

        Parameters:
        -----------
        data : dict | list
            BFRuntime Forwarding Pipeline Config message data which should be converted.
        """
        if isinstance(data, list):
            return [ParseDict(config, bfruntime_pb2.ForwardingPipelineConfig()) for config in data]
        elif isinstance(data, dict):
            return [ParseDict(config, bfruntime_pb2.ForwardingPipelineConfig()) for config in data["config"]]
        else:
            raise TypeError("data must be one of type: dict or list")

    def send_SetForwardingPipelineConfig_request_to_tofino(self, req):
        """
        Send the ForwardingPipeline config request to tofino chip.

        Parameters:
        -----------
        req : BFRuntimeConfigRequest
            BarefootRuntimeConfigRequest object which is already generated previously.
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