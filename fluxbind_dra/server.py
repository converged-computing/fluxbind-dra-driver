import grpc
from concurrent import futures
import time
import os
import logging
from kubernetes import client, config

import fluxbind_dra.nri as nri
from fluxbind.manager import NodeResourceManager
from fluxbind_dra.proto.dra import dra_pb2, dra_pb2_grpc
from fluxbind_dra.proto.pluginregistration import api_pb2 as registration_pb2
from fluxbind_dra.proto.pluginregistration import api_pb2_grpc as registration_pb2_grpc
from fluxbind_dra.proto.nri import api_pb2_grpc as nri_pb2_grpc

import fluxbind_dra.defaults as defaults
import fluxbind_dra.devices as devices

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)



class DraPluginServicer(dra_pb2_grpc.DRAPluginServicer):
    """
    Handles the core DRA logic by calling the NodeResourceManager.
    """

    def __init__(self, cdi_manager):
        self.k8s_client = None
        self.cdi_manager = cdi_manager
        self.prepared = False
        log.info("DraPluginServicer initialized.")

    def prepare_resources(self):
        node_name = os.environ.get("NODE_NAME")
        pod_namespace = os.environ.get("POD_NAMESPACE")
        if not node_name or not pod_namespace:
             raise RuntimeError("NODE_NAME or POD_NAMESPACE env var is not set.")
        devices.create_or_update_resource_slice(node_name, pod_namespace)
        self.prepared = True

    def _get_k8s_client(self):
        """Initializes the K8s client on first use."""
        if self.k8s_client is None:
            log.info("Initializing Kubernetes API client...")
            config.load_incluster_config()
            self.k8s_client = client.CustomObjectsApi()
            log.info("Kubernetes API client initialized.")
        return self.k8s_client
    
    def get_shape_from_claim(self, claim) -> dict:
        """
        Translates a Kubernetes ResourceClaim into a fluxbind shape.
        """
        log.info(f"Fetching full ResourceClaim '{claim.namespace}/{claim.name}' from API server...")
        api = self._get_k8s_client()
        claim_obj = api.get_namespaced_custom_object(
            group="resource.k8s.io",
                version="v1",
                name=claim.name,
                namespace=claim.namespace,
                plural="resourceclaims",
            )
            
        # Now we parse the full object we just fetched
        print(claim_obj)
        opaque_params = claim_obj["spec"]["devices"]["config"][0]["opaque"]["parameters"]
        shape = dict(opaque_params) # It's already a dict-like structure            
        log.info(f"Successfully parsed shape for claim '{claim.name}': {shape}")
        return shape

    def NodePrepareResources(self, request, context):
        log.info(
            f"Received NodePrepareResources request for {len(request.claims)} claims."
        )
        response = dra_pb2.NodePrepareResourcesResponse()

        # We do this here to not slow down / block startup
        if not self.prepared:
            self.prepare_resources()

        for claim in request.claims:
            print(claim)
            try:
                print(dir(claim))
                shape = self.get_shape_from_claim(claim)
            except Exception as e:
                msg = f"Failed to get shape for claim {claim.uid}: {e}"
                log.error(msg)
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(msg)
                return dra_pb2.NodePrepareResourcesResponse()

            # Call the manager from fluxbind!
            binding = self.manager.create_reservation(claim.uid, shape)

            if binding:
                mask, gpu_string = binding.split(";")
                log.info(
                    f"Generated binding for claim {claim.uid}: cpuset={mask}, gpus={gpu_string}"
                )
                device_name = self.cdi_manager.add_device(claim.uid, mask)
                cdi_full_name = f"{defaults.PLUGIN_NAME}/shape={device_name}"
                cdi_ids = [cdi_full_name]
                if gpu_string != "NONE":
                    cdi_ids.append(f"nvidia.com/gpu={gpu_string}")

                # This Device represents the entire allocation via a cpuset
                device = dra_pb2.Device(
                    pool_name="shape",
                    device_name="shape",
                    cdi_device_ids=cdi_ids,
                )
                prepare_response = dra_pb2.NodePrepareResourceResponse(
                    devices=[device]
                )
                response.claims[claim.uid].CopyFrom(prepare_response)

    
            else:
                msg = f"Could not allocate resources for claim {claim.uid}"
                log.error(msg)
                context.set_code(grpc.StatusCode.RESOURCE_EXHAUSTED)
                context.set_details(msg)
                return dra_pb2.NodePrepareResourcesResponse()

        return response

    # NodeUnprepareResources does not need to change.
    def NodeUnprepareResources(self, request, context):
        log.info(
            f"Received NodeUnprepareResources request for {len(request.claims)} claims."
        )
        response = dra_pb2.NodeUnprepareResourcesResponse()
        for claim in request.claims:
            self.manager.release_reservation(claim.uid)
            self.cdi_manager.remove_device(claim.uid)

            unprepare_response = dra_pb2.NodeUnprepareResourceResponse()
            
            # Add an entry to the 'claims' map for this claim UID.
            # Kubelet requires this entry to exist, even if it's empty.
            response.claims[claim.uid].CopyFrom(unprepare_response)

        return response


def prepare_manager():
    """
    Shared function to prepare the manager
    """
    state_file = os.getenv("STATE_FILE_PATH", defaults.STATE_FILE_PATH_DEFAULT)
    return NodeResourceManager(state_file)


class RegistrationServicer(registration_pb2_grpc.RegistrationServicer):
    """
    Handles the plugin registration with Kubelet.
    """

    def GetInfo(self, request, context):
        log.info("Received GetInfo registration request from Kubelet.")
        return registration_pb2.PluginInfo(
            type=defaults.PLUGIN_TYPE,
            name=defaults.PLUGIN_NAME,
            endpoint=defaults.DRA_SOCKET_PATH.replace("unix://", ""),
            supported_versions=["v1beta1.DRAPlugin"],
        )

    def NotifyRegistrationStatus(self, request, context):
        """
        Kubelet calls this to notify the plugin of its registration status.
        For now, we can just log it and return an empty response.
        """
        log.info(f"Received NotifyRegistrationStatus: Registered={request.plugin_registered}, Error={request.error}")
        return registration_pb2.RegistrationStatusResponse()

def serve():
    """
    Configures and runs the gRPC server.
    """
    log.info("Starting DRA plugin server...")

    # Clean up old sockets and create directories
    for path in [defaults.DRA_SOCKET_PATH, defaults.REGISTRATION_SOCKET_PATH, defaults.NRI_SOCKET_PATH]:
        sock_path = path.replace("unix://", "")
        if os.path.exists(sock_path):
            try:
                os.remove(sock_path)
                log.info(f"Removed stale socket: {sock_path}")
            except OSError as e:
                log.error(f"Error removing stale socket {sock_path}: {e}")
                return

        os.makedirs(os.path.dirname(sock_path), exist_ok=True)

    cdi_manager = devices.CDIManager()

    # Create and configure the gRPC server
    config.load_incluster_config()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    plugin = DraPluginServicer(cdi_manager)
    dra_pb2_grpc.add_DRAPluginServicer_to_server(plugin, server)
    registration_pb2_grpc.add_RegistrationServicer_to_server(
        RegistrationServicer(), server
    )
    nri_manager = nri.NriServicer()
    nri_pb2_grpc.add_PluginServicer_to_server(nri_manager, server)
    server.add_insecure_port(defaults.DRA_SOCKET_PATH)
    server.add_insecure_port(defaults.REGISTRATION_SOCKET_PATH)
    server.add_insecure_port(defaults.NRI_SOCKET_PATH)

    # Start the server and wait
    server.start()
    log.info(
        f"gRPC server started, listening on {defaults.DRA_SOCKET_PATH} and {defaults.REGISTRATION_SOCKET_PATH}"
    )

    # Do slower stuff after we've registered
    plugin.prepare_resources()
    manager = prepare_manager()
    plugin.manager = manager

    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        log.info("Shutting down server due to keyboard interrupt.")
    finally:
        server.stop(0)
        log.info("Server stopped.")
