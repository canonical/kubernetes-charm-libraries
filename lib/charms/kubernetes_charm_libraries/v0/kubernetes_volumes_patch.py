# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Library used to leverage the Volumes Kubernetes in charms.

- On bound event (e.g. self.on.volumes_config_changed which is originated
from K8sVolumePatchChangedEvent), it will:
  - Patch the StatefulSet with the required volumes
  - Patch the Pod with the required volume mounts and resources limits when necessary

## Usage

```python

from charms.kubernetes_charm_libraries.v0.volumes import (
    KubernetesHugepagesPatchCharmLib,
    RequestedHugepages,
)


class K8sVolumePatchChangedEvent(EventBase):
    def __init__(self, handle: Handle):
        super().__init__(handle)


class K8sVolumePatchChangedCharmEvents(CharmEvents):
    volumes_config_changed = EventSource(K8sVolumePatchChangedEvent)


class YourCharm(CharmBase):

    on = K8sVolumePatchChangedCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self._kubernetes_volumes_patch = KubernetesHugepagesPatchCharmLib(
            charm=self,
            container_name=self._container_name,
            volumes_request_func=self._volumes_request_func_from_config,
            refresh_event=self.on.volumes_config_changed,
        )

    def _volumes_request_func_from_config(self) -> list[RequestedHugepages]:
        return [
            RequestedHugepages(
                mount_path="/dev/hugepages",
                size="1Gi",
                limit="4Gi",
            )
        ]

"""
import logging
from dataclasses import dataclass
from typing import Callable, Iterable

from lightkube import Client
from lightkube.core.exceptions import ApiError
from lightkube.models.apps_v1 import StatefulSetSpec
from lightkube.models.core_v1 import (
    Container,
    EmptyDirVolumeSource,
    ResourceRequirements,
    Volume,
    VolumeMount,
)
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import Pod
from ops.charm import CharmBase
from ops.framework import BoundEvent, Object

logger = logging.getLogger(__name__)


@dataclass
class RequestedHugepages:
    """RequestedHugepages."""

    mount_path: str
    size: str = "1Gi"
    limit: str = "2Gi"


class KubernetesRequestedVolumesError(Exception):
    """KubernetesRequestedVolumesError."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class ContainerNotFoundError(ValueError):
    """Raised when a given container does not exist in the iterable of containers."""


class KubernetesClient:
    """Class containing all the Kubernetes specific calls."""

    def __init__(self, namespace: str):
        self.client = Client()
        self.namespace = namespace

    @classmethod
    def _get_container(cls, container_name: str, containers: Iterable[Container]) -> Container:
        """Find the container from the container list, assuming list is unique by name.

        Args:
            containers: Iterable of containers
            container_name: Container name

        Raises:
            ContainerNotFoundError, if the user-provided container name does not exist in the list.

        Returns:
            Container: An instance of :class:`Container` whose name matches the given name.
        """
        try:
            return next(iter(filter(lambda ctr: ctr.name == container_name, containers)))
        except StopIteration:
            raise ContainerNotFoundError(f"Container `{container_name}` not found")

    def pod_is_patched(
        self,
        pod_name: str,
        requested_volumemounts: Iterable[VolumeMount],
        requested_resources: ResourceRequirements,
        container_name: str,
    ) -> bool:
        """Returns whether pod contains the given volumes, mounts and resources.

        Args:
            pod_name: Pod name
            requested_volumemounts: Iterable of volumeMounts
            requested_resources: requested resources
            container_name: Container name

        Returns:
            bool: Whether pod contains the given volumes, mounts and resources.
        """
        try:
            pod = self.client.get(Pod, name=pod_name, namespace=self.namespace)
        except ApiError as e:
            if e.status.reason == "Unauthorized":
                logger.debug("kube-apiserver not ready yet")
            else:
                raise KubernetesRequestedVolumesError(f"Pod `{pod_name}` not found")
            return False
        pod_has_volumemounts = self._pod_contains_requested_volumemounts(
            requested_volumemounts=requested_volumemounts,
            containers=pod.spec.containers,  # type: ignore[attr-defined]
            container_name=container_name,
        )
        pod_has_resources = self._pod_resources_are_set(
            containers=pod.spec.containers,  # type: ignore[attr-defined]
            container_name=container_name,
            requested_resources=requested_resources,
        )
        return pod_has_volumemounts and pod_has_resources

    def statefulset_is_patched(
        self,
        statefulset_name: str,
        requested_volumes: Iterable[Volume],
    ) -> bool:
        """Returns whether the statefulset contains the given volumes.

        Args:
            statefulset_name: Statefulset name
            requested_volumes: Iterable of volumes

        Returns:
            bool: Whether the statefulset contains the given volumes.
        """
        try:
            statefulset = self.client.get(
                res=StatefulSet, name=statefulset_name, namespace=self.namespace
            )
        except ApiError as e:
            if e.status.reason == "Unauthorized":
                logger.debug("kube-apiserver not ready yet")
            else:
                raise KubernetesRequestedVolumesError(
                    f"Could not get statefulset {statefulset_name}"
                )
            return False
        return self._statefulset_contains_requested_volumes(
            statefulset_spec=statefulset.spec,  # type: ignore[attr-defined]
            requested_volumes=requested_volumes,
        )

    @staticmethod
    def _statefulset_contains_requested_volumes(
        statefulset_spec: StatefulSetSpec,
        requested_volumes: Iterable[Volume],
    ) -> bool:
        """Returns whether the StatefulSet contains the given volumes.

        Args:
            statefulset_spec: StatefulSet spec
            requested_volumes: Iterable of volumes

        Returns:
            bool: whether the StatefulSet contains the given volumes.
        """
        if not statefulset_spec.template.spec.volumes:
            return False
        return all(
            [
                requested_volume in statefulset_spec.template.spec.volumes
                for requested_volume in requested_volumes
            ]
        )

    def _pod_contains_requested_volumemounts(
        self,
        containers: Iterable[Container],
        container_name: str,
        requested_volumemounts: Iterable[VolumeMount],
    ) -> bool:
        """Returns whether container spec contains the given volumemounts.

        Args:
            containers: Iterable of Containers
            container_name: Container name
            requested_volumemounts: Iterable of volumeMounts that the container shall contain

        Returns:
            bool: whether container spec contains the given volumemounts.
        """
        container = self._get_container(container_name=container_name, containers=containers)
        return all(
            [
                requested_volumemount in container.volumeMounts
                for requested_volumemount in requested_volumemounts
            ]
        )

    def _pod_resources_are_set(
        self,
        containers: Iterable[Container],
        container_name: str,
        requested_resources: ResourceRequirements,
    ) -> bool:
        """Returns whether container spec contains the expected resources requests and limits.

        Args:
            containers: Iterable of Containers
            container_name: Container name
            requested_resources: resource requirements

        Returns:
            bool
        """
        container = self._get_container(container_name=container_name, containers=containers)
        if requested_resources.limits:
            for limit, value in requested_resources.limits.items():
                if not container.resources.limits:
                    return False
                if container.resources.limits.get(limit) != value:
                    return False
        if requested_resources.requests:
            for request, value in requested_resources.requests.items():
                if not container.resources.requests:
                    return False
                if container.resources.requests.get(request) != value:
                    return False
        return True

    def replace_statefulset(
        self,
        statefulset_name: str,
        requested_volumes: Iterable[Volume],
        requested_volumemounts: Iterable[VolumeMount],
        requested_resources: ResourceRequirements,
        container_name: str,
    ) -> None:
        """Updates a StatefulSet and a container in its spec.

         It replaces current volumes in the specified StatefulSet with the given ones.
         It replaces current volumeMounts and resource requirements in the specified container
         with the given ones.


        Args:
            statefulset_name: Statefulset name
            requested_volumes: Iterable of new volumes to be set in the StatefulSet
            requested_volumemounts: Iterable of new volumeMounts to be set in the given container
            requested_resources: new resource requirements to be set in the given container
            container_name: Container name
        """
        if not requested_volumes:
            logger.warning("No requested volumes were provided")
            return
        if not requested_volumemounts:
            logger.warning("No requested volumeMounts were provided")
            return
        try:
            statefulset = self.client.get(
                res=StatefulSet, name=statefulset_name, namespace=self.namespace
            )
        except ApiError:
            raise KubernetesRequestedVolumesError(f"Could not get statefulset {statefulset_name}")
        containers: Iterable[Container] = statefulset.spec.template.spec.containers  # type: ignore[attr-defined]  # noqa: E501
        container = self._get_container(container_name=container_name, containers=containers)
        container.volumeMounts = requested_volumemounts  # type: ignore[assignment]
        container.resources = requested_resources
        statefulset.spec.template.spec.volumes = requested_volumes  # type: ignore[attr-defined]
        try:
            logger.critical("aaaa")
            self.client.replace(obj=statefulset)
        except ApiError:
            raise KubernetesRequestedVolumesError(
                f"Could not replace statefulset {statefulset_name}"
            )
        logger.info("Replaced %s statefulset", statefulset_name)

    def list_volumes(self, statefulset_name: str) -> list[Volume]:
        """Lists current volumes in the given StatefulSet.

        Returns:
            list[Volume]: List of current volumes in the given StatefulSet
        """
        try:
            statefulset = self.client.get(
                res=StatefulSet, name=statefulset_name, namespace=self.namespace
            )
            return statefulset.spec.template.spec.volumes  # type: ignore[attr-defined]
        except ApiError:
            raise KubernetesRequestedVolumesError("Could not list volumes")

    def list_volumemounts(self, statefulset_name: str, container_name: str) -> list[VolumeMount]:
        """Lists current volumeMounts in the given container.

        Returns:
            list[VolumeMount]: List of current volumeMounts in the given container
        """
        try:
            statefulset = self.client.get(
                res=StatefulSet, name=statefulset_name, namespace=self.namespace
            )
        except ApiError:
            raise KubernetesRequestedVolumesError(f"Could not get statefulset {statefulset_name}")
        containers: Iterable[Container] = statefulset.spec.template.spec.containers  # type: ignore[attr-defined]  # noqa: E501
        container = self._get_container(container_name=container_name, containers=containers)
        return container.volumeMounts

    def list_container_resources(
        self, statefulset_name: str, container_name: str
    ) -> ResourceRequirements:
        """Returns resource requirements in the given container.

        Returns:
            ResourceRequirements: resource requirements in the given container
        """
        try:
            statefulset = self.client.get(
                res=StatefulSet, name=statefulset_name, namespace=self.namespace
            )
        except ApiError:
            raise KubernetesRequestedVolumesError(f"Could not get statefulset {statefulset_name}")
        containers: Iterable[
            Container
        ] = statefulset.spec.template.spec.containers  # type: ignore[attr-defined]  # noqa: E501
        container = self._get_container(container_name=container_name, containers=containers)
        return container.resources


class KubernetesHugepagesPatchCharmLib(Object):
    """Class to be instantiated by charms requiring changes in HugePages volumes."""

    def __init__(
        self,
        charm: CharmBase,
        hugepages_volumes_func: Callable[[], Iterable[RequestedHugepages]],
        container_name: str,
        refresh_event: BoundEvent,
    ):
        """Constructor for the KubernetesHugepagesPatchCharmLib.

        Args:
            charm: Charm object
            hugepages_volumes_func: A callable to a function returning a list of
              `RequestedHugepages` to be created.
            container_name: Container name
            refresh_event: a bound event which will be observed to re-apply the patch.
        """
        super().__init__(charm, "kubernetes-requested-volumes")
        self.kubernetes = KubernetesClient(namespace=self.model.name)
        self.hugepages_volumes_func = hugepages_volumes_func
        self.container_name = container_name
        self.framework.observe(refresh_event, self._configure_requested_volumes)

    def _configure_requested_volumes(self, _):
        """Configures HugePages in the StatefulSet and container."""
        if not self.is_patched():
            self._configure_volumes()

    def _pod_is_patched(
        self,
        requested_volumemounts: Iterable[VolumeMount],
        requested_resources: ResourceRequirements,
    ) -> bool:
        """Returns whether pod contains given volumeMounts and resource limits.

        Args:
            requested_volumemounts: Iterable of volumeMounts to be set in the pod.
            requested_resources: resource requirements to be set in the pod.

        Returns:
            bool: Whether pod contains given volumeMounts and resource limits.
        """
        return self.kubernetes.pod_is_patched(
            pod_name=self._pod,
            requested_volumemounts=requested_volumemounts,
            requested_resources=requested_resources,
            container_name=self.container_name,
        )

    @property
    def _pod(self) -> str:
        """Name of the unit's pod.

        Returns:
            str: A string containing the name of the current unit's pod.
        """
        return "-".join(self.model.unit.name.rsplit("/", 1))

    def _statefulset_is_patched(self, requested_volumes: Iterable[Volume]) -> bool:
        """Returns whether statefulset contains requested volumes.

        Args:
            requested_volumes: Iterable of volumes to be set in the statefulset

        Returns:
            bool: Whether statefulset contains requested volumes.
        """
        return self.kubernetes.statefulset_is_patched(
            statefulset_name=self.model.app.name,
            requested_volumes=requested_volumes,
        )

    def is_patched(
        self,
    ) -> bool:
        """Returns whether statefulset and pod are patched.

        Validates that the statefulset contains the appropriate volumes
        and that the pod also contains the appropriate volumeMounts and
        resource requirements.

        Returns:
            bool: Whether statefulset and pod are patched.
        """
        volumes = self._generate_volumes_from_requested_hugepage()
        statefulset_is_patched = self._statefulset_is_patched(volumes)
        volumemounts = self._generate_volumemounts_from_requested_hugepage()
        resource_requirements = self._generate_resource_requirements_from_requested_hugepage()
        pod_is_patched = self._pod_is_patched(
            requested_volumemounts=volumemounts,
            requested_resources=resource_requirements,
        )
        return statefulset_is_patched and pod_is_patched

    def _generate_volumes_from_requested_hugepage(self) -> list[Volume]:
        """Generates the list of required HugePages volumes.

        Returns:
            list[Volume]: list of volumes to be set in the StatefulSet.
        """
        return [
            Volume(
                name=f"hugepages-{requested_hugepages.size.lower()}",
                emptyDir=EmptyDirVolumeSource(medium=f"HugePages-{requested_hugepages.size}"),
            )
            for requested_hugepages in self.hugepages_volumes_func()
        ]

    def _generate_volumemounts_from_requested_hugepage(self) -> list[VolumeMount]:
        """Generates the list of required HugePages volumeMounts.

        Returns:
            list[VolumeMount]: list of volumeMounts to be set in the container.
        """
        return [
            VolumeMount(
                name=f"hugepages-{requested_hugepages.size.lower()}",
                mountPath=requested_hugepages.mount_path,
            )
            for requested_hugepages in self.hugepages_volumes_func()
        ]

    def _generate_resource_requirements_from_requested_hugepage(self) -> ResourceRequirements:
        """Generates the required resource requirements for HugePages.

        Returns:
            ResourceRequirements: required resource requirements to be set in the container.
        """
        limits = {}
        requests = {}
        for hugepage in self.hugepages_volumes_func():
            limits.update({f"hugepages-{hugepage.size}": hugepage.limit})
            requests.update({f"hugepages-{hugepage.size}": hugepage.limit})
        return ResourceRequirements(
            limits=limits,
            requests=requests,
        )

    @staticmethod
    def _volumemount_is_hugepages(volume_mount: VolumeMount) -> bool:
        """Returns whether the specified volumeMount is HugePages."""
        return volume_mount.name.startswith("hugepages")

    @staticmethod
    def _volume_is_hugepages(volume: Volume) -> bool:
        """Returns whether the specified volume is HugePages."""
        return volume.name.startswith("hugepages")

    @staticmethod
    def _limit_or_resource_is_hugepages(key: str) -> bool:
        """Returns whether the specified limit or request regards HugePages."""
        return key.startswith("hugepages")

    def _configure_volumes(self):
        """Configure HugePages in the StatefulSet and Pod.

        1. Goes through the list of current volumeMounts for the specified container
        - If list of requested hugepages is empty:
          - If hugepages is set as volumeMount, remove it.
          - Keep all other volumeMounts
        - If list of requested hugepages is not empty:
          - If hugepages is set as volumeMount, keep it.
          - Else, add volumeMount.
        2. Goes through the list of current volumes for the specified StatefulSet
        - If list of requested hugepages is empty:
          - If hugepages is set as volume, remove it.
          - Keep all other volumes
        - If list of requested hugepages is not empty:
          - If hugepages is set as volume, keep it.
          - Else, add volume.
        3. Goes through the list of current resource requirements for the specified container
        - If list of requested hugepages is empty:
          - If hugepages is set in resource requirements, remove them.
          - Keep all other resource requirements
        - If list of requested hugepages is not empty:
          - If hugepages is set in resource requirements, keep resource requirements.
          - Else, add resource requirements.
        """
        # handle container volumeMounts
        additional_volumemounts = self._generate_volumemounts_from_requested_hugepage()
        current_volumemounts = self.kubernetes.list_volumemounts(
            statefulset_name=self.model.app.name, container_name=self.container_name
        )
        for current_volumemount in current_volumemounts:
            if not self._volumemount_is_hugepages(current_volumemount):
                additional_volumemounts.append(current_volumemount)

        # handle statefulset volumes
        additional_volumes = self._generate_volumes_from_requested_hugepage()
        current_volumes = self.kubernetes.list_volumes(
            statefulset_name=self.model.app.name,
        )
        for current_volume in current_volumes:
            if not self._volume_is_hugepages(current_volume):
                additional_volumes.append(current_volume)

        # handle resource requirements
        additional_resources = self._generate_resource_requirements_from_requested_hugepage()
        current_resources = self.kubernetes.list_container_resources(
            statefulset_name=self.model.app.name, container_name=self.container_name
        )

        if self.hugepages_volumes_func():
            if current_resources.limits:
                new_limits = {
                    limit: value
                    for limit, value in current_resources.limits.items()
                    if not self._limit_or_resource_is_hugepages(limit)
                }
                new_limits = dict(new_limits.items() | additional_resources.limits.items())
            else:
                new_limits = additional_resources.limits
            if current_resources.requests:
                new_requests = {
                    request: value
                    for request, value in current_resources.requests.items()
                    if not self._limit_or_resource_is_hugepages(request)
                }
                new_requests = dict(new_requests.items() | additional_resources.requests.items())
            else:
                new_requests = additional_resources.requests
        else:
            if current_resources.limits:
                new_limits = {
                    limit: value
                    for limit, value in current_resources.limits.items()
                    if not self._limit_or_resource_is_hugepages(limit)
                }
            else:
                new_limits = current_resources.limits
            if current_resources.requests:
                new_requests = {
                    request: value
                    for request, value in current_resources.requests.items()
                    if not self._limit_or_resource_is_hugepages(request)
                }
            else:
                new_requests = current_resources.requests
        new_resources = ResourceRequirements(
            limits=new_limits, requests=new_requests, claims=current_resources.claims
        )

        self.kubernetes.replace_statefulset(
            statefulset_name=self.model.app.name,
            container_name=self.container_name,
            requested_volumes=additional_volumes,
            requested_volumemounts=additional_volumemounts,
            requested_resources=new_resources,
        )
