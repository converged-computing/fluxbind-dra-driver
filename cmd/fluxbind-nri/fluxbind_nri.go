package main

import (
	"context"
	"flag"
	"fmt"
	"strings"
	"time"

	"github.com/containerd/nri/pkg/api"
	"github.com/containerd/nri/pkg/stub"
	"k8s.io/apimachinery/pkg/util/wait"
	"k8s.io/klog/v2"
	"k8s.io/utils/cpuset"
)

// cpusEnvVar holds the Linux cpulist injected by the DRA driver via CDI.
const cpusEnvVar = "FLUXBIND_CPUS"

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

// CreateContainer applies the cpuset from the container environment, if present.
func (d *Driver) CreateContainer(ctx context.Context, pod *api.PodSandbox, ctr *api.Container) (*api.ContainerAdjustment, []*api.ContainerUpdate, error) {
	klog.Infof("CreateContainer request for %s/%s/%s", pod.Namespace, pod.Name, ctr.Name)

	adjustment := &api.ContainerAdjustment{}
	cpus, found, err := cpusFromEnv(ctr.Env)
	if !found {
		klog.V(5).Infof("No %s environment variable found for container %s. No affinity will be applied.", cpusEnvVar, ctr.Name)
		return adjustment, nil, nil
	}
	if err != nil {
		// Fail container creation rather than silently running unbound.
		return nil, nil, fmt.Errorf("container %s/%s/%s: %w", pod.Namespace, pod.Name, ctr.Name, err)
	}

	klog.Infof("Applying cpuset %q to container %s", cpus, ctr.Name)
	adjustment.SetLinuxCPUSetCPUs(cpus)
	return adjustment, nil, nil
}

// cpusFromEnv returns the canonical cpulist from env, whether it was set, and any parse error.
func cpusFromEnv(env []string) (string, bool, error) {
	prefix := cpusEnvVar + "="
	for _, envVar := range env {
		val, ok := strings.CutPrefix(envVar, prefix)
		if !ok {
			continue
		}
		set, err := cpuset.Parse(val)
		if err != nil {
			return "", true, fmt.Errorf("invalid %s %q: %w", cpusEnvVar, val, err)
		}
		if set.IsEmpty() {
			return "", true, fmt.Errorf("%s is empty", cpusEnvVar)
		}
		return set.String(), true, nil
	}
	return "", false, nil
}

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
