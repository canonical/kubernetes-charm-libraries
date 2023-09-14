# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Library used to leverage the AdditionalVolumes Kubernetes in charms.

- On config-changed, it will:
  - Patch the statefulset with the necessary volumes for the container to have additional volumes
"""
import logging
from dataclasses import dataclass
from typing import Union

from lightkube import Client
from lightkube.core.exceptions import ApiError
from lightkube.models.apps_v1 import StatefulSetSpec
from lightkube.models.core_v1 import (
    Container,
    EmptyDirVolumeSource,
    PodSpec,
    PodTemplateSpec,
    ResourceRequirements,
    Volume,
    VolumeMount,
)
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import Pod
from lightkube.types import PatchType
from ops.charm import CharmBase
from ops.framework import Object

logger = logging.getLogger(__name__)


@dataclass
class AdditionalVolume:
    """AdditionalVolume."""

    name: str
    mount_point: str
    medium: str


class KubernetesAdditionalVolumesError(Exception):
    """KubernetesAdditionalVolumesError."""

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
        additional_volumes: list[AdditionalVolume],
        container_name: str,
    ) -> bool:
        """Returns whether pod has the requisite additional volumes.

        Args:
            pod_name: Pod name
            additional_volumes: List of additional volumes
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
                raise KubernetesAdditionalVolumesError(f"Pod {pod_name} not found")
            return False
        return self._pod_contains_additional_volumes(
            pod=pod,  # type: ignore[arg-type]
            additional_volumes=additional_volumes,
            container_name=container_name,
        )

    def statefulset_is_patched(
        self,
        name: str,
        additional_volumes: list[AdditionalVolume],
        container_name: str,
    ) -> bool:
        """Returns whether the statefulset has the expected additional volumes.

        Args:
            name: Statefulset name.
            additional_volumes: list of additional volumes
            container_name: Container name

        Returns:
            bool: Whether the statefulset has the expected additional volumes.
        """
        try:
            statefulset = self.client.get(res=StatefulSet, name=name, namespace=self.namespace)
        except ApiError as e:
            if e.status.reason == "Unauthorized":
                logger.debug("kube-apiserver not ready yet")
            else:
                raise KubernetesAdditionalVolumesError(f"Could not get statefulset {name}")
            return False
        statefulset_volumes_are_patched = self._statefulset_volumes_are_patched(
            statefulset_spec=statefulset.spec,
            additional_volumes=additional_volumes,
        )
        pod_is_patched = self._pod_contains_additional_volumes(
            container_name=container_name,
            additional_volumes=additional_volumes,
            pod=statefulset.spec.template,
        )
        return statefulset_volumes_are_patched and pod_is_patched

    @staticmethod
    def _statefulset_volumes_are_patched(
        statefulset_spec: StatefulSetSpec,
        additional_volumes: list[AdditionalVolume],
    ) -> bool:
        volumes_names = [volume.name for volume in statefulset_spec.template.spec.volumes]
        for additional_volume in additional_volumes:
            if additional_volume.name not in volumes_names:
                return False
        return True

    def _pod_contains_additional_volumes(
        self,
        container_name: str,
        additional_volumes: list[AdditionalVolume],
        pod: Union[PodTemplateSpec, Pod],
    ) -> bool:
        """Returns whether a pod is patched with additional volumes.

        Args:
            container_name: Container name
            additional_volumes: List of additional volumes
            pod: Kubernetes pod object.

        Returns:
            bool
        """
        return self._pod_volumemounts_contain_additional_volumes(
            containers=pod.spec.containers,
            container_name=container_name,
            additional_volumes=additional_volumes,
        )

    @staticmethod
    def _pod_volumemounts_contain_additional_volumes(
        containers: list[Container],
        container_name: str,
        additional_volumes: list[AdditionalVolume],
    ) -> bool:
        """Returns whether container spec contains the expected additional volumes mounts.

        Args:
            containers: list of Containers
            container_name: Container name
            additional_volumes: AdditionalVolumes we expect to be set

        Returns:
            bool
        """
        for container in containers:
            if container.name == container_name:
                volume_mounts_names = [mount.name for mount in container.volumeMounts]
                for additional_volume in additional_volumes:
                    if additional_volume.name not in volume_mounts_names:
                        return False
        return True

    def patch_volumes(
        self,
        name: str,
        additional_volumes: list[AdditionalVolume],
        container_name: str,
    ) -> None:
        """Patches a statefulset with additional volumes.

        Args:
            name: Statefulset name
            additional_volumes: List of additional volumes
            container_name: Container name
        """
        if not additional_volumes:
            logger.info("No additional volumes were provided")
            return
        try:
            statefulset = self.client.get(res=StatefulSet, name=name, namespace=self.namespace)
        except ApiError:
            raise KubernetesAdditionalVolumesError(f"Could not get statefulset {name}")
        container = Container(
            name=container_name,
            volumeMounts=[],
            resources=ResourceRequirements(limits={}, requests={}),
        )
        for additional_volume in additional_volumes:
            container.volumeMounts.append(
                VolumeMount(name=additional_volume.name, mountPath=additional_volume.mount_point)
            )
            if additional_volume.name == "hugepages":
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
                            Volume(
                                name=additional_volume.name,
                                emptyDir=EmptyDirVolumeSource(medium=additional_volume.medium),
                            )
                            for additional_volume in additional_volumes
                        ],
                    ),
                ),
            )
        )
        try:
            self.client.patch(
                res=StatefulSet,
                name=name,
                obj=statefulset_delta,
                patch_type=PatchType.APPLY,
                namespace=self.namespace,
                field_manager=self.__class__.__name__,
            )
        except ApiError:
            raise KubernetesAdditionalVolumesError(f"Could not patch statefulset {name}")
        logger.info("Additional volumes added to %s statefulset", name)

    def remove_volumes(
        self,
        name: str,
        additional_volumes: list[AdditionalVolume],
        container_name: str,
    ) -> None:
        if not additional_volumes:
            logger.info("No additional volumes were provided")
            return
        try:
            statefulset = self.client.get(res=StatefulSet, name=name, namespace=self.namespace)
        except ApiError:
            raise KubernetesAdditionalVolumesError(f"Could not get statefulset {name}")
        containers: list[Container] = statefulset.spec.template.spec.containers
        additional_volumes_names = [
            additional_volume.name for additional_volume in additional_volumes
        ]
        hugepages_volume = False
        if "hugepages" in additional_volumes_names:
            hugepages_volume = True
        for container in containers:
            if container.name == container_name:
                container.volumeMounts = [
                    item
                    for item in container.volumeMounts
                    if item.name not in additional_volumes_names
                ]
                if hugepages_volume:
                    try:
                        del container.resources.limits["hugepages-1Gi"]
                        del container.resources.requests["hugepages-1Gi"]
                    except KeyError:
                        pass
        statefulset_volumes = statefulset.spec.template.spec.volumes
        statefulset.spec.template.spec.volumes = [
            item for item in statefulset_volumes if item.name not in additional_volumes_names
        ]
        try:
            self.client.replace(
                name=name,
                obj=statefulset,
                namespace=self.namespace,
                field_manager=self.__class__.__name__,
            )
        except ApiError:
            raise KubernetesAdditionalVolumesError(f"Could not replace statefulset {name}")
        logger.info("Additional volumes removed from %s statefulset", name)

    def delete_pod(self, pod_name: str) -> None:
        """Deleting given pod.

        Args:
            pod_name (str): Pod name

        """
        self.client.delete(Pod, pod_name, namespace=self.namespace)


class KubernetesVolumesLib(Object):
    """Class to be instantiated by charms requiring additional volumes."""

    def __init__(
        self,
        charm: CharmBase,
        additional_volumes: list[AdditionalVolume],
        container_name: str,
    ):
        """Constructor for the KubernetesAdditionalVolumesCharmLib.

        Args:
            charm: Charm object
            additional_volumes: List of AdditionalVolume.
            container_name: Container name
        """
        super().__init__(charm, "kubernetes-additional volumes")
        self.kubernetes = KubernetesClient(namespace=self.model.name)
        self.additional_volumes = additional_volumes
        self.container_name = container_name
        # self.framework.observe(charm.on.remove, self._on_remove)

    def add_additional_volumes(self) -> None:
        """Creates additional volumes and patches statefulset."""
        if not self.is_ready():
            self.kubernetes.patch_volumes(
                name=self.model.app.name,
                additional_volumes=self.additional_volumes,
                container_name=self.container_name,
            )

    def remove_additional_volumes(self) -> None:
        """Deletes additional volumes from statefulset and pod."""
        if self.is_ready():
            self.kubernetes.remove_volumes(
                name=self.model.app.name,
                additional_volumes=self.additional_volumes,
                container_name=self.container_name,
            )

    def _pod_is_ready(self) -> bool:
        """Returns whether pod is ready with additional volumes."""
        return self.kubernetes.pod_is_ready(
            pod_name=self._pod,
            additional_volumes=self.additional_volumes,
            container_name=self.container_name,
        )

    @property
    def _pod(self) -> str:
        """Name of the unit's pod.

        Returns:
            str: A string containing the name of the current unit's pod.
        """
        return "-".join(self.model.unit.name.rsplit("/", 1))

    def _statefulset_is_patched(self) -> bool:
        """Returns whether statefuset is patched with additional volumes."""
        return self.kubernetes.statefulset_is_patched(
            name=self.model.app.name,
            additional_volumes=self.additional_volumes,
            container_name=self.container_name,
        )

    def is_ready(self) -> bool:
        """Returns whether AdditionalVolumes is ready.

        Validates that the statefulset is
        patched with the appropriate additional volumes and that the pod
        also contains the same additional volumes and resource limits.

        Returns:
            bool: Whether AdditionalVolumes is ready
        """
        statefulset_is_patched = self._statefulset_is_patched()
        pod_is_ready = self._pod_is_ready()
        return statefulset_is_patched and pod_is_ready

    def delete_pod(self) -> None:
        """Delete the pod."""
        self.kubernetes.delete_pod(self._pod)
