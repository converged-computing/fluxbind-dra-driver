package main

import (
	"context"
	"flag"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/containerd/nri/pkg/api"
	"github.com/containerd/nri/pkg/stub"
	"k8s.io/apimachinery/pkg/util/wait"
	"k8s.io/klog/v2"
	"k8s.io/utils/cpuset"
)

const (
	// cpusetEnvVar carries the CPU selection produced by the DRA plugin. It is
	// either an hwloc bitmask ("0x0000000f,,0x0") or a CPU list ("0-3,64").
	cpusetEnvVar = "FLUXBIND_CPUSET"
	// cpusetReversedEnvVar asks for the CPU *order* to be reversed.
	cpusetReversedEnvVar = "FLUXBIND_CPUSET_REVERSED"
	// cpuOrderEnvVar is injected by this plugin. It carries the ordered, explicit
	// CPU list for whatever performs per-process affinity inside the container.
	// The cgroup cannot express order, so ordering has to travel out-of-band.
	cpuOrderEnvVar = "FLUXBIND_CPU_ORDER"

	// hwlocGroupBits is the width of one comma-separated field in an hwloc bitmask.
	hwlocGroupBits = 32
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
//
// We subscribe explicitly rather than returning 0. Returning 0 makes the stub
// fall back to the mask inferred from the implemented handlers, and because this
// Driver implements every handler in the interface (most as no-ops) that would
// put us on the synchronous path for every container lifecycle event on the node.
func (d *Driver) Configure(ctx context.Context, config, runtime, version string) (stub.EventMask, error) {
	klog.Infof("Configure request: runtime=%s, version=%s", runtime, version)
	return api.MustParseEventMask("CreateContainer"), nil
}

// CreateContainer is the core hook where we modify the container spec.
func (d *Driver) CreateContainer(ctx context.Context, pod *api.PodSandbox, ctr *api.Container) (*api.ContainerAdjustment, []*api.ContainerUpdate, error) {
	klog.Infof("CreateContainer request for %s/%s/%s", pod.Namespace, pod.Name, ctr.Name)

	adjustment := &api.ContainerAdjustment{}

	// Find the CPU selection provided by the DRA plugin.
	cpuSpec, wantsReversal := d.findCpusetInEnv(ctr)
	if cpuSpec == "" {
		klog.V(5).Infof("No %s environment variable found for container %s. No affinity will be applied.", cpusetEnvVar, ctr.Name)
		return adjustment, nil, nil
	}

	cpus, err := parseCPUSpec(cpuSpec)
	if err != nil {
		// Deliberately fail the container rather than starting it unbound. A pod that
		// asked for exclusive topology-aware placement and silently received the whole
		// machine is worse than a pod that does not start: it will oversubscribe CPUs
		// that other claims believe they own exclusively.
		klog.Errorf("refusing to create container %s/%s/%s: cannot honor %s=%q: %v",
			pod.Namespace, pod.Name, ctr.Name, cpusetEnvVar, cpuSpec, err)
		return nil, nil, fmt.Errorf("fluxbind: cannot honor %s=%q: %w", cpusetEnvVar, cpuSpec, err)
	}

	// cgroup cpuset.cpus is a *set*. The kernel has no notion of CPU ordering, so the
	// canonical ascending form is the only thing that is meaningful here.
	set := cpuset.New(cpus...)
	adjustment.SetLinuxCPUSetCPUs(set.String())

	// Ordering (including reversal) only means something to whatever calls
	// sched_setaffinity inside the container, so it travels as an ordered env var.
	order := orderedCPUList(cpus, wantsReversal)
	adjustment.AddEnv(cpuOrderEnvVar, order)

	klog.Infof("container %s/%s/%s: cpuset.cpus=%q %s=%q",
		pod.Namespace, pod.Name, ctr.Name, set.String(), cpuOrderEnvVar, order)

	return adjustment, nil, nil
}

// findCpusetInEnv iterates through the container's environment variables to find the
// cpuset and reversal flag injected by the Python CDI manager.
func (d *Driver) findCpusetInEnv(ctr *api.Container) (string, bool) {
	var cpuSpec string
	var wantsReversal bool

	if ctr.Env == nil {
		return "", false
	}

	cpusetPrefix := cpusetEnvVar + "="
	reversalPrefix := cpusetReversedEnvVar + "="

	for _, envVar := range ctr.Env {
		if val, found := strings.CutPrefix(envVar, cpusetPrefix); found {
			cpuSpec = strings.TrimSpace(val)
		}
		if val, found := strings.CutPrefix(envVar, reversalPrefix); found {
			switch strings.ToLower(strings.TrimSpace(val)) {
			case "yes", "true", "1":
				wantsReversal = true
			}
		}
	}
	return cpuSpec, wantsReversal
}

// parseCPUSpec accepts either an hwloc bitmask or a CPU list and returns the
// selected CPU IDs in ascending order.
func parseCPUSpec(spec string) ([]int, error) {
	s := strings.TrimSpace(spec)
	if s == "" {
		return nil, fmt.Errorf("empty CPU spec")
	}

	// An hwloc bitmask always carries at least one "0x" field; a CPU list never does.
	if strings.Contains(strings.ToLower(s), "0x") {
		return parseHwlocMask(s)
	}

	set, err := cpuset.Parse(s)
	if err != nil {
		return nil, fmt.Errorf("CPU list %q is not parseable: %w", s, err)
	}
	if set.Size() == 0 {
		return nil, fmt.Errorf("CPU list %q selects no CPUs", s)
	}
	return set.List(), nil
}

// parseHwlocMask parses an hwloc cpuset bitmask into the CPU IDs it selects.
//
// hwloc prints a bitmask as comma-separated 32-bit fields, most significant field
// FIRST, and compresses runs of all-zero fields by emitting empty fields. Each empty
// field stands for exactly one all-zero 32-bit group. For example, on a 512-PU node:
//
//	PUs 0-3    -> "0x0000000f"
//	PUs 64-67  -> "0x0000000f,,0x0"
//	PU  200    -> "0x00000100,,,,,,0x0"
//
// The previous implementation called strconv.ParseUint(mask, 16, 64) on the whole
// string, so it failed on every mask with more than one field, and silently left
// the container unbound. It also could not represent a CPU above index 63.
func parseHwlocMask(mask string) ([]int, error) {
	s := strings.TrimSpace(mask)
	if s == "" {
		return nil, fmt.Errorf("empty cpuset mask")
	}

	fields := strings.Split(s, ",")
	nFields := len(fields)

	var cpus []int
	for i, field := range fields {
		// The leftmost field holds the most significant bits.
		groupIndex := nFields - 1 - i

		field = strings.TrimSpace(field)
		if field == "" {
			// A compressed all-zero group contributes no CPUs.
			continue
		}

		digits := field
		if lower := strings.ToLower(digits); strings.HasPrefix(lower, "0x") {
			digits = digits[2:]
		}
		if digits == "" {
			return nil, fmt.Errorf("field %d of mask %q has a 0x prefix but no digits", i, mask)
		}

		value, err := strconv.ParseUint(digits, 16, 64)
		if err != nil {
			return nil, fmt.Errorf("field %d of mask %q is not valid hex: %w", i, mask, err)
		}

		// A single-field mask is unambiguous, so allow the full 64 bits for
		// compatibility with tools that print one wide word. As soon as there are
		// multiple fields the positional arithmetic requires exactly 32 bits each.
		width := 64
		if nFields > 1 {
			if value > math.MaxUint32 {
				return nil, fmt.Errorf("field %d of mask %q exceeds %d bits, so its position is ambiguous", i, mask, hwlocGroupBits)
			}
			width = hwlocGroupBits
		}

		for bit := 0; bit < width; bit++ {
			if value&(uint64(1)<<uint(bit)) != 0 {
				cpus = append(cpus, groupIndex*hwlocGroupBits+bit)
			}
		}
	}

	if len(cpus) == 0 {
		return nil, fmt.Errorf("cpuset mask %q selects no CPUs", mask)
	}

	sort.Ints(cpus)
	return cpus, nil
}

// orderedCPUList renders CPU IDs as an ordered, explicit list, optionally reversed.
//
// This is intentionally NOT passed through cpuset.CPUSet: that type is backed by a
// map and its String() method sorts, which is why the previous reversal support was
// a no-op. Order has to survive all the way to the consumer.
func orderedCPUList(cpus []int, reversed bool) string {
	ordered := make([]int, len(cpus))
	copy(ordered, cpus)
	if reversed {
		for i, j := 0, len(ordered)-1; i < j; i, j = i+1, j-1 {
			ordered[i], ordered[j] = ordered[j], ordered[i]
		}
	}

	parts := make([]string, len(ordered))
	for i, cpu := range ordered {
		parts[i] = strconv.Itoa(cpu)
	}
	return strings.Join(parts, ",")
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
