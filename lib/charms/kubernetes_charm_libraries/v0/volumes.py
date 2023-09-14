# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Library used to leverage the Volumes Kubernetes in charms."""
import logging
from dataclasses import dataclass
from typing import Union

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

    def pod_is_ready(
        self,
        pod_name: str,
        *,
        requested_volumes: list[RequestedVolume],
        container_name: str,
    ) -> bool:
        """Returns whether pod has the requisite requested volumes.

        Args:
            pod_name: Pod name
            requested_volumes: List of requested volumes
            container_name: Container name

        Returns:
            bool: Whether pod is ready.


        statefulset.spec.template.metadata.annotations
        pod.metadata.annotations

        statefulset.spec.template.spec.containers
        pod.spec.containers
        """
        try:
            pod = self.client.get(Pod, name=pod_name, namespace=self.namespace)
        except ApiError as e:
            if e.status.reason == "Unauthorized":
                logger.debug("kube-apiserver not ready yet")
            else:
                raise KubernetesRequestedVolumesError(f"Pod {pod_name} not found")
            return False
        return self._pod_contains_requested_volumes(
            pod=pod,  # type: ignore[arg-type]
            requested_volumes=requested_volumes,
            container_name=container_name,
        )

    def statefulset_is_patched(
        self,
        statefulset_name: str,
        requested_volumes: list[RequestedVolume],
    ) -> bool:
        """Returns whether the statefulset has the expected requested volumes.

        Args:
            statefulset_name: Statefulset name.
            requested_volumes: list of requested volumes

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
            statefulset_spec=statefulset.spec,
            requested_volumes=requested_volumes,
        )

    @staticmethod
    def _statefulset_volumes_are_patched(
        statefulset_spec: StatefulSetSpec,
        requested_volumes: list[RequestedVolume],
    ) -> bool:
        """Returns whether a StatefulSet is patched with requested volumes.

        Args:
            statefulset_spec: StatefulSet spec
            requested_volumes: List of requested volumes

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

    def _pod_contains_requested_volumes(
        self,
        container_name: str,
        requested_volumes: list[RequestedVolume],
        pod: Union[PodTemplateSpec, Pod],
    ) -> bool:
        """Returns whether a pod is patched with requested volumes.

        Args:
            container_name: Container name
            requested_volumes: List of requested volumes
            pod: Kubernetes pod object.

        Returns:
            bool
        """
        return self._pod_volumemounts_contain_requested_volumes(
            containers=pod.spec.containers,
            container_name=container_name,
            requested_volumes=requested_volumes,
        )

    @staticmethod
    def _pod_volumemounts_contain_requested_volumes(
        containers: list[Container],
        container_name: str,
        requested_volumes: list[RequestedVolume],
    ) -> bool:
        """Returns whether container spec contains the expected requested volumes mounts.

        Args:
            containers: list of Containers
            container_name: Container name
            requested_volumes: Requested volumes we expect to be set

        Returns:
            bool
        """
        container = next(container for container in containers if container.name == container_name)
        return all(
            [
                requested_volume.volume_mount in container.volumeMounts
                for requested_volume in requested_volumes
            ]
        )

    def patch_volumes(
        self,
        statefulset_name: str,
        requested_volumes: list[RequestedVolume],
        container_name: str,
    ) -> None:
        """Patches a statefulset with requested volumes.

        Args:
            statefulset_name: Statefulset name
            requested_volumes: List of requested volumes
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
        if any(
            [
                requested_volume.volume.emptyDir.medium == "HugePages"
                for requested_volume in requested_volumes
            ]
        ):
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
        requested_volumes: list[RequestedVolume],
        container_name: str,
    ) -> None:
        """Replaces a statefulset removing requested volumes.

        Args:
            statefulset_name: Statefulset name
            requested_volumes: List of requested volumes
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
        containers: list[Container] = statefulset.spec.template.spec.containers
        requested_volumes_mounts = [
            requested_volume.volume_mount for requested_volume in requested_volumes
        ]
        container = next(container for container in containers if container.name == container_name)
        container.volumeMounts = [
            item for item in container.volumeMounts if item not in requested_volumes_mounts
        ]
        if any(
            [
                requested_volume.volume.emptyDir.medium == "HugePages"
                for requested_volume in requested_volumes
            ]
        ):
            try:
                del container.resources.limits["hugepages-1Gi"]
                del container.resources.requests["hugepages-1Gi"]
            except KeyError:
                pass
        statefulset_volumes = statefulset.spec.template.spec.volumes
        requested_volumes_volumes = [
            requested_volume.volume for requested_volume in requested_volumes
        ]
        statefulset.spec.template.spec.volumes = [
            item for item in statefulset_volumes if item not in requested_volumes_volumes
        ]
        try:
            self.client.replace(
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

    def add_requested_volumes(self, requested_volumes, container_name) -> None:
        """Creates volumes and patches statefulset.

        Args:
            requested_volumes: List of volumes to add to the statefulset
            container_name: Container name
        """
        self.kubernetes.patch_volumes(
            statefulset_name=self.application_name,
            requested_volumes=requested_volumes,
            container_name=container_name,
        )

    def remove_requested_volumes(
        self,
        requested_volumes: list[RequestedVolume],
        container_name: str,
    ) -> None:
        """Deletes volumes from statefulset and pod.

        Args:
            requested_volumes: List of volumes to add to the statefulset
            container_name: Container name
        """
        self.kubernetes.remove_volumes(
            statefulset_name=self.application_name,
            requested_volumes=requested_volumes,
            container_name=container_name,
        )

    def _pod_is_ready(self, requested_volumes: list[RequestedVolume]) -> bool:
        """Returns whether pod is ready with requested volumes.

        Args:
            requested_volumes: List of volumes to add to the statefulset
        """
        return self.kubernetes.pod_is_ready(
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

    def _statefulset_is_patched(self, requested_volumes: list[RequestedVolume]) -> bool:
        """Returns whether statefuset is patched with requested volumes.

        Args:
            requested_volumes: List of volumes to add to the statefulset
        """
        return self.kubernetes.statefulset_is_patched(
            statefulset_name=self.application_name,
            requested_volumes=requested_volumes,
        )

    def is_ready(self, requested_volumes: list[RequestedVolume]) -> bool:
        """Returns whether RequestedVolumes is ready.

        Validates that the statefulset is
        patched with the appropriate requested volumes and that the pod
        also contains the same requested volumes and resource limits.

        Args:
            requested_volumes: List of volumes to add to the statefulset

        Returns:
            bool: Whether RequestedVolumes is ready
        """
        statefulset_is_patched = self._statefulset_is_patched(requested_volumes)
        pod_is_ready = self._pod_is_ready(requested_volumes)
        return statefulset_is_patched and pod_is_ready
