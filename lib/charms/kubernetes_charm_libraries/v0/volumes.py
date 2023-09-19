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


class KubernetesClient:
    """Class containing all the Kubernetes specific calls."""

    def __init__(self, namespace: str):
        self.client = Client()
        self.namespace = namespace

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
        pod_has_resources = True
        if self._requested_volumes_have_hugepages(requested_volumes=requested_volumes):
            resources = ResourceRequirements(
                limits={"hugepages-1Gi": "2Gi"},
                requests={"hugepages-1Gi": "2Gi"},
            )
            pod_has_resources = self._pod_resources_contain_requests_and_limits(
                containers=pod.spec.containers,  # type: ignore[attr-defined]
                container_name=container_name,
                requested_resources=resources,
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

    @staticmethod
    def _pod_volumemounts_contain_requested_volumes(
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
        container = next(
            (container for container in containers if container.name == container_name), None
        )  # noqa: E501
        if container:
            return all(
                [
                    requested_volume.volume_mount in container.volumeMounts
                    for requested_volume in requested_volumes
                ]
            )
        return False

    @staticmethod
    def _pod_resources_contain_requests_and_limits(
        containers: Iterable[Container],
        container_name: str,
        requested_resources: ResourceRequirements,
    ) -> bool:
        """Returns whether container spec contains the expected resources requests and limits.

        Args:
            containers: Iterable of Containers
            container_name: Container name
            requested_resources: Requests we expect to be set

        Returns:
            bool
        """
        container = next(
            (container for container in containers if container.name == container_name), None
        )  # noqa: E501
        if container:
            if not container.resources.limits or not container.resources.requests:
                return False
            for limit, value in requested_resources.limits.items():
                if container.resources.limits.get(limit) != value:
                    return False
            for request, value in requested_resources.requests.items():
                if container.resources.requests.get(request) != value:
                    return False
            return True
        return False

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
            logger.info("No requested volumes were provided")
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
        if self._requested_volumes_have_hugepages(requested_volumes):
            container.resources.limits.update({"hugepages-1Gi": "2Gi"})
            container.resources.requests.update({"hugepages-1Gi": "2Gi"})
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
            logger.info("No requested volumes were provided")
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
        container = next(
            (container for container in containers if container.name == container_name), None
        )  # noqa: E501
        if container:
            container.volumeMounts = [
                item for item in container.volumeMounts if item not in requested_volumes_mounts
            ]
            if self._requested_volumes_have_hugepages(requested_volumes):
                try:
                    del container.resources.limits["hugepages-1Gi"]
                    del container.resources.requests["hugepages-1Gi"]
                except KeyError:
                    pass
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
    def _requested_volumes_have_hugepages(requested_volumes: Iterable[RequestedVolume]) -> bool:
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

    def add_requested_volumes(
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

    def remove_requested_volumes(
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
