"""pyVmomi-based vSphere client for advanced operations (clone, network binding, etc.)."""

import os
import ssl
from typing import Optional, List, Dict, Any

from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl, SoapStubAdapter


class PyVmomiClient:
    """Context-managed pyVmomi connection to vCenter."""

    def __init__(
        self,
        host: str = None,
        user: str = None,
        password: str = None,
        port: int = 443,
    ):
        self.host = host or os.environ.get("VCENTER_HOST")
        self.user = user or os.environ.get("VCENTER_USER")
        self.password = password or os.environ.get("VCENTER_PASSWORD")
        self.port = int(os.environ.get("VCENTER_PORT", port))
        self._si = None

    @property
    def si(self):
        if self._si is None:
            self.connect()
        return self._si

    def connect(self):
        """Establish connection. SSL verified via REQUESTS_CA_BUNDLE/VCENTER_CA_BUNDLE if set, insecure fallback if INSECURE=true."""
        ctx = ssl.create_default_context()

        # Check for CA bundle in environment
        ca_bundle = (
            os.environ.get("REQUESTS_CA_BUNDLE")
            or os.environ.get("VCENTER_CA_BUNDLE")
            or os.environ.get("SSL_CERT_FILE")
        )
        insecure = os.environ.get("INSECURE", "false").lower() in ("true", "1", "t")

        if ca_bundle and os.path.exists(ca_bundle) and not insecure:
            # Use CA bundle for verification
            ctx.load_verify_locations(ca_bundle)
            # ctx.check_hostname remains True, verify_mode remains CERT_REQUIRED (defaults)
        else:
            # Insecure fallback (backward compatibility)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        self._si = SmartConnect(
            host=self.host,
            user=self.user,
            pwd=self.password,
            port=self.port,
            sslContext=ctx,
        )
        return self._si

    def disconnect(self):
        if self._si:
            Disconnect(self._si)
            self._si = None

    def close(self):
        self.disconnect()

    # ── Container helpers ────────────────────────────────────────

    @property
    def content(self) -> vim.ServiceInstanceContent:
        return self.si.RetrieveContent()

    def get_container_view(self, obj_type, container=None, recursive=True) -> vim.view.ContainerView:
        """Create a ContainerView filtered by obj_type."""
        if container is None:
            container = self.content.rootFolder
        return self.content.viewManager.CreateContainerView(
            container=container,
            type=[obj_type],
            recursive=recursive,
        )

    # ── Entity lookups ───────────────────────────────────────────

    def find_datacenter(self, name: str) -> Optional[vim.Datacenter]:
        """Find a datacenter by name."""
        for dc in self.content.rootFolder.childEntity:
            if isinstance(dc, vim.Datacenter) and dc.name == name:
                return dc
        return None

    def find_vm(self, name: str, datacenter: vim.Datacenter = None) -> Optional[vim.VirtualMachine]:
        """Find a VM/template by name, optionally scoped to a datacenter."""
        root = datacenter.hostFolder if datacenter else self.content.rootFolder
        # PropertyCollector approach – reliable with all pyVmomi versions
        view_ref = self.get_container_view(vim.VirtualMachine, container=root)
        try:
            # Retrieve name property
            collector = self.content.propertyCollector
            traversal_spec = vmodl.query.PropertyCollector.TraversalSpec(
                name="traverse",
                type=vim.view.ContainerView,
                path="view",
                skip=False,
            )
            obj_spec = vmodl.query.PropertyCollector.ObjectSpec(
                obj=view_ref,
                skip=True,
                selectSet=[traversal_spec],
            )
            prop_spec = vmodl.query.PropertyCollector.PropertySpec(
                type=vim.VirtualMachine,
                pathSet=["name", "config.template"],
                all=False,
            )
            filter_spec = vmodl.query.PropertyCollector.FilterSpec(
                objectSet=[obj_spec],
                propSet=[prop_spec],
            )
            result = collector.RetrieveProperties([filter_spec])
            for obj_content in result:
                props = {p.name: p.val for p in obj_content.propSet}
                if props.get("name") == name:
                    return obj_content.obj
        finally:
            view_ref.Destroy()
        return None

    def find_cluster(self, name: str, datacenter: vim.Datacenter = None) -> Optional[vim.ClusterComputeResource]:
        """Find a cluster by name."""
        root = datacenter.hostFolder if datacenter else self.content.rootFolder
        view_ref = self.get_container_view(vim.ClusterComputeResource, container=root)
        try:
            collector = self.content.propertyCollector
            traversal_spec = vmodl.query.PropertyCollector.TraversalSpec(
                name="traverse",
                type=vim.view.ContainerView,
                path="view",
                skip=False,
            )
            obj_spec = vmodl.query.PropertyCollector.ObjectSpec(
                obj=view_ref,
                skip=True,
                selectSet=[traversal_spec],
            )
            prop_spec = vmodl.query.PropertyCollector.PropertySpec(
                type=vim.ClusterComputeResource,
                pathSet=["name"],
                all=False,
            )
            filter_spec = vmodl.query.PropertyCollector.FilterSpec(
                objectSet=[obj_spec],
                propSet=[prop_spec],
            )
            result = collector.RetrieveProperties([filter_spec])
            for obj_content in result:
                props = {p.name: p.val for p in obj_content.propSet}
                if props.get("name") == name:
                    return obj_content.obj
        finally:
            view_ref.Destroy()
        return None

    def find_datastore(self, name: str, datacenter: vim.Datacenter = None) -> Optional[vim.Datastore]:
        """Find a datastore by name."""
        root = datacenter.datastoreFolder if datacenter else self.content.rootFolder
        view_ref = self.get_container_view(vim.Datastore, container=root)
        try:
            collector = self.content.propertyCollector
            traversal_spec = vmodl.query.PropertyCollector.TraversalSpec(
                name="traverse",
                type=vim.view.ContainerView,
                path="view",
                skip=False,
            )
            obj_spec = vmodl.query.PropertyCollector.ObjectSpec(
                obj=view_ref,
                skip=True,
                selectSet=[traversal_spec],
            )
            prop_spec = vmodl.query.PropertyCollector.PropertySpec(
                type=vim.Datastore,
                pathSet=["name"],
                all=False,
            )
            filter_spec = vmodl.query.PropertyCollector.FilterSpec(
                objectSet=[obj_spec],
                propSet=[prop_spec],
            )
            result = collector.RetrieveProperties([filter_spec])
            for obj_content in result:
                props = {p.name: p.val for p in obj_content.propSet}
                if props.get("name") == name:
                    return obj_content.obj
        finally:
            view_ref.Destroy()
        return None

    def find_network(self, name: str, datacenter: vim.Datacenter = None) -> Optional[vim.Network]:
        """Find a network by name."""
        root = datacenter.networkFolder if datacenter else self.content.rootFolder
        view_ref = self.get_container_view(vim.Network, container=root)
        try:
            collector = self.content.propertyCollector
            traversal_spec = vmodl.query.PropertyCollector.TraversalSpec(
                name="traverse",
                type=vim.view.ContainerView,
                path="view",
                skip=False,
            )
            obj_spec = vmodl.query.PropertyCollector.ObjectSpec(
                obj=view_ref,
                skip=True,
                selectSet=[traversal_spec],
            )
            prop_spec = vmodl.query.PropertyCollector.PropertySpec(
                type=vim.Network,
                pathSet=["name"],
                all=False,
            )
            filter_spec = vmodl.query.PropertyCollector.FilterSpec(
                objectSet=[obj_spec],
                propSet=[prop_spec],
            )
            result = collector.RetrieveProperties([filter_spec])
            for obj_content in result:
                props = {p.name: p.val for p in obj_content.propSet}
                if props.get("name") == name:
                    return obj_content.obj
        finally:
            view_ref.Destroy()
        return None

    def get_vm_parent_folder(self, vm: vim.VirtualMachine) -> Optional[vim.Folder]:
        """Get the parent folder of a VM (used as clone target folder)."""
        # Walk parent chain to find the VM folder
        current = vm.parent
        while current is not None:
            if isinstance(current, vim.Folder):
                return current
            current = current.parent
        return None

    def get_target_folder_from_existing_vm(
        self, vm_name: str, datacenter: vim.Datacenter
    ) -> Optional[vim.Folder]:
        """Reverse-engineer clone target folder from an existing VM in the target DC."""
        vm = self.find_vm(vm_name, datacenter)
        if vm is None:
            return None
        return self.get_vm_parent_folder(vm)

    def get_any_vm_folder(self, datacenter: vim.Datacenter) -> Optional[vim.Folder]:
        """Find any VM folder in a datacenter, falling back to vmFolder root."""
        vm_folder = datacenter.vmFolder
        # Try to find a subfolder with VMs
        folders = [vm_folder]
        for entity in vm_folder.childEntity:
            if isinstance(entity, vim.Folder):
                folders.append(entity)
            elif isinstance(entity, vim.VirtualMachine):
                # There's a VM directly in vmFolder; use it directly
                return vm_folder
        return vm_folder  # Default fallback

    # ── vSAN helpers (read-only) ─────────────────────────────────

    def get_vsan_vc_mos(self) -> Dict[str, Any]:
        """Build vSAN vCenter-side Managed Objects on the /vsanHealth endpoint.

        Reuses the existing vCenter session cookie — no re-authentication.
        All returned MOs are used strictly for read-only Query* calls.

        Returns dict keyed by MO name (see VSAN_API_REFERENCE.md §2.1).
        """
        stub = self.si._stub
        host = stub.host.split(":")[0]
        port = int(stub.host.split(":")[-1])

        # The real SSL context lives in stub.schemeArgs['context'].
        # (stub.sslcontext / stub.sslContext are unused legacy attrs — None here.)
        ctx = (getattr(stub, "schemeArgs", None) or {}).get("context")

        vsan_stub = SoapStubAdapter(
            host=host,
            port=port,
            path="/vsanHealth",
            version="vim.version.version11",
            sslContext=ctx,
        )
        vsan_stub.cookie = stub.cookie  # key: reuse the vCenter session

        return {
            "vsan-cluster-health-system":
                vim.cluster.VsanVcClusterHealthSystem(
                    "vsan-cluster-health-system", vsan_stub),
            "vsan-disk-management-system":
                vim.cluster.VsanVcDiskManagementSystem(
                    "vsan-disk-management-system", vsan_stub),
            "vsan-performance-manager":
                vim.cluster.VsanPerformanceManager(
                    "vsan-performance-manager", vsan_stub),
            "vsan-cluster-space-report-system":
                vim.cluster.VsanSpaceReportSystem(
                    "vsan-cluster-space-report-system", vsan_stub),
            "vsan-cluster-object-system":
                vim.cluster.VsanObjectSystem(
                    "vsan-cluster-object-system", vsan_stub),
            "vsan-vc-capability-system":
                vim.cluster.VsanCapabilitySystem(
                    "vsan-vc-capability-system", vsan_stub),
            "vsan-cluster-ioinsight-manager":
                vim.cluster.VsanIoInsightManager(
                    "vsan-cluster-ioinsight-manager", vsan_stub),
        }

    def find_vsan_cluster(
        self, name: str, datacenter: vim.Datacenter = None
    ) -> Optional[vim.ClusterComputeResource]:
        """Find a cluster by name and verify vSAN is enabled on it.

        Returns the ClusterComputeResource if found AND vSAN-enabled,
        otherwise None. Read-only — performs no mutation.
        """
        cluster = self.find_cluster(name, datacenter)
        if cluster is None:
            return None
        if self.is_vsan_enabled(cluster):
            return cluster
        return None

    def is_vsan_enabled(self, cluster: vim.ClusterComputeResource) -> bool:
        """Check whether vSAN is enabled on a cluster (read-only).

        Primary signal: cluster.config.vsanConfigInfo.enabled.
        Fallback: any mounted datastore is a vSAN datastore.
        """
        try:
            cfg = getattr(cluster, "config", None)
            vsan_cfg = getattr(cfg, "vsanConfigInfo", None) if cfg else None
            if vsan_cfg is not None:
                return bool(getattr(vsan_cfg, "enabled", False))
        except Exception:
            pass

        # Fallback: a vSAN datastore mounted on any cluster host
        try:
            host_moids = {h._moId for h in (cluster.host or [])}
            if not host_moids:
                return False
            dc = cluster
            while dc and not isinstance(dc, vim.Datacenter):
                dc = dc.parent
            view = self.get_container_view(
                vim.Datastore, container=dc if dc else self.content.rootFolder
            )
            try:
                for d in view.view:
                    info = d.info
                    if info is None or not isinstance(info, vim.host.VsanDatastoreInfo):
                        continue
                    for m in (d.host or []):
                        if m.key and m.key._moId in host_moids:
                            return True
            finally:
                view.Destroy()
        except Exception:
            pass
        return False
