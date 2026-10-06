#!/bin/bash
# Report the CPU affinity the kernel actually enforces for this container and
# compare it with the cpulist the fluxbind DRA driver requested.

# Expand a cpulist like "0-2,5" to one cpu per line, sorted.
expand_cpulist() {
    tr ',' '\n' <<< "$1" | awk -F- 'NF { for (i = $1; i <= ($2 == "" ? $1 : $2); i++) print i }' | sort -n
}

expected="${FLUXBIND_CPUS:-}"
actual=$(awk '/^Cpus_allowed_list:/ {print $2}' /proc/self/status)
mems=$(awk '/^Mems_allowed_list:/ {print $2}' /proc/self/status)
cgroup_cpus=$(cat /sys/fs/cgroup/cpuset.cpus.effective 2>/dev/null || echo "unknown")
mask=$(hwloc-bind --get 2>/dev/null)
cores=$(hwloc-calc --physical-output --intersect core "$mask" 2>/dev/null)
pus=$(hwloc-calc --physical-output --intersect pu "$mask" 2>/dev/null)

echo "Requested FLUXBIND_CPUS:  ${expected:-<unset>}"
echo "Requested FLUXBIND_CPUSET: ${FLUXBIND_CPUSET:-<unset>}"
echo "Cpus_allowed_list:         ${actual}"
echo "cgroup cpuset.cpus.eff:    ${cgroup_cpus}"
echo "Mems_allowed_list:         ${mems}"
echo "hwloc-bind --get:          ${mask}"
echo "Physical PUs:              ${pus:-none}"
echo "Physical cores:            ${cores:-none}"
[[ -n "$CUDA_VISIBLE_DEVICES" ]] && echo "CUDA_VISIBLE_DEVICES:      ${CUDA_VISIBLE_DEVICES}"
[[ -n "$ROCR_VISIBLE_DEVICES" ]] && echo "ROCR_VISIBLE_DEVICES:      ${ROCR_VISIBLE_DEVICES}"

if [[ -z "$expected" ]]; then
    echo "fluxbind: UNBOUND (no FLUXBIND_CPUS set)"
elif [[ "$(expand_cpulist "$expected")" == "$(expand_cpulist "$actual")" ]]; then
    echo "fluxbind: MATCH"
else
    echo "fluxbind: MISMATCH (requested ${expected}, enforced ${actual})"
fi

if [[ $# -gt 0 ]]; then
    exec "$@"
fi
exec sleep infinity
