

import base64
import hashlib
import json
import subprocess
import os
import shlex

from orchestrator_utils.til.til_msg_pb2 import TenantMetadata
from orchestrator_utils.logger.logger import init_logger
from orchestrator_utils.til.orchestrator_msg_pb2 import TIFRequest, AcceleratorType, Bmv2ForwardingPipelineConfig
from orchestrator_utils.bfrt_proto import bfruntime_pb2

from conf.in_updater_settings import ACCELERATOR_CONFIGURATION
from updater.accelerator.utils import create_path_bf_rt, create_path_context, create_path_tofino,generate_BFForwardingPipelineConfig_proto_msg, generate_BFProfileInfo_dict

class AcceleratorCompilerException(Exception):
    pass

class Accelerator(object):
    """
    General accelerator class. This contains the structure how to compile the code for a specified accelerator.
    """
    path = ""
    out_path = ""
    compiler = ""
    target = ""
    arch = ""
    std = ""
    last_compiled_code_parts = {}
    last_compiled_code_parts_hashes = {}

    def __init__(self, path, dev_init_mode=None) -> None:
        self.path = path
        self.logger = init_logger(self.__class__.__name__)
        self.dev_init_mode = dev_init_mode

    def load(self):
        """
        Abstract method to load code.
        """
        raise NotImplementedError()
    
    def encode_base64(self, data):
        if isinstance(data, str):
            data = data.encode()
        return base64.b64encode(data)

    def decode_base64(self, data):
        return base64.b64decode(data).decode()

    def hash_code(self, code):
        return hashlib.sha256(str(code).encode("utf-8"))

    def generate_hashes(self, code_dict : dict):
        """
        Generates hashes by a given dictionary containing code parts which should be hashed.
        """
        hashes = {}
        for name, code in code_dict.items():
            hashes[name] = self.hash_code(code)
        return hashes
    
    def load_file(self, path, binary=False):
        """
        Load file.

        Parameters:
        -----------
        path : str
            path to the file which should be loaded.
        binary : bool 
            The file should be loaded as binary file or not.
        """
        if binary:
            with open(path, "rb") as f:
                return f.read()
        else:
            with open(path) as f :
                return f.read()

    def load_compiled_code(self):
        """
        Abstract method to load compiled code.
        """
        raise NotImplementedError()

    def preprocess(self, definitions):
        """
        Abstract method to preprocess code.
        """
        raise NotImplementedError()

    def compile(self, code):
        """
        Abstract method to compile code.
        """
        raise NotImplementedError()

    def hash_compiled_code(self):
        """
        Abstract method to hash compiled code-
        """
        raise NotImplementedError()

    def compare_hashes(self, hashes_to_compare):
        """
        Abstract method to compare hashes of a accelerator.
        """
        raise NotImplementedError()

    def construct_code_parts_struct(self):
        """
        Abstract method to generate code parts struct.
        """
        raise NotImplementedError()

    def extract_code_parts(self, message):
        """
        Abstract method to extract code parts.
        """
        raise NotImplementedError()
    
    def cleanup_build(self):
        """
        Abstract method to cleanup build. 
        """
        raise NotImplementedError()
    
    def buildTIFRequest(self):
        """
        Abstract method to build a TIF Request Protobuf message for the accelerator.
        """
        raise NotImplementedError()


class Tofino(Accelerator):
    """
    Implementation for the Tofino Accelerator.
    """
    compiler = "/home/netlabadmin/BF/bf-sde-9.7.0/install/bin/bf-p4c"
    target = ""
    arch = ""
    std = ""
    p4runtime_files = ""
    main_construct_file = "tenant_inc.p4"
    defines = [
    ]
    switches = []
    otf_apply_parameter = "hdr, meta, ig_intr_md, ig_tm_md"

    def __init__(self, path="inc_template/" + ACCELERATOR_CONFIGURATION["tofino"]["template"].value, out_path=None, dev_init_mode=ACCELERATOR_CONFIGURATION["tofino"]["dev_init_mode"]) -> None:
        super().__init__(path, dev_init_mode)
        if out_path is None:
            self.out_path = os.path.splitext(self.main_construct_file)[0] + "/tofino/"
        else:
            self.out_path = out_path
        self.profile_name = "pipe"

    def compile(self, code, update_last : bool =True, retries : int =3):
        """
        Compile method for Tofino.

        Parameters:
        -----------
        code : str
            This is not needed for this accelerator.
        update_last : bool
            If true, load the compiled code to the accelerator.
        retries : int
            Count of retries until the compilation process should fail.
        """
        build_command = "./p4-build-cmake.sh {}".format(
             os.path.splitext(self.main_construct_file)[0]
        )
        env = os.environ.copy()
        self.logger.debug(build_command) 
        self.logger.info("Compiling Code")
        retry_count = 1
        process = None
        while True:
            process : subprocess.CompletedProcess = subprocess.run(shlex.split(build_command), cwd=self.path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            # TODO: The Compilation process fails at the first time if the directory is clean. Workaround: Trying another time.
            if retry_count <= retries and process.returncode != 0:
                self.logger.debug("stdout: " + str(process.stdout.decode()) + ", stderr:" + str(process.stderr.decode()))
                self.logger.warn("Compiling failed. Trying another time ({} attempt)".format(retry_count))
                retry_count += 1
            else:
                self.logger.info("Compilation successful.")
                break
        if process.returncode != 0:
            raise AcceleratorCompilerException("Error while compiling P4 Code (after {} retries): " + "{}\n\n".format(retries, process.stdout.decode()) + str(process.stderr.decode()))
        else: 
            self.logger.info("Builded Tofino P4 Code")
            self.logger.debug("stdout: " + str(process.stdout.decode()) + ", stderr:" + str(process.stderr.decode()))
            if update_last:
                bfrt_json, context, binary_code = self.load_compiled_code()
                self.update_last_code_parts(bfrt_json, context, binary_code)
                self.hash_compiled_code()

    def extract_code_parts(self, message : dict):
        code_parts = {}
        code_parts["bfrt_json"] = self.decode_base64(message["bfFwdPipelineConfig"][0]["bfruntimeInfo"])
        code_parts["context"] = self.decode_base64(message["bfFwdPipelineConfig"][0]["profiles"][0]["context"])
        code_parts["binary_code"] = message["bfFwdPipelineConfig"][0]["profiles"][0]["binary"]
        return code_parts
    
    def construct_code_parts_struct(self):
        """
        Generate general code parts struct without values.
        """
        return {
            "bfrt_json": "",
            "context": "",
            "binary_code": ""
        }

    def compare_hashes(self, hashes_to_compare):
        """
        Compare incoming hashes with the latest loaed ones.

        Parameters:
        -----------
        hashes_to_compare : dict
            dictionary of hashes which should be compared.
        """
        assert set(hashes_to_compare.keys()) == set(self.last_compiled_code_parts_hashes)
        for name, hash in hashes_to_compare.items():
            self.logger.debug(str(hash.hexdigest()) + " = " + str(self.last_compiled_code_parts_hashes[name].hexdigest()))
            if self.last_compiled_code_parts_hashes[name].hexdigest() != hash.hexdigest():
                return False
        return True

    def update_last_code_parts(self, bfrt_json, context, binary_code):
        """
        Load the latest code parts to the struct. 
        """
        self.last_compiled_code_parts["bfrt_json"] = bfrt_json
        self.last_compiled_code_parts["context"] = context
        self.last_compiled_code_parts["binary_code"] = binary_code
    
    def hash_compiled_code(self):
        """
        Hash the compiled code which was loaded last.
        """
        self.last_compiled_code_parts_hashes["bfrt_json"] = self.hash_code(self.last_compiled_code_parts["bfrt_json"])
        self.last_compiled_code_parts_hashes["context"] = self.hash_code(self.last_compiled_code_parts["context"])
        self.last_compiled_code_parts_hashes["binary_code"] = self.hash_code(self.last_compiled_code_parts["binary_code"])

    def load_compiled_code(self):
        """
        Load compiled code from files.
        """
        bfrt_json = self.load_file(create_path_bf_rt(self.path + self.out_path), True)
        context = self.load_file(create_path_context(self.path + self.out_path, self.profile_name), True)
        binary_code = self.load_file(create_path_tofino(self.path + self.out_path, self.profile_name, self.__class__.__name__.lower()), True)
        return bfrt_json, context, binary_code



    def cleanup_build(self):
        """
        Cleanup build directory.
        """
        build_command = "./cleanup-cmake.sh"
        self.logger.info(build_command)
        self.logger.info(shlex.split(build_command))
        self.logger.info(os.getcwd())
        try:
            process : subprocess.CompletedProcess = subprocess.run(shlex.split(build_command), cwd=self.path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if process.returncode == 0:
                self.logger.info("Cleaned up Tofino P4 build files")
                self.logger.debug("stdout: " + str(process.stdout.decode()) + ", stderr:" + str(process.stderr.decode()))
            else:
                raise AcceleratorCompilerException("Error while cleaning P4 build files: " + str(process.stderr.decode()))
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)

    def buildTIFRequest(self):
        """
        Build a TIF Request Protobuf message for the Tofino accelerator.
        """
        name = os.path.splitext(self.main_construct_file)[0]
        action = bfruntime_pb2.SetForwardingPipelineConfigRequest.Action.VERIFY_AND_WARM_INIT_BEGIN_AND_END
        profile_info_list = [generate_BFProfileInfo_dict(self.profile_name,
                            self.last_compiled_code_parts["context"],
                            self.last_compiled_code_parts["binary_code"],
                            [0,1])]
        config_list = [
            generate_BFForwardingPipelineConfig_proto_msg(
                name,
                self.last_compiled_code_parts["bfrt_json"],
                profile_info_list
            )
        ]
        return TIFRequest(
            tenantMetadata = TenantMetadata(),
            acceleratorType = AcceleratorType.ACCELERATOR_TYPE_TNA,
            bfFwdPipelineConfigRequest = bfruntime_pb2.SetForwardingPipelineConfigRequest(
                dev_init_mode = self.dev_init_mode.value,
                action = action,
                config = config_list
            )
        )


class BMv2(Accelerator):
    compiler = "/usr/bin/p4c-bm2-ss"
    target = "bmv2"
    arch = "v1model"
    std = "p4-16"
    p4runtime_files = ".p4info.txt"
    main_construct_file = "tenant_inc.p4"
    defines = [
        "FLOW_TYPE_FLOWS", 
        "SUBFLOW_WINDOW_POWER_OF_TWO=2", 
        "RF_TREE_COUNT=4", 
        "DEFAULT_RF_TREE_COUNT=1", 
        "FLOW_ACTIVE_TIMEOUT=16", 
        "FLOW_INACTIVE_TIMEOUT=16", 
        "FLOW_EXPORT_STRATEGY_EXPORT_PACKETS"
    ]
    switches = []
    otf_apply_parameter = "hdr, meta, standard_metadata"
    code_parts = {}

    def __init__(self, path="inc_template/bmv2/", out_path=None, dev_init_mode=ACCELERATOR_CONFIGURATION["bmv2"]["dev_init_mode"]) -> None:
        super().__init__(path, dev_init_mode)
        if out_path is None:
            self.out_path = "p4build"
        else:
            self.out_path = out_path

    def load_compiled_code(self):
        """
        Implementation for load compiled code for BMv2.
        """
        compiled_code = None
        p4info_code = None
        with open(self.path + "/p4build/" + os.path.splitext(self.main_construct_file)[0] + ".json") as f:
            compiled_code = json.load(f)
        with open(self.path + "/p4build/" + os.path.splitext(self.main_construct_file)[0] + self.p4runtime_files) as f:
            p4info_code = f.read()
        
        self.code_parts["compiled_code"] = compiled_code
        self.code_parts["compiled_code"] = p4info_code
        return compiled_code, p4info_code

    def compile(self, code):
        """
        Compile the code for BMv2
        
        Parameters: 
        -----------
        code : str
            Code which should be compiled for this accelerator. (This is not needed for this accelerator.)
        """
        build_command = "{} --target {} --arch {} --std {} -o {}/{}/{} --p4runtime-files {}/{}/{} --pp {}/{}.txt {} {}".format(
            self.compiler, 
            self.target, 
            self.arch, 
            self.std, 
            self.path, self.out_path, os.path.splitext(self.main_construct_file)[0] + ".json", 
            self.path, self.out_path, os.path.splitext(self.main_construct_file)[0] + self.p4runtime_files, 
            self.path, os.path.splitext(self.main_construct_file)[0], 
            self.path + "/" + self.main_construct_file,
            "-D" + " -D".join(self.defines)
        )
        self.logger.info(build_command)
        process : subprocess.CompletedProcess = subprocess.run(shlex.split(build_command), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if process.returncode == 0:
            self.logger.info("Builded BMv2 P4 Code")
            self.logger.debug("stdout: " + str(process.stdout) + ", stderr:" + str(process.stderr))
        else:
            raise AcceleratorCompilerException("Error while compiling P4 Code: " + str(process.stderr))

    def buildTIRequest(self):
        """
        Build a TIF Request Protobuf message for the Tofino accelerator.
        """
        code, p4info = self.load_compiled_code()
        return TIFRequest(
            tenantMetadata=TenantMetadata(),
            acceleratorType=AcceleratorType.ACCELERATOR_TYPE_BMV2,
            bmv2ForwardingPipelineConfig = Bmv2ForwardingPipelineConfig(
                compiledP4Code= str(code),
                compiledP4InfoCode= p4info,
            )
        )

acceleratorClasses = {
    "tofino" : Tofino,
    "bmv2" : BMv2
}