# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from unittest.mock import Mock, patch

import httpx
from charms.kubernetes_charm_libraries.v0.kubernetes_hugepages_volumes_patch import (  # type: ignore[import]  # noqa E501
    ContainerNotFoundError,
    KubernetesClient,
    KubernetesHugePagesPatchCharmLib,
    KubernetesHugePagesVolumesPatchError,
    RequestedHugePages,
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
from lightkube.resources.core_v1 import Pod
from ops import EventBase, EventSource
from ops.charm import CharmBase, CharmEvents
from ops.testing import Harness

VOLUMES_LIBRARY_PATH = "charms.kubernetes_charm_libraries.v0.kubernetes_hugepages_volumes_patch"

CONTAINER_NAME = "whatever container name"
STATEFULSET_NAME = "whatever statefulset name"


class TestKubernetes(unittest.TestCase):
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    def setUp(self) -> None:
        self.namespace = "whatever ns"
        self.kubernetes_volumes = KubernetesClient(namespace=self.namespace)

    @patch("lightkube.core.client.Client.replace")
    def test_given_no_requested_volume_when_replace_statefulset_then_statefulset_is_not_replaced(
        self, patch_replace
    ):
        requested_volumes = []

        self.kubernetes_volumes.replace_statefulset(
            statefulset_name=STATEFULSET_NAME,
            requested_volumes=requested_volumes,
            requested_volumemounts=[],
            requested_resources=ResourceRequirements(),
            container_name=CONTAINER_NAME,
        )

        patch_replace.assert_not_called()

    @patch("lightkube.core.client.Client.replace")
    def test_given_no_requested_volumemonuts_when_replace_statefulset_then_statefulset_is_not_replaced(  # noqa: E501
        self, patch_replace
    ):
        requested_volumes = [
            Volume(name="a-volume", emptyDir=EmptyDirVolumeSource(medium="a-medium")),
        ]

        self.kubernetes_volumes.replace_statefulset(
            statefulset_name=STATEFULSET_NAME,
            requested_volumes=requested_volumes,
            requested_volumemounts=[],
            requested_resources=ResourceRequirements(),
            container_name=CONTAINER_NAME,
        )

        patch_replace.assert_not_called()

    @patch("lightkube.core.client.Client.replace")
    @patch("lightkube.core.client.Client.get")
    def test_given_statefulset_doesnt_have_requested_volumes_when_replace_statefulset_then_statefulset_is_replaced(  # noqa: E501
        self, patch_get, patch_replace
    ):
        requested_volumes = [
            Volume(name="a-volume", emptyDir=EmptyDirVolumeSource(medium="a-medium")),
        ]
        requested_volumemounts = [
            VolumeMount(
                name="a-volume-mount",
                mountPath="/some/mountpath",
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
                                name=CONTAINER_NAME,
                                volumeMounts=[],
                                resources=ResourceRequirements(),
                            )
                        ],
                        volumes=[],
                    ),
                ),
            )
        )
        patch_get.return_value = initial_statefulset

        self.kubernetes_volumes.replace_statefulset(
            statefulset_name=STATEFULSET_NAME,
            requested_volumes=requested_volumes,
            requested_resources=ResourceRequirements(),
            requested_volumemounts=requested_volumemounts,
            container_name=CONTAINER_NAME,
        )
        patch_replace.assert_called()

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_api_error_when_replace_statefulset_then_custom_exception_is_raised(  # noqa: E501
        self,
        patch_get,
    ):
        requested_volumes = [
            Volume(name="a-volume", emptyDir=EmptyDirVolumeSource(medium="a-medium")),
        ]
        requested_volumemounts = [
            VolumeMount(
                name="a-volume-mount",
                mountPath="/some/mountpath",
            )
        ]
        requested_resources = ResourceRequirements()
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=500, json={"reason": "Internal Server Error"}),
        )
        with self.assertRaises(KubernetesHugePagesVolumesPatchError):
            self.kubernetes_volumes.replace_statefulset(
                statefulset_name=STATEFULSET_NAME,
                requested_volumes=requested_volumes,
                requested_volumemounts=requested_volumemounts,
                requested_resources=requested_resources,
                container_name=CONTAINER_NAME,
            )

    @patch("lightkube.core.client.Client.replace")
    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_replace_throws_api_error_when_replace_statefulset_then_custom_exception_is_raised(  # noqa: E501
        self, patch_get, patch_replace
    ):
        requested_volumes = [
            Volume(name="a-volume", emptyDir=EmptyDirVolumeSource(medium="a-medium")),
        ]
        requested_volumemounts = [
            VolumeMount(
                name="a-volume-mount",
                mountPath="/some/mountpath",
            )
        ]
        requested_resources = ResourceRequirements()
        initial_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[Container(name=CONTAINER_NAME)],
                        volumes=[],
                    ),
                ),
            )
        )
        patch_get.return_value = initial_statefulset
        patch_replace.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=500, json={"reason": "Internal Server Error"}),
        )
        with self.assertRaises(KubernetesHugePagesVolumesPatchError):
            self.kubernetes_volumes.replace_statefulset(
                statefulset_name=STATEFULSET_NAME,
                requested_volumes=requested_volumes,
                requested_volumemounts=requested_volumemounts,
                requested_resources=requested_resources,
                container_name=CONTAINER_NAME,
            )

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_unhandled_api_error_when_statefulset_is_patched_then_custom_exception_is_raised(  # noqa: E501
        self, patch_get
    ):
        requested_volumes = [
            Volume(name="a-volume", emptyDir=EmptyDirVolumeSource(medium="a-medium")),
        ]
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=500, json={"reason": "Internal Server Error"}),
        )
        with self.assertRaises(KubernetesHugePagesVolumesPatchError):
            self.kubernetes_volumes.statefulset_is_patched(
                statefulset_name=STATEFULSET_NAME,
                requested_volumes=requested_volumes,
            )

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_unauthorized_api_error_when_statefulset_is_patched_then_returns_false(  # noqa: E501
        self, patch_get
    ):
        requested_volumes = [
            Volume(name="a-volume", emptyDir=EmptyDirVolumeSource(medium="a-medium")),
        ]
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=401, json={"reason": "Unauthorized"}),
        )

        statefulset_is_patched = self.kubernetes_volumes.statefulset_is_patched(
            statefulset_name=STATEFULSET_NAME,
            requested_volumes=requested_volumes,
        )

        self.assertFalse(statefulset_is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_no_requested_volumes_when_statefulset_is_patched_then_returns_false(
        self, patch_get
    ):
        requested_volumes = [
            Volume(name="a-volume", emptyDir=EmptyDirVolumeSource(medium="a-medium")),
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
            statefulset_name=STATEFULSET_NAME,
            requested_volumes=requested_volumes,
        )

        self.assertFalse(statefulset_is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_requested_volumes_are_different_when_statefulset_is_patched_then_returns_false(
        self, patch_get
    ):
        requested_volumes_in_statefulset = [
            Volume(name="a-volume-existing", emptyDir=EmptyDirVolumeSource(medium="a-medium")),
        ]
        requested_volumes = [
            Volume(name="a-volume-new", emptyDir=EmptyDirVolumeSource(medium="a-medium")),
        ]
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[],
                        volumes=requested_volumes_in_statefulset,
                    )
                ),
            )
        )

        statefulset_is_patched = self.kubernetes_volumes.statefulset_is_patched(
            statefulset_name=STATEFULSET_NAME,
            requested_volumes=requested_volumes,
        )

        self.assertFalse(statefulset_is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_requested_volumes_are_already_present_when_statefulset_is_patched_then_returns_true(  # noqa: E501
        self, patch_get
    ):
        requested_volumes = [
            Volume(name="a-volume", emptyDir=EmptyDirVolumeSource(medium="a-medium"))
        ]
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[],
                        volumes=requested_volumes,
                    ),
                ),
            )
        )

        statefulset_is_patched = self.kubernetes_volumes.statefulset_is_patched(
            statefulset_name=STATEFULSET_NAME,
            requested_volumes=requested_volumes,
        )

        self.assertTrue(statefulset_is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_unhandled_api_error_when_pod_is_patched_then_custom_exception_is_raised(  # noqa: E501
        self, patch_get
    ):
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=500, json={"reason": "Internal Server Error"}),
        )
        requested_volumemounts = [
            VolumeMount(
                name="a-volume-mount",
                mountPath="/some/mountpath",
            )
        ]
        with self.assertRaises(KubernetesHugePagesVolumesPatchError):
            self.kubernetes_volumes.pod_is_patched(
                pod_name="pod name",
                requested_volumemounts=requested_volumemounts,
                requested_resources=ResourceRequirements(),
                container_name=CONTAINER_NAME,
            )

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_unauthorized_api_error_when_pod_is_patched_then_returns_false(
        self, patch_get
    ):
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=401, json={"reason": "Unauthorized"}),
        )
        requested_volumemounts = [
            VolumeMount(
                name="a-volume-mount",
                mountPath="/some/mountpath",
            )
        ]
        is_patched = self.kubernetes_volumes.pod_is_patched(
            pod_name="pod name",
            requested_volumemounts=requested_volumemounts,
            requested_resources=ResourceRequirements(),
            container_name=CONTAINER_NAME,
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_requested_volumemount_not_set_when_pod_is_patched_then_returns_false(
        self, patch_get
    ):
        patch_get.return_value = Pod(
            spec=PodSpec(
                containers=[
                    Container(
                        name=CONTAINER_NAME,
                        volumeMounts=[],
                        resources=ResourceRequirements(),
                    )
                ],
                volumes=[],
            )
        )

        requested_volumemounts = [
            VolumeMount(
                name="a-volume",
                mountPath="/some/mountpath",
            )
        ]

        is_patched = self.kubernetes_volumes.pod_is_patched(
            pod_name="pod name",
            requested_volumemounts=requested_volumemounts,
            requested_resources=ResourceRequirements(),
            container_name=CONTAINER_NAME,
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_requested_resources_not_set_when_pod_is_patched_then_returns_false(
        self, patch_get
    ):
        requested_volumemounts = [
            VolumeMount(
                name="a-volume",
                mountPath="/some/mountpath",
            )
        ]
        requested_resource_requirements = ResourceRequirements(
            limits={"a-key": "a-value"},
        )
        patch_get.return_value = Pod(
            spec=PodSpec(
                containers=[
                    Container(
                        name=CONTAINER_NAME,
                        volumeMounts=requested_volumemounts,
                        resources=ResourceRequirements(),
                    )
                ],
                volumes=[],
            )
        )

        is_patched = self.kubernetes_volumes.pod_is_patched(
            pod_name="pod name",
            requested_volumemounts=requested_volumemounts,
            requested_resources=requested_resource_requirements,
            container_name=CONTAINER_NAME,
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_pod_is_patched_when_pod_is_patched_then_returns_true(self, patch_get):
        requested_volumemounts = [
            VolumeMount(
                name="a-volume-mount",
                mountPath="/some/mountpath",
            )
        ]
        requested_resources = ResourceRequirements(limits={"a-limit": "a-value"})
        patch_get.return_value = Pod(
            spec=PodSpec(
                containers=[
                    Container(
                        name=CONTAINER_NAME,
                        volumeMounts=requested_volumemounts,
                        resources=requested_resources,
                    ),
                ],
                volumes=[],
            ),
        )

        is_patched = self.kubernetes_volumes.pod_is_patched(
            pod_name="pod name",
            requested_volumemounts=requested_volumemounts,
            requested_resources=requested_resources,
            container_name=CONTAINER_NAME,
        )

        self.assertTrue(is_patched)

    def test_given_pod_resources_are_not_set_when_pod_resources_are_set_then_returns_false(
        self,
    ):
        current_resource = ResourceRequirements(
            limits={"a-limit": "a-value"}, requests={"a-request": "a-value"}
        )
        expected_resources = ResourceRequirements(
            limits={"a-limit": "another-value"},
        )
        containers = [
            Container(
                name=CONTAINER_NAME,
                resources=current_resource,
            )
        ]

        pod_resources_are_set = self.kubernetes_volumes._pod_resources_are_set(
            containers=containers,
            container_name=CONTAINER_NAME,
            requested_resources=expected_resources,
        )

        self.assertFalse(pod_resources_are_set)

    def test_given_container_not_existing_the_get_container_raises(self):
        container_list = [Container(name="a-container")]
        with self.assertRaises(ContainerNotFoundError):
            self.kubernetes_volumes._get_container(
                container_name="a-nonexistent-container",
                containers=container_list,
            )

    @patch("lightkube.core.client.Client.get")
    def test_list_volumes_returns_statefulset_volumes(self, patch_get):
        expected_volumes = [
            Volume(
                name="a-volume",
                emptyDir=EmptyDirVolumeSource(
                    medium="a-medium",
                ),
            )
        ]
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[],
                        volumes=expected_volumes,
                    ),
                ),
            )
        )
        volumes = self.kubernetes_volumes.list_volumes(
            statefulset_name=STATEFULSET_NAME,
        )
        self.assertEqual(volumes, expected_volumes)

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_api_error_when_list_volumes_then_custom_exception_is_raised(
        self, patch_get
    ):
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=500, json={"reason": "Internal Server Error"}),
        )
        with self.assertRaises(KubernetesHugePagesVolumesPatchError):
            self.kubernetes_volumes.list_volumes(
                statefulset_name=STATEFULSET_NAME,
            )

    @patch("lightkube.core.client.Client.get")
    def test_list_volumemounts_returns_volumemounts(self, patch_get):
        expected_volumemounts = [
            VolumeMount(
                name="a-volume-mount",
                mountPath="/some/mountpath",
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
                                name=CONTAINER_NAME,
                                volumeMounts=expected_volumemounts,
                                resources=ResourceRequirements(),
                            )
                        ],
                        volumes=[],
                    ),
                ),
            )
        )
        volumemounts = self.kubernetes_volumes.list_volumemounts(
            statefulset_name=STATEFULSET_NAME,
            container_name=CONTAINER_NAME,
        )
        self.assertEqual(volumemounts, expected_volumemounts)

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_api_error_when_list_volumemounts_then_custom_exception_is_raised(
        self, patch_get
    ):
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=500, json={"reason": "Internal Server Error"}),
        )
        with self.assertRaises(KubernetesHugePagesVolumesPatchError):
            self.kubernetes_volumes.list_volumemounts(
                statefulset_name=STATEFULSET_NAME,
                container_name=CONTAINER_NAME,
            )

    @patch("lightkube.core.client.Client.get")
    def test_list_container_resources_returns_container_resource_requirements(self, patch_get):
        expected_resource_requirements = ResourceRequirements(limits={"a-limit": "a-value"})
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=CONTAINER_NAME,
                                volumeMounts=[],
                                resources=expected_resource_requirements,
                            )
                        ],
                        volumes=[],
                    ),
                ),
            )
        )
        resource_requirements = self.kubernetes_volumes.list_container_resources(
            statefulset_name=STATEFULSET_NAME,
            container_name=CONTAINER_NAME,
        )
        self.assertEqual(resource_requirements, expected_resource_requirements)

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_api_error_when_list_container_resources_then_custom_exception_is_raised(  # noqa: E501
        self, patch_get
    ):
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=500, json={"reason": "Internal Server Error"}),
        )
        with self.assertRaises(KubernetesHugePagesVolumesPatchError):
            self.kubernetes_volumes.list_container_resources(
                statefulset_name=STATEFULSET_NAME,
                container_name=CONTAINER_NAME,
            )


class K8sHugePagesVolumePatchChangedEvent(EventBase):
    """Charm Event triggered when a K8S HugePages volume is changed."""


class K8sHugePagesVolumePatchChangedCharmEvents(CharmEvents):
    """K8S hugepages config changed events."""

    hugepages_volumes_config_changed = EventSource(K8sHugePagesVolumePatchChangedEvent)


class _TestCharmNoVolumes(CharmBase):
    on = K8sHugePagesVolumePatchChangedCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self.kubernetes_volumes = KubernetesHugePagesPatchCharmLib(
            charm=self,
            hugepages_volumes_func=self._volumes_func,
            container_name=CONTAINER_NAME,
            refresh_event=self.on.hugepages_volumes_config_changed,
        )

    @staticmethod
    def _volumes_func() -> list[RequestedHugePages]:
        return []


class _TestCharmAddVolumes(CharmBase):
    on = K8sHugePagesVolumePatchChangedCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self.kubernetes_volumes = KubernetesHugePagesPatchCharmLib(
            charm=self,
            hugepages_volumes_func=self._volumes_func,
            container_name=CONTAINER_NAME,
            refresh_event=self.on.hugepages_volumes_config_changed,
        )

    @staticmethod
    def _volumes_func() -> list[RequestedHugePages]:
        return [
            RequestedHugePages(
                mount_path="/dev/hugepages",
                size="1Gi",
                limit="4Gi",
            )
        ]


class TestKubernetesHugePagesPatchCharmLib(unittest.TestCase):
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.pod_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.replace_statefulset")
    def test_given_no_hugepages_and_no_existing_hugepages_when_huge_config_changed_then_replace_is_not_called(  # noqa: E501
        self,
        patch_replace_statefulset,
        patch_statefulset_is_patched,
        patch_pod_is_patched,
    ):
        patch_pod_is_patched.return_value = True
        patch_statefulset_is_patched.return_value = True
        harness = Harness(_TestCharmNoVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.hugepages_volumes_config_changed.emit()

        patch_replace_statefulset.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.pod_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.replace_statefulset")
    def test_given_no_hugepages_and_existing_hugepages_when_huge_config_changed_then_replace_is_called(  # noqa: E501
        self,
        patch_replace_statefulset,
        patch_statefulset_is_patched,
        patch_pod_is_patched,
        patch_get,
    ):
        current_volumes = [
            Volume(name="hugepages-1gi", emptyDir=EmptyDirVolumeSource(medium="HugePages-1Gi"))
        ]
        current_volumemounts = [VolumeMount(name="hugepages-1gi", mountPath="/dev/hugepages")]
        current_resources = ResourceRequirements(
            limits={"hugepages-1gi": "4Gi"},
            requests={"hugepages-1gi": "4Gi"},
        )
        current_podspec = PodSpec(
            containers=[
                Container(
                    name=CONTAINER_NAME,
                    volumeMounts=current_volumemounts,
                    resources=current_resources,
                )
            ],
            volumes=current_volumes,
        )
        current_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=current_podspec,
                ),
            )
        )
        patch_get.side_effect = [
            current_statefulset,
            current_statefulset,
            current_statefulset,
            current_podspec,
        ]
        patch_pod_is_patched.return_value = False
        patch_statefulset_is_patched.return_value = False
        harness = Harness(_TestCharmNoVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.hugepages_volumes_config_changed.emit()

        patch_replace_statefulset.assert_called_with(
            statefulset_name=harness.charm.app.name,
            container_name=CONTAINER_NAME,
            requested_volumes=[],
            requested_volumemounts=[],
            requested_resources=ResourceRequirements(claims=None, limits={}, requests={}),
        )

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.pod_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.replace_statefulset")
    def test_given_hugepages_and_no_existing_hugepages_when_huge_config_changed_then_replace_is_called(  # noqa: E501
        self,
        patch_replace_statefulset,
        patch_statefulset_is_patched,
        patch_pod_is_patched,
        patch_get,
    ):
        expected_volumes = [
            Volume(
                name="hugepages-1gi",
                emptyDir=EmptyDirVolumeSource(medium="HugePages-1Gi"),
            )
        ]
        expected_volumemounts = [
            VolumeMount(
                name="hugepages-1gi",
                mountPath="/dev/hugepages",
            )
        ]
        expected_resources = ResourceRequirements(
            limits={"hugepages-1Gi": "4Gi"},
            requests={"hugepages-1Gi": "4Gi"},
        )
        current_podspec = PodSpec(
            containers=[
                Container(
                    name=CONTAINER_NAME,
                    volumeMounts=[],
                    resources=ResourceRequirements(),
                )
            ],
            volumes=[],
        )
        current_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=current_podspec,
                ),
            )
        )
        patch_get.side_effect = [
            current_statefulset,
            current_statefulset,
            current_statefulset,
            current_podspec,
        ]
        patch_pod_is_patched.return_value = False
        patch_statefulset_is_patched.return_value = False
        harness = Harness(_TestCharmAddVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.hugepages_volumes_config_changed.emit()

        patch_replace_statefulset.assert_called_with(
            statefulset_name=harness.charm.app.name,
            container_name=CONTAINER_NAME,
            requested_volumes=expected_volumes,
            requested_volumemounts=expected_volumemounts,
            requested_resources=expected_resources,
        )

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch("lightkube.core.client.Client.get")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.pod_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    @patch(f"{VOLUMES_LIBRARY_PATH}.KubernetesClient.replace_statefulset")
    def test_given_hugepages_and_existing_volumes_when_huge_config_changed_then_replace_is_called_all_volumes_are_kept(  # noqa: E501
        self,
        patch_replace_statefulset,
        patch_statefulset_is_patched,
        patch_pod_is_patched,
        patch_get,
    ):
        current_volumes = [
            Volume(name="a-volume", emptyDir=EmptyDirVolumeSource(medium="a-medium"))
        ]
        current_volumemounts = [
            VolumeMount(
                name="a-volume",
                mountPath="/some/mountpath",
            )
        ]
        current_resources = ResourceRequirements(
            limits={"a-limit": "a-value"},
            requests={"a-request": "a-value"},
        )
        expected_volumes = [
            Volume(
                name="hugepages-1gi",
                emptyDir=EmptyDirVolumeSource(medium="HugePages-1Gi"),
            )
        ]
        expected_volumemounts = [
            VolumeMount(
                name="hugepages-1gi",
                mountPath="/dev/hugepages",
            )
        ]
        expected_resources = ResourceRequirements(
            limits={"a-limit": "a-value", "hugepages-1Gi": "4Gi"},
            requests={"a-request": "a-value", "hugepages-1Gi": "4Gi"},
        )
        current_podspec = PodSpec(
            containers=[
                Container(
                    name=CONTAINER_NAME,
                    volumeMounts=current_volumemounts,
                    resources=current_resources,
                )
            ],
            volumes=current_volumes,
        )
        current_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    spec=current_podspec,
                ),
            )
        )
        patch_get.side_effect = [
            current_statefulset,
            current_statefulset,
            current_statefulset,
            current_podspec,
        ]
        patch_pod_is_patched.return_value = False
        patch_statefulset_is_patched.return_value = False
        harness = Harness(_TestCharmAddVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.hugepages_volumes_config_changed.emit()

        patch_replace_statefulset.assert_called_with(
            statefulset_name=harness.charm.app.name,
            container_name=CONTAINER_NAME,
            requested_volumes=expected_volumes + current_volumes,
            requested_volumemounts=expected_volumemounts + current_volumemounts,
            requested_resources=expected_resources,
        )

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    def test_given_hugepages_when_generate_resources_then_hugepages_resources_are_correctly_generated(  # noqa: E501
        self,
    ):
        harness = Harness(_TestCharmAddVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()
        generated_resources = (
            harness.charm.kubernetes_volumes._generate_resource_requirements_from_requested_hugepage()  # noqa: E501
        )

        self.assertEqual(
            generated_resources,
            ResourceRequirements(
                limits={"hugepages-1Gi": "4Gi"},
                requests={
                    "hugepages-1Gi": "4Gi",
                },
            ),
        )

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    def test_given_hugepages_when_generate_volumes_then_hugepages_volumes_are_correctly_generated(
        self,
    ):
        harness = Harness(_TestCharmAddVolumes)
        self.addCleanup(harness.cleanup)
        harness.begin()
        generated_volumes = (
            harness.charm.kubernetes_volumes._generate_volumes_from_requested_hugepage()
        )

        self.assertEqual(
            generated_volumes,
            [Volume(name="hugepages-1gi", emptyDir=EmptyDirVolumeSource(medium="HugePages-1Gi"))],
        )
