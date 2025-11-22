package main

import (
	"context"
	"flag"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/containerd/nri/pkg/api"
	"github.com/containerd/nri/pkg/stub"
	"k8s.io/apimachinery/pkg/util/wait"
	"k8s.io/klog/v2"
	"k8s.io/utils/cpuset"
)

// Renamed for clarity as it's used for both env vars now.
const (
	cpusetEnvVar         = "FLUXBIND_CPUSET"
	cpusetReversedEnvVar = "FLUXBIND_CPUSET_REVERSED"
)

// Driver is the structure that holds all runtime information for our NRI plugin.
type Driver struct {
	stub       stub.Stub
	pluginName string
}

// Start creates and starts a new NRI Driver.
func Start(ctx context.Context, pluginName, pluginIdx string) (*Driver, error) {
	d := &Driver{
		pluginName: pluginName,
	}
	opts := []stub.Option{
		stub.WithPluginName(pluginName),
		stub.WithPluginIdx(pluginIdx),
		stub.WithOnClose(func() {
			klog.Infof("NRI connection closed")
		}),
	}
	stub, err := stub.New(d, opts...)
	if err != nil {
		return nil, fmt.Errorf("failed to create NRI plugin stub: %w", err)
	}
	d.stub = stub

	go func() {
		wait.Forever(func() {
			klog.Infof("Starting NRI plugin...")
			err := d.stub.Run(ctx)
			if err != nil {
				klog.Errorf("NRI plugin failed: %v", err)
			}
		}, 5*time.Second)
	}()

	return d, nil
}

// Configure is called by NRI to register the plugin and subscribe to events.
func (d *Driver) Configure(ctx context.Context, config, runtime, version string) (stub.EventMask, error) {
	klog.Infof("Configure request: runtime=%s, version=%s", runtime, version)
	return 0, nil
}

// CreateContainer is the core hook where we modify the container spec.
func (d *Driver) CreateContainer(ctx context.Context, pod *api.PodSandbox, ctr *api.Container) (*api.ContainerAdjustment, []*api.ContainerUpdate, error) {
	klog.Infof("CreateContainer request for %s/%s/%s", pod.Namespace, pod.Name, ctr.Name)

	adjustment := &api.ContainerAdjustment{}

	// Step 1: Find the environment variables provided by the Python plugin.
	hexMaskStr, wantsReversal := d.findCpusetInEnv(ctr)
	if hexMaskStr == "" {
		klog.V(5).Infof("No %s environment variable found for container %s. No affinity will be applied.", cpusetEnvVar, ctr.Name)
		return adjustment, nil, nil
	}

	// Step 2: Convert the hex mask into a slice of integer CPU IDs.
	cpus, err := parseHexMaskToCPUs(hexMaskStr)
	if err != nil {
		klog.Errorf("Failed to parse hex mask %q for container %s: %v. No affinity will be applied.", hexMaskStr, ctr.Name, err)
		return adjustment, nil, nil
	}

	// Step 3: If requested, reverse the order of the CPUs.
	if wantsReversal {
		klog.Infof("Reversing CPU order for container %s", ctr.Name)
		reverseCPUs(cpus)
	}

	// Step 4: Format the final (potentially reversed) slice into the string runc needs.
	finalCpusetStr := formatCPUListString(cpus)

	klog.Infof("Applying final cpuset %q to container %s", finalCpusetStr, ctr.Name)

	// Step 5: Apply the adjustment to the container's cgroup.
	if adjustment.Linux == nil {
		adjustment.Linux = &api.LinuxContainerAdjustment{}
	}
	if adjustment.Linux.Resources == nil {
		adjustment.Linux.Resources = &api.LinuxResources{}
	}
	if adjustment.Linux.Resources.Cpu == nil {
		adjustment.Linux.Resources.Cpu = &api.LinuxCPU{}
	}
	adjustment.Linux.Resources.Cpu.Cpus = finalCpusetStr

	return adjustment, nil, nil
}

// findCpusetInEnv iterates through the container's environment variables to find the
// cpuset and reversal flag injected by the Python CDI manager.
func (d *Driver) findCpusetInEnv(ctr *api.Container) (string, bool) {
	var hexMask string
	var wantsReversal bool

	if ctr.Env == nil {
		return "", false
	}

	cpusetPrefix := cpusetEnvVar + "="
	reversalPrefix := cpusetReversedEnvVar + "="

	for _, envVar := range ctr.Env {
		if val, found := strings.CutPrefix(envVar, cpusetPrefix); found {
			hexMask = val
		}
		if val, found := strings.CutPrefix(envVar, reversalPrefix); found {
			if strings.ToLower(val) == "yes" {
				wantsReversal = true
			}
		}
	}
	return hexMask, wantsReversal
}

// --- NEW MODULAR HELPER FUNCTIONS ---

// parseHexMaskToCPUs takes a hex string like "0x00ff" and returns a slice of integers, e.g., [0, 1, 2, 3, 4, 5, 6, 7].
func parseHexMaskToCPUs(hexMask string) ([]int, error) {
	if !strings.HasPrefix(hexMask, "0x") {
		return nil, fmt.Errorf("invalid hex mask format: missing '0x' prefix")
	}
	hexVal := strings.TrimPrefix(hexMask, "0x")

	mask, err := strconv.ParseUint(hexVal, 16, 64)
	if err != nil {
		return nil, fmt.Errorf("failed to parse hex string %q: %w", hexVal, err)
	}

	var cpus []int
	for i := 0; i < 64; i++ { // Check up to 64 CPUs
		if (mask & (1 << i)) != 0 {
			cpus = append(cpus, i)
		}
	}

	if len(cpus) == 0 {
		return nil, fmt.Errorf("hex mask %q resulted in an empty CPU set", hexMask)
	}

	return cpus, nil
}

// reverseCPUs reverses a slice of integers in-place.
func reverseCPUs(s []int) {
	for i, j := 0, len(s)-1; i < j; i, j = i+1, j-1 {
		s[i], s[j] = s[j], s[i]
	}
}

// formatCPUListString converts a slice of integer CPU IDs to a CPU list string (e.g., "0-7,15").
func formatCPUListString(cpus []int) string {
	// Use the k8s utility to create the properly formatted string.
	cs := cpuset.New(cpus...)
	return cs.String()
}

// --- All other plugin methods from the template are UNCHANGED ---

func (d *Driver) Synchronize(ctx context.Context, pods []*api.PodSandbox, containers []*api.Container) ([]*api.ContainerUpdate, error) {
	return nil, nil
}
func (d *Driver) Shutdown(ctx context.Context)                                    {}
func (d *Driver) RunPodSandbox(ctx context.Context, pod *api.PodSandbox) error    { return nil }
func (d *Driver) StopPodSandbox(ctx context.Context, pod *api.PodSandbox) error   { return nil }
func (d *Driver) RemovePodSandbox(ctx context.Context, pod *api.PodSandbox) error { return nil }
func (d *Driver) PostCreateContainer(ctx context.Context, pod *api.PodSandbox, ctr *api.Container) error {
	return nil
}
func (d *Driver) StartContainer(ctx context.Context, pod *api.PodSandbox, ctr *api.Container) error {
	return nil
}
func (d *Driver) PostStartContainer(ctx context.Context, pod *api.PodSandbox, ctr *api.Container) error {
	return nil
}
func (d *Driver) UpdateContainer(ctx context.Context, pod *api.PodSandbox, ctr *api.Container, r *api.LinuxResources) ([]*api.ContainerUpdate, error) {
	return nil, nil
}
func (d *Driver) PostUpdateContainer(ctx context.Context, pod *api.PodSandbox, ctr *api.Container) error {
	return nil
}
func (d *Driver) StopContainer(ctx context.Context, pod *api.PodSandbox, ctr *api.Container) ([]*api.ContainerUpdate, error) {
	return nil, nil
}
func (d *Driver) RemoveContainer(ctx context.Context, pod *api.PodSandbox, ctr *api.Container) error {
	return nil
}

func main() {
	klog.InitFlags(nil)
	var (
		pluginName string
		pluginIdx  string
	)
	flag.StringVar(&pluginName, "name", "fluxbind", "plugin name to register to NRI")
	flag.StringVar(&pluginIdx, "idx", "01", "plugin index to register to NRI")
	flag.Parse()

	klog.Infof("Starting NRI sidecar plugin: %s (idx: %s)", pluginName, pluginIdx)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	driver, err := Start(ctx, pluginName, pluginIdx)
	if err != nil {
		klog.Fatalf("Failed to start driver: %v", err)
	}

	klog.Info("NRI Driver started, waiting for events...")
	<-ctx.Done()

	klog.Info("Shutting down NRI Driver")
	driver.stub.Stop()
}
