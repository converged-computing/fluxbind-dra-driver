PLUGIN_NAME = "fluxbind"
PLUGIN_TYPE = "DRAPlugin"
STATE_FILE_PATH_DEFAULT = "/var/lib/fluxbind-dra/state.json"

DRA_SOCKET_PATH = f"unix:///var/lib/kubelet/plugins/{PLUGIN_NAME}.sock"
REGISTRATION_SOCKET_PATH = (
    f"unix:///var/lib/kubelet/plugins_registry/{PLUGIN_NAME}.sock"
)

CDI_SPEC_PATH = f"/var/run/cdi/{PLUGIN_NAME}.json"
# Linux cpulist (e.g. "0-3,48-51") consumed by the NRI plugin.
CDI_CPUS_ENVVAR = "FLUXBIND_CPUS"
# hwloc bitmap of the same set, informational only.
CDI_CPUSET_ENVVAR = "FLUXBIND_CPUSET"
