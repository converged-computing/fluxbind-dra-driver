from kubernetes import client
import logging
import threading
import fluxbind_dra.defaults as defaults


log = logging.getLogger(__name__)


# In fluxbind_dra/devices.py
import json
import os
import logging

log = logging.getLogger(__name__)


class CDIManager:
    """
    Manages the dynamic CDI specification file in a thread-safe manner.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._initialize_spec_file()

    def _initialize_spec_file(self):
        """
        Ensure a base spec file exists on startup.
        """
        with self._lock:
            log.info(f"Initializing CDI specification at {defaults.CDI_SPEC_PATH}...")
            os.makedirs(os.path.dirname(defaults.CDI_SPEC_PATH), exist_ok=True)
            if not os.path.exists(defaults.CDI_SPEC_PATH):
                base_spec = {
                    "cdiVersion": "0.6.0",
                    "kind": f"{defaults.PLUGIN_NAME}/shape",
                    "devices": [],
                }
                self._write_spec(base_spec)

    def _read_spec(self) -> dict:
        """
        Reads and parses the current CDI spec file.
        """
        with open(defaults.CDI_SPEC_PATH, 'r') as f:
            return json.load(f)

    def _write_spec(self, spec: dict):
        """
        Writes the spec object to the file.
        """
        with open(defaults.CDI_SPEC_PATH, 'w') as f:
            json.dump(spec, f, indent=2)

    def add_device(self, claim_uid: str, cpuset: str):
        """
        Adds a new device entry to the CDI spec for a specific claim.
        This is called by NodePrepareResources.
        """
        with self._lock:
            log.info(f"Adding device for claim {claim_uid} to CDI spec...")
            spec = self._read_spec()

            device_name = f"claim-{claim_uid}"

            # This is the environment variable that will be injected into the container.
            # NRI will have a hook that can find this envar and apply it.
            env_var = f"{defaults.CDI_ENVVAR_PREFIX}={cpuset}"

            # Remove any stale entry for this device name (idempotency)
            spec["devices"] = [d for d in spec["devices"] if d.get("name") != device_name]

            # edit the container's linux cgroup resources.
            new_device = {
                "name": device_name,
                "containerEdits": {
                    "env": [env_var],
                }
            }
        
            spec["devices"].append(new_device)
            self._write_spec(spec)
            log.info(f"Successfully added device {device_name} to CDI spec.")
            return device_name

    def remove_device(self, claim_uid: str):
        """
        Removes a device entry from the CDI spec.
        This is called by NodeUnprepareResources.
        """
        with self._lock:
            log.info(f"Removing device for claim {claim_uid} from CDI spec...")
            spec = self._read_spec()
            device_name = f"claim-{claim_uid}"
            
            initial_count = len(spec["devices"])
            spec["devices"] = [d for d in spec["devices"] if d.get("name") != device_name]
            
            if len(spec["devices"]) < initial_count:
                self._write_spec(spec)
                log.info(f"Successfully removed device {device_name} from CDI spec.")
            else:
                log.warning(f"Device {device_name} not found in CDI spec for removal.")


def create_or_update_resource_slice(node_name: str, pod_namespace: str):
    """
    Creates or updates the ResourceSlice object for this node using the
    dedicated ResourceV1Api client.
    """
    log.info(f"Advertising resource inventory for node '{node_name}'...")
    try:
        core_api = client.CoreV1Api()
        custom_objects_api = client.CustomObjectsApi()
        
        object_name = f"{node_name}-{defaults.PLUGIN_NAME}-slice"

        try:
            node = core_api.read_node(name=node_name)
            node_uid = node.metadata.uid
        except client.ApiException as e:
            log.error(f"Failed to read node object '{node_name}' to get UID: {e}")
            raise

        body = client.V1ResourceSlice(
            api_version="resource.k8s.io/v1",
            kind="ResourceSlice",
            spec={
                "driver": defaults.PLUGIN_NAME,
                "node_name": node_name,
                # V1Device
                "pool": {
                   "name": "shape",
                   "resourceSliceCount": 100,
                },
                "devices": [
                    {"name": "shape", "nodeName": node_name}
                ],
                "nodeName": node_name,
            },
            metadata=client.V1ObjectMeta(
                name=object_name,
                owner_references=[
                    client.V1OwnerReference(
                        api_version="v1",
                        kind="Node",
                        name=node_name,
                        uid=node_uid,
                    )
                ]
            ),
        )
        
        try:
            custom_objects_api.get_cluster_custom_object(
                group="resource.k8s.io", version="v1", name=object_name,
                plural="resourceslices",
            )
        except client.ApiException as e:
            log.info(f"Creating ResourceSlice object '{object_name}'.")
            custom_objects_api.create_cluster_custom_object(body=body, group="resource.k8s.io", version="v1", plural="resourceslices")

        log.info(f"Successfully advertised resource inventory for node '{node_name}'.")

    except Exception as e:
        log.error(f"Failed to create or update ResourceSlice for node {node_name}: {e}")
        raise
