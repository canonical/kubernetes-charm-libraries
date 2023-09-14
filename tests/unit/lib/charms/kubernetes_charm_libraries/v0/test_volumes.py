# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import Mock, patch

import httpx
from charms.kubernetes_charm_libraries.v0.volumes import (  # type: ignore[import]
    AdditionalVolume,
    KubernetesAdditionalVolumesError,
    KubernetesClient,
    KubernetesVolumesLib,
)
from lightkube.core.exceptions import ApiError
from lightkube.models.apps_v1 import StatefulSet, StatefulSetSpec
from lightkube.models.core_v1 import (
    Container,
    EmptyDirVolumeSource,
    PodSpec,
    PodTemplateSpec,
    ResourceRequirements,
    Volume,
    VolumeMount,
)
from lightkube.models.meta_v1 import LabelSelector
from lightkube.resources.apps_v1 import StatefulSet as StatefulSetResource
from lightkube.resources.core_v1 import Pod
from lightkube.types import PatchType
from ops.charm import CharmBase
from ops.testing import Harness

VOLUMES_LIBRARY_PATH = "charms.kubernetes_charm_libraries.v0.volumes"


class TestKubernetes(unittest.TestCase):
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    def setUp(self) -> None:
        self.namespace = "whatever ns"
        self.kubernetes_volumes = KubernetesClient(namespace=self.namespace)

    @patch("lightkube.core.client.Client.patch")
    def test_given_no_additional_volume_when_patch_statefulset_then_statefulset_is_not_patched(
        self, patch_patch
    ):
        additional_volumes = []

        self.kubernetes_volumes.patch_volumes(
            name="whatever statefulset name",
            additional_volumes=additional_volumes,
            container_name="container-name",
        )

        patch_patch.assert_not_called()

    @patch("lightkube.core.client.Client.patch")
    @patch("lightkube.core.client.Client.get")
    def test_given_statefulset_doesnt_have_additional_volumes_when_patch_statefulset_then_statefulset_is_patched(  # noqa: E501
        self, patch_get, patch_patch
    ):
        container_name = "whatever container name"
        statefulset_name = "whatever statefulset name"
        additional_volumes = [
            AdditionalVolume(name="hugepage-1", medium="HugePages", mount_point="/some/mountpoint")
        ]
        initial_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=container_name,
                                volumeMounts=[],
                            )
                        ],
                        volumes=[],
                    ),
                ),
            )
        )
        patch_get.return_value = initial_statefulset

        self.kubernetes_volumes.patch_volumes(
            name="whatever statefulset name",
            additional_volumes=additional_volumes,
            container_name="container-name",
        )

        args, kwargs = patch_patch.call_args
        self.assertEqual(kwargs["res"], StatefulSetResource)
        self.assertEqual(kwargs["name"], statefulset_name)
        self.assertEqual(kwargs["patch_type"], PatchType.APPLY)
        self.assertEqual(kwargs["namespace"], self.namespace)

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_unauthorized_api_error_when_statefulset_is_patched_then_returns_false(  # noqa: E501
        self, patch_get
    ):
        statefulset_name = "whatever name"
        additional_volumes = [
            AdditionalVolume(name="hugepage-1", medium="HugePages", mount_point="/some/mountpoint")
        ]
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=401, json={"reason": "Unauthorized"}),
        )

        is_patched = self.kubernetes_volumes.statefulset_is_patched(
            name=statefulset_name,
            additional_volumes=additional_volumes,
            container_name="container name",
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_no_additional_volumes_when_statefulset_is_patched_then_returns_false(
        self, patch_get
    ):
        statefulset_name = "whatever name"
        additional_volumes = [
            AdditionalVolume(name="hugepage-1", medium="HugePages", mount_point="/some/mountpoint")
        ]
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name="container name",
                                volumeMounts=[],
                            )
                        ],
                        volumes=[],
                    )
                ),
            )
        )

        is_patched = self.kubernetes_volumes.statefulset_is_patched(
            name=statefulset_name,
            additional_volumes=additional_volumes,
            container_name="container name",
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_additional_volumes_are_different_when_statefulset_is_patched_then_returns_false(
        self, patch_get
    ):
        statefulset_name = "whatever name"
        additional_volumes_in_statefulset = [
            AdditionalVolume(
                name="hugepage-existing", medium="HugePages", mount_point="/some/mountpoint"
            )
        ]
        additional_volumes = [
            AdditionalVolume(
                name="hugepage-1", medium="HugePages", mount_point="/some/other/mountpoint"
            )
        ]
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name="container name",
                                volumeMounts=[
                                    VolumeMount(
                                        name=additional_volume.name,
                                        mountPath=additional_volume.mount_point,
                                    )
                                    for additional_volume in additional_volumes_in_statefulset
                                ],
                                resources=ResourceRequirements(
                                    limits={"hugepages-1Gi": "2Gi"},
                                    requests={"hugepages-1Gi": "2Gi"},
                                ),
                            )
                        ],
                        volumes=[
                            Volume(
                                name=additional_volume.name,
                                emptyDir=EmptyDirVolumeSource(medium=additional_volume.medium),
                            )
                            for additional_volume in additional_volumes
                        ],
                    )
                ),
            )
        )

        is_patched = self.kubernetes_volumes.statefulset_is_patched(
            name=statefulset_name,
            additional_volumes=additional_volumes,
            container_name="container name",
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_additional_volumes_are_already_present_when_statefulset_is_patched_then_returns_true(
        self, patch_get
    ):
        container_name = "whatever"
        statefulset_name = "whatever name"
        additional_volumes = [
            AdditionalVolume(name="hugepage-1", medium="HugePages", mount_point="/some/mountpoint")
        ]
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=container_name,
                                volumeMounts=[
                                    VolumeMount(
                                        name=additional_volume.name,
                                        mountPath=additional_volume.mount_point,
                                    )
                                    for additional_volume in additional_volumes
                                ],
                                resources=ResourceRequirements(
                                    limits={"hugepages-1Gi": "2Gi"},
                                    requests={"hugepages-1Gi": "2Gi"},
                                ),
                            )
                        ],
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

        is_patched = self.kubernetes_volumes.statefulset_is_patched(
            name=statefulset_name,
            additional_volumes=additional_volumes,
            container_name=container_name,
        )

        self.assertTrue(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_unauthorized_api_error_when_pod_is_ready_then_returns_false(
        self, patch_get
    ):
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=401, json={"reason": "Unauthorized"}),
        )
        additional_volumes = [
            AdditionalVolume(name="hugepage-1", medium="HugePages", mount_point="/some/mountpoint")
        ]
        is_ready = self.kubernetes_volumes.pod_is_ready(
            pod_name="pod name",
            additional_volumes=additional_volumes,
            container_name="container-name",
        )

        self.assertFalse(is_ready)

    @patch("lightkube.core.client.Client.get")
    def test_given_additional_volume_not_set_when_pod_is_ready_then_returns_false(self, patch_get):
        patch_get.return_value = Pod(
            spec=PodSpec(
                containers=[
                    Container(
                        name="container-name",
                        volumeMounts=[],
                        resources=ResourceRequirements(limits={}, requests={}),
                    )
                ],
                volumes=[],
            )
        )

        additional_volumes = [
            AdditionalVolume(name="hugepage-1", medium="HugePages", mount_point="/some/mountpoint")
        ]

        is_ready = self.kubernetes_volumes.pod_is_ready(
            pod_name="pod name",
            additional_volumes=additional_volumes,
            container_name="container-name",
        )

        self.assertFalse(is_ready)

    @patch("lightkube.core.client.Client.get")
    def test_given_pod_is_ready_when_pod_is_ready_then_returns_true(self, patch_get):
        additional_volumes = [
            AdditionalVolume(name="hugepage-1", medium="HugePages", mount_point="/some/mountpoint")
        ]
        container_name = "whatever name"
        patch_get.return_value = Pod(
            spec=PodSpec(
                containers=[
                    Container(
                        name=container_name,
                        volumeMounts=[
                            VolumeMount(
                                name=additional_volume.name,
                                mountPath=additional_volume.mount_point,
                            )
                            for additional_volume in additional_volumes
                        ],
                    ),
                ],
                volumes=[
                    Volume(
                        name=additional_volume.name,
                        emptyDir=EmptyDirVolumeSource(medium=additional_volume.medium),
                    )
                    for additional_volume in additional_volumes
                ],
            ),
        )

        is_ready = self.kubernetes_volumes.pod_is_ready(
            pod_name="pod name",
            additional_volumes=additional_volumes,
            container_name="container-name",
        )

        self.assertTrue(is_ready)


class _TestCharmNoAdditionalVolumes(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.additional_volumes = []
        self.kubernetes_volumes = KubernetesVolumesLib(
            charm=self,
            additional_volumes=self.additional_volumes,
            container_name="container-name",
        )


class _TestCharmSingleAdditionalVolumes(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.container_name = "container-name"
        self.volume_name = "hugepages-1Gi"
        self.volume_mount_point = "/dev/hugepages"
        self.volume_medium = "hugepages"
        self.additional_volumes = [
            AdditionalVolume(
                name=self.volume_name,
                mount_point=self.volume_mount_point,
                medium=self.volume_medium,
            )
        ]
        self.kubernetes_volumes = KubernetesVolumesLib(
            charm=self,
            additional_volumes=self.additional_volumes,
            container_name=self.container_name,
        )


class TestKubernetesAdditionalVolumesCharmLib(unittest.TestCase):
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.pod_is_ready")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    def test_given_pod_not_ready_when_is_ready_then_return_false(
        self,
        patch_statefulset_is_patched,
        patch_pod_is_ready,
    ):
        patch_statefulset_is_patched.return_value = True
        patch_pod_is_ready.return_value = False

        harness = Harness(_TestCharmSingleAdditionalVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()

        is_ready = harness.charm.kubernetes_volumes.is_ready()
        self.assertFalse(is_ready)

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.pod_is_ready")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    def test_given_pod_is_ready_when_is_ready_then_return_true(
        self,
        patch_statefulset_is_patched,
        patch_pod_is_ready,
    ):
        patch_statefulset_is_patched.return_value = True
        patch_pod_is_ready.return_value = True

        harness = Harness(_TestCharmSingleAdditionalVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()

        is_ready = harness.charm.kubernetes_volumes.is_ready()
        self.assertTrue(is_ready)

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.delete_pod")
    def test_given_pod_is_deleted_when_additional_volumes_delete_pod_then_k8s_client_delete_pod_is_called(
        self, patch_delete
    ):  # noqa: E501
        harness = Harness(_TestCharmNoAdditionalVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.charm.kubernetes_volumes.delete_pod()
        patch_delete.assert_called_once()
