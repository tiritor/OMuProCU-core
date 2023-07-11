
import re
import subprocess

from kubernetes.client import V1Deployment

from orchestrator_utils.logger.logger import init_logger

from kube_handler.kube_handler import KubeBackendHandler


NAME = re.compile('name "([^"]+)" is in use')


class PodmanKubeHandler(KubeBackendHandler):
    """
    Adapted from Ansible Module in containers.podman.podman_play
    ATTENTION: This is unmaintained, and very unstable!
    """

    def __init__(self, params, executable):
        super().__init__(params)
        self.logger = init_logger(self.__class__.__name__)
        self.actions = []
        self.executable = executable
        self.command = [self.executable, 'play', 'kube']
        creds = []
        # pod_name = extract_pod_name(params.params['kube_file'])
        if 'username' in self.params:
            creds += [self.params['username']]
            if 'password' in self.params:
                creds += [self.params['password']]
            creds = ":".join(creds)
            self.command.extend(['--creds=%s' % creds])
        if 'network' in self.params:
            networks = ",".join(self.params['network'])
            self.command.extend(['--network=%s' % networks])
        if 'configmap' in self.params :
            configmaps = ",".join(self.params['configmap'])
            self.command.extend(['--configmap=%s' % configmaps])
        start = self.params['state'] == 'started'
        self.command.extend(['--start=%s' % str(start).lower()])
        for arg, param in {
            '--authfile': 'authfile',
            '--cert-dir': 'cert_dir',
            '--log-driver': 'log_driver',
            '--seccomp-profile-root': 'seccomp_profile_root',
            '--tls-verify': 'tls_verify',
            '--log-level': 'log_level',
            '--quiet': 'quiet',
        }.items():
            if param in self.params:
                self.command += ["%s=%s" % (arg, self.params[param])]
        self.command += [self.params['kube_file']]

    def _command_run(self, cmd):
        def run_command(cmd):
            self.logger.info(cmd)
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return proc.returncode, proc.stdout.decode(), proc.stderr.decode()

        rc, out, err = run_command(cmd)
        self.actions.append(" ".join(cmd))
        self.logger.debug('PODMAN-PLAY-KUBE command: %s' % " ".join(cmd))
        self.logger.debug('PODMAN-PLAY-KUBE stdout: %s' % out)
        self.logger.debug('PODMAN-PLAY-KUBE stderr: %s' % err)
        self.logger.debug('PODMAN-PLAY-KUBE rc: %s' % rc)
        return rc, out, err

    def discover_pods(self):
        pod_name = self.get_pod_name()
        # Find all pods
        all_pods = ''
        # In case of one pod or replicasets
        for name in ("name=%s$", "name=%s-pod-*"):
            cmd = [self.executable,
                   "pod", "ps", "-q", "--filter", name % pod_name]
            rc, out, err = self._command_run(cmd)
            all_pods += out
        ids = list(set([i for i in all_pods.splitlines() if i]))
        return ids

    def remove_associated_pods(self, pods):
        changed = False
        out_all, err_all = '', ''
        # Delete all pods
        for pod_id in pods:
            rc, out, err = self._command_run(
                [self.executable, "pod", "rm", "-f", pod_id])
            if rc != 0:
                self.logger.error("Can NOT delete Pod %s" % pod_id)
            else:
                changed = True
                out_all += out
                err_all += err
        return changed, out_all, err_all

    def pod_recreate(self):
        pods = self.discover_pods()
        self.remove_associated_pods(pods)
        # Create a pod
        rc, out, err = self._command_run(self.command)
        if rc != 0:
            self.logger.error("Can NOT create Pod! Error: %s" % err)
        return out, err
        
    def play(self):
        rc, out, err = self._command_run(self.command)
        changed = False
        if rc != 0 and 'pod already exists' in str(err):
            if 'recreate' in self.params:
                out, err = self.pod_recreate()
                changed = True
            else:
                changed = False
            err = "\n".join([
                i for i in err.splitlines() if 'pod already exists' not in i])
        elif rc != 0:
            self.logger.error(msg="Output: %s\nError=%s" % (out, err))
        else:
            changed = True
        return changed, out, err

    def delete(self, tenantId, tenantFuncName, dep: V1Deployment = None):
        return self.apply()

    def apply(self):
        """
        Apply the Podman Deployment.
        """
        if self.params['state'] == 'absent':
            pods = self.discover_pods()
            changed, out, err = self.remove_associated_pods(pods)
        else:
            changed, out, err = self.play()
        return changed, out, err