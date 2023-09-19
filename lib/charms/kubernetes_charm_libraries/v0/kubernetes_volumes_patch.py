# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Library used to leverage the Volumes Kubernetes in charms."""
import logging
from dataclasses import dataclass
from typing import Iterable

from lightkube import Client
from lightkube.core.exceptions import ApiError
from lightkube.models.apps_v1 import StatefulSetSpec
from lightkube.models.core_v1 import (
    Container,
    PodSpec,
    PodTemplateSpec,
    ResourceRequirements,
    Volume,
    VolumeMount,
)
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import Pod
from lightkube.types import PatchType

logger = logging.getLogger(__name__)

HUGEPAGES_RESOURCES_LIMITS = {"hugepages-1Gi": "2Gi"}
HUGEPAGES_RESOURCES_REQUESTS = {"hugepages-1Gi": "2Gi"}
HUGEPAGES_RESOURCES = ResourceRequirements(
    limits=HUGEPAGES_RESOURCES_LIMITS,
    requests=HUGEPAGES_RESOURCES_REQUESTS,
)


@dataclass
class RequestedVolume:
    """RequestedVolume."""

    volume: Volume
    volume_mount: VolumeMount


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
            raise ContainerNotFoundError(f"Container '{container_name}' not found")

    def pod_is_patched(
        self,
        pod_name: str,
        *,
        requested_volumes: Iterable[RequestedVolume],
        container_name: str,
    ) -> bool:
        """Returns whether pod has the requisite requested volumes and resources (when required).

        Args:
            pod_name: Pod name
            requested_volumes: Iterable of requested volumes
            container_name: Container name

        Returns:
            bool: Whether pod is patched.
        """
        try:
            pod = self.client.get(Pod, name=pod_name, namespace=self.namespace)
        except ApiError as e:
            if e.status.reason == "Unauthorized":
                logger.debug("kube-apiserver not ready yet")
            else:
                raise KubernetesRequestedVolumesError(f"Pod {pod_name} not found")
            return False
        pod_has_volumemounts = self._pod_volumemounts_contain_requested_volumes(
            requested_volumes=requested_volumes,
            containers=pod.spec.containers,  # type: ignore[attr-defined]
            container_name=container_name,
        )
        pod_has_resources = self._pod_resources_are_set(
            containers=pod.spec.containers,  # type: ignore[attr-defined]
            container_name=container_name,
            requested_volumes=requested_volumes,
        )
        return pod_has_volumemounts and pod_has_resources

    def statefulset_is_patched(
        self,
        statefulset_name: str,
        requested_volumes: Iterable[RequestedVolume],
    ) -> bool:
        """Returns whether the statefulset has the expected requested volumes.

        Args:
            statefulset_name: Statefulset name.
            requested_volumes: Iterable of requested volumes

        Returns:
            bool: Whether the statefulset has the expected requested volumes.
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
        return self._statefulset_volumes_are_patched(
            statefulset_spec=statefulset.spec,  # type: ignore[attr-defined]
            requested_volumes=requested_volumes,
        )

    @staticmethod
    def _statefulset_volumes_are_patched(
        statefulset_spec: StatefulSetSpec,
        requested_volumes: Iterable[RequestedVolume],
    ) -> bool:
        """Returns whether a StatefulSet is patched with requested volumes.

        Args:
            statefulset_spec: StatefulSet spec
            requested_volumes: Iterable of requested volumes

        Returns:
            bool
        """
        if not statefulset_spec.template.spec.volumes:
            return False
        return all(
            [
                requested_volume.volume in statefulset_spec.template.spec.volumes
                for requested_volume in requested_volumes
            ]
        )

    def _pod_volumemounts_contain_requested_volumes(
        self,
        containers: Iterable[Container],
        container_name: str,
        requested_volumes: Iterable[RequestedVolume],
    ) -> bool:
        """Returns whether container spec contains the expected requested volumes mounts.

        Args:
            containers: Iterable of Containers
            container_name: Container name
            requested_volumes: Requested volumes we expect to be set

        Returns:
            bool
        """
        container = self._get_container(container_name=container_name, containers=containers)
        return all(
            [
                requested_volume.volume_mount in container.volumeMounts
                for requested_volume in requested_volumes
            ]
        )

    def _pod_resources_are_set(
        self,
        containers: Iterable[Container],
        container_name: str,
        requested_volumes: Iterable[RequestedVolume],
    ) -> bool:
        """Returns whether container spec contains the expected resources requests and limits.

        Args:
            containers: Iterable of Containers
            container_name: Container name
            requested_volumes: Iterable of requested volumes

        Returns:
            bool
        """
        container = self._get_container(container_name=container_name, containers=containers)
        if not self._hugepages_in_requested_volumes(requested_volumes):
            return True
        if not container.resources.limits or not container.resources.requests:
            return False
        for limit, value in HUGEPAGES_RESOURCES_LIMITS.items():
            if container.resources.limits.get(limit) != value:
                return False
        for request, value in HUGEPAGES_RESOURCES_REQUESTS.items():
            if container.resources.requests.get(request) != value:
                return False
        return True

    def patch_volumes(
        self,
        statefulset_name: str,
        requested_volumes: Iterable[RequestedVolume],
        container_name: str,
    ) -> None:
        """Patches a statefulset with requested volumes.

        Args:
            statefulset_name: Statefulset name
            requested_volumes: Iterable of requested volumes
            container_name: Container name
        """
        if not requested_volumes:
            logger.warning("No requested volumes were provided")
            return
        try:
            statefulset = self.client.get(
                res=StatefulSet, name=statefulset_name, namespace=self.namespace
            )
        except ApiError:
            raise KubernetesRequestedVolumesError(f"Could not get statefulset {statefulset_name}")
        container = Container(
            name=container_name,
            volumeMounts=[requested_volume.volume_mount for requested_volume in requested_volumes],
            resources=ResourceRequirements(limits={}, requests={}),
        )
        if self._hugepages_in_requested_volumes(requested_volumes):
            container.resources = HUGEPAGES_RESOURCES
        statefulset_delta = StatefulSet(
            spec=StatefulSetSpec(
                selector=statefulset.spec.selector,  # type: ignore[attr-defined]
                serviceName=statefulset.spec.serviceName,  # type: ignore[attr-defined]
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[container],
                        volumes=[
                            requested_volume.volume for requested_volume in requested_volumes
                        ],
                    ),
                ),
            )
        )
        try:
            self.client.patch(
                res=StatefulSet,
                name=statefulset_name,
                obj=statefulset_delta,
                patch_type=PatchType.APPLY,
                namespace=self.namespace,
                field_manager=self.__class__.__name__,
            )
        except ApiError:
            raise KubernetesRequestedVolumesError(
                f"Could not patch statefulset {statefulset_name}"
            )
        logger.info("Requested volumes added to %s statefulset", statefulset_name)

    def remove_volumes(
        self,
        statefulset_name: str,
        requested_volumes: Iterable[RequestedVolume],
        container_name: str,
    ) -> None:
        """Replaces a statefulset removing requested volumes.

        Args:
            statefulset_name: Statefulset name
            requested_volumes: Iterable of requested volumes
            container_name: Container name
        """
        if not requested_volumes:
            logger.warning("No requested volumes were provided")
            return
        try:
            statefulset = self.client.get(
                res=StatefulSet, name=statefulset_name, namespace=self.namespace
            )
        except ApiError:
            raise KubernetesRequestedVolumesError(f"Could not get statefulset {statefulset_name}")
        containers: Iterable[Container] = statefulset.spec.template.spec.containers  # type: ignore[attr-defined]  # noqa: E501
        requested_volumes_mounts = [
            requested_volume.volume_mount for requested_volume in requested_volumes
        ]
        container = self._get_container(container_name=container_name, containers=containers)
        container.volumeMounts = [
            item for item in container.volumeMounts if item not in requested_volumes_mounts
        ]
        if self._hugepages_in_requested_volumes(requested_volumes):
            for limit in HUGEPAGES_RESOURCES_LIMITS.keys():
                container.resources.limits.pop(limit, None)
            for request in HUGEPAGES_RESOURCES_REQUESTS.keys():
                container.resources.requests.pop(request, None)
        statefulset_volumes = statefulset.spec.template.spec.volumes  # type: ignore[attr-defined]  # noqa: E501
        requested_volumes_volumes = [
            requested_volume.volume for requested_volume in requested_volumes
        ]
        statefulset.spec.template.spec.volumes = [  # type: ignore[attr-defined]
            item for item in statefulset_volumes if item not in requested_volumes_volumes
        ]
        try:
            self.client.replace(  # type: ignore[call-overload]
                name=statefulset_name,
                obj=statefulset,
                namespace=self.namespace,
                field_manager=self.__class__.__name__,
            )
        except ApiError:
            raise KubernetesRequestedVolumesError(
                f"Could not replace statefulset {statefulset_name}"
            )
        logger.info("Requested volumes removed from %s statefulset", statefulset_name)

    @staticmethod
    def _hugepages_in_requested_volumes(requested_volumes: Iterable[RequestedVolume]) -> bool:
        """Returns whether requested volumes contain an HugePages volume.

        Args:
            requested_volumes: Iterable of requested volumes

        Returns:
            bool: Whether requested volumes contain an HugePages volume
        """
        return any(
            [
                requested_volume.volume.emptyDir.medium == "HugePages"
                for requested_volume in requested_volumes
            ]
        )


class KubernetesVolumesPatchLib:
    """Class to be instantiated by charms requiring requested volumes."""

    def __init__(
        self,
        namespace: str,
        application_name: str,
        unit_name: str,
        container_name: str,
    ):
        """Constructor for the KubernetesVolumesPatchLib.

        Args:
            namespace: Namespace name
            application_name: Charm application name
            unit_name: Unit name
            container_name: Container name
        """
        self.kubernetes = KubernetesClient(namespace=namespace)
        self.model_name = namespace
        self.application_name = application_name
        self.unit_name = unit_name
        self.container_name = container_name

    def add_volumes(
        self,
        requested_volumes: Iterable[RequestedVolume],
        container_name: str,
    ) -> None:
        """Add requested volumes and patches statefulset.

        Args:
            requested_volumes: Iterable of volumes to add to the statefulset
            container_name: Container name
        """
        self.kubernetes.patch_volumes(
            statefulset_name=self.application_name,
            requested_volumes=requested_volumes,
            container_name=container_name,
        )

    def remove_volumes(
        self,
        requested_volumes: Iterable[RequestedVolume],
        container_name: str,
    ) -> None:
        """Deletes volumes from statefulset and pod.

        Args:
            requested_volumes: Iterable of volumes to remove from the statefulset and pod
            container_name: Container name
        """
        self.kubernetes.remove_volumes(
            statefulset_name=self.application_name,
            requested_volumes=requested_volumes,
            container_name=container_name,
        )

    def _pod_is_patched(self, requested_volumes: Iterable[RequestedVolume]) -> bool:
        """Returns whether pod is patched with requested volumes and resource limits.

        Args:
            requested_volumes: Iterable of volumes to be set in the pod.

        Returns:
            bool: Whether pod is patched
        """
        return self.kubernetes.pod_is_patched(
            pod_name=self._pod,
            requested_volumes=requested_volumes,
            container_name=self.container_name,
        )

    @property
    def _pod(self) -> str:
        """Name of the unit's pod.

        Returns:
            str: A string containing the name of the current unit's pod.
        """
        return "-".join(self.unit_name.rsplit("/", 1))

    def _statefulset_is_patched(self, requested_volumes: Iterable[RequestedVolume]) -> bool:
        """Returns whether statefulset is patched with requested volumes.

        Args:
            requested_volumes: Iterable of volumes to be set in the statefulset

        Returns:
            bool: Whether statefulset is patched
        """
        return self.kubernetes.statefulset_is_patched(
            statefulset_name=self.application_name,
            requested_volumes=requested_volumes,
        )

    def is_patched(self, requested_volumes: Iterable[RequestedVolume]) -> bool:
        """Returns whether statefulset and pod are patched.

        Validates that the statefulset is patched with the appropriate
        requested volumes and that the pod also contains the same requested
        volumes and resource limits.

        Args:
            requested_volumes: Iterable of volumes to add to the statefulset

        Returns:
            bool: Whether statefulset and pod are patched
        """
        statefulset_is_patched = self._statefulset_is_patched(requested_volumes)
        pod_is_patched = self._pod_is_patched(requested_volumes)
        return statefulset_is_patched and pod_is_patched
