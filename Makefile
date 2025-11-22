IMG ?= ghcr.io/converged-computing/fluxbind-dra-driver

# CONTAINER_TOOL defines the container tool to be used for building images.
# Be aware that the target commands are only tested with Docker which is
# scaffolded by default. However, you might want to replace it to use other
# tools. (i.e. podman)
CONTAINER_TOOL ?= docker

# Setting SHELL to bash allows bash commands to be executed by recipes.
# Options are set to exit when a recipe line exits non-zero or a piped command fails.
SHELL = /usr/bin/env bash -o pipefail
.SHELLFLAGS = -ec

.PHONY: all
all: build build-nri

.PHONY: help
help: ## Display this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

    .PHONY: protoc
protoc: $(LOCALBIN)
	GOBIN=$(LOCALBIN) go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.28
	GOBIN=$(LOCALBIN) go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.2

# You can use make protoc to download proto
.PHONY: proto
proto: protoc
	mkdir -p ./fluxbind_dra/proto
	python -m grpc_tools.protoc -I=. --python_out=./ --grpc_python_out=./ fluxbind_dra/proto/dra/dra.proto
	python -m grpc_tools.protoc -I=. --python_out=./ --grpc_python_out=./ fluxbind_dra/proto/pluginregistration/api.proto

# If you wish to build the manager image targeting other platforms you can use the --platform flag.
# (i.e. docker build --platform linux/arm64). However, you must enable docker buildKit for it.
# More info: https://docs.docker.com/develop/develop-images/build_enhancements/
.PHONY: build
build: ## Build docker image with the manager.
	$(CONTAINER_TOOL) build -f docker/Dockerfile --no-cache -t ${IMG} .

.PHONY: build-nri
build-nri: ## Build docker image with the manager.
	$(CONTAINER_TOOL) build -f docker/Dockerfile.nri -t ${IMG}:nri .

.PHONY: build-hwloc
build-hwloc: ## Build docker image with the manager.
	$(CONTAINER_TOOL) build -f docker/Dockerfile.hwloc -t ${IMG}:hwloc .

.PHONY: load
load:
	kind load docker-image ${IMG}

.PHONY: load
load: load-dra load-nri

.PHONY: load-dra
load-dra:
	kind load docker-image ${IMG}

.PHONY: load-nri
load-nri:
	kind load docker-image ${IMG}:nri

.PHONY: build-load
build-load: build load

.PHONY: kind
kind:
	kind create cluster --config examples/kind-config.yaml

.PHONY: push
push: ## Push docker image with the manager.
	$(CONTAINER_TOOL) push ${IMG}
