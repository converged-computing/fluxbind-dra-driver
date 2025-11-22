#!/bin/bash

echo "Received FLUXBIND_CPUSET: $FLUXBIND_CPUSET"
BIND_LOCATION=$FLUXBIND_CPUSET

if [[ "${BIND_LOCATION}" == "" ]]; then
    # For an unbound task, the "effective" binding is the entire machine.
    binding_source="UNBOUND"
    cpuset_mask=$(hwloc-calc machine:0)
    logical_cpu_list=$(hwloc-calc "$cpuset_mask" --intersect PU 2>/dev/null)
    physical_core_list=$(hwloc-calc "$cpuset_mask" --intersect core 2>/dev/null)
else
    # For a bound task, calculate the mask and lists from the target location string.
    binding_source=${BIND_LOCATION}
    cpuset_mask=$(hwloc-calc ${BIND_LOCATION})
    logical_cpu_list=$(hwloc-calc ${BIND_LOCATION} --intersect PU 2>/dev/null)
    physical_core_list=$(hwloc-calc ${BIND_LOCATION} --intersect core 2>/dev/null)
fi

if [[ "$FLUXBIND_NOCOLOR" != "1" ]]
  then
  YELLOW='\033[1;33m'
  GREEN='\033[0;32m'
  RESET='\033[0m'
  BLUE='\e[0;34m'
  CYAN='\e[0;36m'
  MAGENTA='\e[0;35m'
  ORANGE='\033[0;33m'
else
  YELLOW=""
  GREEN=""
  RESET=""
  BLUE=""
  CYAN=""
  MAGENTA=""
  ORANGE=""
fi

if [[ "$FLUXBIND_QUIET" != "1" ]]
  then
  prefix="${YELLOW}rank ${rank}${RESET}"
  echo -e "${prefix}: Binding Source:         ${MAGENTA}$binding_source${RESET}"
  echo -e "${prefix}: PID for container:      ${GREEN}$$ ${RESET}"
  echo -e "${prefix}: Effective Cpuset Mask:  ${CYAN}$cpuset_mask${RESET}"
  echo -e "${prefix}: Logical CPUs (PUs):     ${BLUE}${logical_cpu_list:-none}${RESET}"
  echo -e "${prefix}: Physical Cores:         ${ORANGE}${physical_core_list:-none}${RESET}"
  if [[ ! -z "$CUDA_VISIBLE_DEVICES" ]]; then
    echo -e "${prefix}: CUDA Devices:           ${YELLOW}${CUDA_VISIBLE_DEVICES}${RESET}"
  fi
  if [[ ! -z "$ROCR_VISIBLE_DEVICES" ]]; then
    echo -e "${prefix}: ROCR Devices:           ${YELLOW}${ROCR_VISIBLE_DEVICES}${RESET}"
  fi
  echo
fi

# The 'exec' command replaces this script's process, preserving the env.
# I learned this developing singularity shell, exec, etc :)
if [[ "${BIND_LOCATION}" == "UNBOUND" ]]; then
    if [[ "$FLUXBIND_SILENT" != "1" ]]; then echo -e "${GREEN}fluxbind${RESET}: Container is ${BIND_LOCATION} to execute: $@" >&2; fi
else
   echo -e "${GREEN}fluxbind${RESET}: Container is bound to ${BIND_LOCATION} to execute: $@" >&2;
fi

sleep infinity
