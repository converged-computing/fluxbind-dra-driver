package main

import (
	"context"
	"testing"

	"github.com/containerd/nri/pkg/api"
)

func TestCpusFromEnv(t *testing.T) {
	tests := []struct {
		name    string
		env     []string
		want    string
		found   bool
		wantErr bool
	}{
		{name: "unset", env: []string{"PATH=/bin"}, found: false},
		{name: "nil env", env: nil, found: false},
		{name: "range", env: []string{"FLUXBIND_CPUS=0-3"}, want: "0-3", found: true},
		{name: "beyond 64 cpus", env: []string{"FLUXBIND_CPUS=0,48,95,191"}, want: "0,48,95,191", found: true},
		{name: "canonicalized", env: []string{"FLUXBIND_CPUS=3,2,1,0,48-49"}, want: "0-3,48-49", found: true},
		{name: "mask is ignored", env: []string{"FLUXBIND_CPUSET=0xff"}, found: false},
		{name: "empty", env: []string{"FLUXBIND_CPUS="}, found: true, wantErr: true},
		{name: "garbage", env: []string{"FLUXBIND_CPUS=0xff"}, found: true, wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, found, err := cpusFromEnv(tt.env)
			if found != tt.found {
				t.Fatalf("found = %v, want %v", found, tt.found)
			}
			if (err != nil) != tt.wantErr {
				t.Fatalf("err = %v, wantErr %v", err, tt.wantErr)
			}
			if got != tt.want {
				t.Fatalf("cpus = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestCreateContainerSetsCpuset(t *testing.T) {
	d := &Driver{}
	pod := &api.PodSandbox{Namespace: "default", Name: "p"}
	ctr := &api.Container{Name: "c", Env: []string{"FLUXBIND_CPUS=0,48,1,49"}}

	adj, _, err := d.CreateContainer(context.Background(), pod, ctr)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	got := adj.GetLinux().GetResources().GetCpu().GetCpus()
	if got != "0-1,48-49" {
		t.Fatalf("cpuset = %q, want %q", got, "0-1,48-49")
	}
}

func TestCreateContainerFailsOnInvalidCpus(t *testing.T) {
	d := &Driver{}
	pod := &api.PodSandbox{Namespace: "default", Name: "p"}
	ctr := &api.Container{Name: "c", Env: []string{"FLUXBIND_CPUS=not-a-list"}}

	if _, _, err := d.CreateContainer(context.Background(), pod, ctr); err == nil {
		t.Fatal("expected error for invalid cpulist")
	}
}

func TestCreateContainerNoEnvIsNoop(t *testing.T) {
	d := &Driver{}
	pod := &api.PodSandbox{Namespace: "default", Name: "p"}
	ctr := &api.Container{Name: "c"}

	adj, _, err := d.CreateContainer(context.Background(), pod, ctr)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if adj.GetLinux() != nil {
		t.Fatalf("expected no linux adjustment, got %v", adj.GetLinux())
	}
}
