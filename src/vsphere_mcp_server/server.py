"""vSphere MCP Server - Main server implementation - Docker/Environment version."""

import os
import re
from typing import Dict, List

from mcp.server.fastmcp import FastMCP

from .vsphere_client import VSphereClient
from .pyvmomi_client import PyVmomiClient
from pyVmomi import vim, vmodl

# Initialize MCP server
mcp = FastMCP("vSphere MCP Server")


def _handle_error(e: Exception, operation: str) -> str:
    """Handle errors consistently across all tools."""
    error_msg = str(e)

    if "Authentication failed" in error_msg:
        return (
            f"Authentication failed for {operation}. "
            "Check your environment variables (VCENTER_HOST, VCENTER_USER, VCENTER_PASSWORD)."
        )
    if "Connection" in error_msg or "timeout" in error_msg.lower():
        return f"Connection failed for {operation}. Check network connectivity and hostname."
    return f"Error in {operation}: {error_msg}"


# vSAN-specific error patterns (see VSAN_API_REFERENCE.md §7).
# Order matters: first match wins.
VSAN_ERROR_PATTERNS = [
    ("vsan is not enabled", "vSAN is not enabled on this cluster"),
    ("no vsan configuration", "This cluster has no vSAN configuration"),
    ("vsan license", "vSAN license missing or expired"),
    ("license not available", "vSAN license missing or expired"),
    ("vsan api not available", "vSAN management API unavailable (vCenter 7.0 U2+ required)"),
    ("connection refused", "vSAN service unavailable (degraded cluster or /vsanHealth not reachable)"),
    ("permission denied", "Insufficient permissions for vSAN — need Read-only role with 'Profile-driven storage > View'"),
    ("invalidlogin", "vSAN session expired — retry the operation"),
    ("notfound", "vSAN data not built yet (cold cluster — no disk mappings/objects yet)"),
    ("invalidargument", "Invalid vSAN argument (unknown entityType/perfMetricId/groupId)"),
]


def _handle_vsan_error(e: Exception, operation: str) -> str:
    """Handle vSAN errors with friendly, actionable messages.

    Falls back to the generic _handle_error for unrecognized cases.
    """
    error_msg = str(e)
    lower = error_msg.lower()
    for pattern, friendly in VSAN_ERROR_PATTERNS:
        if pattern in lower:
            return f"{friendly} (operation: {operation})"
    return _handle_error(e, operation)


# VM Management Tools
@mcp.tool()
def list_vms(hostname: str = None) -> str:
    """List all virtual machines with basic information.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        response = client.get("vcenter/vm")
        vms = response.get("value", [])

        if not vms:
            return "No virtual machines found"

        result = f"Found {len(vms)} virtual machines:\n\n"
        for vm in vms:
            result += f"• {vm.get('name', 'Unknown')} (ID: {vm.get('vm')})\n"
            result += f"  Power State: {vm.get('power_state', 'Unknown')}\n"
            result += f"  CPU Count: {vm.get('cpu_count', 'Unknown')}\n"
            result += f"  Memory: {vm.get('memory_size_MiB', 'Unknown')} MiB\n\n"

        return result.strip()

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "listing VMs")
    finally:
        client.close()


@mcp.tool()
def get_vm_details(vm_id: str, hostname: str = None) -> str:
    """Get detailed information about a specific virtual machine.

    Args:
        vm_id: Virtual machine ID or name
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        # If vm_id doesn't start with 'vm-', assume it's a name and look up the ID
        if not vm_id.startswith("vm-"):
            vms_response = client.get("vcenter/vm")
            vms = vms_response.get("value", [])

            # Find VM by name (case-insensitive)
            vm_id_found = None
            for vm in vms:
                if vm.get("name", "").lower() == vm_id.lower():
                    vm_id_found = vm.get("vm")
                    break

            if not vm_id_found:
                return f"Virtual machine '{vm_id}' not found by name"

            vm_id = vm_id_found

        response = client.get(f"vcenter/vm/{vm_id}")
        vm = response.get("value", {})

        if not vm:
            return f"Virtual machine {vm_id} not found"

        result = f"VM Details: {vm.get('name', 'Unknown')}\n"
        result += f"ID: {vm_id}\n"
        result += f"Power State: {vm.get('power_state', 'Unknown')}\n"
        result += f"CPU Count: {vm.get('cpu', {}).get('count', 'Unknown')}\n"
        result += f"Memory: {vm.get('memory', {}).get('size_MiB', 'Unknown')} MiB\n"
        result += f"Guest OS: {vm.get('guest_OS', 'Unknown')}\n"
        result += (
            f"Hardware Version: {vm.get('hardware', {}).get('version', 'Unknown')}\n"
        )

        # Network info
        nics = vm.get("nics", [])
        if nics:
            result += "\nNetwork Interfaces:\n"
            for i, nic in enumerate(nics):
                network_name = "Unknown"
                if isinstance(nic, dict):
                    backing = nic.get("backing", {})
                    if isinstance(backing, dict):
                        network_name = backing.get("network_name", "Unknown")
                result += f"  NIC {i}: {network_name}\n"

        return result

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"getting VM {vm_id} details")
    finally:
        client.close()


@mcp.tool()
def power_on_vm(vm_id: str, hostname: str = None) -> str:
    """Power on a virtual machine.

    Args:
        vm_id: Virtual machine ID
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        client.post(f"vcenter/vm/{vm_id}/power/start")
        return "Power on initiated for VM " + vm_id

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"powering on VM {vm_id}")
    finally:
        client.close()


@mcp.tool()
def power_off_vm(vm_id: str, hostname: str = None) -> str:
    """Power off a virtual machine.

    Args:
        vm_id: Virtual machine ID
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        client.post(f"vcenter/vm/{vm_id}/power/stop")
        return f"Power off initiated for VM {vm_id}"

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"powering off VM {vm_id}")
    finally:
        client.close()


# Infrastructure Tools
@mcp.tool()
def list_hosts(hostname: str = None) -> str:
    """List all ESXi hosts.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        response = client.get("vcenter/host")
        hosts = response.get("value", [])

        if not hosts:
            return "No ESXi hosts found"

        result = f"Found {len(hosts)} ESXi hosts:\n\n"
        for host in hosts:
            result += f"• {host.get('name', 'Unknown')} (ID: {host.get('host')})\n"
            result += f"  Connection State: {host.get('connection_state', 'Unknown')}\n"
            result += f"  Power State: {host.get('power_state', 'Unknown')}\n\n"

        return result.strip()

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "listing hosts")
    finally:
        client.close()


@mcp.tool()
def get_host_details(hostname: str = None, host_id: str = None) -> str:
    """Get detailed information about an ESXi host.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
        host_id: ESXi host ID
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return 'Error: No hostname provided and VCENTER_HOST not set in environment'
    client = VSphereClient(hostname)
    try:
        # Use filter.hosts workaround (GET /vcenter/host/{id} doesn't exist in vCenter 8.0+)
        response = client.get(f"vcenter/host?filter.hosts={host_id}")
        hosts = response.get("value", [])

        if not hosts:
            return f"ESXi host {host_id} not found"

        host = hosts[0]
        result = f"Host Details: {host.get('name', 'Unknown')}\n"
        result += f"ID: {host_id}\n"
        result += f"Connection State: {host.get('connection_state', 'Unknown')}\n"
        result += f"Power State: {host.get('power_state', 'Unknown')}\n"

        return result

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"getting host {host_id} details")
    finally:
        client.close()


@mcp.tool()
def list_datacenters(hostname: str = None) -> str:
    """List all datacenters.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get("VCENTER_HOST")
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        response = client.get("vcenter/datacenter")
        datacenters = response.get("value", [])

        if not datacenters:
            return "No datacenters found"

        result = f"Found {len(datacenters)} datacenters:\n\n"
        for dc in datacenters:
            result += f"• {dc.get('name', 'Unknown')} (ID: {dc.get('datacenter')})\n"

        return result.strip()

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "listing datacenters")
    finally:
        client.close()


@mcp.tool()
def get_datacenter_details(hostname: str = None, datacenter_id: str = None) -> str:
    """Get detailed information about a datacenter.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
        datacenter_id: Datacenter ID
    """
    if hostname is None:
        hostname = os.environ.get("VCENTER_HOST")
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        response = client.get(f"vcenter/datacenter/{datacenter_id}")
        dc = response.get("value", {})

        if not dc:
            return f"Datacenter {datacenter_id} not found"

        result = f"Datacenter Details: {dc.get('name', 'Unknown')}\n"
        result += f"ID: {datacenter_id}\n"

        return result

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"getting datacenter {datacenter_id} details")
    finally:
        client.close()


@mcp.tool()
def list_datastores(hostname: str = None) -> str:
    """List all datastores with capacity information.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        response = client.get("vcenter/datastore")
        datastores = response.get("value", [])

        if not datastores:
            return "No datastores found"

        result = f"Found {len(datastores)} datastores:\n\n"
        for ds in datastores:
            capacity = ds.get("capacity", 0)
            free_space = ds.get("free_space", 0)
            used_space = capacity - free_space
            used_pct = (used_space / capacity * 100) if capacity > 0 else 0

            result += f"• {ds.get('name', 'Unknown')} (ID: {ds.get('datastore')})\n"
            result += f"  Type: {ds.get('type', 'Unknown')}\n"
            result += f"  Capacity: {capacity / (1024**3):.1f} GB\n"
            result += f"  Used: {used_space / (1024**3):.1f} GB ({used_pct:.1f}%)\n"
            result += f"  Free: {free_space / (1024**3):.1f} GB\n\n"

        return result.strip()

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "listing datastores")
    finally:
        client.close()


@mcp.tool()
def get_datastore_details(hostname: str = None, datastore_id: str = None) -> str:
    """Get detailed information about a datastore.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
        datastore_id: Datastore ID
    """
    if hostname is None:
        hostname = os.environ.get("VCENTER_HOST")
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        response = client.get(f"vcenter/datastore/{datastore_id}")
        ds = response.get("value", {})

        if not ds:
            return f"Datastore {datastore_id} not found"

        capacity = ds.get("capacity", 0) or 0
        free_space = ds.get("free_space", 0) or 0

        # Ensure values are positive
        if capacity <= 0 or free_space < 0:
            result = f"Datastore Details: {ds.get('name', 'Unknown')}\n"
            result += f"ID: {datastore_id}\n"
            result += f"Type: {ds.get('type', 'Unknown')}\n"
            result += "Capacity information not available or invalid\n"
            return result

        used_space = capacity - free_space
        used_pct = (used_space / capacity * 100) if capacity > 0 else 0

        result = f"Datastore Details: {ds.get('name', 'Unknown')}\n"
        result += f"ID: {datastore_id}\n"
        result += f"Type: {ds.get('type', 'Unknown')}\n"
        result += f"Capacity: {capacity / (1024**3):.1f} GB\n"
        result += f"Used: {used_space / (1024**3):.1f} GB ({used_pct:.1f}%)\n"
        result += f"Free: {free_space / (1024**3):.1f} GB\n"

        return result

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"getting datastore {datastore_id} details")
    finally:
        client.close()


# Organization Tools
@mcp.tool()
def list_folders(hostname: str = None, folder_type: str = "VIRTUAL_MACHINE") -> str:
    """List folders by type.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
        folder_type: Folder type (VIRTUAL_MACHINE, HOST, DATACENTER, DATASTORE, NETWORK)
    """
    if hostname is None:
        hostname = os.environ.get("VCENTER_HOST")
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        response = client.get(f"vcenter/folder?filter.type={folder_type}")
        folders = response.get("value", [])

        if not folders:
            return f"No {folder_type} folders found"

        result = f"Found {len(folders)} {folder_type} folders:\n\n"
        for folder in folders:
            result += (
                f"• {folder.get('name', 'Unknown')} (ID: {folder.get('folder')})\n"
            )

        return result.strip()

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"listing {folder_type} folders")
    finally:
        client.close()


@mcp.tool()
def get_folder_details(hostname: str = None, folder_id: str = None) -> str:
    """Get detailed information about a folder.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
        folder_id: Folder ID
    """
    if hostname is None:
        hostname = os.environ.get("VCENTER_HOST")
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        response = client.get(f"vcenter/folder/{folder_id}")
        folder = response.get("value", {})

        if not folder:
            return f"Folder {folder_id} not found or inaccessible"

        result = f"Folder Details: {folder.get('name', 'Unknown')}\n"
        result += f"ID: {folder_id}\n"
        result += f"Type: {folder.get('type', 'Unknown')}\n"

        return result

    except (ConnectionError, ValueError, KeyError) as e:
        error_msg = str(e)
        if "404" in error_msg:
            return f"Folder {folder_id} not found or access denied (may be a system folder)"
        return _handle_error(e, f"getting folder {folder_id} details")
    finally:
        client.close()


# Network Tools
@mcp.tool()
def list_networks(hostname: str = None) -> str:
    """List all networks with VLAN information.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        response = client.get("vcenter/network")
        networks = response.get("value", [])

        if not networks:
            return "No networks found"

        result = f"Found {len(networks)} networks:\n\n"
        for network in networks:
            name = network.get("name", "Unknown")
            result += f"• {name} (ID: {network.get('network')})\n"
            result += f"  Type: {network.get('type', 'Unknown')}\n"

            # Extract VLAN info from name
            vlan_match = re.search(r"v(\d+)-|VLAN(\d+)", name)
            if vlan_match:
                vlan_id = vlan_match.group(1) or vlan_match.group(2)
                result += f"  VLAN ID: {vlan_id}\n"

            result += "\n"

        return result.strip()

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "listing networks")
    finally:
        client.close()


@mcp.tool()
def get_network_details(hostname: str = None, network_id: str = None) -> str:
    """Get detailed information about a network.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
        network_id: Network ID
    """
    if hostname is None:
        hostname = os.environ.get("VCENTER_HOST")
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        response = client.get(f"vcenter/network/{network_id}")
        network = response.get("value", {})

        if not network:
            return f"Network {network_id} not found or inaccessible"

        name = network.get("name", "Unknown")
        result = f"Network Details: {name}\n"
        result += f"ID: {network_id}\n"
        result += f"Type: {network.get('type', 'Unknown')}\n"

        # Extract VLAN info from name
        vlan_match = re.search(r"v(\d+)-|VLAN(\d+)", name)
        if vlan_match:
            vlan_id = vlan_match.group(1) or vlan_match.group(2)
            result += f"VLAN ID: {vlan_id}\n"

        return result

    except (ConnectionError, ValueError, KeyError) as e:
        error_msg = str(e)
        if "404" in error_msg:
            return (
                f"Network {network_id} not found or is a distributed portgroup "
                "(not accessible via this API)"
            )
        return _handle_error(e, f"getting network {network_id} details")
    finally:
        client.close()


@mcp.tool()
def get_vlan_info(hostname: str = None, vlan_query: str = "") -> str:
    """Get information about a VLAN by name or VLAN ID.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
        vlan_query: VLAN name (e.g., v1306-MEL03-Secure-Management) or VLAN ID (e.g., 1306)
    """
    if hostname is None:
        hostname = os.environ.get("VCENTER_HOST")
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        response = client.get("vcenter/network")
        networks = response.get("value", [])

        if not networks:
            return "No networks found"

        matches = []

        # Search by name (partial match, case-insensitive)
        for network in networks:
            name = network.get("name", "")
            if vlan_query.lower() in name.lower():
                matches.append(network)

        # If no name matches and query is numeric, search by VLAN ID
        if not matches and vlan_query.isdigit():
            vlan_id = vlan_query
            for network in networks:
                name = network.get("name", "")
                vlan_match = re.search(r"v(\d+)-|VLAN(\d+)", name)
                if vlan_match:
                    extracted_vlan = vlan_match.group(1) or vlan_match.group(2)
                    if extracted_vlan == vlan_id:
                        matches.append(network)

        if not matches:
            return f"No VLAN found matching '{vlan_query}'"

        result = f"VLAN Search Results for '{vlan_query}':\n\n"

        for network in matches:
            name = network.get("name", "Unknown")
            result += f"• {name}\n"
            result += f"  Network ID: {network.get('network', 'Unknown')}\n"
            result += f"  Type: {network.get('type', 'Unknown')}\n"

            # Extract VLAN ID from name
            vlan_match = re.search(r"v(\d+)-|VLAN(\d+)", name)
            if vlan_match:
                vlan_id = vlan_match.group(1) or vlan_match.group(2)
                result += f"  VLAN ID: {vlan_id}\n"

            result += "\n"

        result += f"Found {len(matches)} matching network(s)"
        return result

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"searching for VLAN '{vlan_query}'")
    finally:
        client.close()


@mcp.tool()
def list_vlans(hostname: str = None) -> str:
    """Extract and list VLAN information from network names.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get("VCENTER_HOST")
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    client = VSphereClient(hostname)
    try:
        response = client.get("vcenter/network")
        networks = response.get("value", [])

        if not networks:
            return "No networks found"

        vlans: Dict[str, List[str]] = {}
        for network in networks:
            name = network.get("name", "Unknown")
            vlan_match = re.search(r"v(\d+)-|VLAN(\d+)", name)
            if vlan_match:
                vlan_id = vlan_match.group(1) or vlan_match.group(2)
                if vlan_id not in vlans:
                    vlans[vlan_id] = []
                vlans[vlan_id].append(name)

        if not vlans:
            return "No VLAN information found in network names"

        result = f"Found {len(vlans)} VLANs:\n\n"
        for vlan_id in sorted(vlans.keys(), key=int):
            result += f"VLAN {vlan_id}:\n"
            for network_name in vlans[vlan_id]:
                result += f"  • {network_name}\n"
            result += "\n"

        return result.strip()

    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "extracting VLAN information")
    finally:
        client.close()


@mcp.tool()
def get_vm_disk_usage(hostname: str = None) -> str:
    """Get disk usage information for all VMs.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # Get all VMs
        response = client.get("vcenter/vm")
        vms = response.get("value", [])
        
        if not vms:
            return "No virtual machines found"
        
        result = f"Disk Usage Report for {len(vms)} VMs:\n\n"
        
        for vm in vms:
            vm_id = vm.get('vm')
            vm_name = vm.get('name', 'Unknown')
            
            try:
                # Get detailed VM information including disks
                vm_details = client.get(f"vcenter/vm/{vm_id}")
                vm_data = vm_details.get("value", {})
                
                # Get disk information
                disks = vm_data.get("disks", [])
                
                result += f"• {vm_name} (ID: {vm_id})\n"
                
                if disks:
                    for i, disk in enumerate(disks):
                        capacity = disk.get("capacity", 0)
                        if capacity > 0:
                            # Convert bytes to GB
                            capacity_gb = capacity / (1024**3)
                            result += f"  Disk {i}: {capacity_gb:.1f} GB\n"
                        else:
                            result += f"  Disk {i}: Capacity not available\n"
                else:
                    result += "  No disk information available\n"
                
                result += "\n"
                
            except Exception as e:
                result += f"• {vm_name} (ID: {vm_id}) - Error getting disk info: {str(e)}\n\n"
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "getting VM disk usage")
    finally:
        client.close()


@mcp.tool()
def get_vm_storage_info(hostname: str = None) -> str:
    """Get detailed storage information for all VMs including datastore usage.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # Get all VMs
        response = client.get("vcenter/vm")
        vms = response.get("value", [])
        
        if not vms:
            return "No virtual machines found"
        
        result = f"Storage Information for {len(vms)} VMs:\n\n"
        
        for vm in vms:
            vm_id = vm.get('vm')
            vm_name = vm.get('name', 'Unknown')
            
            try:
                # Get detailed VM information
                vm_details = client.get(f"vcenter/vm/{vm_id}")
                vm_data = vm_details.get("value", {})
                
                result += f"• {vm_name} (ID: {vm_id})\n"
                
                # Get disk information
                disks = vm_data.get("disks", [])
                if disks:
                    for i, disk in enumerate(disks):
                        capacity = disk.get("capacity", 0)
                        if capacity > 0:
                            capacity_gb = capacity / (1024**3)
                            result += f"  Disk {i}: {capacity_gb:.1f} GB allocated\n"
                        else:
                            result += f"  Disk {i}: Size not available\n"
                else:
                    result += "  No disk information available\n"
                
                # Get datastore information
                datastores = vm_data.get("datastores", [])
                if datastores:
                    result += "  Datastores:\n"
                    for ds in datastores:
                        result += f"    - {ds}\n"
                
                result += "\n"
                
            except Exception as e:
                result += f"• {vm_name} (ID: {vm_id}) - Error: {str(e)}\n\n"
        
        result += "\nNote: For actual disk usage percentage, VMware Tools must be installed in VMs and vRealize Operations or similar tools are needed.\n"
        result += "This report shows allocated disk space, not actual usage."
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "getting VM storage information")
    finally:
        client.close()


@mcp.tool()
def get_datastore_usage(hostname: str = None) -> str:
    """Get datastore usage information to identify potential storage issues.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # Get all datastores
        response = client.get("vcenter/datastore")
        datastores = response.get("value", [])
        
        if not datastores:
            return "No datastores found"
        
        result = f"Datastore Usage Report:\n\n"
        high_usage_ds = []
        
        for ds in datastores:
            ds_id = ds.get('datastore')
            ds_name = ds.get('name', 'Unknown')
            capacity = ds.get("capacity", 0)
            free_space = ds.get("free_space", 0)
            
            if capacity > 0 and free_space >= 0:
                used_space = capacity - free_space
                used_pct = (used_space / capacity * 100) if capacity > 0 else 0
                
                result += f"• {ds_name}\n"
                result += f"  Capacity: {capacity / (1024**3):.1f} GB\n"
                result += f"  Used: {used_space / (1024**3):.1f} GB ({used_pct:.1f}%)\n"
                result += f"  Free: {free_space / (1024**3):.1f} GB\n"
                
                if used_pct > 90:
                    high_usage_ds.append(f"{ds_name} ({used_pct:.1f}%)")
                
                result += "\n"
        
        if high_usage_ds:
            result += f"⚠️  Datastores with >90% usage:\n"
            for ds in high_usage_ds:
                result += f"  - {ds}\n"
            result += "\n"
        
        result += "Note: This shows datastore usage, not individual VM disk usage."
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "getting datastore usage")
    finally:
        client.close()


@mcp.tool()
def get_vm_performance_info(hostname: str = None) -> str:
    """Get performance information for all VMs including CPU, RAM, and network.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # Get all VMs
        response = client.get("vcenter/vm")
        vms = response.get("value", [])
        
        if not vms:
            return "No virtual machines found"
        
        result = f"Performance Information for {len(vms)} VMs:\n\n"
        
        for vm in vms:
            vm_id = vm.get('vm')
            vm_name = vm.get('name', 'Unknown')
            power_state = vm.get('power_state', 'Unknown')
            
            try:
                # Get detailed VM information
                vm_details = client.get(f"vcenter/vm/{vm_id}")
                vm_data = vm_details.get("value", {})
                
                result += f"• {vm_name} (ID: {vm_id})\n"
                result += f"  Power State: {power_state}\n"
                
                if power_state == "POWERED_ON":
                    # CPU Information
                    cpu_info = vm_data.get("cpu", {})
                    if cpu_info:
                        cpu_count = cpu_info.get("count", "Unknown")
                        result += f"  CPU: {cpu_count} vCPUs\n"
                    
                    # Memory Information
                    memory_info = vm_data.get("memory", {})
                    if memory_info:
                        memory_mb = memory_info.get("size_MiB", "Unknown")
                        if memory_mb != "Unknown":
                            memory_gb = memory_mb / 1024
                            result += f"  Memory: {memory_gb:.1f} GB ({memory_mb} MB)\n"
                        else:
                            result += f"  Memory: {memory_mb}\n"
                    
                    # Network Information
                    nics = vm_data.get("nics", [])
                    if nics:
                        result += f"  Network Interfaces: {len(nics)}\n"
                        for i, nic in enumerate(nics):
                            if isinstance(nic, dict):
                                backing = nic.get("backing", {})
                                if isinstance(backing, dict):
                                    network_name = backing.get("network_name", "Unknown")
                                    result += f"    NIC {i}: {network_name}\n"
                    
                    # Guest OS Information
                    guest_os = vm_data.get("guest_OS", "Unknown")
                    result += f"  Guest OS: {guest_os}\n"
                    
                else:
                    result += f"  VM is {power_state.lower()} - performance data not available\n"
                
                result += "\n"
                
            except Exception as e:
                result += f"• {vm_name} (ID: {vm_id}) - Error: {str(e)}\n\n"
        
        result += "\nNote: This shows allocated resources, not actual usage. For real-time performance metrics, vRealize Operations or similar tools are needed."
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "getting VM performance information")
    finally:
        client.close()


@mcp.tool()
def get_host_performance_info(hostname: str = None) -> str:
    """Get performance information for all ESXi hosts.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # Get all hosts
        response = client.get("vcenter/host")
        hosts = response.get("value", [])
        
        if not hosts:
            return "No ESXi hosts found"
        
        result = f"Host Performance Information for {len(hosts)} hosts:\n\n"
        
        for host in hosts:
            host_id = host.get('host')
            host_name = host.get('name', 'Unknown')
            connection_state = host.get('connection_state', 'Unknown')
            power_state = host.get('power_state', 'Unknown')
            
            result += f"• {host_name} (ID: {host_id})\n"
            result += f"  Connection State: {connection_state}\n"
            result += f"  Power State: {power_state}\n"
            
            if connection_state == "CONNECTED":
                try:
                    # Get detailed host information
                    host_details = client.get(f"vcenter/host/{host_id}")
                    host_data = host_details.get("value", {})
                    
                    # CPU Information
                    cpu_info = host_data.get("cpu", {})
                    if cpu_info:
                        cpu_count = cpu_info.get("count", "Unknown")
                        result += f"  CPU: {cpu_count} physical CPUs\n"
                    
                    # Memory Information
                    memory_info = host_data.get("memory", {})
                    if memory_info:
                        memory_mb = memory_info.get("size_MiB", "Unknown")
                        if memory_mb != "Unknown":
                            memory_gb = memory_mb / 1024
                            result += f"  Memory: {memory_gb:.1f} GB ({memory_mb} MB)\n"
                        else:
                            result += f"  Memory: {memory_mb}\n"
                    
                    # Network Information
                    nics = host_data.get("nics", [])
                    if nics:
                        result += f"  Network Interfaces: {len(nics)}\n"
                        for i, nic in enumerate(nics):
                            if isinstance(nic, dict):
                                nic_name = nic.get("device", "Unknown")
                                result += f"    NIC {i}: {nic_name}\n"
                    
                except Exception as e:
                    result += f"  Error getting detailed info: {str(e)}\n"
            else:
                result += f"  Host is {connection_state.lower()} - detailed info not available\n"
            
            result += "\n"
        
        result += "\nNote: This shows host hardware configuration, not real-time performance metrics."
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "getting host performance information")
    finally:
        client.close()


@mcp.tool()
def get_vms_with_high_resource_usage(hostname: str = None) -> str:
    """Get VMs that might have high resource usage based on configuration.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # Get all VMs
        response = client.get("vcenter/vm")
        vms = response.get("value", [])
        
        if not vms:
            return "No virtual machines found"
        
        result = f"VMs with High Resource Configuration:\n\n"
        high_cpu_vms = []
        high_memory_vms = []
        
        for vm in vms:
            vm_id = vm.get('vm')
            vm_name = vm.get('name', 'Unknown')
            power_state = vm.get('power_state', 'Unknown')
            
            if power_state == "POWERED_ON":
                try:
                    # Get detailed VM information
                    vm_details = client.get(f"vcenter/vm/{vm_id}")
                    vm_data = vm_details.get("value", {})
                    
                    # Check CPU
                    cpu_info = vm_data.get("cpu", {})
                    if cpu_info:
                        cpu_count = cpu_info.get("count", 0)
                        if cpu_count >= 8:  # VMs with 8+ vCPUs
                            high_cpu_vms.append(f"{vm_name} ({cpu_count} vCPUs)")
                    
                    # Check Memory
                    memory_info = vm_data.get("memory", {})
                    if memory_info:
                        memory_mb = memory_info.get("size_MiB", 0)
                        if memory_mb >= 16384:  # VMs with 16GB+ RAM
                            memory_gb = memory_mb / 1024
                            high_memory_vms.append(f"{vm_name} ({memory_gb:.1f} GB)")
                    
                except Exception as e:
                    continue
        
        if high_cpu_vms:
            result += "🔴 VMs with High CPU Configuration (8+ vCPUs):\n"
            for vm in high_cpu_vms:
                result += f"  - {vm}\n"
            result += "\n"
        
        if high_memory_vms:
            result += "🔴 VMs with High Memory Configuration (16GB+ RAM):\n"
            for vm in high_memory_vms:
                result += f"  - {vm}\n"
            result += "\n"
        
        if not high_cpu_vms and not high_memory_vms:
            result += "✅ No VMs found with high resource configuration.\n"
        
        result += "\nNote: This shows resource allocation, not actual usage. High allocation doesn't necessarily mean high usage."
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "getting VMs with high resource usage")
    finally:
        client.close()


# Snapshot Management Tools
@mcp.tool()
def list_vm_snapshots(vm_id: str, hostname: str = None) -> str:
    """List all snapshots for a specific VM.

    Args:
        vm_id: Virtual machine ID or name
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # If vm_id doesn't start with 'vm-', assume it's a name and look up the ID
        if not vm_id.startswith("vm-"):
            vms_response = client.get("vcenter/vm")
            vms = vms_response.get("value", [])
            
            vm_id_found = None
            for vm in vms:
                if vm.get("name", "").lower() == vm_id.lower():
                    vm_id_found = vm.get("vm")
                    break
            
            if not vm_id_found:
                return f"Virtual machine '{vm_id}' not found by name"
            vm_id = vm_id_found
        
        # Get VM snapshots
        response = client.get(f"vcenter/vm/{vm_id}/snapshot")
        snapshots = response.get("value", [])
        
        if not snapshots:
            return f"No snapshots found for VM {vm_id}"
        
        result = f"Snapshots for VM {vm_id}:\n\n"
        for snapshot in snapshots:
            result += f"• {snapshot.get('name', 'Unknown')} (ID: {snapshot.get('snapshot')})\n"
            result += f"  Created: {snapshot.get('create_time', 'Unknown')}\n"
            result += f"  State: {snapshot.get('state', 'Unknown')}\n\n"
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"listing snapshots for VM {vm_id}")
    finally:
        client.close()


@mcp.tool()
def create_vm_snapshot(vm_id: str, snapshot_name: str, description: str = "", hostname: str = None) -> str:
    """Create a snapshot for a specific VM.

    Args:
        vm_id: Virtual machine ID or name
        snapshot_name: Name for the snapshot
        description: Description for the snapshot (optional)
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # If vm_id doesn't start with 'vm-', assume it's a name and look up the ID
        if not vm_id.startswith("vm-"):
            vms_response = client.get("vcenter/vm")
            vms = vms_response.get("value", [])
            
            vm_id_found = None
            for vm in vms:
                if vm.get("name", "").lower() == vm_id.lower():
                    vm_id_found = vm.get("vm")
                    break
            
            if not vm_id_found:
                return f"Virtual machine '{vm_id}' not found by name"
            vm_id = vm_id_found
        
        # Create snapshot
        snapshot_data = {
            "name": snapshot_name,
            "description": description,
            "memory": True,
            "quiesce": True
        }
        
        client.post(f"vcenter/vm/{vm_id}/snapshot", snapshot_data)
        return f"Snapshot '{snapshot_name}' created successfully for VM {vm_id}"
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"creating snapshot for VM {vm_id}")
    finally:
        client.close()


# Template Management Tools
@mcp.tool()
def list_templates(hostname: str = None) -> str:
    """List all VM templates.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # Get all VMs and filter for templates
        response = client.get("vcenter/vm")
        vms = response.get("value", [])
        
        templates = []
        for vm in vms:
            # Check if VM is a template (this might need adjustment based on your vSphere setup)
            vm_name = vm.get('name', '')
            if 'template' in vm_name.lower() or vm.get('template', False):
                templates.append(vm)
        
        if not templates:
            return "No templates found"
        
        result = f"Found {len(templates)} templates:\n\n"
        for template in templates:
            result += f"• {template.get('name', 'Unknown')} (ID: {template.get('vm')})\n"
            result += f"  Power State: {template.get('power_state', 'Unknown')}\n"
            result += f"  Guest OS: {template.get('guest_OS', 'Unknown')}\n\n"
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "listing templates")
    finally:
        client.close()


# Advanced Monitoring Tools
@mcp.tool()
def get_vm_events(vm_id: str, hostname: str = None, max_count: int = 20) -> str:
    """Get recent events for a specific VM via pyVmomi EventManager.

    Args:
        vm_id: Virtual machine ID (vm-N) or name
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
        max_count: Maximum number of events to return (default 20)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"

    client = PyVmomiClient(host=hostname)
    try:
        # Resolve VM name to MoRef
        vm_ref = None
        if vm_id.startswith("vm-"):
            # It's a MoRef - need to find the VM object
            # Search through all VMs to find matching _moId
            view = client.get_container_view(vim.VirtualMachine, container=client.content.rootFolder, recursive=True)
            try:
                for vm in view.view:
                    if vm._moId == vm_id:
                        vm_ref = vm
                        break
            finally:
                view.Destroy()

            if not vm_ref:
                return f"Virtual machine '{vm_id}' not found"
        else:
            # It's a name
            vm_ref = client.find_vm(vm_id)
            if not vm_ref:
                return f"Virtual machine '{vm_id}' not found"

        # Query events via EventManager
        em = client.content.eventManager
        filter_spec = vim.event.EventFilterSpec()
        filter_spec.entity = vim.event.EventFilterSpec.ByEntity(entity=vm_ref, recursion="self")
        filter_spec.maxCount = max_count

        events = em.QueryEvents(filter_spec)

        if not events:
            return f"No recent events found for VM {vm_id}"

        result = f"Recent Events for VM {vm_id} (last {len(events)}):\n\n"
        for event in events:
            event_type = type(event).__name__
            timestamp = event.createdTime.isoformat() if hasattr(event, 'createdTime') and event.createdTime else "Unknown"
            message = event.fullFormattedMessage if hasattr(event, 'fullFormattedMessage') and event.fullFormattedMessage else event_type

            result += f"• {event_type}\n"
            result += f"  Time: {timestamp}\n"
            result += f"  Message: {message}\n\n"

        return result.strip()

    except Exception as e:
        return f"Error getting events for VM {vm_id} via pyVmomi: {e}"
    finally:
        client.close()



@mcp.tool()
def get_alarms(hostname: str = None, entity_type: str = None) -> str:
    """Get active alarms in the vSphere environment via pyVmomi AlarmManager.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
        entity_type: Optional filter - "HostSystem" or "VirtualMachine" to limit scope
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"

    client = PyVmomiClient(host=hostname)
    try:
        am = client.content.alarmManager
        root_folder = client.content.rootFolder

        # Determine which entity types to scan
        if entity_type == "HostSystem":
            obj_types = [vim.HostSystem]
        elif entity_type == "VirtualMachine":
            obj_types = [vim.VirtualMachine]
        else:
            obj_types = [vim.HostSystem, vim.VirtualMachine]

        triggered_alarms = []

        for obj_type in obj_types:
            view = client.get_container_view(obj_type, container=root_folder, recursive=True)
            try:
                # Limit to first 50 entities per type to avoid slowness
                entities = list(view.view)[:50]

                for entity in entities:
                    try:
                        # Get alarm states for this entity
                        alarm_states = am.GetAlarmState(entity)

                        for state in alarm_states:
                            # Filter for triggered alarms (not gray/green)
                            if state.overallStatus not in ("gray", "green"):
                                triggered_alarms.append({
                                    "entity": entity.name,
                                    "entity_type": type(entity).__name__,
                                    "alarm": state.alarm.info.name if state.alarm and state.alarm.info else "Unknown",
                                    "status": state.overallStatus,
                                    "acknowledged": state.acknowledged,
                                    "time": state.time.isoformat() if state.time else "Unknown"
                                })
                    except Exception:
                        # Skip entities we can't read (permission/state issues)
                        continue
            finally:
                view.Destroy()

        if not triggered_alarms:
            return "No active alarms found"

        result = f"Active Alarms ({len(triggered_alarms)}):\n\n"
        for alarm in triggered_alarms:
            result += f"• {alarm['alarm']}\n"
            result += f"  Entity: {alarm['entity']} ({alarm['entity_type']})\n"
            result += f"  Status: {alarm['status']}\n"
            result += f"  Acknowledged: {alarm['acknowledged']}\n"
            result += f"  Time: {alarm['time']}\n\n"

        return result.strip()

    except Exception as e:
        return f"Error getting alarms via pyVmomi: {e}"
    finally:
        client.close()


# ────────────────────────────────────────────────────────────────────────────
# vSAN Monitoring Tools (read-only)
# NOTE: vSAN-specific REST endpoints (vcenter/vsan/*) do NOT exist on
# vCenter 8.0.3 — verified 404. All vSAN tools use pyVmomi via
# PyVmomiClient.get_vsan_vc_mos() on the /vsanHealth endpoint. All read-only.
# ────────────────────────────────────────────────────────────────────────────


def _vsan_status_icon(status: str) -> str:
    """Map vSAN health status string to an icon."""
    s = (status or "").lower()
    return {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(s, "⚪")


@mcp.tool()
def list_vsan_clusters(hostname: str = None) -> str:
    """List all vSAN-enabled clusters with basic configuration.

    Read-only. Uses pyVmomi: finds clusters where vSAN is enabled and
    reports host count, vSAN UUID, and cluster MoRef.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get("VCENTER_HOST")
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"

    client = PyVmomiClient(host=hostname)
    try:
        view = client.get_container_view(vim.ClusterComputeResource, recursive=True)
        try:
            clusters = list(view.view)
        finally:
            view.Destroy()

        vsan_clusters = []
        for cl in clusters:
            if not client.is_vsan_enabled(cl):
                continue
            cfg = getattr(cl, "config", None)
            vsan_cfg = getattr(cfg, "vsanConfigInfo", None) if cfg else None
            vsan_clusters.append({
                "name": cl.name,
                "moId": cl._moId,
                "hosts": len(cl.host) if cl.host else 0,
                "uuid": getattr(vsan_cfg, "clusterUuid", None) or getattr(vsan_cfg, "uuid", None),
            })

        if not vsan_clusters:
            return "No vSAN clusters found"

        result = f"Found {len(vsan_clusters)} vSAN cluster(s):\n\n"
        for c in vsan_clusters:
            result += f"• {c['name']}\n"
            result += f"  vSAN enabled: yes\n"
            result += f"  Hosts: {c['hosts']}\n"
            result += f"  Cluster ID: {c['moId']}\n"
            if c["uuid"]:
                result += f"  vSAN UUID: {c['uuid']}\n"
            result += "\n"

        return result.strip()

    except Exception as e:
        return _handle_vsan_error(e, "listing vSAN clusters")
    finally:
        client.close()


@mcp.tool()
def get_vsan_cluster_health(cluster_name: str, hostname: str = None) -> str:
    """Get overall vSAN health status for a cluster.

    Read-only. Uses vim.cluster.VsanVcClusterHealthSystem.QueryClusterHealthSummary.
    Reports overall status (green/yellow/red) plus per-host health.

    Args:
        cluster_name: Name of the vSAN cluster (e.g. "New Cluster 122")
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get("VCENTER_HOST")
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"

    client = PyVmomiClient(host=hostname)
    try:
        cluster = client.find_cluster(cluster_name)
        if cluster is None:
            return f"Cluster '{cluster_name}' not found"
        if not client.is_vsan_enabled(cluster):
            return f"Cluster '{cluster_name}' has no vSAN configuration (vSAN is not enabled)"

        mos = client.get_vsan_vc_mos()
        health_sys = mos["vsan-cluster-health-system"]
        summary = health_sys.QueryClusterHealthSummary(cluster=cluster)

        status_obj = getattr(summary, "clusterStatus", None)
        overall = getattr(status_obj, "status", None) or "unknown"
        goal = getattr(status_obj, "goalState", None)
        tracked = getattr(status_obj, "trackedHostsStatus", None) or []
        untracked = getattr(status_obj, "untrackedHosts", None) or []

        result = f"vSAN Cluster Health: {cluster.name}\n"
        result += f"ID: {cluster._moId}\n"
        result += f"Overall status: {_vsan_status_icon(overall)} {overall.upper()}\n"
        if goal:
            result += f"Goal state: {goal}\n"

        if tracked:
            result += f"\nHosts ({len(tracked)}):\n"
            for h in tracked:
                hname = getattr(h, "hostname", "Unknown")
                hstatus = getattr(h, "status", "unknown")
                issues = getattr(h, "issues", None) or []
                result += f"  {_vsan_status_icon(hstatus)} {hname}: {hstatus}\n"
                for issue in issues:
                    result += f"      ⚠ {issue}\n"

        if untracked:
            result += f"\nUntracked hosts: {', '.join(untracked)}\n"

        result += "\n(Detailed per-group checks: get_vsan_health_checks — Phase 2)"
        return result

    except Exception as e:
        return _handle_vsan_error(e, f"getting vSAN health for cluster {cluster_name}")
    finally:
        client.close()


@mcp.tool()
def get_vsan_capacity_info(cluster_name: str, hostname: str = None) -> str:
    """Get vSAN capacity information for a cluster (total/free/used).

    Read-only. Uses vim.cluster.VsanSpaceReportSystem.VsanQuerySpaceUsage.
    Note: vim.host.VsanDatastoreInfo.capacity returns 0 on vSAN 8.x — real
    capacity comes from this space-usage report.

    Args:
        cluster_name: Name of the vSAN cluster (e.g. "New Cluster 122")
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get("VCENTER_HOST")
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"

    def _gb(n):
        return (n or 0) / (1024 ** 3)

    client = PyVmomiClient(host=hostname)
    try:
        cluster = client.find_cluster(cluster_name)
        if cluster is None:
            return f"Cluster '{cluster_name}' not found"
        if not client.is_vsan_enabled(cluster):
            return f"Cluster '{cluster_name}' has no vSAN configuration (vSAN is not enabled)"

        mos = client.get_vsan_vc_mos()
        space_sys = mos["vsan-cluster-space-report-system"]
        report = space_sys.VsanQuerySpaceUsage(cluster=cluster)
        entry = report[0] if isinstance(report, list) and report else report

        total = getattr(entry, "totalCapacityB", 0) or 0
        free = getattr(entry, "freeCapacityB", 0) or 0
        used = getattr(entry, "usedB", None)
        # usedB may be absent on some versions — derive from total-free
        if used is None or used == 0:
            used = total - free
        used_pct = (used / total * 100) if total else 0.0

        result = f"vSAN Capacity — {cluster.name}:\n\n"
        result += f"Total capacity:  {_gb(total):8.1f} GB\n"
        result += f"Used:            {_gb(used):8.1f} GB ({used_pct:.1f}%)\n"
        result += f"Free:            {_gb(free):8.1f} GB\n"

        # Optional fields present on some versions
        dedup = getattr(entry, "dedupRatio", None)
        compr = getattr(entry, "compressionRatio", None)
        if dedup or compr:
            result += "\nData efficiency:\n"
            if dedup:
                result += f"  Deduplication: {dedup}\n"
            if compr:
                result += f"  Compression:   {compr}\n"

        return result

    except Exception as e:
        return _handle_vsan_error(e, f"getting vSAN capacity for cluster {cluster_name}")
    finally:
        client.close()


# ── vSAN Phase 2: disk groups, performance, health checks ─────────
# All three are strictly read-only (Tier 1) — see memory vsan-readonly-only-rule.


def _format_vsan_state(raw) -> str:
    """Flatten pyVmomi enum/strList state into a short human-readable token.

    pyVmomi sometimes returns ``['ok']`` as a string list and sometimes a
    single enum value; this helper normalises both into a plain string.
    """
    if raw is None:
        return "?"
    if isinstance(raw, (list, tuple)):
        return ", ".join(str(x) for x in raw) or "?"
    return str(raw)


@mcp.tool()
def get_vsan_disk_groups(cluster_name: str, hostname: str = None) -> str:
    """Get vSAN disk groups for all hosts in a cluster.

    Read-only. Iterates each ESXi host and queries its disk mapping
    (cache SSD + capacity tier). Returns per-host cache/capacity layout
    and a cluster-wide summary.

    Args:
        cluster_name: Name of the vSAN-enabled cluster.
        hostname: Optional vCenter hostname (uses VCENTER_HOST env by default).

    Returns:
        Markdown table per host plus cluster summary.
    """
    client = PyVmomiClient(host=hostname)
    try:
        cluster = client.find_vsan_cluster(cluster_name)
        if cluster is None:
            # Distinguish "not found" from "found but vSAN disabled"
            plain = client.find_cluster(cluster_name)
            if plain is None:
                return _handle_error(
                    Exception(f"cluster '{cluster_name}' not found"),
                    f"getting vSAN disk groups for cluster {cluster_name}",
                )
            return _vsan_status_icon("yellow") + (
                f" Cluster '{cluster_name}' exists but vSAN is not enabled. "
                "This tool requires a vSAN-enabled cluster."
            )

        mos = client.get_vsan_vc_mos()
        disk_sys = mos["vsan-disk-management-system"]

        all_flash_total = 0
        hybrid_total = 0
        hosts_data = []

        for host in (cluster.host or []):
            try:
                # QueryDiskMappings is per-host (host=vim.HostSystem)
                mapping = disk_sys.QueryDiskMappings(host=host)
            except Exception as he:
                hosts_data.append({
                    "hostname": host.name,
                    "error": f"{type(he).__name__}: {str(getattr(he, 'msg', he))[:120]}",
                })
                continue

            # DiskMapInfoEx is per host; mapping is a single object with
            # mapping.ssd (cache) + mapping.nonSsd[] (capacity).
            # But QueryDiskMappings returns DiskMapInfoEx[] — typically one entry per host.
            host_block = {
                "hostname": host.name,
                "moId": host._moId,
                "disk_groups": [],
                "all_flash_count": 0,
                "hybrid_count": 0,
            }

            for dme in (mapping or []):
                m = getattr(dme, "mapping", None) or dme  # tolerate both shapes
                ssd = getattr(m, "ssd", None)
                non_ssd = getattr(m, "nonSsd", None) or []

                cache_disk = None
                if ssd is not None:
                    cap_blocks = getattr(
                        getattr(ssd, "capacity", None), "blockSize", None
                    )
                    cap_total_b = getattr(
                        getattr(ssd, "capacity", None), "block", None
                    )
                    # capacity has blockSize * block = bytes for some shapes
                    blocks = getattr(
                        getattr(ssd, "capacity", None), "block", None
                    )
                    blk_size = getattr(
                        getattr(ssd, "capacity", None), "blockSize", None
                    )
                    cap_b = (blocks or 0) * (blk_size or 0) if (blocks and blk_size) else None
                    state_raw = getattr(ssd, "operationalState", None)
                    cache_disk = {
                        "displayName": getattr(ssd, "displayName", None),
                        "vsanUuid": getattr(
                            getattr(ssd, "vsanDiskInfo", None), "vsanUuid", None
                        ),
                        "state": _format_vsan_state(state_raw),
                        "capacityBytes": cap_b,
                    }

                cap_disks = []
                for cd in non_ssd:
                    blocks = getattr(getattr(cd, "capacity", None), "block", None)
                    blk_size = getattr(getattr(cd, "capacity", None), "blockSize", None)
                    cap_b = (blocks or 0) * (blk_size or 0) if (blocks and blk_size) else None
                    state_raw = getattr(cd, "operationalState", None)
                    cap_disks.append({
                        "displayName": getattr(cd, "displayName", None),
                        "vsanUuid": getattr(
                            getattr(cd, "vsanDiskInfo", None), "vsanUuid", None
                        ),
                        "state": _format_vsan_state(state_raw),
                        "capacityBytes": cap_b,
                    })

                is_af = bool(getattr(dme, "isAllFlash", False))
                is_mounted = bool(getattr(dme, "isMounted", False))
                host_block["disk_groups"].append({
                    "cache": cache_disk,
                    "capacity": cap_disks,
                    "isAllFlash": is_af,
                    "isMounted": is_mounted,
                })
                if is_af:
                    host_block["all_flash_count"] += 1
                else:
                    host_block["hybrid_count"] += 1

            all_flash_total += host_block["all_flash_count"]
            hybrid_total += host_block["hybrid_count"]
            hosts_data.append(host_block)

        # Render
        result = f"# vSAN Disk Groups: {cluster_name}\n\n"
        result += f"Hosts: {len(hosts_data)}\n"
        result += f"Disk groups: all-flash = {all_flash_total}, hybrid = {hybrid_total}\n\n"

        for hd in hosts_data:
            result += f"## Host: {hd['hostname']}"
            if "error" in hd:
                result += f"  ⚠ error: {hd['error']}\n\n"
                continue
            result += f"  (moId: `{hd['moId']}`)\n\n"
            if not hd["disk_groups"]:
                result += "  _(no disk groups)_\n\n"
                continue
            for i, dg in enumerate(hd["disk_groups"], 1):
                tier = "all-flash" if dg["isAllFlash"] else "hybrid"
                mounted = "mounted" if dg["isMounted"] else "NOT mounted"
                result += f"  **Disk group {i}** — {tier}, {mounted}\n"
                if dg["cache"]:
                    cap_mb = (
                        round(dg["cache"]["capacityBytes"] / 1024 / 1024)
                        if dg["cache"]["capacityBytes"]
                        else "?"
                    )
                    result += (
                        f"    Cache SSD: `{dg['cache']['displayName']}` "
                        f"({cap_mb} MB, state={dg['cache']['state']})\n"
                    )
                else:
                    result += "    Cache SSD: _(none)_\n"
                if dg["capacity"]:
                    result += f"    Capacity disks ({len(dg['capacity'])}):\n"
                    for cd in dg["capacity"]:
                        cap_gb = (
                            round(cd["capacityBytes"] / 1024 / 1024 / 1024, 1)
                            if cd["capacityBytes"]
                            else "?"
                        )
                        result += (
                            f"      - `{cd['displayName']}` "
                            f"({cap_gb} GB, state={cd['state']})\n"
                        )
                else:
                    result += "    Capacity disks: _(none)_\n"
                result += "\n"

        result += (
            "\n_Note: QueryDiskMappings is per-host (vSAN API signature). "
            "Cluster-scoped query is not supported by pyVmomi._\n"
        )
        return result

    except Exception as e:
        return _handle_vsan_error(e, f"getting vSAN disk groups for cluster {cluster_name}")
    finally:
        client.close()


@mcp.tool()
def get_vsan_performance_metrics(
    cluster_name: str,
    entity_type: str = "cluster-domclient",
    hostname: str = None,
) -> str:
    """Get vSAN performance metrics (IOPS, throughput, latency, congestion, oio).

    Read-only. Queries the vSAN Performance Service for the cluster. The
    Performance Service runs only if the vSAN stats object exists and has
    accumulated samples; on idle clusters the response may legitimately
    be empty — that is reported as informational, not an error.

    Args:
        cluster_name: Name of the vSAN-enabled cluster.
        entity_type: One of:
            - "cluster-domclient" (default) — VM-consumption view of cluster
            - "host-domclient" — per-host VM-consumption view
        hostname: Optional vCenter hostname.

    Returns:
        Markdown summary + per-metric CSV values (or informational note
        if no samples available).
    """
    client = PyVmomiClient(host=hostname)
    try:
        cluster = client.find_vsan_cluster(cluster_name)
        if cluster is None:
            plain = client.find_cluster(cluster_name)
            if plain is None:
                return _handle_error(
                    Exception(f"cluster '{cluster_name}' not found"),
                    f"getting vSAN perf for cluster {cluster_name}",
                )
            return _vsan_status_icon("yellow") + (
                f" Cluster '{cluster_name}' exists but vSAN is not enabled."
            )

        mos = client.get_vsan_vc_mos()
        pm = mos["vsan-performance-manager"]

        # Verify stats object exists (performance service activation).
        # VsanPerfQueryStatsObjectInformation returns a single
        # VsanObjectInformation object (not a list) — confirmed by probe.
        stats_info = pm.VsanPerfQueryStatsObjectInformation(cluster=cluster)
        stats_obj = stats_info if stats_info is not None else None
        stats_obj_uuid = getattr(stats_obj, "vsanObjectUuid", None) if stats_obj else None
        stats_obj_health = getattr(stats_obj, "vsanHealth", None) if stats_obj else None
        stats_obj_policy = (
            getattr(stats_obj, "spbmProfileName", None) if stats_obj else None
        )

        # Build query spec list.
        from datetime import datetime, timedelta, timezone

        labels = [
            "iopsRead", "iopsWrite",
            "throughputRead", "throughputWrite",
            "latencyAvgRead", "latencyAvgWrite",
            "congestion", "oio",
        ]

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=1)

        specs = []
        if entity_type == "host-domclient":
            for host in (cluster.host or []):
                specs.append(vim.cluster.VsanPerfQuerySpec(
                    entityRefId=f"host-domclient:{host._moId}",
                    startTime=start, endTime=end, interval=300,
                    labels=labels,
                ))
        else:
            specs.append(vim.cluster.VsanPerfQuerySpec(
                entityRefId=f"cluster-domclient:{cluster._moId}",
                startTime=start, endTime=end, interval=300,
                labels=labels,
            ))

        result_set = pm.VsanPerfQueryPerf(querySpecs=specs, cluster=cluster)

        # Render
        result = f"# vSAN Performance Metrics: {cluster_name}\n\n"
        result += f"Window: last 1 hour (interval=300s)\n"
        result += f"Entity type: `{entity_type}`\n"
        if stats_obj_uuid:
            result += (
                f"Stats object: `{stats_obj_uuid}` "
                f"(health={stats_obj_health}, policy={stats_obj_policy})\n\n"
            )
        else:
            result += "Stats object: _not present — vSAN Performance Service not running._\n\n"

        if not result_set:
            result += (
                "⚠ vSAN Performance Service returned no data. "
                "This is informational, not an error: it usually means the "
                "Performance Service is enabled but the stats object has not "
                "yet accumulated samples (cluster is idle or service was just "
                "started).\n"
            )
            return result

        any_samples = False
        for row in result_set:
            ref_id = getattr(row, "entityRefId", "?")
            sample_info = getattr(row, "sampleInfo", "") or ""
            value_csvs = getattr(row, "value", None) or []

            # Translate moId back to a friendly label
            label = ref_id
            if ref_id.startswith("host-domclient:"):
                mo = ref_id.split(":", 1)[1]
                for h in (cluster.host or []):
                    if h._moId == mo:
                        label = f"host: {h.name}"
                        break
            elif ref_id.startswith("cluster-domclient:"):
                label = f"cluster: {cluster_name}"

            result += f"## {label}\n"
            result += f"Sample info: `{sample_info or '(empty)'}`\n\n"

            if not value_csvs:
                result += (
                    "  _(no samples in window — see Stats object status above)_\n\n"
                )
                continue

            # VsanPerfMetricSeriesCSV: .entityRefId, .metricId (group, label),
            # .values (str CSV of numbers)
            for series in value_csvs:
                mid = getattr(series, "metricId", None)
                mlbl = getattr(mid, "label", "?") if mid else "?"
                mname = getattr(mid, "name", mlbl) if mid else "?"
                vals = getattr(series, "values", None) or ""
                result += f"- **{mname}** (`{mlbl}`): `{vals or '(empty)'}`\n"
                if vals:
                    any_samples = True
            result += "\n"

        if not any_samples:
            result += (
                "_All metric series returned empty values. This is informational: "
                "the vSAN Performance Service is running but no IO has been "
                "sampled in the requested window._\n"
            )

        return result

    except Exception as e:
        return _handle_vsan_error(e, f"getting vSAN performance metrics for cluster {cluster_name}")
    finally:
        client.close()


@mcp.tool()
def get_vsan_health_checks(cluster_name: str, hostname: str = None) -> str:
    """Get vSAN health summary with per-group metadata and per-host status.

    Read-only. Aggregates the cluster health summary from
    QueryClusterHealthSummary (overall + groups + per-host statuses + issues)
    and augments with per-host vSAN node state (master/backup/agent) via
    QueryHostStatus. No tests are executed — this is a fast snapshot view.

    Args:
        cluster_name: Name of the vSAN-enabled cluster.
        hostname: Optional vCenter hostname.

    Returns:
        Markdown overview + per-host block.
    """
    client = PyVmomiClient(host=hostname)
    try:
        cluster = client.find_vsan_cluster(cluster_name)
        if cluster is None:
            plain = client.find_cluster(cluster_name)
            if plain is None:
                return _handle_error(
                    Exception(f"cluster '{cluster_name}' not found"),
                    f"getting vSAN health checks for cluster {cluster_name}",
                )
            return _vsan_status_icon("yellow") + (
                f" Cluster '{cluster_name}' exists but vSAN is not enabled."
            )

        mos = client.get_vsan_vc_mos()
        health_sys = mos["vsan-cluster-health-system"]

        summary = health_sys.QueryClusterHealthSummary(cluster=cluster)

        overall = getattr(summary, "overallHealth", "unknown") or "unknown"
        desc = getattr(summary, "overallHealthDescription", "") or ""
        timestamp = getattr(summary, "timestamp", None)

        cs = getattr(summary, "clusterStatus", None)
        tracked = (getattr(cs, "trackedHostsStatus", None) or []) if cs else []
        untracked = (getattr(cs, "untrackedHosts", None) or []) if cs else []

        groups = getattr(summary, "groups", None) or []

        result = f"# vSAN Health Checks: {cluster_name}\n\n"
        result += f"Overall: {_vsan_status_icon(overall)} **{overall.upper()}**\n"
        if desc:
            result += f"Description: {desc}\n"
        if timestamp:
            try:
                result += f"Sampled at: {timestamp}\n"
            except Exception:
                pass
        result += "\n"

        # Groups (metadata only — tests are NOT executed)
        result += f"## Health groups ({len(groups)})\n\n"
        if groups:
            result += "| # | Group | ID | In progress |\n"
            result += "|---|-------|----|-------------|\n"
            for i, g in enumerate(groups, 1):
                gname = getattr(g, "groupName", None) or "?"
                gid = getattr(g, "groupId", None) or "?"
                in_prog = getattr(g, "inProgress", None)
                in_prog_s = "yes" if in_prog else "no"
                result += f"| {i} | {gname} | `{gid}` | {in_prog_s} |\n"
            result += "\n"
        else:
            result += "  _(no groups returned)_\n\n"

        # Tracked hosts
        result += f"## Tracked hosts ({len(tracked)})\n\n"
        if tracked:
            for h in tracked:
                hname = getattr(h, "hostname", "?") or "?"
                hstatus = getattr(h, "status", "unknown") or "unknown"
                issues = list(getattr(h, "issues", None) or [])
                result += f"- {_vsan_status_icon(hstatus)} **{hname}** — {hstatus.upper()}\n"
                if issues:
                    for iss in issues:
                        result += f"    - {iss}\n"
                else:
                    result += "    - (no issues)\n"
            result += "\n"
        else:
            result += "  _(no tracked hosts)_\n\n"

        # Untracked hosts
        if untracked:
            result += f"## Untracked hosts ({len(untracked)})\n\n"
            for uh in untracked:
                result += f"- {uh}\n"
            result += "\n"

        # Per-host node state via QueryHostStatus (read-only)
        result += f"## Per-host vSAN node state\n\n"
        result += "| Host | State | Node UUID |\n"
        result += "|------|-------|-----------|\n"
        for host in (cluster.host or []):
            try:
                host_status = host.configManager.vsanSystem.QueryHostStatus()
                # nodeState is a vim.vsan.host.ClusterStatus.State — extract .state
                ns_obj = getattr(host_status, "nodeState", None)
                ns_state = getattr(ns_obj, "state", None) if ns_obj else None
                node_state_s = str(ns_state) if ns_state is not None else "?"
                node_uuid = getattr(host_status, "nodeUuid", None) or "?"
                result += f"| {host.name} | {node_state_s} | `{node_uuid}` |\n"
            except Exception as he:
                result += (
                    f"| {host.name} | error | `{type(he).__name__}: "
                    f"{str(getattr(he, 'msg', he))[:80]}` |\n"
                )
        result += "\n"

        result += (
            "_Note: groups listed above are metadata only — no individual "
            "tests were executed. For deep diagnostics use vSphere Client._\n"
        )
        return result

    except Exception as e:
        return _handle_vsan_error(e, f"getting vSAN health checks for cluster {cluster_name}")
    finally:
        client.close()


# ── vSAN Phase 3: objects, storage policies, capabilities ─────────
# All read-only (Tier 1) — see memory vsan-readonly-only-rule.


@mcp.tool()
def get_vsan_objects(
    cluster_name: str,
    object_type: str = "all",
    hostname: str = None,
) -> str:
    """List vSAN objects in a cluster with type breakdown and health overview.

    Read-only. Uses vsan-cluster-object-system.QueryObjectIdentities which
    returns every vSAN object (vdisks, namespaces, vmswap, statsdb, etc.)
    on the cluster plus per-object SPBM profile assignment.

    Args:
        cluster_name: Name of the vSAN-enabled cluster.
        object_type: Filter — "all" (default), "vdisk", "namespace",
            "vmswap", "statsdb", "vmem", "traceobject", "other".
        hostname: Optional vCenter hostname.

    Returns:
        Markdown summary with type breakdown, profile breakdown,
        and per-VM list (top N) when objects are present.
    """
    client = PyVmomiClient(host=hostname)
    try:
        cluster = client.find_vsan_cluster(cluster_name)
        if cluster is None:
            plain = client.find_cluster(cluster_name)
            if plain is None:
                return _handle_error(
                    Exception(f"cluster '{cluster_name}' not found"),
                    f"getting vSAN objects for cluster {cluster_name}",
                )
            return _vsan_status_icon("yellow") + (
                f" Cluster '{cluster_name}' exists but vSAN is not enabled."
            )

        mos = client.get_vsan_vc_mos()
        obj_sys = mos["vsan-cluster-object-system"]
        oih = obj_sys.QueryObjectIdentities(cluster=cluster)
        identities = list(getattr(oih, "identities", None) or [])

        # Apply filter
        if object_type != "all":
            identities = [i for i in identities
                          if getattr(i, "type", None) == object_type]

        from collections import Counter

        type_breakdown = Counter(getattr(i, "type", "?") for i in identities)
        profile_breakdown = Counter(
            (getattr(i, "spbmProfileName", None) or "(no profile)")
            for i in identities
        )

        result = f"# vSAN Objects: {cluster_name}\n\n"
        result += f"Total objects (filter=`{object_type}`): {len(identities)}\n\n"

        if type_breakdown:
            result += "## Type breakdown\n\n"
            result += "| Type | Count |\n|------|-------|\n"
            for t, n in sorted(type_breakdown.items(), key=lambda kv: -kv[1]):
                result += f"| {t} | {n} |\n"
            result += "\n"

        if profile_breakdown:
            result += "## SPBM profile assignment\n\n"
            result += "| Profile | Objects |\n|---------|---------|\n"
            for p, n in sorted(profile_breakdown.items(), key=lambda kv: -kv[1]):
                result += f"| {p} | {n} |\n"
            result += "\n"

        # Show up to 30 sample objects with VM reference
        if identities:
            result += f"## Sample objects (up to 30)\n\n"
            result += "| Type | UUID | SPBM Profile | VM | Description |\n"
            result += "|------|------|--------------|----|-------------|\n"
            for i in identities[:30]:
                t = getattr(i, "type", "?") or "?"
                u = getattr(i, "uuid", "") or ""
                profile = getattr(i, "spbmProfileName", None) or "—"
                vm_ref = getattr(i, "vm", None)
                vm_s = (
                    str(vm_ref).replace("vim.VirtualMachine:", "vm-")
                    if vm_ref is not None
                    else "—"
                )
                desc = getattr(i, "description", None) or "—"
                # truncate long descriptions
                if len(desc) > 80:
                    desc = desc[:77] + "..."
                result += f"| {t} | `{u[:8]}…` | {profile} | {vm_s} | {desc} |\n"
            if len(identities) > 30:
                result += f"\n_(showing first 30 of {len(identities)})_\n"
            result += "\n"

        result += (
            "_Note: identity+health is a snapshot — health and spaceSummary "
            "fields are not populated on this endpoint in vSAN 8.x. For "
            "per-VM health use vSphere Client → Cluster → Monitor → vSAN._\n"
        )
        return result

    except Exception as e:
        return _handle_vsan_error(e, f"getting vSAN objects for cluster {cluster_name}")
    finally:
        client.close()


@mcp.tool()
def get_vsan_storage_policies(hostname: str = None) -> str:
    """List vCenter storage policies, including vSAN-aware ones.

    Read-only. Uses the vCenter REST endpoint `GET /vcenter/storage/policies`
    which returns all storage policies on the vCenter (including built-in
    vSAN defaults like "vSAN Default Storage Policy", "vSAN ESA Default
    Policy - RAID5/6", "vSAN-HA-Policy-by-GS", and custom policies).

    Args:
        hostname: Optional vCenter hostname.

    Returns:
        Markdown table of all policies with name, description, id, and a
        flag indicating whether the name suggests vSAN-awareness.
    """
    import os
    # VSphereClient does not read VCENTER_HOST from env, so resolve it here.
    rest_host = hostname or os.environ.get("VCENTER_HOST")
    if not rest_host:
        return _handle_error(
            Exception(
                "no hostname provided and VCENTER_HOST not set in environment"
            ),
            "listing vCenter storage policies",
        )
    rest = VSphereClient(hostname=rest_host)
    try:
        # Resolve hostname for PyVmomiClient only to validate connectivity;
        # the actual data is REST-only.
        raw = rest.get("/vcenter/storage/policies")
        # REST response shape: {"value": [{"name", "description", "policy"}]}
        policies = (raw or {}).get("value") or []
        if not policies:
            return "No storage policies returned by /vcenter/storage/policies."

        vsan_keywords = ("vsan", "fabra", "strecthed", "esa")
        vsan_policies = []
        other_policies = []
        for p in policies:
            name = (p.get("name") or "").lower()
            desc = (p.get("description") or "").lower()
            is_vsan_related = any(
                kw in name or kw in desc for kw in vsan_keywords
            )
            if is_vsan_related:
                vsan_policies.append(p)
            else:
                other_policies.append(p)

        result = f"# Storage Policies ({len(policies)} total)\n\n"
        result += f"vSAN-related: {len(vsan_policies)} | other: {len(other_policies)}\n\n"

        if vsan_policies:
            result += "## vSAN-related policies\n\n"
            result += "| Name | ID | Description |\n|------|----|-------------|\n"
            for p in vsan_policies:
                pid = p.get("policy") or "?"
                desc = p.get("description") or "—"
                if len(desc) > 90:
                    desc = desc[:87] + "..."
                result += f"| **{p.get('name')}** | `{pid}` | {desc} |\n"
            result += "\n"

        if other_policies:
            result += "## Other policies\n\n"
            result += "| Name | ID | Description |\n|------|----|-------------|\n"
            for p in other_policies:
                pid = p.get("policy") or "?"
                desc = p.get("description") or "—"
                if len(desc) > 90:
                    desc = desc[:87] + "..."
                result += f"| {p.get('name')} | `{pid}` | {desc} |\n"
            result += "\n"

        result += (
            "_Note: this endpoint lists policy names and IDs only — detailed "
            "rule sets (capabilities, FTT, stripes) require the SPBM API "
            "(`/pbm/...`), which is not exposed via the vCenter REST API in "
            "8.0.3. For full rule inspection use the vSphere Client._\n"
        )
        return result

    except Exception as e:
        return _handle_error(e, "listing vCenter storage policies")
    finally:
        try:
            rest.session.close()
        except Exception:
            pass


@mcp.tool()
def get_vsan_capabilities(hostname: str = None) -> str:
    """Get vSAN capabilities advertised by this vCenter.

    Read-only. Calls VsanCapabilitySystem.VsanGetCapabilities (no
    cluster argument) which returns the union of vSAN features supported
    by this vCenter + cluster combination.

    Args:
        hostname: Optional vCenter hostname.

    Returns:
        Markdown summary: capability count + full list grouped by category.
    """
    client = PyVmomiClient(host=hostname)
    try:
        mos = client.get_vsan_vc_mos()
        cap_sys = mos["vsan-vc-capability-system"]
        # NOTE: VsanGetCapabilities takes NO arguments (cluster= not accepted).
        caps = cap_sys.VsanGetCapabilities()

        result = "# vSAN Capabilities (this vCenter)\n\n"

        if not caps:
            return result + "⚠ vCenter returned no capability record.\n"

        # Typically a single VsanCapability object (or list with one entry).
        all_features = []
        statuses_by_target = []
        for cap in caps:
            all_features.extend(getattr(cap, "capabilities", None) or [])
            st = getattr(cap, "statuses", None) or []
            tg = getattr(cap, "target", None)
            if st:
                statuses_by_target.append((tg, st))

        result += f"Capability records: {len(caps)}\n"
        result += f"Advertised features: {len(all_features)}\n\n"

        if all_features:
            # Try to surface a meaningful icon per feature using a small heuristic
            def icon(feat: str) -> str:
                fl = feat.lower()
                if "stretch" in fl:
                    return "🛰️"
                if "encrypt" in fl:
                    return "🔐"
                if "dataefficiency" in fl or "dedup" in fl or "compression" in fl:
                    return "📦"
                if "allflash" in fl:
                    return "⚡"
                if "iscsi" in fl:
                    return "💾"
                if "perf" in fl:
                    return "📈"
                if "witness" in fl:
                    return "👁️"
                return "•"

            result += "## Advertised features\n\n"
            for f in sorted(set(all_features)):
                result += f"- {icon(f)} `{f}`\n"
            result += "\n"

        if statuses_by_target:
            result += "## Per-feature status (if reported)\n\n"
            for tgt, sts in statuses_by_target:
                target_s = str(tgt) if tgt else "(no target)"
                result += f"- Target: `{target_s}` — {len(sts)} entries\n"
                for s in sts[:5]:
                    result += f"    - {getattr(s, 'name', s)} = {getattr(s, 'value', '?')}\n"
            result += "\n"

        result += (
            "_Note: this is the vCenter-side capability advertisement "
            "(`vim.cluster.VsanCapabilitySystem`). It does not reflect "
            "license state — to verify vSAN licensing use the vSphere Client._\n"
        )
        return result

    except Exception as e:
        return _handle_vsan_error(e, "getting vSAN capabilities")
    finally:
        client.close()


@mcp.tool()
def get_vsan_witness_info(cluster_name: str, hostname: str = None) -> str:
    """Get vSAN stretched-cluster witness host information.

    Read-only. Targets the
    ``vim.cluster.VsanVcStretchedClusterSystem`` MO on the ``/vsanHealth``
    endpoint. Returns the witness host(s) registered for a stretched
    cluster, including hostname/MoRef, node UUID, and preferred fault
    domain.

    Graceful fallbacks (cluster 122 is non-stretched, so the typical
    outcome here is the "not stretched" message):

    - Capability flag ``stretchedcluster`` absent → "vSAN stretched
      cluster is not supported on this vCenter version".
    - MO ``vsan-cluster-stretched-system`` not registered (typical for
      non-stretched vCenters) → "Cluster ... is not stretched".

    Args:
        cluster_name: Name of the vSAN-enabled cluster.
        hostname: Optional vCenter hostname.

    Returns:
        Markdown summary: cluster stretched status, witness host(s), or
        graceful fallback message.
    """
    client = PyVmomiClient(host=hostname)
    try:
        cluster = client.find_vsan_cluster(cluster_name)
        if cluster is None:
            plain = client.find_cluster(cluster_name)
            if plain is None:
                return _handle_error(
                    Exception(f"cluster '{cluster_name}' not found"),
                    f"getting vSAN witness info for cluster {cluster_name}",
                )
            return _vsan_status_icon("yellow") + (
                f" Cluster '{cluster_name}' exists but vSAN is not enabled. "
                "This tool requires a vSAN-enabled cluster."
            )

        mos = client.get_vsan_vc_mos()
        cap_sys = mos["vsan-vc-capability-system"]

        # Capability gate: stretched cluster support advertised?
        try:
            caps = cap_sys.VsanGetCapabilities() or []
            all_features = []
            for cap in caps:
                all_features.extend(getattr(cap, "capabilities", None) or [])
            stretched_supported = any("stretch" in f.lower() for f in all_features)
        except Exception as ce:
            stretched_supported = False
            capability_error = f"{type(ce).__name__}: {str(ce)[:120]}"
        else:
            capability_error = None

        if not stretched_supported:
            return (
                f"# vSAN Witness Info — {cluster_name}\n\n"
                f"{_vsan_status_icon('yellow')} vSAN stretched cluster is not "
                "supported (or not licensed) on this vCenter.\n\n"
                f"_Underlying error: {capability_error or 'stretchedcluster flag absent in capabilities'}_\n"
            )

        # Stretched cluster support advertised → try the stretched-cluster MO.
        from pyVmomi import SoapStubAdapter

        stub = client.si._stub
        vsan_stub = SoapStubAdapter(
            host=stub.host.split(":")[0],
            port=int(stub.host.split(":")[-1]),
            path="/vsanHealth",
            version="vim.version.version11",
            sslContext=(getattr(stub, "schemeArgs", None) or {}).get("context"),
        )
        vsan_stub.cookie = stub.cookie
        scs = vim.cluster.VsanVcStretchedClusterSystem(
            "vsan-cluster-stretched-system", vsan_stub
        )

        # Capability gate (per-cluster, optional): confirms stretched
        # cluster service is enabled on this cluster. Some vCenters
        # advertise the capability flag globally but never enable the
        # service for any specific cluster — RetrieveStretchedClusterVcCapability
        # raises ManagedObjectNotFound in that case.
        try:
            sc_cap = scs.RetrieveStretchedClusterVcCapability(cluster=cluster)
            stretched_enabled = bool(getattr(sc_cap, "stretchedClusterSupported", True))
        except Exception:
            stretched_enabled = False

        if not stretched_enabled:
            return (
                f"# vSAN Witness Info — {cluster_name}\n\n"
                f"{_vsan_status_icon('green')} Cluster '{cluster_name}' is **not stretched** "
                "(vSAN stretched cluster service is not enabled on this cluster).\n\n"
                "_Note: this cluster has no witness host. To enable stretched "
                "cluster, contact your vSphere admin._\n"
            )

        # Stretched → enumerate witness hosts.
        try:
            witness_hosts = scs.VSANVcGetWitnessHosts(cluster=cluster) or []
        except Exception as we:
            return _handle_vsan_error(we, f"listing vSAN witness hosts for cluster {cluster_name}")

        result = f"# vSAN Witness Info — {cluster_name}\n\n"
        result += f"Stretched cluster: {_vsan_status_icon('green')} enabled\n"
        result += f"Witness hosts registered: {len(witness_hosts)}\n\n"

        if not witness_hosts:
            result += (
                f"{_vsan_status_icon('yellow')} Stretched cluster is enabled, but no "
                "witness hosts are currently registered.\n"
            )
            return result

        result += "## Witness hosts\n\n"
        for i, w in enumerate(witness_hosts, 1):
            host_ref = getattr(w, "host", None)
            host_name = getattr(host_ref, "name", None) if host_ref else None
            host_moid = getattr(host_ref, "_moId", None) if host_ref else None
            node_uuid = getattr(w, "nodeUuid", None)
            preferred_fd = getattr(w, "preferredFdName", None)

            result += f"### Witness [{i}]\n\n"
            result += f"- Hostname: `{host_name or '(unknown)'}`\n"
            result += f"- MoRef: `{host_moid or '(unknown)'}`\n"
            result += f"- Node UUID: `{node_uuid or '(unknown)'}`\n"
            result += f"- Preferred fault domain: `{preferred_fd or '(none)'}`\n\n"

        result += (
            "_Note: witness host IP/connectivity is not exposed via this API. "
            "To verify witness traffic, use the vSphere Client → "
            "Cluster → Monitor → vSAN → Witness Hosts._\n"
        )
        return result

    except Exception as e:
        return _handle_vsan_error(e, f"getting vSAN witness info for cluster {cluster_name}")
    finally:
        client.close()


# Network Management Tools
@mcp.tool()
def get_port_groups(hostname: str = None) -> str:
    """Get all port groups in the vSphere environment.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # Get port groups (this might be available through network endpoints)
        response = client.get("vcenter/network")
        networks = response.get("value", [])
        
        if not networks:
            return "No networks found"
        
        result = f"Network Port Groups ({len(networks)}):\n\n"
        for network in networks:
            result += f"• {network.get('name', 'Unknown')}\n"
            result += f"  Type: {network.get('type', 'Unknown')}\n"
            result += f"  ID: {network.get('network', 'Unknown')}\n\n"
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "getting port groups")
    finally:
        client.close()


# Reporting and Analytics Tools
@mcp.tool()
def generate_vm_report(hostname: str = None) -> str:
    """Generate a comprehensive report of all VMs.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # Get all VMs
        response = client.get("vcenter/vm")
        vms = response.get("value", [])
        
        if not vms:
            return "No virtual machines found"
        
        # Get datastores for storage info
        ds_response = client.get("vcenter/datastore")
        datastores = ds_response.get("value", [])
        
        # Get hosts for host info
        host_response = client.get("vcenter/host")
        hosts = host_response.get("value", [])
        
        result = f"=== vSphere VM Report ===\n"
        result += f"Generated: {os.popen('date').read().strip()}\n"
        result += f"Total VMs: {len(vms)}\n"
        result += f"Total Hosts: {len(hosts)}\n"
        result += f"Total Datastores: {len(datastores)}\n\n"
        
        # VM Summary
        powered_on = sum(1 for vm in vms if vm.get('power_state') == 'POWERED_ON')
        powered_off = len(vms) - powered_on
        
        result += f"=== VM Summary ===\n"
        result += f"Powered On: {powered_on}\n"
        result += f"Powered Off: {powered_off}\n\n"
        
        # Detailed VM List
        result += f"=== Detailed VM List ===\n"
        for vm in vms:
            vm_name = vm.get('name', 'Unknown')
            power_state = vm.get('power_state', 'Unknown')
            result += f"• {vm_name} - {power_state}\n"
        
        result += f"\n=== Datastore Summary ===\n"
        for ds in datastores:
            ds_name = ds.get('name', 'Unknown')
            capacity = ds.get("capacity", 0)
            free_space = ds.get("free_space", 0)
            if capacity > 0:
                used_pct = ((capacity - free_space) / capacity * 100)
                result += f"• {ds_name}: {used_pct:.1f}% used\n"
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "generating VM report")
    finally:
        client.close()


@mcp.tool()
def get_resource_utilization_summary(hostname: str = None) -> str:
    """Get a summary of resource utilization across the vSphere environment.

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # Get all VMs
        vm_response = client.get("vcenter/vm")
        vms = vm_response.get("value", [])
        
        # Get all hosts
        host_response = client.get("vcenter/host")
        hosts = host_response.get("value", [])
        
        # Get all datastores
        ds_response = client.get("vcenter/datastore")
        datastores = ds_response.get("value", [])
        
        result = f"=== Resource Utilization Summary ===\n\n"
        
        # CPU Summary
        total_vcpus = 0
        total_physical_cpus = 0
        
        for vm in vms:
            if vm.get('power_state') == 'POWERED_ON':
                try:
                    vm_details = client.get(f"vcenter/vm/{vm.get('vm')}")
                    vm_data = vm_details.get("value", {})
                    cpu_info = vm_data.get("cpu", {})
                    if cpu_info:
                        total_vcpus += cpu_info.get("count", 0)
                except:
                    continue
        
        for host in hosts:
            if host.get('connection_state') == 'CONNECTED':
                try:
                    host_details = client.get(f"vcenter/host/{host.get('host')}")
                    host_data = host_details.get("value", {})
                    cpu_info = host_data.get("cpu", {})
                    if cpu_info:
                        total_physical_cpus += cpu_info.get("count", 0)
                except:
                    continue
        
        result += f"CPU Utilization:\n"
        result += f"  Total vCPUs allocated: {total_vcpus}\n"
        result += f"  Total physical CPUs: {total_physical_cpus}\n"
        if total_physical_cpus > 0:
            cpu_ratio = total_vcpus / total_physical_cpus
            result += f"  vCPU to Physical CPU ratio: {cpu_ratio:.2f}:1\n"
        result += "\n"
        
        # Memory Summary
        total_vm_memory = 0
        total_host_memory = 0
        
        for vm in vms:
            if vm.get('power_state') == 'POWERED_ON':
                try:
                    vm_details = client.get(f"vcenter/vm/{vm.get('vm')}")
                    vm_data = vm_details.get("value", {})
                    memory_info = vm_data.get("memory", {})
                    if memory_info:
                        total_vm_memory += memory_info.get("size_MiB", 0)
                except:
                    continue
        
        for host in hosts:
            if host.get('connection_state') == 'CONNECTED':
                try:
                    host_details = client.get(f"vcenter/host/{host.get('host')}")
                    host_data = host_details.get("value", {})
                    memory_info = host_data.get("memory", {})
                    if memory_info:
                        total_host_memory += memory_info.get("size_MiB", 0)
                except:
                    continue
        
        result += f"Memory Utilization:\n"
        result += f"  Total VM memory allocated: {total_vm_memory / 1024:.1f} GB\n"
        result += f"  Total host memory: {total_host_memory / 1024:.1f} GB\n"
        if total_host_memory > 0:
            memory_ratio = (total_vm_memory / total_host_memory) * 100
            result += f"  Memory overcommitment: {memory_ratio:.1f}%\n"
        result += "\n"
        
        # Storage Summary
        total_capacity = 0
        total_free = 0
        
        for ds in datastores:
            total_capacity += ds.get("capacity", 0)
            total_free += ds.get("free_space", 0)
        
        total_used = total_capacity - total_free
        used_percentage = (total_used / total_capacity * 100) if total_capacity > 0 else 0
        
        result += f"Storage Utilization:\n"
        result += f"  Total capacity: {total_capacity / (1024**3):.1f} GB\n"
        result += f"  Total used: {total_used / (1024**3):.1f} GB ({used_percentage:.1f}%)\n"
        result += f"  Total free: {total_free / (1024**3):.1f} GB\n"
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "getting resource utilization summary")
    finally:
        client.close()


# Automation Tools
@mcp.tool()
def bulk_power_operations(operation: str, vm_list: str, hostname: str = None) -> str:
    """Perform bulk power operations on multiple VMs.

    Args:
        operation: Power operation ('on', 'off', 'restart')
        vm_list: Comma-separated list of VM names or IDs
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    if operation not in ['on', 'off', 'restart']:
        return "Error: Operation must be 'on', 'off', or 'restart'"
    
    client = VSphereClient(hostname)
    try:
        # Get all VMs to resolve names to IDs
        response = client.get("vcenter/vm")
        vms = response.get("value", [])
        
        vm_names = [name.strip() for name in vm_list.split(',')]
        results = []
        
        for vm_name in vm_names:
            vm_id = None
            for vm in vms:
                if vm.get("name", "").lower() == vm_name.lower():
                    vm_id = vm.get("vm")
                    break
            
            if not vm_id:
                results.append(f"❌ {vm_name}: VM not found")
                continue
            
            try:
                if operation == 'on':
                    client.post(f"vcenter/vm/{vm_id}/power/start")
                    results.append(f"✅ {vm_name}: Power on initiated")
                elif operation == 'off':
                    client.post(f"vcenter/vm/{vm_id}/power/stop")
                    results.append(f"✅ {vm_name}: Power off initiated")
                elif operation == 'restart':
                    client.post(f"vcenter/vm/{vm_id}/power/reset")
                    results.append(f"✅ {vm_name}: Restart initiated")
            except Exception as e:
                results.append(f"❌ {vm_name}: Error - {str(e)}")
        
        result = f"Bulk {operation.upper()} Operation Results:\n\n"
        for res in results:
            result += f"{res}\n"
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"bulk {operation} operation")
    finally:
        client.close()


# Destructive Operations with Confirmation
@mcp.tool()
def delete_vm_snapshot(vm_id: str, snapshot_id: str, confirm: bool = False, hostname: str = None) -> str:
    """Delete a snapshot for a specific VM. REQUIRES CONFIRMATION.

    Args:
        vm_id: Virtual machine ID or name
        snapshot_id: Snapshot ID to delete
        confirm: Must be True to proceed with deletion
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if not confirm:
        return f"⚠️  DESTRUCTIVE OPERATION: Delete snapshot {snapshot_id} for VM {vm_id}\n\nThis operation cannot be undone!\n\nTo proceed, call this function again with confirm=True"
    
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # If vm_id doesn't start with 'vm-', assume it's a name and look up the ID
        if not vm_id.startswith("vm-"):
            vms_response = client.get("vcenter/vm")
            vms = vms_response.get("value", [])
            
            vm_id_found = None
            for vm in vms:
                if vm.get("name", "").lower() == vm_id.lower():
                    vm_id_found = vm.get("vm")
                    break
            
            if not vm_id_found:
                return f"Virtual machine '{vm_id}' not found by name"
            vm_id = vm_id_found
        
        # Delete snapshot
        client.delete(f"vcenter/vm/{vm_id}/snapshot/{snapshot_id}")
        return f"✅ Snapshot {snapshot_id} deleted successfully for VM {vm_id}"
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"deleting snapshot {snapshot_id} for VM {vm_id}")
    finally:
        client.close()


@mcp.tool()
def delete_vm(vm_id: str, confirm: bool = False, hostname: str = None) -> str:
    """Delete a virtual machine. REQUIRES CONFIRMATION.

    Args:
        vm_id: Virtual machine ID or name
        confirm: Must be True to proceed with deletion
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if not confirm:
        return f"⚠️  DESTRUCTIVE OPERATION: Delete VM {vm_id}\n\nThis operation will permanently delete the virtual machine and all its data!\nThis operation cannot be undone!\n\nTo proceed, call this function again with confirm=True"
    
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # If vm_id doesn't start with 'vm-', assume it's a name and look up the ID
        if not vm_id.startswith("vm-"):
            vms_response = client.get("vcenter/vm")
            vms = vms_response.get("value", [])
            
            vm_id_found = None
            for vm in vms:
                if vm.get("name", "").lower() == vm_id.lower():
                    vm_id_found = vm.get("vm")
                    break
            
            if not vm_id_found:
                return f"Virtual machine '{vm_id}' not found by name"
            vm_id = vm_id_found
        
        # Delete VM
        client.delete(f"vcenter/vm/{vm_id}")
        return f"✅ VM {vm_id} deleted successfully"
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"deleting VM {vm_id}")
    finally:
        client.close()


@mcp.tool()
def modify_vm_resources(vm_id: str, cpu_count: int = None, memory_gb: int = None, confirm: bool = False, hostname: str = None) -> str:
    """Modify VM resources (CPU and/or Memory). REQUIRES CONFIRMATION.

    Args:
        vm_id: Virtual machine ID or name
        cpu_count: New CPU count (optional)
        memory_gb: New memory in GB (optional)
        confirm: Must be True to proceed with modification
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if not confirm:
        changes = []
        if cpu_count is not None:
            changes.append(f"CPU: {cpu_count} vCPUs")
        if memory_gb is not None:
            changes.append(f"Memory: {memory_gb} GB")
        
        return f"⚠️  DESTRUCTIVE OPERATION: Modify VM {vm_id}\n\nProposed changes:\n" + "\n".join(f"  - {change}" for change in changes) + "\n\nThis operation will modify the VM configuration!\n\nTo proceed, call this function again with confirm=True"
    
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    if cpu_count is None and memory_gb is None:
        return "Error: At least one resource (CPU or Memory) must be specified"
    
    client = VSphereClient(hostname)
    try:
        # If vm_id doesn't start with 'vm-', assume it's a name and look up the ID
        if not vm_id.startswith("vm-"):
            vms_response = client.get("vcenter/vm")
            vms = vms_response.get("value", [])
            
            vm_id_found = None
            for vm in vms:
                if vm.get("name", "").lower() == vm_id.lower():
                    vm_id_found = vm.get("vm")
                    break
            
            if not vm_id_found:
                return f"Virtual machine '{vm_id}' not found by name"
            vm_id = vm_id_found
        
        # Prepare modification data
        modification_data = {}
        
        if cpu_count is not None:
            modification_data["cpu"] = {"count": cpu_count}
        
        if memory_gb is not None:
            modification_data["memory"] = {"size_MiB": memory_gb * 1024}
        
        # Apply modifications
        client.patch(f"vcenter/vm/{vm_id}", modification_data)
        
        changes = []
        if cpu_count is not None:
            changes.append(f"CPU: {cpu_count} vCPUs")
        if memory_gb is not None:
            changes.append(f"Memory: {memory_gb} GB")
        
        return f"✅ VM {vm_id} modified successfully:\n" + "\n".join(f"  - {change}" for change in changes)
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"modifying VM {vm_id}")
    finally:
        client.close()


@mcp.tool()
def bulk_delete_vms(vm_list: str, confirm: bool = False, hostname: str = None) -> str:
    """Delete multiple VMs. REQUIRES CONFIRMATION.

    Args:
        vm_list: Comma-separated list of VM names or IDs
        confirm: Must be True to proceed with deletion
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if not confirm:
        vm_names = [name.strip() for name in vm_list.split(',')]
        return f"⚠️  DESTRUCTIVE OPERATION: Delete Multiple VMs\n\nVMs to be deleted:\n" + "\n".join(f"  - {name}" for name in vm_names) + "\n\nThis operation will permanently delete all specified VMs and all their data!\nThis operation cannot be undone!\n\nTo proceed, call this function again with confirm=True"
    
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # Get all VMs to resolve names to IDs
        response = client.get("vcenter/vm")
        vms = response.get("value", [])
        
        vm_names = [name.strip() for name in vm_list.split(',')]
        results = []
        
        for vm_name in vm_names:
            vm_id = None
            for vm in vms:
                if vm.get("name", "").lower() == vm_name.lower():
                    vm_id = vm.get("vm")
                    break
            
            if not vm_id:
                results.append(f"❌ {vm_name}: VM not found")
                continue
            
            try:
                client.delete(f"vcenter/vm/{vm_id}")
                results.append(f"✅ {vm_name}: Deleted successfully")
            except Exception as e:
                results.append(f"❌ {vm_name}: Error - {str(e)}")
        
        result = f"Bulk Delete Operation Results:\n\n"
        for res in results:
            result += f"{res}\n"
        
        return result.strip()
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, "bulk delete operation")
    finally:
        client.close()


@mcp.tool()
def force_power_off_vm(vm_id: str, confirm: bool = False, hostname: str = None) -> str:
    """Force power off a virtual machine (equivalent to pulling the power cord). REQUIRES CONFIRMATION.

    Args:
        vm_id: Virtual machine ID or name
        confirm: Must be True to proceed with force power off
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
    """
    if not confirm:
        return f"⚠️  DESTRUCTIVE OPERATION: Force Power Off VM {vm_id}\n\nThis operation will immediately power off the VM without graceful shutdown!\nThis is equivalent to pulling the power cord and may cause data loss!\n\nTo proceed, call this function again with confirm=True"
    
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"
    
    client = VSphereClient(hostname)
    try:
        # If vm_id doesn't start with 'vm-', assume it's a name and look up the ID
        if not vm_id.startswith("vm-"):
            vms_response = client.get("vcenter/vm")
            vms = vms_response.get("value", [])
            
            vm_id_found = None
            for vm in vms:
                if vm.get("name", "").lower() == vm_id.lower():
                    vm_id_found = vm.get("vm")
                    break
            
            if not vm_id_found:
                return f"Virtual machine '{vm_id}' not found by name"
            vm_id = vm_id_found
        
        # Force power off
        client.post(f"vcenter/vm/{vm_id}/power/stop")
        return f"⚠️  VM {vm_id} force powered off (equivalent to pulling power cord)"
        
    except (ConnectionError, ValueError, KeyError) as e:
        return _handle_error(e, f"force powering off VM {vm_id}")
    finally:
        client.close()


# ── Performance Metrics Tools ──────────────────────────────────


@mcp.tool()
def get_vm_metrics(vm_id: str, hostname: str = None, interval_id: int = 20, max_sample: int = 10) -> str:
    """Get real-time performance metrics for a VM via pyVmomi PerformanceManager.

    Args:
        vm_id: Virtual machine ID (vm-N) or name
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
        interval_id: Performance interval (20=realtime last ~30min, 300=5min historical)
        max_sample: Maximum number of samples to retrieve (default 10)

    Note: VMware Tools required for guest-level metrics. Powered-off VMs return no realtime data.
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"

    client = PyVmomiClient(host=hostname)
    try:
        # Resolve VM name to MoRef
        vm_ref = None
        if vm_id.startswith("vm-"):
            # Search through all VMs to find matching _moId
            view = client.get_container_view(vim.VirtualMachine, container=client.content.rootFolder, recursive=True)
            try:
                for vm in view.view:
                    if vm._moId == vm_id:
                        vm_ref = vm
                        break
            finally:
                view.Destroy()

            if not vm_ref:
                return f"Virtual machine '{vm_id}' not found"
        else:
            # It's a name
            vm_ref = client.find_vm(vm_id)
            if not vm_ref:
                return f"Virtual machine '{vm_id}' not found"

        pm = client.content.perfManager

        # Build counter ID lookup by name
        counter_info = {}
        for counter in pm.perfCounter:
            group_key = counter.groupInfo.key
            name_key = counter.nameInfo.key
            rollup = counter.rollupType
            key = f"{group_key}.{name_key}.{rollup}"
            counter_info[key] = counter.key

        # Define metrics to retrieve
        metric_names = [
            "cpu.usage.average",
            "cpu.ready.summation",
            "mem.active.average",
            "mem.consumed.average",
            "disk.read.average",
            "disk.write.average",
            "disk.totalLatency.average",
            "net.received.average",
            "net.transmitted.average",
        ]

        metric_ids = []
        for metric_name in metric_names:
            if metric_name in counter_info:
                metric_ids.append(
                    vim.PerformanceManager.MetricId(counterId=counter_info[metric_name], instance="*")
                )

        if not metric_ids:
            return "No performance counters found"

        # Query performance stats
        spec = vim.PerformanceManager.QuerySpec(
            entity=vm_ref,
            metricId=metric_ids,
            intervalId=interval_id,
            maxSample=max_sample
        )

        samples = pm.QueryStats([spec])

        if not samples or not samples[0].value:
            return f"No performance data available for VM {vm_id} (VM may be powered off or interval not available)"

        result = f"Performance Metrics for VM {vm_id}:\n\n"

        for metric_series in samples[0].value:
            counter_id = metric_series.id.counterId
            instance = metric_series.id.instance or "*"

            # Reverse lookup counter name
            counter_name = "Unknown"
            for key, cid in counter_info.items():
                if cid == counter_id:
                    counter_name = key
                    break

            # Calculate average value
            if metric_series.value:
                avg_value = sum(metric_series.value) / len(metric_series.value)
                result += f"• {counter_name} [{instance}]: {avg_value:.2f}\n"

        return result.strip()

    except Exception as e:
        return f"Error getting VM metrics via pyVmomi: {e}"
    finally:
        client.close()


@mcp.tool()
def get_host_metrics(host_id: str, hostname: str = None, interval_id: int = 20, max_sample: int = 10) -> str:
    """Get real-time performance metrics for an ESXi host via pyVmomi PerformanceManager.

    Args:
        host_id: ESXi host ID (host-N) or IP/hostname
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment if not provided)
        interval_id: Performance interval (20=realtime last ~30min, 300=5min historical)
        max_sample: Maximum number of samples to retrieve (default 10)
    """
    if hostname is None:
        hostname = os.environ.get('VCENTER_HOST')
        if not hostname:
            return "Error: No hostname provided and VCENTER_HOST not set in environment"

    client = PyVmomiClient(host=hostname)
    try:
        # Resolve host to MoRef
        host_ref = None
        view = client.get_container_view(vim.HostSystem, container=client.content.rootFolder, recursive=True)
        try:
            for host in view.view:
                # Match by _moId or by name (IP/hostname)
                if host._moId == host_id or host.name == host_id:
                    host_ref = host
                    break
        finally:
            view.Destroy()

        if not host_ref:
            return f"ESXi host '{host_id}' not found"

        pm = client.content.perfManager

        # Build counter ID lookup by name
        counter_info = {}
        for counter in pm.perfCounter:
            group_key = counter.groupInfo.key
            name_key = counter.nameInfo.key
            rollup = counter.rollupType
            key = f"{group_key}.{name_key}.{rollup}"
            counter_info[key] = counter.key

        # Define metrics to retrieve for hosts
        metric_names = [
            "cpu.usage.average",
            "cpu.ready.summation",
            "mem.active.average",
            "mem.consumed.average",
            "disk.read.average",
            "disk.write.average",
            "disk.totalLatency.average",
            "net.received.average",
            "net.transmitted.average",
        ]

        metric_ids = []
        for metric_name in metric_names:
            if metric_name in counter_info:
                metric_ids.append(
                    vim.PerformanceManager.MetricId(counterId=counter_info[metric_name], instance="*")
                )

        if not metric_ids:
            return "No performance counters found"

        # Query performance stats
        spec = vim.PerformanceManager.QuerySpec(
            entity=host_ref,
            metricId=metric_ids,
            intervalId=interval_id,
            maxSample=max_sample
        )

        samples = pm.QueryStats([spec])

        if not samples or not samples[0].value:
            return f"No performance data available for host {host_id}"

        result = f"Performance Metrics for Host {host_id} ({host_ref.name}):\n\n"

        for metric_series in samples[0].value:
            counter_id = metric_series.id.counterId
            instance = metric_series.id.instance or "*"

            # Reverse lookup counter name
            counter_name = "Unknown"
            for key, cid in counter_info.items():
                if cid == counter_id:
                    counter_name = key
                    break

            # Calculate average value
            if metric_series.value:
                avg_value = sum(metric_series.value) / len(metric_series.value)
                result += f"• {counter_name} [{instance}]: {avg_value:.2f}\n"

        return result.strip()

    except Exception as e:
        return f"Error getting host metrics via pyVmomi: {e}"
    finally:
        client.close()


# ── pyVmomi-based Advanced Tools ──────────────────────────────────


@mcp.tool()
def list_datacenters_pyvmomi(hostname: str = None) -> str:
    """List all datacenters using pyVmomi (direct SOAP connection).

    Args:
        hostname: vSphere hostname (optional, uses VCENTER_HOST from environment)
    """
    client = PyVmomiClient(host=hostname)
    try:
        dcs = client.content.rootFolder.childEntity
        dc_list = [dc for dc in dcs if hasattr(dc, "hostFolder")]
        if not dc_list:
            return "No datacenters found."
        result = f"Found {len(dc_list)} datacenter(s):\n\n"
        for dc in dc_list:
            result += f"  • {dc.name}\n"
        return result.strip()
    except Exception as e:
        return f"Error listing datacenters via pyVmomi: {e}"
    finally:
        client.close()


@mcp.tool()
def list_clusters_pyvmomi(datacenter: str = None, hostname: str = None) -> str:
    """List all clusters in a datacenter using pyVmomi.

    Args:
        datacenter: Datacenter name (required). Use list_datacenters_pyvmomi first.
        hostname: vSphere hostname (optional)
    """
    if not datacenter:
        return "Error: datacenter name is required."

    client = PyVmomiClient(host=hostname)
    try:
        dc = client.find_datacenter(datacenter)
        if dc is None:
            return f"Datacenter '{datacenter}' not found."

        view = client.get_container_view(vim.ClusterComputeResource, container=dc.hostFolder)
        try:
            clusters = list(view.view)
        finally:
            view.Destroy()

        if not clusters:
            return f"No clusters found in datacenter '{datacenter}'."

        result = f"Clusters in '{datacenter}' ({len(clusters)}):\n\n"
        for cluster in clusters:
            result += f"  • {cluster.name}\n"
        return result.strip()
    except Exception as e:
        return f"Error listing clusters via pyVmomi: {e}"
    finally:
        client.close()


@mcp.tool()
def find_template_pyvmomi(name: str, datacenter: str = None, hostname: str = None) -> str:
    """Find a VM template by name using pyVmomi PropertyCollector.

    Args:
        name: Template name (full or partial, case-insensitive)
        datacenter: Datacenter name to scope search (optional)
        hostname: vSphere hostname (optional)
    """
    client = PyVmomiClient(host=hostname)
    try:
        dc = client.find_datacenter(datacenter) if datacenter else None
        root = dc.hostFolder if dc else client.content.rootFolder

        view = client.get_container_view(vim.VirtualMachine, container=root)
        try:
            collector = client.content.propertyCollector
            traversal_spec = vmodl.query.PropertyCollector.TraversalSpec(
                name="traverse", type=vim.view.ContainerView, path="view", skip=False
            )
            obj_spec = vmodl.query.PropertyCollector.ObjectSpec(
                obj=view, skip=True, selectSet=[traversal_spec]
            )
            prop_spec = vmodl.query.PropertyCollector.PropertySpec(
                type=vim.VirtualMachine,
                pathSet=["name", "config.template", "runtime.powerState"],
                all=False,
            )
            filter_spec = vmodl.query.PropertyCollector.FilterSpec(
                objectSet=[obj_spec], propSet=[prop_spec]
            )
            results = collector.RetrieveProperties([filter_spec])

            matches = []
            for obj_content in results:
                props = {p.name: p.val for p in obj_content.propSet}
                vm_name = props.get("name", "")
                is_template = props.get("config.template")
                if is_template and name.lower() in vm_name.lower():
                    matches.append((vm_name, is_template))

            if not matches:
                return f"No template matching '{name}' found."

            result = f"Templates matching '{name}':\n\n"
            for vm_name, is_tpl in matches:
                result += f"  • {vm_name}"
                if datacenter:
                    result += f" (DC: {datacenter})"
                result += "\n"
            return result.strip()
        finally:
            view.Destroy()
    except Exception as e:
        return f"Error finding template: {e}"
    finally:
        client.close()


@mcp.tool()
def clone_vm(
    template_name: str,
    vm_name: str,
    cluster_name: str,
    datastore_name: str = "",
    cpu_count: int = 0,
    memory_gb: int = 0,
    target_datacenter: str = "",
    network_name: str = "",
    confirm: bool = False,
    hostname: str = None,
) -> str:
    """Clone a VM from a template using pyVmomi.

    Supports cross-datacenter cloning with proper network binding.
    Relies on the latest pyVmomi (9.x) for full API support.

    Args:
        template_name: Source template VM name
        vm_name: Name for the new cloned VM
        cluster_name: Target cluster name
        datastore_name: Target datastore name (optional; if omitted, uses template's datastore)
        cpu_count: CPU count for new VM (0 = use template default)
        memory_gb: Memory in GB for new VM (0 = use template default)
        target_datacenter: Datacenter name containing target cluster
                           (required for cross-DC cloning)
        network_name: Network/portgroup name to attach (optional)
        confirm: Must be True to proceed
        hostname: vSphere hostname (optional)
    """
    if not confirm:
        return (
            f"⚠️  CLONE OPERATION: Clone VM from template\n\n"
            f"  Template: {template_name}\n"
            f"  New VM: {vm_name}\n"
            f"  Target Cluster: {cluster_name}\n"
            f"  Target Datacenter: {target_datacenter or '(auto-detect)'}\n"
            f"  Datastore: {datastore_name or '(template default)'}\n"
            f"  CPU: {cpu_count or '(template default)'}\n"
            f"  Memory: {f'{memory_gb} GB' if memory_gb else '(template default)'}\n"
            f"  Network: {network_name or '(template default)'}\n\n"
            f"To proceed, call again with confirm=True."
        )

    client = PyVmomiClient(host=hostname)
    try:
        si = client.si
        content = client.content

        # ── Step 1: Locate template ──
        template_vm = client.find_vm(template_name)
        if template_vm is None:
            return f"Template '{template_name}' not found."

        # Verify it is a template
        if not template_vm.config.template:
            return f"Error: '{template_name}' is a VM, not a template."

        # Remember which DC the template is in
        source_dc = None
        obj = template_vm.parent
        while obj:
            if hasattr(obj, "hostFolder"):
                source_dc = obj
                break
            obj = obj.parent

        # ── Step 2: Locate target datacenter & cluster ──
        if target_datacenter:
            tg_dc = client.find_datacenter(target_datacenter)
            if tg_dc is None:
                return f"Target datacenter '{target_datacenter}' not found."
        else:
            tg_dc = source_dc

        tg_cluster = client.find_cluster(cluster_name, tg_dc)
        if tg_cluster is None:
            return f"Cluster '{cluster_name}' not found in datacenter '{tg_dc.name}'."

        # ── Step 3: Datastore ──
        if datastore_name:
            tg_datastore = client.find_datastore(datastore_name, tg_dc)
            if tg_datastore is None:
                return f"Datastore '{datastore_name}' not found in datacenter '{tg_dc.name}'."
        else:
            # Use the first datastore of the template (or cluster default)
            if template_vm.datastore:
                tg_datastore = template_vm.datastore[0]
            else:
                return "No datastore found on template and none specified."

        # ── Step 4: Resource pool ──
        resource_pool = tg_cluster.resourcePool

        # ── Step 5: Target folder ──
        # Strategy: find any existing VM in the target DC and use its parent folder
        target_folder = client.get_any_vm_folder(tg_dc)

        # ── Step 6: Build RelocateSpec ──
        relocate_spec = vim.vm.RelocateSpec()
        relocate_spec.pool = resource_pool
        relocate_spec.datastore = tg_datastore

        # Network binding
        if network_name:
            tg_network = client.find_network(network_name, tg_dc)
            if tg_network is None:
                return f"Network '{network_name}' not found in datacenter '{tg_dc.name}'."
            # Map all template NICs to the target network
            device_changes = []
            for device in template_vm.config.hardware.device:
                if isinstance(device, vim.vm.device.VirtualEthernetCard):
                    backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
                    backing.deviceName = network_name
                    backing.network = tg_network
                    nic_spec = vim.vm.device.VirtualDeviceSpec()
                    nic_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
                    nic_spec.device = device
                    nic_spec.device.backing = backing
                    device_changes.append(nic_spec)
            relocate_spec.deviceChange = device_changes if device_changes else None

        # ── Step 7: Build CloneSpec ──
        clone_spec = vim.vm.CloneSpec()
        clone_spec.location = relocate_spec
        clone_spec.powerOn = False
        clone_spec.template = False

        # Customization (CPU/Memory)
        if cpu_count or memory_gb:
            config_spec = vim.vm.ConfigSpec()
            if cpu_count:
                config_spec.numCPUs = cpu_count
            if memory_gb:
                config_spec.memoryMB = memory_gb * 1024
            clone_spec.config = config_spec

        # ── Step 8: Execute clone ──
        task = template_vm.CloneVM_Task(
            folder=target_folder,
            name=vm_name,
            spec=clone_spec,
        )

        import time
        from pyVmomi import vim as vim_mod

        # Wait for task (poll with timeout)
        timeout = 600
        interval = 3
        elapsed = 0
        task_info = task.info
        while task_info.state in (vim.TaskInfo.State.queued, vim.TaskInfo.State.running):
            if elapsed >= timeout:
                return f"Clone task timed out after {timeout}s. Task: {task_info.name} (state={task_info.state})"
            time.sleep(interval)
            elapsed += interval
            task_info = task.info

        if task_info.state == vim.TaskInfo.State.success:
            return (
                f"✅ VM clone completed successfully!\n\n"
                f"  Template: {template_name}\n"
                f"  New VM: {vm_name}\n"
                f"  Cluster: {cluster_name}\n"
                f"  Datacenter: {tg_dc.name}\n"
                f"  Datastore: {tg_datastore.name}\n"
                f"  CPU: {cpu_count or '(template default)'}\n"
                f"  Memory: {f'{memory_gb} GB' if memory_gb else '(template default)'}\n"
                f"  Network: {network_name or '(template default)'}\n"
            )
        else:
            error = task_info.error
            return (
                f"❌ Clone task failed: state={task_info.state}\n"
                f"  Error: {error.msg if error else 'Unknown error'}\n"
                f"  Task: {task_info.name}"
            )

    except Exception as e:
        return f"Error during clone: {e}"
    finally:
        client.close()


@mcp.tool()
def get_vm_networks_pyvmomi(vm_name: str, hostname: str = None) -> str:
    """Get network adapter details of a VM using pyVmomi.

    Args:
        vm_name: VM name
        hostname: vSphere hostname (optional)
    """
    client = PyVmomiClient(host=hostname)
    try:
        vm = client.find_vm(vm_name)
        if vm is None:
            return f"VM '{vm_name}' not found."

        result = f"Network adapters for '{vm_name}':\n\n"
        nics_found = False
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                nics_found = True
                backing = device.backing
                network_name = "Unknown"
                if hasattr(backing, "deviceName"):
                    network_name = backing.deviceName
                elif hasattr(backing, "network") and backing.network:
                    network_name = backing.network.name
                result += f"  • {device.deviceInfo.label}\n"
                result += f"    MAC: {device.macAddress}\n"
                result += f"    Network: {network_name}\n"
                result += f"    Connected: {device.connectable.connected}\n\n"

        if not nics_found:
            result += "  No network adapters found."
        return result.strip()
    except Exception as e:
        return f"Error getting network info: {e}"
    finally:
        client.close()


@mcp.tool()
def get_vm_ip(vm_name: str, hostname: str = None) -> str:
    """Get guest IP address(es) of a VM via pyVmomi (vm.guest — reported by VMware Tools).

    Returns the primary IP, per-NIC IP details, and VMware Tools status.
    Requires a powered-on VM with VMware Tools running in the guest; otherwise
    returns an informative message instead of an IP.

    Args:
        vm_name: VM name
        hostname: vSphere hostname (optional)
    """
    client = PyVmomiClient(host=hostname)
    try:
        vm = client.find_vm(vm_name)
        if vm is None:
            return f"VM '{vm_name}' not found."

        summary = vm.summary
        power_state = str(summary.runtime.powerState)
        if power_state != "poweredOn":
            return (
                f"VM '{vm_name}' is {power_state} — guest IP is only available "
                "for powered-on VMs."
            )

        guest = vm.guest
        tools_status = "unknown"
        if guest is not None:
            tools_status = str(
                getattr(guest, "toolsRunningStatus", None)
                or getattr(guest, "toolsStatus", None)
                or "unknown"
            )

        if guest is None or tools_status != "guestToolsRunning":
            return (
                f"VMware Tools not running on '{vm_name}' (status: {tools_status}) — "
                "guest IP unavailable. Install/start VMware Tools in the guest OS."
            )

        primary_ip = summary.guest.ipAddress if summary.guest else None
        guest_hostname = getattr(guest, "hostName", None) or "N/A"
        tools_version = getattr(guest, "toolsVersion", None) or "N/A"

        result = f"Guest IP info for '{vm_name}':\n"
        result += f"  Primary IP: {primary_ip or 'N/A'}\n"
        result += f"  Guest hostname: {guest_hostname}\n"
        result += f"  VMware Tools: {tools_status} (version {tools_version})\n"

        # Per-NIC details from guest (vim.vm.GuestInfo.NicInfo)
        nics = getattr(guest, "net", None) or []
        if nics:
            result += "\nNetwork adapters (from guest):\n"
            for nic in nics:
                network = getattr(nic, "network", None) or "Unknown"
                mac = getattr(nic, "macAddress", None) or "N/A"
                connected = getattr(nic, "connected", None)
                result += f"  • {network}  [{mac}] connected={connected}\n"

                ips = []
                ip_config = getattr(nic, "ipConfig", None)
                if ip_config is not None:
                    for ipa in getattr(ip_config, "ipAddress", []) or []:
                        addr = getattr(ipa, "ipAddress", None)
                        prefix = getattr(ipa, "prefixLength", None)
                        if addr:
                            ips.append(f"{addr}/{prefix}" if prefix is not None else addr)
                if not ips:
                    for addr in getattr(nic, "ipAddress", []) or []:
                        ips.append(addr)

                if ips:
                    for addr in ips:
                        result += f"      IP: {addr}\n"
                else:
                    result += "      IP: (none reported)\n"
        elif primary_ip is None:
            result += f"\nNo guest IP reported by VMware Tools for '{vm_name}'."

        return result.rstrip()
    except Exception as e:
        return f"Error getting VM IP info: {e}"
    finally:
        client.close()


@mcp.tool()
def list_vm_ips(hostname: str = None) -> str:
    """List primary guest IP for all VMs in one query (pyVmomi PropertyCollector).

    Reads vm.summary.guest.ipAddress for every non-template VM. Powered-off VMs
    and VMs without running VMware Tools show '—'. Read-only, safe for inventory.

    Args:
        hostname: vSphere hostname (optional)
    """
    client = PyVmomiClient(host=hostname)
    try:
        view_ref = client.get_container_view(vim.VirtualMachine)
        rows = []
        try:
            collector = client.content.propertyCollector
            traversal = vmodl.query.PropertyCollector.TraversalSpec(
                name="traverse",
                type=vim.view.ContainerView,
                path="view",
                skip=False,
            )
            obj_spec = vmodl.query.PropertyCollector.ObjectSpec(
                obj=view_ref,
                skip=True,
                selectSet=[traversal],
            )
            prop_spec = vmodl.query.PropertyCollector.PropertySpec(
                type=vim.VirtualMachine,
                pathSet=[
                    "name",
                    "runtime.powerState",
                    "guest.ipAddress",
                    "config.template",
                ],
                all=False,
            )
            filter_spec = vmodl.query.PropertyCollector.FilterSpec(
                objectSet=[obj_spec],
                propSet=[prop_spec],
            )
            for obj in collector.RetrieveProperties([filter_spec]):
                props = {p.name: p.val for p in obj.propSet}
                if props.get("config.template"):
                    continue
                name = props.get("name", "Unknown")
                power = str(props.get("runtime.powerState", "unknown"))
                ip = props.get("guest.ipAddress") or None
                rows.append((name, ip, power))
        finally:
            view_ref.Destroy()

        if not rows:
            return "No virtual machines found."

        rows.sort(key=lambda r: r[0].lower())
        with_ip = sum(1 for _, ip, _ in rows if ip)

        result = "VM guest IPs (powered-on VMs with VMware Tools):\n\n"
        for name, ip, power in rows:
            if ip:
                result += f"  • {name}   {ip}   {power}\n"
            elif power == "poweredOn":
                result += f"  • {name}   — (no IP/Tools)   {power}\n"
            else:
                result += f"  • {name}   —   {power}\n"

        result += f"\nTotal: {len(rows)} VMs, {with_ip} with guest IP."
        return result
    except Exception as e:
        return f"Error listing VM IPs: {e}"
    finally:
        client.close()


def main() -> None:
    """Main entry point for the MCP server."""
    import os
    from dotenv import load_dotenv
    
    # Load environment variables
    load_dotenv()
    
    # Configure FastMCP settings for streamable HTTP transport
    mcp.settings.host = os.getenv("SERVER_HOST", "0.0.0.0")
    mcp.settings.port = int(os.getenv("SERVER_PORT", "8000"))
    mcp.settings.stateless_http = False
    mcp.settings.json_response = True  # Return JSON instead of SSE for simpler parsing
    
    # Run with streamable HTTP transport
    mcp.run(transport="streamable-http")


# Export the Starlette/FastAPI app for testing and external use
app = mcp.streamable_http_app()


if __name__ == "__main__":
    main()
