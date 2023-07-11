
from datetime import datetime
import logging
import re
from orchestrator_utils.config import TENANT_ACCELERATOR_PATH
import yaml
import os

from kubernetes.client import V1Deployment, CoreV1Api, V1Namespace, V1NamespaceList, V1DeploymentList
from kubernetes import config, client

from orchestrator_utils.logger.logger import init_logger
from orchestrator_utils.tools.persistence import Persistor

NAME = re.compile('name "([^"]+)" is in use')

class AbstractKubeBackendHandler(object):
    """
    Parent class for Kubernetes backend handling
    """
    PREFIX = "omuprocu"

    def apply(self):
        raise NotImplementedError

    def delete(self):
        raise NotImplementedError

    def _add_tenant_communication_unix_socket_volume(self, socket_name):
        raise NotImplementedError

class KubeBackendHandler(AbstractKubeBackendHandler, Persistor):
    """
    Main class for Kubernetes backend handling
    """
    tenant_cnfs = {}

    def __init__(self, params, persistence_path="./persistence/", persistence_file="kube_backend_tenant_cnfs.dat", socket_root_dir=TENANT_ACCELERATOR_PATH) -> None:
        super().__init__(persistence_path, persistence_file, self.__class__.__name__)
        self.logger = init_logger(self.__class__.__name__, logging.INFO)
        self.params = params
        self.socket_root_dir = socket_root_dir
        if not self.create_persistence_paths():
            # Persisted data available, loading it.
            self.tenant_cnfs = self.read_from_persistence()

    def __exit__(self, exc_type, exc_value, traceback):
        self.store_to_persistence(self.tenant_cnfs)

    def update_params(self, params):
        """
        Update the params struct.

        Parameters:
        -----------
        params : dict
            dictionary with parameter values for the deployment which should be handled
        """
        self.params = params
        self.params["name"] = self.get_pod_name()

    def get_pod_name(self):
        """
        Get the pod name from the Kubernetes deployment.
        """
        if 'kube_file' in self.params:
            with open(self.params['kube_file']) as f:
                pod = yaml.safe_load(f)
                if 'metadata' in pod:
                    pod_name = pod['metadata'].get('name')
                    return pod_name
                else:
                    self.logger.error(
                        "No metadata in Kube file!\n%s" % pod)
        else:
            with open(self.params['kube_file']) as text:
                re_pod = NAME.search(text.read())
                if re_pod:
                    pod_name = re_pod.group(1)
                    return pod_name
                if not pod_name:
                    self.logger.error("Deployment doesn't have a name!")

    def _get_tenant_namespace_for_deployment(self, tenantId, deployment):
        """
        Get the tenant namespace for this deployment or generate tenant namespace name for it

        Parameters:
        -----------
        tenantId : str | int
            ID of tenant which wants to deploy the TDC
        
        deployment : dict
            Kubernetes deployment which was part in the TDC of the tenant
        """
        p = re.compile(self.PREFIX + '-t[0-9]+' + "-" + '[a-zA-Z0-9\-]*')
        if isinstance(deployment, V1Deployment):
            deployment_dict = deployment.to_dict()
        else:
            deployment_dict = deployment
        if p.match(deployment_dict["metadata"]["namespace"]) is None:
            return self.PREFIX + "-t" + str(tenantId) + "-" + deployment_dict["metadata"]["namespace"]
        else:
            return deployment_dict["metadata"]["namespace"]

    def get_namespaced_deployments_by_label(self, namespace, labels: dict):
        """
        Collect all deployments deployed in a given namespace and return it as list.

        Parameters:
        -----------
        namespace : str
            Name of the namespace where all deployments should be collected.
        labels : dict
            dictionary with labels which should be set in the deployment.
        """
        # conf = config.list_kube_config_contexts()
        # config.load_kube_config( context="omuprocu") # external way
        config.load_kube_config() # internal way

        k8s_apps_v1 = client.AppsV1Api()

        labels_str = ",".join(["{}:{}".format(key, value) for key, value in labels.items()])
        deployments : V1DeploymentList = k8s_apps_v1.list_namespaced_deployment(namespace, label_selector=labels_str)
        return deployments

    def get_all_deployments_of_namespace(self, namespace):
        """
        Collect all deployments deployed in a given namespace and return it as list.

        Parameters:
        -----------
        namespace : str
            Name of the namespace where all deployments should be collected.
        """
        # conf = config.list_kube_config_contexts()
        # config.load_kube_config( context="omuprocu") # external way
        config.load_kube_config() # internal way

        k8s_apps_v1 = client.AppsV1Api()

        return k8s_apps_v1.list_namespaced_deployment(namespace)

    def get_all_deployments_of_orchestrator(self):
        """
        Collect all deployments deployed and managed from the orchestrator and return it as list.
        """
        orchestrator_deployments = []

        # conf = config.list_kube_config_contexts()
        # config.load_kube_config( context="omuprocu") # external way
        config.load_kube_config() # internal way

        k8s_apps_v1 = client.AppsV1Api()
        k8s_core_v1 = client.CoreV1Api()

        namespaces: V1NamespaceList = k8s_core_v1.list_namespace()

        for namespace in namespaces.items:
            if self.PREFIX in namespace.metadata.name:
                deployments : V1DeploymentList = k8s_apps_v1.list_namespaced_deployment(namespace.metadata.name)
                orchestrator_deployments += deployments.items

        return orchestrator_deployments

    def create(self, tenantId, kube_file=None):
        """
        Create the CNF deployment on the Kubernetes cluster

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who wants to deploy the tenant CNF.
        kube_file : str
            If kube_file is String, it will be handled as file path, else it should be a YAML-based string.
        """
        # conf = config.list_kube_config_contexts()
        # config.load_kube_config( context="orchestrator-test-vm") # external way
        config.load_kube_config() # internal way

        tenant_cnf_id = ""

        changed = False

        if kube_file is not None:
            kf = kube_file
        else:
            kf = self.params["kube_file"]
        dep = ""
        if os.path.isfile(kf):
            with open(kf) as f:
                dep = yaml.safe_load(f)
        else:
            dep = yaml.safe_load(kf)
        
        k8s_apps_v1 = client.AppsV1Api()
        k8s_core_v1 = client.CoreV1Api()

        old_deployment_exists = False
        namesp_exist = False

        tenant_cnf_id = "t" + str(tenantId) + "-" + dep["metadata"]["labels"]["tenantFuncName"]

        namespace_name = self._get_tenant_namespace_for_deployment(tenantId, dep)
        dep["metadata"]["namespace"] = namespace_name
        namespaces: V1NamespaceList = k8s_core_v1.list_namespace()
        for i, namespace in enumerate(namespaces.items):
            if namespace_name == namespace.metadata.name:
                namesp_exist = True
        if not namesp_exist:
            self.logger.warn("Namespace {:s} does not exist! Creating it.".format(dep["metadata"]["name"]))
            namesp_resp, _, _ = self._create_tenant_namespace(tenantId, dep)
            self.logger.warn("Namespace {:s} created. status={:s}".format(namespace_name, namesp_resp.metadata.name))
        else:
            deployments : V1DeploymentList = k8s_apps_v1.list_namespaced_deployment(namespace_name)
            for i, deployment in enumerate(deployments.items):
                if dep["metadata"]["name"] == deployment.metadata.name:
                    old_deployment_exists = True
                    break
        if not old_deployment_exists:
            resp = k8s_apps_v1.list_namespaced_deployment(namespace=namespace_name, label_selector='tenantFuncName={:s},tenantId={:s}'.format(dep["metadata"]["labels"]["tenantFuncName"], dep["metadata"]["labels"]["tenantId"]))
            if len(resp.items) > 0:
                self.logger.error("Could not create deployment: Deployment {:s} exists!".format(resp.items[0].metadata.name))
                return changed, "", "Could not create deployment: Deployment {:s} exists!".format(resp.items[0].metadata.name)
        else:
            try:
                resp = k8s_apps_v1.create_namespaced_deployment(
                body=dep, namespace=namespace_name)
                self.logger.debug("Deployment created. status='%s'" % resp.status)
            except client.ApiException as ex:
                self.logger.error("Failed to create Deployment: {} ".format(ex))
                return changed, "", "Failed to create Deployment: {} ".format(ex)
        if tenant_cnf_id not in self.tenant_cnfs.keys():
            self.tenant_cnfs.update({tenant_cnf_id: dep})
            changed = True
            self.logger.debug("Added {} to Tenant_CNF dict".format(tenant_cnf_id))
        elif self.tenant_cnfs.get(tenant_cnf_id) == dep:
            self.logger.debug("No changes since deployment for {} is unchanged.".format(tenant_cnf_id))
        else:
            self.tenant_cnfs.update({tenant_cnf_id: dep})
            changed = True
            self.logger.debug("Updated {} in Tenant_CNF dict".format(tenant_cnf_id))
        self.store_to_persistence(self.tenant_cnfs)
        return changed, "", ""

    def apply(self, tenantId, kube_file=None):
        """
        Apply the CNF deployment on the Kubernetes cluster

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who wants to deploy the tenant CNF.
        kube_file : str
            If kube_file is String, it will be handled as file path, else it should be a YAML-based string.
        """
        # conf = config.list_kube_config_contexts()
        # config.load_kube_config( context="orchestrator-test-vm") # external way
        config.load_kube_config() # internal way

        tenant_cnf_id = ""

        changed = False

        dep = ""

        if kube_file is not None:
            kf = kube_file
        else:
            kf = self.params["kube_file"]
        if isinstance(kf, str):
            if os.path.exists(kf):
                with open(kf) as f:
                    dep = yaml.safe_load(f)
            else:
                dep = yaml.safe_load(kf)
        else:
            dep = kf
            
        k8s_apps_v1 = client.AppsV1Api()
        k8s_core_v1 = client.CoreV1Api()

        old_deployment_exists = False
        namesp_exist = False

        tenant_cnf_id = "t" + str(tenantId) + "-" + dep["metadata"]["labels"]["tenantFuncName"]

        namespace_name = self._get_tenant_namespace_for_deployment(tenantId, dep)
        dep["metadata"]["namespace"] = namespace_name

        namespaces: V1NamespaceList = k8s_core_v1.list_namespace()
        for i, namespace in enumerate(namespaces.items):
            if namespace_name == namespace.metadata.name:
                namesp_exist = True

        if not namesp_exist:
            self.logger.warn("Namespace {:s} does not exist! Creating it.".format(dep["metadata"]["name"]))
            namesp_resp, _, _ = self._create_tenant_namespace(tenantId, dep)
            self.logger.warn("Namespace {:s} created. status={:s}".format(namespace_name, namesp_resp.metadata.name))
        else:
            deployments : V1DeploymentList = k8s_apps_v1.list_namespaced_deployment(namespace_name)
            for i, deployment in enumerate(deployments.items):
                if dep["metadata"]["name"] == deployment.metadata.name:
                    old_deployment_exists = True
        if not old_deployment_exists:
            resp = k8s_apps_v1.list_namespaced_deployment(namespace=namespace_name, label_selector='tenantFuncName={:s},tenantId={:s}'.format(dep["metadata"]["labels"]["tenantFuncName"], dep["metadata"]["labels"]["tenantId"]))
            if len(resp.items) > 0:
                if resp.items[0].metadata.name != dep["metadata"]["name"]:
                    self.logger.warn("Old deployment {:s} exists. Delete before creating new deployment {:s}.".format(resp.items[0].metadata.name, dep["metadata"]["name"]))
                    try:
                        k8s_apps_v1.delete_namespaced_deployment(namespace=namespace_name, name=resp.items[0].metadata.name)
                    except client.ApiException as ex:
                        self.logger.error("Failed to delete Deployment: {} ".format(ex))
                        return changed, "", "Failed to delete Deployment: {} ".format(ex)
            try:
                resp = k8s_apps_v1.create_namespaced_deployment(
                body=dep, namespace=namespace_name)
                self.logger.debug("Deployment created. status='%s'" % resp.status)
            except client.ApiException as ex:
                self.logger.error("Failed to create Deployment: {} ".format(ex))
                return changed, "", "Failed to create Deployment: {} ".format(ex)
        else:
            try:
                resp = k8s_apps_v1.replace_namespaced_deployment(name=dep["metadata"]["name"],
                    body=dep, namespace=namespace_name)
                self.logger.debug("Deployment replaced. status='%s'" % resp.status)
            except client.ApiException as ex:
                self.logger.error("Failed to replace Deployment: {} ".format(ex))
                return changed, "", "Failed to replace Deployment: {} ".format(ex)
        if tenant_cnf_id not in self.tenant_cnfs.keys():
            self.tenant_cnfs.update({tenant_cnf_id: dep})
            changed = True
            self.logger.debug("Added {} to Tenant_CNF dict".format(tenant_cnf_id))
        elif self.tenant_cnfs.get(tenant_cnf_id) == dep:
            self.logger.debug("No changes since deployment for {} is unchanged.".format(tenant_cnf_id))
        else:
            self.tenant_cnfs.update({tenant_cnf_id: dep})
            changed = True
            self.logger.debug("Updated {} in Tenant_CNF dict".format(tenant_cnf_id))
        self.store_to_persistence(self.tenant_cnfs)
        return changed, "", ""

    def delete(self, tenantId, tenantFuncName, dep = None):
        """
        Delete the CNF deployment on the Kubernetes cluster

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who wants to deploy the tenant CNF.
        dep : str
            deployment which should be deleted. If None, it tries to load from the file path defined in the object params.
        """
        stderr = ""
        # conf = config.list_kube_config_contexts()
        # config.load_kube_config( context="orchestrator-test-vm") # external way
        config.load_kube_config() # internal way

        k8s_apps_v1 = client.AppsV1Api()
        k8s_core_v1 = client.CoreV1Api()

        if dep is None:
            if os.path.exists(self.params["kube_file"]):
                with open(self.params["kube_file"]) as f:
                    dep = yaml.safe_load(f)

        namesp_exist = False

        namespace_name = self._get_tenant_namespace_for_deployment(tenantId, dep)
        if isinstance(dep, V1Deployment):
            dep.metadata.namespace = namespace_name
            dep = dep.to_dict()
        elif isinstance(dep, dict):
            dep["metadata"]["namespace"] = namespace_name

        namespaces: V1NamespaceList = k8s_core_v1.list_namespace()
        for i, namespace in enumerate(namespaces.items):
            if namespace_name == namespace.metadata.name:
                namesp_exist = True
                break

        if namesp_exist:
            if "tenantFuncName" in dep["metadata"]["labels"] and "tenantId" in dep["metadata"]["labels"]:
                labels_selector = 'tenantFuncName={:s},tenantId={:s}'.format(dep["metadata"]["labels"]["tenantFuncName"], dep["metadata"]["labels"]["tenantId"])
            else:
                labels_selector = 'tenantFuncName={:s},tenantId={:d}'.format(tenantFuncName, tenantId)
            resp = k8s_apps_v1.list_namespaced_deployment(namespace=namespace_name, label_selector=labels_selector)
            if len(resp.items) > 0:
                self.logger.debug("Deleting Deployment {:s}.".format(resp.items[0].metadata.name))
                try:
                    resp = k8s_apps_v1.delete_namespaced_deployment(namespace=namespace_name, name=resp.items[0].metadata.name)
                    self.logger.debug("Deployment deleted, status: {}".format(resp))
                except client.ApiException as ex:
                    self.logger.error("Failed to delete Deployment: {} ".format(ex))
                    stderr = "Failed to delete Deployment: {} ".format(ex)
            else:
                self.logger.error("Failed to delete Deployment: No deployment found!")
                stderr = "Failed to delete Deployment: No deployment found!"
            if len(self.tenant_cnfs) > 1:
                self.tenant_cnfs.pop("t" + str(dep["metadata"]["labels"]["tenantId"]) + "-" + dep["metadata"]["labels"]["tenantFuncName"])
        else:
            self.logger.error("Could not delete deployment: Namespace does not exist!")
            stderr = "Could not delete deployment: Namespace does not exist!"
        self.store_to_persistence(self.tenant_cnfs)
        return resp.status == "Success" if resp is not None and hasattr(resp, 'status') else False, "", stderr

    def _create_tenant_namespace(self, tenantId, deployment: V1Deployment = None, namespace: V1Namespace = None, write_to_file = False):
        """
        Helper method to create a tenant namespace. 

        Parameters:
        -----------
        tenantId : str | int
            ID of the tenant for which the namespace should be created.
        deployment : V1Deployment
            Kubernetes Deployment from where the Kubernetes namespace object should be created. If None, it tries to load from the file path defined in the object params.
        namespace : V1Namespace
            Kubernetes namespace object which should be created. If None, the object will be generated from the given Kubernetes Deployment parameter.
        write_to_file : bool
            If True, save the Kubernetes Deployment to file.
        """
        if deployment is None:
            with open(self.params['kube_file']) as f:
                deployment = yaml.safe_load(f)
        if namespace is None:
            name = self._get_tenant_namespace_for_deployment(tenantId, deployment)
            namespace = V1Namespace(
                metadata={
                    "name": name,
                    "annotations": {
                        self.PREFIX + "-" + "managed-by": "orchestrator",
                        self.PREFIX + "-" + "last-updated": datetime.now().strftime("%Y-%m-%d-%H%M%S")
                    },
                    "labels": {
                        "name": deployment["metadata"]["namespace"]},
                        "tenantId": tenantId}
                )
        k8s_core_v1 = client.CoreV1Api()
        resp = k8s_core_v1.create_namespace(namespace)

        if write_to_file:
            with open(self.params['kube_file'], "w") as f:
                yaml.safe_dump(deployment, f)

        return resp, deployment, namespace

    def _add_annotations_to_namespace(self, namespace: V1Namespace):
        """
        Helper method to add orchestrator annotations to Kubernetes namespace.

        Parameters:
        -----------
        namespace : V1Namespace
            Kubernetes Namespace object where the annotations should be added.
        """
        if "annotations" in namespace["metadata"]:
            namespace["metadata"]["annotations"].update({
                self.PREFIX + "-" + "managed-by": "orchestrator",
                self.PREFIX + "-" + "last-updated": datetime.now().strftime("%Y-%m-%d-%H%M%S")
            })
        else:
            namespace["metadata"]["annotations"] = {
                self.PREFIX + "-" + "managed-by": "orchestrator",
                self.PREFIX + "-" + "last-updated": datetime.now().strftime("%Y-%m-%d-%H%M%S")
            }
        return namespace

    def _add_annotations_to_deployment(self, deployment: V1Deployment = None, write_to_file = True):
        """
        Helper method to add orchestrator annotations to Kubernetes deployment.

        Parameters:
        -----------
        deployment : V1Deployment
            Kubernetes Deployment object where the annotations should be added. If None, it tries to load from the file path defined in the object params.
        write_to_file : bool
            If True, save the Kubernetes Deployment to file.
        """
        if deployment is None:
            with open(self.params['kube_file']) as f:
                deployment = yaml.safe_load(f)
        if "annotations" in deployment["metadata"]:
            deployment["metadata"]["annotations"].update({
                self.PREFIX + "-" + "managed-by": "orchestrator",
                self.PREFIX + "-" + "last-updated": datetime.now().strftime("%Y-%m-%d-%H%M%S")
            })
        else:
            deployment["metadata"]["annotations"] = {
                self.PREFIX + "-" + "managed-by": "orchestrator",
                self.PREFIX + "-" + "last-updated": datetime.now().strftime("%Y-%m-%d-%H%M%S")
            }
        if write_to_file and os.path.exists(self.params['kube_file']):
            with open(self.params['kube_file'], "w") as f:
                yaml.safe_dump(deployment, f)
        return deployment

    def _add_tenantMetadata_to_deployment(self, tenantFuncName, tenantId, deployment : V1Deployment = None, write_to_file=True):
        """
        Helper method to add TDC metadata to Kubernetes deployment.

        Parameters:
        -----------
        tenantId : int
            ID of the tenant who submitted the TDC
        tenantFuncName : str
            Function name provided in the TDC
        deployment : V1Deployment
            Kubernetes Deployment object where the TDC metadata should be added. If None, it tries to load from the file path defined in the object params.
        write_to_file : bool
            If True, save the Kubernetes Deployment to file.
        """
        if deployment is None:
            with open(self.params['kube_file']) as f:
                deployment = yaml.safe_load(f)
        deployment["metadata"]["labels"].update({
            "tenantFuncName": tenantFuncName,
            "tenantId" : str(tenantId)
        })
        if write_to_file and os.path.exists(self.params['kube_file']):
            with open(self.params['kube_file'], "w") as f:
                yaml.safe_dump(deployment, f)
        return deployment

    def _add_tenant_communication_unix_socket_volume(self, socket_name, deployment : V1Deployment = None, write_to_file=True):
        """
        Helper method to add tenant communication unix socket volume to the Kubernetes Deployment. This should be used for the communication between the Accelerator and the CNF deployed in Kubernetes.

        Parameters:
        -----------
        socket_name : str
            Name for this socket
        deployment: V1Deployment
            Kubernetes Deployment where the tenant communication unix socket volume should attached. If None, it tries to load from the file path defined in the object params.
        write_to_file : bool
            If True, save the Kubernetes Deployment to file.
        """
        internal_name = "offload-function"
        external_name = socket_name + "-offloaded-function"
        internal_socket = "offload_function.sock"
        external_socket = socket_name + ".sock"
        if deployment is None:
            with open(self.params['kube_file']) as f:
                deployment = yaml.safe_load(f)
        if "volumeMounts" in deployment["spec"]["template"]["spec"]["containers"][0]:
            found = False
            for i, volumeMount in enumerate(deployment["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]):
                if volumeMount["name"] == external_name:
                    deployment["spec"]["template"]["spec"]["containers"][0]["volumeMounts"][i] = ({"mountPath": "/{}".format(internal_socket), "name": external_name})
                    found = True
                    break
            if not found:
                deployment["spec"]["template"]["spec"]["containers"][0]["volumeMounts"].append({"mountPath": "/{}".format(internal_socket), "name": "{}_offloaded_function".format(socket_name)})
        else:
            deployment["spec"]["template"]["spec"]["containers"][0]["volumeMounts"] = [{"mountPath": "/{}".format(internal_socket), "name": external_name}]
        if "volumes" in deployment["spec"]["template"]["spec"]:
            found = False
            for i, volume in enumerate(deployment["spec"]["template"]["spec"]["volumes"]):
                if volume["name"] == external_name:
                    deployment["spec"]["template"]["spec"]["volumes"][i] = ({"hostPath": {"path": "{}/{}".format(self.socket_root_dir, external_socket), "type": "Socket"}, "name": external_name  })
                    found = True
                    break
            if not found:
                deployment["spec"]["template"]["spec"]["volumes"].append({"hostPath": {"path": "{}/{}".format(self.socket_root_dir, external_socket), "type": "Socket"}, "name": external_name  })
        else:
            deployment["spec"]["template"]["spec"]["volumes"] = [{"hostPath": {"path": "{}/{}".format(self.socket_root_dir, external_socket), "type": "Socket"}, "name": external_name  }]
        if write_to_file and os.path.exists(self.params['kube_file']):
            with open(self.params['kube_file'], "w") as f:
                yaml.safe_dump(deployment, f)
        return deployment
