---
name: vsphere-mcp
description: Manage VMware vSphere / vCenter / ESXi environments (VMs, templates, snapshots, hosts, clusters, datastores, networks, VLANs, alarms, resource utilization, real-time performance metrics, guest IP addresses, vSAN monitoring) through the vmware-vsphere-mcp-server. Use whenever the user mentions vSphere, vCenter, ESXi, VMware, virtual machines on VMware, VM templates, snapshots, datastore usage, ESXi hosts, clusters, port groups, VLANs, VM power ops, VM cloning from template, performance metrics, CPU/memory/disk/network usage, guest IP / VM IP address / find VM by IP, **vSAN, stretched cluster, witness host, vSAN capacity, vSAN disk groups, vSAN health, vSAN performance metrics, vSAN objects, vSAN storage policies** — even when the word "VMware" is not used explicitly. Covers 55+ tools across 12 categories. All vSAN tools are read-only (Tier 1).
---

# vSphere MCP skill (template)

> **This is a public template.** Replace every placeholder wrapped in `<…>`
> with values from your own environment before relying on this skill.
> The `vmware-vsphere-mcp-server` exposes identical tool surfaces on
> however many MCP backends you configure — names below are **placeholders**.

---

## 0. Placeholders — fill in for your environment

| Placeholder | What it means | Example value (DO NOT use as-is) |
|---|---|---|
| `<MCP_BACKEND_A>` | First MCP server name (e.g. one per vCenter) | `<your-vsphere-dc1>` |
| `<MCP_BACKEND_B>` | Second MCP server name | `<your-vsphere-dc2>` |
| `<MCP_BACKEND_C>` | Third MCP server name | `<your-vsphere-dc3>` |
| `<VCENTER_FQDN>` | vCenter hostname / IP your backend points at | `<vcenter.example.com>` |
| `<DATACENTER_NAME>` | Default datacenter name in your vCenter | `<DC-Main>` |
| `<CLUSTER_NAME>` | Default cluster name | `<Prod-Cluster>` |
| `<DATASTORE_NAME>` | Default datastore name | `<vsan-datastore>` |
| `<NETWORK_NAME>` | Default port group name | `<vlan-100-mgmt>` |
| `<TEMPLATE_NAME>` | Default VM template | `<ubuntu-22.04-tpl>` |
| `<VLAN_QUERY>` | Sample VLAN name or ID for queries | `<v1306-Mgmt>` or `<1306>` |

**Runtime prefix pattern:** every MCP tool is invoked as
`mcp__<MCP_BACKEND_X>__<tool_short_name>`. Examples below use
`<MCP_BACKEND_A>` — substitute your actual backend name.

---

## 1. Safety model — read this first

vSphere operations are live infrastructure. Three tiers:

### Tier 1 — Read-only (safe, run freely)

`list_vms`, `get_vm_details`, `get_vm_disk_usage`, `get_vm_events`,
`get_vm_performance_info`, `get_vm_storage_info`,
`get_vms_with_high_resource_usage`, `generate_vm_report`,
`get_vm_networks_pyvmomi`, `get_vm_metrics`, `get_vm_ip`, `list_vm_ips`,
`list_vm_snapshots`,
`list_templates`, `find_template_pyvmomi`, `list_datacenters`,
`list_datacenters_pyvmomi`, `list_clusters_pyvmomi`, `list_hosts`,
`get_host_details`, `get_host_performance_info`, `get_host_metrics`,
`list_folders`, `list_networks`, `get_network_details`, `list_vlans`,
`get_vlan_info`, `get_port_groups`, `list_datastores`,
`get_datastore_details`, `get_datastore_usage`, `get_datacenter_details`,
`get_folder_details`, `get_alarms`, `get_resource_utilization_summary`,
`list_vsan_clusters`, `get_vsan_cluster_health`, `get_vsan_capacity_info`,
`get_vsan_disk_groups`, `get_vsan_performance_metrics`,
`get_vsan_health_checks`, `get_vsan_objects`, `get_vsan_storage_policies`,
`get_vsan_capabilities`, `get_vsan_witness_info`.

All vSAN tools are read-only. Destructive vSAN operations (add/remove/claim
disk, evacuate, witness add/remove) are **not implemented** and out of scope.

### Tier 2 — Mutating (need context + care)

`power_on_vm`, `power_off_vm` (graceful), `bulk_power_operations`,
`create_vm_snapshot`, `clone_vm`, `modify_vm_resources`.

Before applying Tier 2 on an unfamiliar vCenter, run the matching read first:
`list_datacenters` → `list_hosts` / `list_clusters_pyvmomi` → `list_datastores`
→ `list_vms` → `list_templates` → `list_vm_snapshots`.

### Tier 3 — Destructive / irreversible (require explicit user confirmation AND `confirm=True`)

| Tool | Why dangerous | `confirm` gate |
|---|---|---|
| `delete_vm` | Permanently removes VM + virtual disks + snapshots. **Cannot be undone.** | **yes** (default `false`) |
| `bulk_delete_vms` | Permanently removes multiple VMs. | **yes** (default `false`) |
| `force_power_off_vm` | "Equivalent to pulling the power cord" — risks filesystem/DB corruption. | **yes** (default `false`) |
| `delete_vm_snapshot` | Deletes a snapshot; state deltas may merge into parent. | **yes** (default `false`) |
| `modify_vm_resources` | Hot-modifies CPU/memory of a VM. Wrong values can starve or crash it. | **yes** (default `false`) |
| `clone_vm` | Creates a new VM from template; wrong target/storage/network wastes resources. | **yes** (default `false`) |

**Confirm-gating rule:** these tools silently refuse to act unless
`confirm=True` is passed. If you omit `confirm` or set it `false`, the tool
returns an error and performs nothing — re-call with `confirm=True` only
**after** explicit user confirmation.

### Asymmetric gating — do not assume symmetry

- `power_off_vm` (graceful) → **NOT gated** by `confirm`.
- `force_power_off_vm` → **gated** by `confirm`.
- `create_vm_snapshot` → **NOT gated** by `confirm`.
- `delete_vm_snapshot` → **gated** by `confirm`.

### What this server does NOT have

- ❌ No `approval_token` parameter on any tool. Only the boolean `confirm` is used.
- ❌ No token-issuing tool. Confirmation is a plain boolean — there is no two-step nonce flow.
- ❌ No read-only execution mode toggle, no command allowlist/denylist by tool name.
- ❌ No job/async tracking surface. Operations are synchronous in the tool call.

### Security caveats

- **SSL:** pyVmomi supports CA-aware SSL via `REQUESTS_CA_BUNDLE` /
  `VCENTER_CA_BUNDLE` env vars on the MCP server side.
- Run the MCP server with **least-privilege vCenter credentials**
  (read-only role for listing; restricted role for destructive tools).
- Auth is **env-var only**; no per-user sessions. Anyone who can call this
  MCP server can act as the configured vCenter user.

---

## 2. Common data formats & conventions

| Concept | Format | Example | Used by |
|---|---|---|---|
| Backend choice | pick one MCP per task | `<MCP_BACKEND_A>` OR `<MCP_BACKEND_B>` OR `<MCP_BACKEND_C>` | all calls |
| `vm_id` | VM ID **or** VM name (string) | `"vm-123"`, `"web-01"` | most VM tools, `get_vm_metrics` |
| `host_id` | ESXi host ID (host-N) **or** IP/hostname | `"host-21"`, `"192.0.2.10"` | `get_host_details`, `get_host_metrics` |
| `vm_name` | VM name (string) | `"web-01"` | `clone_vm` (new), `get_vm_networks_pyvmomi`, `get_vm_ip` |
| `template_name` | template VM name | `"ubuntu-22.04-tpl"` | `clone_vm` (source), `find_template_pyvmomi` (partial/case-insensitive) |
| `cluster_name` | cluster name | `"Prod-Cluster"` | `clone_vm`, all `get_vsan_*` |
| `datacenter` | datacenter name | `"DC-Main"` | `list_clusters_pyvmomi`, `find_template_pyvmomi` |
| `datastore_name` | datastore name | `"vsan-datastore"` | `clone_vm` (optional; omit = use template's) |
| `network_name` | portgroup/network name | `"vlan-100-mgmt"` | `clone_vm` (optional; omit = inherit template's) |
| `cpu_count` | integer | `4` | `clone_vm`, `modify_vm_resources` (`0` = template default) |
| `memory_gb` | integer GB | `8` | `clone_vm`, `modify_vm_resources` (`0` = template default) |
| `snapshot_id` | snapshot ID string | from `list_vm_snapshots` | `delete_vm_snapshot` |
| `vlan_query` | VLAN name **or** VLAN ID | `"v1306-Mgmt"`, `1306` | `get_vlan_info` |
| `vm_list` | comma-separated VM names/IDs | `"web-01,db-02,vm-99"` | `bulk_delete_vms`, `bulk_power_operations` |
| `operation` | enum: `on` / `off` / `restart` | `"off"` | `bulk_power_operations` |
| `interval_id` | performance interval | `20` (realtime ~30min), `300` (5min historical) | `get_vm_metrics`, `get_host_metrics` |
| `max_sample` | max samples to retrieve | `10` | `get_vm_metrics`, `get_host_metrics` |
| `max_count` | max events to retrieve | `20` | `get_vm_events` |
| `entity_type` | alarm filter | `"HostSystem"`, `"VirtualMachine"` | `get_alarms` |
| `confirm` | boolean | `true` | 6 destructive tools (see Tier 3) |
| `hostname` | vCenter/ESXi host (optional override) | `"vcenter.example.com"` | every tool; defaults to `VCENTER_HOST` env |
| `folder_type` | enum | `VIRTUAL_MACHINE` (default), `HOST`, `DATACENTER`, `DATASTORE`, `NETWORK` | `list_folders` |

### ID resolution

- Most VM tools accept either the VM ID or the VM name in `vm_id` / `vm_name`.
  Capture and pass exactly what a prior tool returned.
- `find_template_pyvmomi(name=...)` is **partial + case-insensitive** — good for discovery.
- `get_vm_networks_pyvmomi` uses `vm_name` (not `vm_id`) — it goes through
  the pyVmomi SOAP path.

---

## 3. Categories

### Cluster, nodes & inventory (read-only)

`list_datacenters`, `list_datacenters_pyvmomi`, `list_clusters_pyvmomi`,
`list_hosts`, `get_host_details`, `get_host_performance_info`,
`get_host_metrics`, `get_datacenter_details`, `get_resource_utilization_summary`.

- **First call after connect:** `list_datacenters` + `list_hosts` →
  confirm reachability, learn names.
- `list_clusters_pyvmomi(datacenter="<DATACENTER_NAME>")` is **required-param**
  — go through `list_datacenters_pyvmomi` first to get valid names.
- `get_host_performance_info()` returns CPU/RAM/network across all ESXi hosts
  (aggregate).
- `get_host_metrics(host_id, interval_id=20, max_sample=10)` — real-time
  per-host metrics through pyVmomi PerformanceManager (CPU usage/ready per
  core, memory active/consumed, disk read/write/latency, network
  received/transmitted).

```text
list_datacenters()
list_datacenters_pyvmomi()
list_hosts()
get_host_details(host_id="host-21")
get_host_metrics(host_id="host-21", interval_id=20, max_sample=10)
list_clusters_pyvmomi(datacenter="<DATACENTER_NAME>")
get_resource_utilization_summary()
```

### Virtual Machines — listing & details (read-only)

`list_vms`, `get_vm_details`, `get_vm_disk_usage`, `get_vm_events`,
`get_vm_performance_info`, `get_vm_storage_info`,
`get_vms_with_high_resource_usage`, `generate_vm_report`,
`get_vm_networks_pyvmomi`, `get_vm_metrics`, `get_vm_ip`, `list_vm_ips`.

- `list_vms()` → all VMs with basics. `get_vm_details(vm_id="vm-100")` → full config.
- `generate_vm_report()` → comprehensive dump of all VMs (heavier; use for audits).
- `get_vm_events(vm_id, max_count=20)` → recent vCenter events for a VM
  through pyVmomi EventManager.
- `get_vm_networks_pyvmomi(vm_name="web-01")` → network adapter details via
  SOAP (more reliable than REST for vNIC config).
- `get_vm_metrics(vm_id, interval_id=20, max_sample=10)` → real-time VM
  metrics through pyVmomi PerformanceManager (CPU usage/ready, memory
  active/consumed, disk read/write/latency, network received/transmitted).
  **Note:** VMware Tools required for guest-level metrics; powered-off VMs
  return no realtime data.
- `get_vm_ip(vm_name="web-01")` → guest OS IP address(es) via pyVmomi
  `vm.guest` (REST API does **not** expose guest IP). Returns primary IP,
  guest hostname, VMware Tools version, and per-NIC details (network,
  MAC, connected state, IPv4/IPv6 with prefix length).
  **Requires:** VM powered on **and** VMware Tools running. Graceful
  fallback messages if VM not found / not powered on / Tools not running.
- `list_vm_ips()` → one-shot summary of guest IPs across every powered-on
  VM with running VMware Tools (single PropertyCollector query; skips
  templates). Useful for network inventory and "find VM by IP" lookups.

**⚠️ Memory metric interpretation:**

- `mem.active` — actually used by guest OS processes (the real load).
- `mem.consumed` — reserved by ESXi (includes overhead, caches, balloon driver).
- **Do not confuse:** `consumed` ≠ guest usage. If `active = 53 MB` while
  `consumed = 4 GB`, the guest is using only 53 MB.
- For real load assessment, look at `mem.active`, not `consumed`.

```text
list_vms()
get_vm_details(vm_id="vm-100")
get_vm_performance_info()
get_vm_storage_info()
get_vm_events(vm_id="vm-100", max_count=20)
get_vm_networks_pyvmoki(vm_name="web-01")
get_vm_metrics(vm_id="web-01", interval_id=20, max_sample=10)
get_vm_ip(vm_name="web-01")
list_vm_ips()
get_vms_with_high_resource_usage()
```

### VM power operations

`power_on_vm`, `power_off_vm`, `force_power_off_vm`, `bulk_power_operations`.

- `power_on_vm` / `power_off_vm` → graceful, **not confirm-gated**.
- `force_power_off_vm(vm_id, confirm=True)` → "pull the power cord" —
  **confirm-gated**, Tier 3.
- `bulk_power_operations(operation="off", vm_list="web-01,db-02")` →
  applies to all in list. `operation`: `on` / `off` / `restart`.

```text
power_on_vm(vm_id="vm-100")
power_off_vm(vm_id="vm-100")
force_power_off_vm(vm_id="vm-100", confirm=True)   # Tier 3
bulk_power_operations(operation="restart", vm_list="web-01,web-02,web-03")
```

### VM lifecycle — clone, modify, delete (destructive)

`clone_vm`, `modify_vm_resources`, `delete_vm`, `bulk_delete_vms`.

- `clone_vm` required: `template_name`, `vm_name`, `cluster_name`. Optional:
  `datastore_name` (omit = use template's), `cpu_count=0` (0 = template
  default), `memory_gb=0` (0 = template default), `target_datacenter`
  (**required for cross-DC cloning**), `network_name`, `confirm=True`
  (gated), `hostname`.
- `modify_vm_resources` required: `vm_id`. Optional: `cpu_count`,
  `memory_gb`, `confirm=True` (gated), `hostname`.
- `delete_vm` required: `vm_id`. Optional: `confirm=True` (gated —
  **default `false`**), `hostname`.
- `bulk_delete_vms` required: `vm_list` (comma-separated). Optional:
  `confirm=True` (gated), `hostname`.

```text
# Clone from template (same DC)
clone_vm(template_name="<TEMPLATE_NAME>", vm_name="web-05",
         cluster_name="<CLUSTER_NAME>",
         datastore_name="<DATASTORE_NAME>",
         network_name="<NETWORK_NAME>",
         cpu_count=4, memory_gb=8, confirm=True)

# Clone cross-DC
clone_vm(template_name="<TEMPLATE_NAME>", vm_name="web-dr-01",
         cluster_name="<DR_CLUSTER_NAME>",
         target_datacenter="<DR_DATACENTER>",
         datastore_name="<DR_DATASTORE>",
         network_name="<DR_NETWORK>",
         cpu_count=4, memory_gb=8, confirm=True)

# Modify resources
modify_vm_resources(vm_id="vm-100", cpu_count=8, memory_gb=16, confirm=True)

# Delete (Tier 3 — confirm with user first)
delete_vm(vm_id="vm-100", confirm=True)
bulk_delete_vms(vm_list="web-old-01,web-old-02,web-old-03", confirm=True)
```

### Snapshots

`list_vm_snapshots`, `create_vm_snapshot`, `delete_vm_snapshot`.

- `create_vm_snapshot` required: `vm_id`, `snapshot_name`. Optional:
  `description`, `hostname`. **Not confirm-gated** (Tier 2).
- `delete_vm_snapshot` required: `vm_id`, `snapshot_id` (from
  `list_vm_snapshots`). Optional: `confirm=True` (**gated**), `hostname`.
  Tier 3.
- **Always `create_vm_snapshot` before destructive workflows** (delete,
  risky `modify_vm_resources`, `force_power_off_vm`).

```text
list_vm_snapshots(vm_id="vm-100")
create_vm_snapshot(vm_id="vm-100", snapshot_name="pre-upgrade",
                   description="before kernel update")
delete_vm_snapshot(vm_id="vm-100", snapshot_id="snap-42",
                   confirm=True)   # Tier 3
```

### Templates

`list_templates`, `find_template_pyvmomi`.

- `list_templates()` → all VM templates.
- `find_template_pyvmomi(name="ubuntu")` → partial + case-insensitive
  match; scope with `datacenter` if needed.

```text
list_templates()
find_template_pyvmomi(name="ubuntu")
find_template_pyvmoki(name="win2022", datacenter="<DATACENTER_NAME>")
```

### Datastores

`list_datastores`, `get_datastore_details`, `get_datastore_usage`.

- `list_datastores()` → all datastores with capacity.
- `get_datastore_usage()` → usage snapshot to spot storage pressure.
- `get_datastore_details(datastore_id="datastore-42")` → one datastore detail.

```text
list_datastores()
get_datastore_usage()
get_datastore_details(datastore_id="datastore-42")
```

### Networks, VLANs, port groups

`list_networks`, `get_network_details`, `list_vlans`, `get_vlan_info`,
`get_port_groups`, `list_folders`, `get_folder_details`.

- `get_vlan_info(vlan_query="1306")` → by ID;
  `get_vlan_info(vlan_query="v1306-Mgmt")` → by name.
- `get_port_groups()` → all port groups (needed before `clone_vm` `network_name`).
- `list_folders(folder_type="VIRTUAL_MACHINE")` → `folder_type`:
  `VIRTUAL_MACHINE` (default), `HOST`, `DATACENTER`, `DATASTORE`, `NETWORK`.

```text
list_networks()
get_network_details(network_id="network-17")
list_vlans()
get_vlan_info(vlan_query="<VLAN_QUERY>")
get_port_groups()
list_folders(folder_type="VIRTUAL_MACHINE")
get_folder_details(folder_id="group-v42")
```

### Monitoring & Alarms

`get_alarms`, `get_resource_utilization_summary`.

- `get_alarms(entity_type=None)` → active vSphere alarms through pyVmomi
  AlarmManager. Optional `entity_type`: `"HostSystem"` or `"VirtualMachine"`
  for filtering.
- `get_resource_utilization_summary()` → CPU/RAM/storage/network utilisation
  across the environment.

**Real-time metrics** are available through:
- `get_vm_metrics(vm_id, interval_id=20, max_sample=10)` — VM details
  (see "Virtual Machines" section).
- `get_host_metrics(host_id, interval_id=20, max_sample=10)` — host details
  (see "Cluster, nodes & inventory" section).

```text
get_alarms()
get_alarms(entity_type="VirtualMachine")
get_resource_utilization_summary()
get_vm_metrics(vm_id="web-01", interval_id=20)
get_host_metrics(host_id="host-21", interval_id=20)
```

### vSAN monitoring (read-only — all 10 tools are Tier 1)

`list_vsan_clusters`, `get_vsan_cluster_health`, `get_vsan_capacity_info`,
`get_vsan_disk_groups`, `get_vsan_performance_metrics`,
`get_vsan_health_checks`, `get_vsan_objects`, `get_vsan_storage_policies`,
`get_vsan_capabilities`, `get_vsan_witness_info`.

- **All vSAN tools are read-only (Tier 1).** Destructive vSAN operations
  (add/remove/claim disk, evacuate, witness add/remove) are **not
  implemented** and out of scope.
- **Backend:** pyVmomi on the `/vsanHealth` endpoint
  (`vim.version.version11`). vSAN-specific REST endpoints
  (`vcenter/vsan/*`) are typically absent on vCenter 8.0.x — implementation
  goes through SOAP. The only exception is `get_vsan_storage_policies`,
  which uses REST `/vcenter/storage/policies`.
- **Three-layer model:** inventory → health → objects/policies.

**Inventory / overview:**

- `list_vsan_clusters()` → all vSAN-enabled clusters.
- `get_vsan_cluster_health(cluster_name)` → 🟢/🟡/🔴 overall + per-host
  (via `VsanVcClusterHealthSystem.QueryClusterHealthSummary`).
- `get_vsan_capacity_info(cluster_name)` → total/free/used TB + % (via
  `VsanSpaceReportSystem.VsanQuerySpaceUsage`).

**Health / performance:**

- `get_vsan_disk_groups(cluster_name)` → cache SSD + capacity tier per host
  (per-host iteration is required — `QueryDiskMappings` takes `host=`, not
  `cluster=`).
- `get_vsan_performance_metrics(cluster_name, entity_type="cluster-domclient")`
  → IOPS read/write, throughput, latency, congestion, outstanding IO.
  **Idle clusters return empty `value=[]` — that's a valid production
  state, not an error.**
- `get_vsan_health_checks(cluster_name)` → overall + 9 health groups +
  per-host node state (master/backup/agent).

**Objects / policies / capabilities:**

- `get_vsan_objects(cluster_name, object_type="all")` → all vSAN objects
  with type breakdown (vdisk/namespace/vmswap/...) and SPBM profiles. Uses
  `QueryObjectIdentities` (not `QueryObjects`, which is absent on 8.0.3).
- `get_vsan_storage_policies(hostname=None)` → all vCenter SPBM policies
  with vSAN-related filter (REST).
- `get_vsan_capabilities(hostname=None)` → 100+ advertised vCenter
  vSAN features (`VsanGetCapabilities()`, no cluster arg). **`VsanGetCapabilities()`
  does NOT take a cluster arg** (only vCenter-wide).
- `get_vsan_witness_info(cluster_name)` → for stretched clusters returns
  witness host(s); for ordinary (most prod) — graceful "Cluster is not
  stretched" (via `RetrieveStretchedClusterVcCapability` →
  `ManagedObjectNotFound`).

```text
list_vsan_clusters()
get_vsan_cluster_health(cluster_name="<CLUSTER_NAME>")
get_vsan_capacity_info(cluster_name="<CLUSTER_NAME>")
get_vsan_disk_groups(cluster_name="<CLUSTER_NAME>")
get_vsan_performance_metrics(cluster_name="<CLUSTER_NAME>")
get_vsan_health_checks(cluster_name="<CLUSTER_NAME>")
get_vsan_objects(cluster_name="<CLUSTER_NAME>")
get_vsan_objects(cluster_name="<CLUSTER_NAME>", object_type="vdisk")
get_vsan_storage_policies()
get_vsan_capabilities()
get_vsan_witness_info(cluster_name="<CLUSTER_NAME>")
# graceful "not stretched" for ordinary clusters
```

---

## 4. Complex workflows

### A. Clone a VM from template, end-to-end

```text
1. list_datacenters()                                  # confirm DC name
2. list_clusters_pyvmomi(datacenter="<DATACENTER>")    # confirm cluster
3. list_datastores()                                   # pick datastore
4. get_port_groups()                                   # pick network
5. find_template_pyvmomi(name="ubuntu-22.04")          # confirm template
6. clone_vm(template_name="<TEMPLATE_NAME>",
            vm_name="web-05", cluster_name="<CLUSTER>",
            datastore_name="<DATASTORE>",
            network_name="<NETWORK>",
            cpu_count=4, memory_gb=8, confirm=True)
7. get_vm_details(vm_id="web-05")                      # verify
```

### B. Snapshot before a destructive op, delete if it goes wrong

```text
1. list_vm_snapshots(vm_id="vm-100")
2. create_vm_snapshot(vm_id="vm-100", snapshot_name="before-cleanup")
3. # ... apply the risky change ...
4. # if it broke — restore from snapshot via vSphere client
   # (this MCP has no rollback tool)
5. # if it went well:
   delete_vm_snapshot(vm_id="vm-100", snapshot_id="snap-42",
                      confirm=True)   # Tier 3
```

> Note: this MCP server has **no snapshot rollback/restore tool**. Rollback
> must be done via vSphere UI/PowerCLI.

### C. Bulk graceful shutdown of a tier, then force-off stragglers

```text
1. list_vms()                                          # confirm target names
2. bulk_power_operations(operation="off",
                         vm_list="web-01,web-02,web-03")
3. # check what's still powered on
4. force_power_off_vm(vm_id="web-02", confirm=True)    # Tier 3
```

### D. Audit: high-resource VMs + datastore pressure + alarms

```text
1. get_vms_with_high_resource_usage()
2. get_datastore_usage()
3. get_alarms()
4. generate_vm_report()                                # full dump
```

### E. Modify VM resources safely

```text
1. get_vm_details(vm_id="vm-100")                      # current CPU/RAM
2. create_vm_snapshot(vm_id="vm-100", snapshot_name="pre-resize")
3. modify_vm_resources(vm_id="vm-100", cpu_count=8,
                       memory_gb=16, confirm=True)
4. get_vm_details(vm_id="vm-100")                      # verify
```

### F. vSAN cluster health check (read-only)

```text
1. list_vsan_clusters()                                # confirm vSAN clusters
2. get_vsan_cluster_health(cluster_name="<VSAN_CLUSTER>")
                                                        # overall + per-host
3. get_vsan_capacity_info(cluster_name="<VSAN_CLUSTER>")
                                                        # free/used TB + %
4. get_vsan_disk_groups(cluster_name="<VSAN_CLUSTER>")
                                                        # cache + capacity tier
5. get_vsan_health_checks(cluster_name="<VSAN_CLUSTER>")
                                                        # 9 health groups + node states
6. # If stretched cluster is suspected:
7. get_vsan_witness_info(cluster_name="<VSAN_CLUSTER>")
                                                        # witness host(s) or "not stretched"
```

### G. vSAN inventory + SPBM policy audit

```text
1. list_vsan_clusters()                                # cluster names
2. get_vsan_objects(cluster_name="<VSAN_CLUSTER>")     # all objects (with VM MoRefs)
3. get_vsan_objects(cluster_name="<VSAN_CLUSTER>", object_type="vdisk")
                                                        # only vdisks
4. get_vsan_storage_policies()                         # all SPBM policies
5. get_vsan_capabilities()                             # 100+ vCenter features
```

### H. Network inventory / "find VM by IP"

```text
1. list_vm_ips()                                       # one-shot: every powered-on VM with Tools running
2. get_vm_ip(vm_name="<vm>")                           # detail: primary IP + hostname + Tools version + per-NIC
3. get_vm_networks_pyvmomi(vm_name="<vm>")             # static vNIC config (works even without Tools)
```

Use `list_vm_ips()` first to scan, then drill in with `get_vm_ip(vm_name=...)`.
Both rely on VMware Tools — VMs without it show "—" and need
`get_vm_networks_pyvmomi` as fallback.

---

## 5. Backend selection

This server may expose the same tool surface through multiple MCP backends
— one per vCenter, per cluster, per region, etc. Rules:

1. **Pick one per task.** Do not split a workflow across backends — keep
   state coherent.
2. Backend → cluster/vCenter mapping is whatever your `claude_desktop_config.json`
   or `~/.claude.json` `mcpServers` block defines. Each backend name is local
   to your installation — substitute `<MCP_BACKEND_A>` etc. with the actual
   keys you configured.
3. vSAN tools (`list_vsan_clusters`, `get_vsan_*`) called on a backend whose
   vCenter has no vSAN clusters will return `No vSAN clusters found` or
   `cluster '<X>' not found` — this is correct graceful fallback, not an error.
4. If one backend errors repeatedly, you may switch — re-run discovery
   (`list_datacenters`) on the new one first.
5. At the runtime layer, prefix every call: `mcp__<MCP_BACKEND_X>__<tool>`.
6. Each backend is bound to **one vCenter** (different `VCENTER_HOST` on the
   server side). Confirm with `list_datacenters` which vCenter you're hitting.

---

## 6. Operating checklist

Before **changing** anything on an unfamiliar vCenter:

1. `list_datacenters()` + `list_datacenters_pyvmomi()` — DC names.
2. `list_hosts()` / `list_clusters_pyvmomi(datacenter=...)` — host/cluster names.
3. `list_datastores()` + `get_datastore_usage()` — storage pools and headroom.
4. `list_vms()` — inventory, statuses, IDs.
5. `list_templates()` / `find_template_pyvmomi()` — valid template names for `clone_vm`.
6. `get_port_groups()` — valid `network_name` for `clone_vm`.
7. For destructive/risky work: `list_vm_snapshots(vm_id=...)` — confirm a
   snapshot exists; if not, `create_vm_snapshot` first.
8. Only then apply Tier 2/3 changes — passing `confirm=True` for the gated
   tools **after** explicit user confirmation.

For **vSAN clusters** (read-only inspection):

1. `list_vsan_clusters()` — confirm vSAN clusters exist.
2. `get_vsan_cluster_health(cluster_name=...)` + `get_vsan_capacity_info(...)`
   — overall health + capacity headroom.
3. `get_vsan_disk_groups(cluster_name=...)` — verify cache/capacity tier layout.
4. `get_vsan_health_checks(cluster_name=...)` — drill into 9 health groups
   if any are 🟡/🔴.
5. `get_vsan_performance_metrics(cluster_name=...)` — only if cluster is
   active (idle returns empty samples — that's fine).
6. `get_vsan_objects(cluster_name=...)` + `get_vsan_storage_policies()` —
   inventory + SPBM policy audit.
7. `get_vsan_witness_info(cluster_name=...)` — only meaningful for stretched
   clusters; otherwise expect "not stretched".

**All vSAN tools are Tier 1 read-only. There are no vSAN mutating tools in
this server — destructive vSAN operations are explicitly out of scope.**

---

## 7. Failure patterns to expect

| Symptom | Likely cause |
|---|---|
| `list_*` auth failure / connection refused | `VCENTER_HOST` / `VCENTER_USER` / `VCENTER_PASSWORD` not set or wrong on the MCP server |
| Tool returned "requires confirmation" / did nothing | omitted `confirm=True` on a gated tool — re-call with `confirm=True` after user OK |
| `clone_vm` fails "datastore not found" / "network not found" | cross-DC clone with omitted `datastore_name` / `network_name` — template's aren't visible in target DC. Pass both explicitly. |
| `clone_vm` fails "target_datacenter required" | cross-DC clone attempted without `target_datacenter` |
| `find_template_pyvmomi` returns empty | name too specific — use partial/case-insensitive substring |
| `delete_vm_snapshot` rejected | missing `confirm=True`, or wrong `snapshot_id` (get it from `list_vm_snapshots`) |
| pyVmomi tools (`*_pyvmomi`) fail while REST tools work | pyVmomi not installed on the server, or SSL/MITM intercept breaking SmartConnect |
| `get_vm_ip` returns "VM not found" | name typo or VM not visible to this backend — try `list_vms` to confirm exact spelling |
| `get_vm_ip` returns "is not powered on" | Guest IP only available for powered-on VMs — start it first or use `get_vm_networks_pyvmomi` for static NIC config |
| `get_vm_ip` returns "VMware Tools not running" | Tools service stopped or never installed — guest IP lives inside `vm.guest`, requires Tools. `get_vm_networks_pyvmomi` still works (it reads `vm.config.hardware`) |
| `list_vm_ips` output shows "—" for many VMs | Powered-off VMs and VMs without running Tools are skipped by design (matches pyVmomi's `vm.summary.guest.ipAddress = None`) |
| `list_clusters_pyvmomi` errors | missing required `datacenter` param — get name from `list_datacenters_pyvmomi` first |
| Tool result inconsistent across backends | each backend targets a fixed vCenter — `list_datacenters` per backend reveals scope; vSAN tools on a non-vSAN vCenter return graceful "not found" |
| `modify_vm_resources` / hot-add fails | VM's guest OS or version doesn't support hot-plug; power off first if allowed |
| `get_vsan_performance_metrics` returns empty samples | Idle vSAN cluster (valid production state) — not an error |
| `get_vsan_capabilities` errors with `unexpected keyword argument 'cluster'` | Pass no cluster argument — `VsanGetCapabilities()` is vCenter-wide and does NOT take a cluster |
| `get_vsan_objects` errors with `MethodNotFound` on `QueryObjects` | Expected — endpoint has `QueryObjectIdentities` instead; the tool already uses it internally |
| `get_vsan_witness_info` returns "Cluster is not stretched" | Expected for non-stretched vSAN clusters (most prod); capability flag ≠ stretched state |
| vSAN tool returns `ManagedObjectNotFound` for `vsan-cluster-stretched-system` | vCenter-side stretched-cluster service is not registered (typical for non-stretched vCenters) — graceful fallback in `get_vsan_witness_info` |
| `get_vsan_disk_groups` errors with `unexpected keyword argument 'cluster'` on `QueryDiskMappings` | Tool already handles this — `QueryDiskMappings` is per-host (`host=`), the tool iterates `cluster.host[]` |
| `get_vsan_storage_policies` returns no vSAN-related policies | Check vSAN policy naming — tool filters by keywords like "vsan", "ESA", "RAID" in name/description |

### Don'ts

- ❌ Don't pass `approval_token` — it doesn't exist on this server.
- ❌ Don't assume graceful `power_off_vm` is gated — only `force_power_off_vm` is.
- ❌ Don't assume `create_vm_snapshot` is gated — only `delete_vm_snapshot` is.
- ❌ Don't call `delete_vm` / `bulk_delete_vms` / `force_power_off_vm` /
  `modify_vm_resources` / `clone_vm` / `delete_vm_snapshot` without
  `confirm=True` — they'll silently no-op.
- ❌ Don't expect a snapshot rollback tool — this server can only create/delete
  snapshots, not revert.
- ❌ Don't chain destructive ops in one turn without user confirmation between them.

---

## 8. Customising this template for your environment

Before using this skill in your own installation:

1. **Replace placeholders** (section 0) with the MCP backend names and
   resource names from your `mcpServers` config.
2. **Verify** the tool count matches what your server exposes — different
   forks may add or drop tools (e.g. some forks include vSAN, others don't;
   some forks have `get_vm_metrics`, others don't).
3. **Tune safety language** to match your own operational rules. The three-tier
   model above is a sensible default, but your team may want stricter gates
   (e.g. always require explicit user confirmation before any Tier 2 op).
4. **Append environment-specific notes** to section 7 (Failure patterns) based
   on what you observe in production.

This template intentionally contains **no real infrastructure names** —
copy it, then fill it in for your own vSphere environment.
