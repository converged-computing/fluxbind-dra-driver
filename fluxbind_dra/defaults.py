PLUGIN_NAME = "fluxbind"
PLUGIN_TYPE = "DRAPlugin"
STATE_FILE_PATH_DEFAULT = "/var/lib/fluxbind-dra/state.json"

DRA_SOCKET_PATH = f"unix:///var/lib/kubelet/plugins/{PLUGIN_NAME}.sock"
REGISTRATION_SOCKET_PATH = (
    f"unix:///var/lib/kubelet/plugins_registry/{PLUGIN_NAME}.sock"
)

CDI_SPEC_PATH = f"/var/run/cdi/{PLUGIN_NAME}.json"
CDI_ENVVAR_PREFIX = "FLUXBIND_CPUSET"
