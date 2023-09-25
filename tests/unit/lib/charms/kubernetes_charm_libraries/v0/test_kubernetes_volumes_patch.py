# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import Mock, patch

import httpx
from charms.kubernetes_charm_libraries.v0.kubernetes_volumes_patch import (  # type: ignore[import]
    KubernetesClient,
    KubernetesVolumesPatchCharmLib,
    RequestedVolume,
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
from ops import EventBase, EventSource, Handle
from ops.charm import CharmBase, CharmEvents
from ops.testing import Harness

VOLUMES_LIBRARY_PATH = "charms.kubernetes_charm_libraries.v0.kubernetes_volumes_patch"


class TestKubernetes(unittest.TestCase):
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    def setUp(self) -> None:
        self.namespace = "whatever ns"
        self.kubernetes_volumes = KubernetesClient(namespace=self.namespace)

    @patch("lightkube.core.client.Client.patch")
    def test_given_no_requested_volume_when_patch_statefulset_then_statefulset_is_not_patched(
        self, patch_patch
    ):
        requested_volumes = []

        self.kubernetes_volumes.patch_volumes(
            statefulset_name="whatever statefulset name",
            requested_volumes=requested_volumes,
            container_name="container-name",
        )

        patch_patch.assert_not_called()

    @patch("lightkube.core.client.Client.replace")
    def test_given_no_requested_volume_when_replace_statefulset_then_statefulset_is_not_replaced(
        self, patch_replace
    ):
        requested_volumes = []

        self.kubernetes_volumes.remove_volumes(
            statefulset_name="whatever statefulset name",
            requested_volumes=requested_volumes,
            container_name="container-name",
        )

        patch_replace.assert_not_called()

    @patch("lightkube.core.client.Client.patch")
    @patch("lightkube.core.client.Client.get")
    def test_given_statefulset_doesnt_have_requested_volumes_when_patch_statefulset_then_statefulset_is_patched(  # noqa: E501
        self, patch_get, patch_patch
    ):
        container_name = "whatever container name"
        statefulset_name = "whatever statefulset name"
        requested_volumes = [
            RequestedVolume(
                volume=Volume(
                    name="hugepage-1", emptyDir=EmptyDirVolumeSource(medium="HugePages")
                ),
                volume_mount=VolumeMount(name="hugepage-1", mountPath="/some/mountpoint"),
            )
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
            statefulset_name="whatever statefulset name",
            requested_volumes=requested_volumes,
            container_name=container_name,
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
        requested_volumes = [
            RequestedVolume(
                volume=Volume(
                    name="hugepage-1", emptyDir=EmptyDirVolumeSource(medium="HugePages")
                ),
                volume_mount=VolumeMount(name="hugepage-1", mountPath="/some/mountpoint"),
            )
        ]
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=401, json={"reason": "Unauthorized"}),
        )

        statefulset_is_patched = self.kubernetes_volumes.statefulset_is_patched(
            statefulset_name=statefulset_name,
            requested_volumes=requested_volumes,
        )

        self.assertFalse(statefulset_is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_no_requested_volumes_when_statefulset_is_patched_then_returns_false(
        self, patch_get
    ):
        statefulset_name = "whatever name"
        requested_volumes = [
            RequestedVolume(
                volume=Volume(
                    name="hugepage-1", emptyDir=EmptyDirVolumeSource(medium="HugePages")
                ),
                volume_mount=VolumeMount(name="hugepage-1", mountPath="/some/mountpoint"),
            )
        ]
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[],
                        volumes=[],
                    )
                ),
            )
        )

        statefulset_is_patched = self.kubernetes_volumes.statefulset_is_patched(
            statefulset_name=statefulset_name,
            requested_volumes=requested_volumes,
        )

        self.assertFalse(statefulset_is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_requested_volumes_are_different_when_statefulset_is_patched_then_returns_false(
        self, patch_get
    ):
        statefulset_name = "whatever name"
        requested_volumes_in_statefulset = [
            RequestedVolume(
                volume=Volume(
                    name="hugepage-existing", emptyDir=EmptyDirVolumeSource(medium="HugePages")
                ),
                volume_mount=VolumeMount(name="hugepage-existing", mountPath="some/mountpoint"),
            )
        ]
        requested_volumes = [
            RequestedVolume(
                volume=Volume(
                    name="hugepage-1", emptyDir=EmptyDirVolumeSource(medium="HugePages")
                ),
                volume_mount=VolumeMount(name="hugepage-1", mountPath="/some/other/mountpoint"),
            )
        ]
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[],
                        volumes=[
                            requested_volume.volume
                            for requested_volume in requested_volumes_in_statefulset
                        ],
                    )
                ),
            )
        )

        statefulset_is_patched = self.kubernetes_volumes.statefulset_is_patched(
            statefulset_name=statefulset_name,
            requested_volumes=requested_volumes,
        )

        self.assertFalse(statefulset_is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_requested_volumes_are_already_present_when_statefulset_is_patched_then_returns_true(  # noqa: E501
        self, patch_get
    ):
        statefulset_name = "whatever name"
        requested_volumes = [
            RequestedVolume(
                volume=Volume(
                    name="hugepage-1", emptyDir=EmptyDirVolumeSource(medium="HugePages")
                ),
                volume_mount=VolumeMount(name="hugepage-1", mountPath="/some/mountpoint"),
            )
        ]
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[],
                        volumes=[
                            requested_volume.volume for requested_volume in requested_volumes
                        ],
                    ),
                ),
            )
        )

        statefulset_is_patched = self.kubernetes_volumes.statefulset_is_patched(
            statefulset_name=statefulset_name,
            requested_volumes=requested_volumes,
        )

        self.assertTrue(statefulset_is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_unauthorized_api_error_when_pod_is_patched_then_returns_false(
        self, patch_get
    ):
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=401, json={"reason": "Unauthorized"}),
        )
        requested_volumes = [
            RequestedVolume(
                volume=Volume(
                    name="hugepage-1", emptyDir=EmptyDirVolumeSource(medium="HugePages")
                ),
                volume_mount=VolumeMount(name="hugepage-1", mountPath="/some/mountpoint"),
            )
        ]
        is_patched = self.kubernetes_volumes.pod_is_patched(
            pod_name="pod name",
            requested_volumes=requested_volumes,
            container_name="container-name",
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_requested_volume_not_set_when_pod_is_patched_then_returns_false_hugepages(
        self, patch_get
    ):
        patch_get.return_value = Pod(
            spec=PodSpec(
                containers=[
                    Container(
                        name="container-name",
                        volumeMounts=[],
                        resources=ResourceRequirements(),
                    )
                ],
                volumes=[],
            )
        )

        requested_volumes = [
            RequestedVolume(
                volume=Volume(
                    name="hugepage-1", emptyDir=EmptyDirVolumeSource(medium="HugePages")
                ),
                volume_mount=VolumeMount(name="hugepage-1", mountPath="/some/mountpoint"),
            )
        ]

        is_patched = self.kubernetes_volumes.pod_is_patched(
            pod_name="pod name",
            requested_volumes=requested_volumes,
            container_name="container-name",
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_requested_volume_not_set_when_pod_is_patched_then_returns_false_generic(
        self, patch_get
    ):
        patch_get.return_value = Pod(
            spec=PodSpec(
                containers=[
                    Container(
                        name="container-name",
                        volumeMounts=[],
                        resources=ResourceRequirements(),
                    )
                ],
                volumes=[],
            )
        )

        requested_volumes = [
            RequestedVolume(
                volume=Volume(name="volume-1", emptyDir=EmptyDirVolumeSource(medium="Memory")),
                volume_mount=VolumeMount(name="volume-1", mountPath="/some/mountpoint"),
            )
        ]

        is_patched = self.kubernetes_volumes.pod_is_patched(
            pod_name="pod name",
            requested_volumes=requested_volumes,
            container_name="container-name",
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_requested_volume_not_fully_set_when_pod_is_patched_then_returns_false_hugepages(
        self, patch_get
    ):  # noqa: E501
        requested_volumes = [
            RequestedVolume(
                volume=Volume(
                    name="hugepage-1", emptyDir=EmptyDirVolumeSource(medium="HugePages")
                ),
                volume_mount=VolumeMount(name="hugepage-1", mountPath="/some/mountpoint"),
            )
        ]
        container_name = "whatever name"
        patch_get.return_value = Pod(
            spec=PodSpec(
                containers=[
                    Container(
                        name=container_name,
                        volumeMounts=[
                            requested_volume.volume_mount for requested_volume in requested_volumes
                        ],
                        resources=ResourceRequirements(),
                    ),
                ],
                volumes=[requested_volume.volume for requested_volume in requested_volumes],
            ),
        )

        is_patched = self.kubernetes_volumes.pod_is_patched(
            pod_name="pod name",
            requested_volumes=requested_volumes,
            container_name=container_name,
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_pod_is_patched_when_pod_is_patched_then_returns_true_hugepages(self, patch_get):
        requested_volumes = [
            RequestedVolume(
                volume=Volume(
                    name="hugepage-1", emptyDir=EmptyDirVolumeSource(medium="HugePages")
                ),
                volume_mount=VolumeMount(name="hugepage-1", mountPath="/some/mountpoint"),
            )
        ]
        container_name = "whatever name"
        patch_get.return_value = Pod(
            spec=PodSpec(
                containers=[
                    Container(
                        name=container_name,
                        volumeMounts=[
                            requested_volume.volume_mount for requested_volume in requested_volumes
                        ],
                        resources=ResourceRequirements(
                            limits={"hugepages-1Gi": "2Gi"}, requests={"hugepages-1Gi": "2Gi"}
                        ),
                    ),
                ],
                volumes=[requested_volume.volume for requested_volume in requested_volumes],
            ),
        )

        is_patched = self.kubernetes_volumes.pod_is_patched(
            pod_name="pod name",
            requested_volumes=requested_volumes,
            container_name=container_name,
        )

        self.assertTrue(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_pod_is_patched_when_pod_is_patched_then_returns_true_generic(self, patch_get):
        requested_volumes = [
            RequestedVolume(
                volume=Volume(name="volume-1", emptyDir=EmptyDirVolumeSource(medium="Memory")),
                volume_mount=VolumeMount(name="volume-1", mountPath="/some/mountpoint"),
            )
        ]
        container_name = "whatever name"
        patch_get.return_value = Pod(
            spec=PodSpec(
                containers=[
                    Container(
                        name=container_name,
                        volumeMounts=[
                            requested_volume.volume_mount for requested_volume in requested_volumes
                        ],
                        resources=ResourceRequirements(),
                    ),
                ],
                volumes=[requested_volume.volume for requested_volume in requested_volumes],
            ),
        )

        is_patched = self.kubernetes_volumes.pod_is_patched(
            pod_name="pod name",
            requested_volumes=requested_volumes,
            container_name=container_name,
        )

        self.assertTrue(is_patched)


class K8sVolumePatchChangedEvent(EventBase):
    """Charm Event triggered when a K8S volume patch is changed."""

    def __init__(self, handle: Handle):
        super().__init__(handle)


class K8sVolumePatchChangedCharmEvents(CharmEvents):
    """K8S volumes config changed events."""

    volumes_config_changed = EventSource(K8sVolumePatchChangedEvent)


class _TestCharmNoVolumes(CharmBase):
    on = K8sVolumePatchChangedCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self.kubernetes_volumes = KubernetesVolumesPatchCharmLib(
            charm=self,
            volumes_to_add_func=self._volumes_to_add_func,
            volumes_to_remove_func=self._volumes_to_remove_func,
            container_name="container-name",
            refresh_event=self.on.volumes_config_changed,
        )

    @staticmethod
    def _volumes_to_add_func() -> list[RequestedVolume]:
        return []

    @staticmethod
    def _volumes_to_remove_func() -> list[RequestedVolume]:
        return []


class _TestCharmAddVolumes(CharmBase):
    on = K8sVolumePatchChangedCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self.kubernetes_volumes = KubernetesVolumesPatchCharmLib(
            charm=self,
            volumes_to_add_func=self._volumes_to_add_func,
            volumes_to_remove_func=self._volumes_to_remove_func,
            container_name="container-name",
            refresh_event=self.on.volumes_config_changed,
        )

    @staticmethod
    def _volumes_to_add_func() -> list[RequestedVolume]:
        return [
            RequestedVolume(
                volume=Volume(
                    name="hugepage-1", emptyDir=EmptyDirVolumeSource(medium="HugePages")
                ),
                volume_mount=VolumeMount(name="hugepage-1", mountPath="/some/other/mountpoint"),
            )
        ]

    @staticmethod
    def _volumes_to_remove_func() -> list[RequestedVolume]:
        return []


class _TestCharmDeleteVolumes(CharmBase):
    on = K8sVolumePatchChangedCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self.kubernetes_volumes = KubernetesVolumesPatchCharmLib(
            charm=self,
            volumes_to_add_func=self._volumes_to_add_func,
            volumes_to_remove_func=self._volumes_to_remove_func,
            container_name="container-name",
            refresh_event=self.on.volumes_config_changed,
        )

    @staticmethod
    def _volumes_to_add_func() -> list[RequestedVolume]:
        return []

    @staticmethod
    def _volumes_to_remove_func() -> list[RequestedVolume]:
        return [
            RequestedVolume(
                volume=Volume(
                    name="hugepage-1", emptyDir=EmptyDirVolumeSource(medium="HugePages")
                ),
                volume_mount=VolumeMount(name="hugepage-1", mountPath="/some/other/mountpoint"),
            )
        ]


class TestKubernetesVolumesPatchCharmLib(unittest.TestCase):
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.patch_volumes")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.pod_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    def test_given_no_add_volumes_when_config_changed_then_add_volumes_is_not_called(
        self,
        patch_patch_volumes,
        patch_statefulset_is_patched,
        patch_pod_is_patched,
    ):
        patch_statefulset_is_patched.return_value = True
        patch_pod_is_patched.return_value = False

        harness = Harness(_TestCharmNoVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.volumes_config_changed.emit()

        patch_patch_volumes.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.remove_volumes")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.pod_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    def test_given_no_delete_volumes_when_config_changed_then_remove_volumes_is_not_called(
        self,
        patch_remove_volumes,
        patch_statefulset_is_patched,
        patch_pod_is_patched,
    ):
        patch_statefulset_is_patched.return_value = False
        patch_pod_is_patched.return_value = False

        harness = Harness(_TestCharmNoVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.volumes_config_changed.emit()

        patch_remove_volumes.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.patch_volumes")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.pod_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    def test_given_no_volumes_then_add_volumes_when_config_changed_then_add_volumes_is_called(
        self,
        patch_patch_volumes,
        patch_statefulset_is_patched,
        patch_pod_is_patched,
    ):
        patch_statefulset_is_patched.return_value = False
        patch_pod_is_patched.return_value = False

        harness = Harness(_TestCharmAddVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.volumes_config_changed.emit()

        patch_patch_volumes.assert_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.pod_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.patch_volumes")
    def test_given_volumes_then_add_volumes_when_config_changed_then_add_volumes_is_not_called(
        self,
        patch_patch_volumes,
        patch_statefulset_is_patched,
        patch_pod_is_patched,
    ):
        patch_statefulset_is_patched.return_value = True
        patch_pod_is_patched.return_value = True

        harness = Harness(_TestCharmAddVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.volumes_config_changed.emit()

        patch_patch_volumes.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.pod_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.remove_volumes")
    def test_given_volumes_then_delete_volumes_when_config_changed_then_remove_volumes_is_called(
        self,
        patch_remove_volumes,
        patch_statefulset_is_patched,
        patch_pod_is_patched,
    ):
        patch_statefulset_is_patched.return_value = True
        patch_pod_is_patched.return_value = True

        harness = Harness(_TestCharmDeleteVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.volumes_config_changed.emit()

        patch_remove_volumes.assert_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.pod_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.remove_volumes")
    def test_given_no_volumes_then_delete_volumes_when_config_changed_then_remove_volumes_is_not_called(  # noqa: E501
        self,
        patch_remove_volumes,
        patch_statefulset_is_patched,
        patch_pod_is_patched,
    ):
        patch_statefulset_is_patched.return_value = False
        patch_pod_is_patched.return_value = False

        harness = Harness(_TestCharmDeleteVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.volumes_config_changed.emit()

        patch_remove_volumes.assert_not_called()
