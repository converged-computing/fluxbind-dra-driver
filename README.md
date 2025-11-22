# Fluxbind Dynamic Resource Assignment Driver

Kubernetes Device Resource Assignment (DRA) driver for node resources.

Fluxbind DRA is DRA driver that enables node-level scheduling (and binding) of resources discovered with hwloc.

## Getting Started

Create a test cluster with DRA enabled. This typically means Kubernetes version 1.34.0 or later.

```bash
make kind
```

If you need to build the container (to load into kind), otherwise just skip this step to pull it.

```bash
make build
kind load docker-image ghcr.io/converged-computing/fluxbind-dra-driver
# or
make build-load
```

Install the driver:

```bash
kubectl apply -f install.yaml
```

Development

```bash
kind delete cluster && make kind && make build-nri && make build-load && kubectl apply -f install.yaml
```

## License

DevTools is distributed under the terms of the MIT license.
All new contributions must be made under this license.

See [LICENSE](https://github.com/converged-computing/cloud-select/blob/main/LICENSE),
[COPYRIGHT](https://github.com/converged-computing/cloud-select/blob/main/COPYRIGHT), and
[NOTICE](https://github.com/converged-computing/cloud-select/blob/main/NOTICE) for details.

SPDX-License-Identifier: (MIT)

LLNL-CODE- 842614
