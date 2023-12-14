# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import Mock, call, patch

import httpx
import pytest
from charms.kubernetes_charm_libraries.v0.multus import (  # type: ignore[import]
    KubernetesClient,
    KubernetesMultusCharmLib,
    KubernetesMultusError,
    NetworkAnnotation,
    NetworkAttachmentDefinition,
)
from lightkube.core.exceptions import ApiError
from lightkube.models.apps_v1 import StatefulSet, StatefulSetSpec
from lightkube.models.core_v1 import (
    Capabilities,
    Container,
    PodSpec,
    PodTemplateSpec,
    SecurityContext,
)
from lightkube.models.meta_v1 import LabelSelector, ObjectMeta
from lightkube.resources.apps_v1 import StatefulSet as StatefulSetResource
from lightkube.resources.core_v1 import Pod
from lightkube.types import PatchType
from ops import EventBase, EventSource, Handle
from ops.charm import CharmBase, CharmEvents
from ops.testing import Harness

MULTUS_LIBRARY_PATH = "charms.kubernetes_charm_libraries.v0.multus"


class TestKubernetes(unittest.TestCase):
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    def setUp(self) -> None:
        self.namespace = "whatever ns"
        self.kubernetes_multus = KubernetesClient(namespace=self.namespace)

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_existing_nad_identical_to_new_one_when_nad_is_created_then_return_true(
        self, patch_get
    ):
        existing_nad = NetworkAttachmentDefinition(metadata=ObjectMeta(name="whatever name"))
        patch_get.return_value = existing_nad

        is_created = self.kubernetes_multus.network_attachment_definition_is_created(
            network_attachment_definition=existing_nad
        )

        self.assertTrue(is_created)

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_notfound_api_error_when_nad_is_created_then_return_false(
        self, patch_get
    ):
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=400, json={"reason": "NotFound"}),
        )

        is_created = self.kubernetes_multus.network_attachment_definition_is_created(
            network_attachment_definition=NetworkAttachmentDefinition(
                metadata=ObjectMeta(name="whatever name")
            )
        )

        self.assertFalse(is_created)

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_unauthorized_api_error_when_nad_is_created_then_return_false(
        self, patch_get
    ):
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=401, json={"reason": "Unauthorized"}),
        )

        is_created = self.kubernetes_multus.network_attachment_definition_is_created(
            network_attachment_definition=NetworkAttachmentDefinition(
                metadata=ObjectMeta(name="whatever name")
            )
        )

        self.assertFalse(is_created)

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_other_api_error_when_nad_is_created_then_custom_exception_is_thrown(  # noqa: E501
        self, patch_get
    ):
        nad_name = "whatever name"
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=400, json={"reason": "whatever reason"}),
        )

        with pytest.raises(KubernetesMultusError) as e:
            self.kubernetes_multus.network_attachment_definition_is_created(
                network_attachment_definition=NetworkAttachmentDefinition(
                    metadata=ObjectMeta(name="whatever name")
                )
            )
        self.assertEqual(
            e.value.message,
            f"Unexpected outcome when retrieving NetworkAttachmentDefinition {nad_name}",
        )

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_404_httpx_error_when_nad_is_created_then_exception_is_thrown(
        self, patch_get
    ):
        patch_get.side_effect = httpx.HTTPStatusError(
            message="error message",
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(
                status_code=404,
            ),
        )

        with pytest.raises(KubernetesMultusError) as e:
            self.kubernetes_multus.network_attachment_definition_is_created(
                network_attachment_definition=NetworkAttachmentDefinition(
                    metadata=ObjectMeta(name="whatever name")
                )
            )
        self.assertEqual(
            e.value.message,
            "NetworkAttachmentDefinition resource not found. "
            "You may need to install Multus CNI.",
        )

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_other_httpx_error_when_nad_is_created_then_exception_is_thrown(
        self, patch_get
    ):
        nad_name = "whatever name"
        patch_get.side_effect = httpx.HTTPStatusError(
            message="error message",
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(
                status_code=405,
            ),
        )

        with pytest.raises(KubernetesMultusError) as e:
            self.kubernetes_multus.network_attachment_definition_is_created(
                network_attachment_definition=NetworkAttachmentDefinition(
                    metadata=ObjectMeta(name="whatever name")
                )
            )
        self.assertEqual(
            e.value.message,
            f"Unexpected outcome when retrieving NetworkAttachmentDefinition {nad_name}",
        )

    @patch("lightkube.core.client.Client.create")
    def test_given_nad_when_create_nad_then_k8s_create_is_called(self, patch_create):
        nad_name = "whatever name"
        nad_spec = {"a": "b"}
        network_attachment_definition = NetworkAttachmentDefinition(
            metadata=ObjectMeta(name=nad_name),
            spec=nad_spec,
        )

        self.kubernetes_multus.create_network_attachment_definition(
            network_attachment_definition=network_attachment_definition
        )

        patch_create.assert_called_with(
            obj=NetworkAttachmentDefinition(
                metadata=ObjectMeta(name=nad_name),
                spec=nad_spec,
            ),
            namespace=self.namespace,
        )

    @patch("lightkube.core.client.Client.patch")
    def test_given_no_annotation_when_patch_statefulset_then_statefulset_is_not_patched(
        self, patch_patch
    ):
        multus_annotations = []

        self.kubernetes_multus.patch_statefulset(
            name="whatever statefulset name",
            network_annotations=multus_annotations,
            container_name="container-name",
            cap_net_admin=False,
            privileged=False,
        )

        patch_patch.assert_not_called()

    @patch("lightkube.core.client.Client.patch")
    @patch("lightkube.core.client.Client.get")
    def test_given_statefulset_doesnt_have_network_annotations_when_patch_statefulset_then_statefulset_is_patched(  # noqa: E501
        self, patch_get, patch_patch
    ):
        container_name = "whatever container name"
        statefulset_name = "whatever statefulset name"
        network_annotations = [
            NetworkAnnotation(interface="whatever interface 1", name="whatever name 1"),
            NetworkAnnotation(interface="whatever interface 2", name="whatever name 2"),
        ]
        initial_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    metadata=ObjectMeta(
                        annotations={},
                    ),
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=container_name,
                                securityContext=SecurityContext(),
                            )
                        ]
                    ),
                ),
            )
        )
        patch_get.return_value = initial_statefulset

        self.kubernetes_multus.patch_statefulset(
            name=statefulset_name,
            network_annotations=network_annotations,
            container_name="container-name",
            cap_net_admin=True,
            privileged=False,
        )

        args, kwargs = patch_patch.call_args
        self.assertEqual(kwargs["res"], StatefulSetResource)
        self.assertEqual(kwargs["name"], statefulset_name)
        self.assertEqual(
            kwargs["obj"].spec.template.metadata.annotations["k8s.v1.cni.cncf.io/networks"],
            json.dumps([network_annotation.dict() for network_annotation in network_annotations]),
        )
        self.assertEqual(
            kwargs["obj"].spec.template.spec.containers[0].securityContext.capabilities.add,
            ["NET_ADMIN"],
        )
        self.assertEqual(kwargs["patch_type"], PatchType.APPLY)
        self.assertEqual(kwargs["namespace"], self.namespace)

    @patch("lightkube.core.client.Client.patch")
    @patch("lightkube.core.client.Client.get")
    def test_given_network_annotations_with_optional_arguments_when_patch_statefulset_without_network_annotations_then_requested_network_annotations_are_added(  # noqa: E501
        self, patch_get, patch_patch
    ):
        container_name = "whatever container name"
        statefulset_name = "whatever statefulset name"
        network_annotations = [
            NetworkAnnotation(
                interface="whatever interface 1",
                name="whatever name 1",
                mac="whatever mac 1",
                ips=["1.2.3.4"],
            ),
            NetworkAnnotation(
                interface="whatever interface 2",
                name="whatever name 2",
                mac="whatever mac 2",
                ips=["4.3.2.1"],
            ),
        ]
        initial_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    metadata=ObjectMeta(
                        annotations={},
                    ),
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=container_name,
                                securityContext=SecurityContext(),
                            )
                        ]
                    ),
                ),
            )
        )
        patch_get.return_value = initial_statefulset

        self.kubernetes_multus.patch_statefulset(
            name=statefulset_name,
            network_annotations=network_annotations,
            container_name="container-name",
            cap_net_admin=True,
            privileged=False,
        )

        args, kwargs = patch_patch.call_args
        self.assertEqual(
            kwargs["obj"].spec.template.metadata.annotations["k8s.v1.cni.cncf.io/networks"],
            json.dumps([network_annotation.dict() for network_annotation in network_annotations]),
        )

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_unauthorized_api_error_when_statefulset_is_patched_then_returns_false(  # noqa: E501
        self, patch_get
    ):
        statefulset_name = "whatever name"
        network_annotations = [
            NetworkAnnotation(interface="whatever interface 1", name="whatever name 1"),
            NetworkAnnotation(interface="whatever interface 2", name="whatever name 2"),
        ]
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=401, json={"reason": "Unauthorized"}),
        )

        is_patched = self.kubernetes_multus.statefulset_is_patched(
            name=statefulset_name,
            network_annotations=network_annotations,
            container_name="container name",
            privileged=False,
            cap_net_admin=False,
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_no_annotations_when_statefulset_is_patched_then_returns_false(self, patch_get):
        statefulset_name = "whatever name"
        network_annotations = [
            NetworkAnnotation(interface="whatever interface 1", name="whatever name 1"),
            NetworkAnnotation(interface="whatever interface 2", name="whatever name 2"),
        ]
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    metadata=ObjectMeta(
                        annotations={},
                    ),
                ),
            )
        )

        is_patched = self.kubernetes_multus.statefulset_is_patched(
            name=statefulset_name,
            network_annotations=network_annotations,
            container_name="container name",
            privileged=False,
            cap_net_admin=False,
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_annotations_are_different_when_statefulset_is_patched_then_returns_false(
        self, patch_get
    ):
        statefulset_name = "whatever name"
        network_annotations_in_statefulset = [
            NetworkAnnotation(interface="whatever interface 1", name="whatever name 1"),
            NetworkAnnotation(interface="whatever interface 2", name="whatever name 2"),
        ]
        network_annotations = [
            NetworkAnnotation(interface="whatever new interface 1", name="whatever new name 1"),
            NetworkAnnotation(interface="whatever new interface 2", name="whatever new name 2"),
        ]
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    metadata=ObjectMeta(
                        annotations={
                            "k8s.v1.cni.cncf.io/networks": json.dumps(
                                [
                                    network_annotation.dict()
                                    for network_annotation in network_annotations_in_statefulset
                                ]
                            )
                        },
                    ),
                ),
            )
        )

        is_patched = self.kubernetes_multus.statefulset_is_patched(
            name=statefulset_name,
            network_annotations=network_annotations,
            container_name="container name",
            privileged=False,
            cap_net_admin=False,
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_annotations_are_already_present_when_statefulset_is_patched_then_returns_true(
        self, patch_get
    ):
        container_name = "whatever"
        statefulset_name = "whatever name"
        network_annotations = [
            NetworkAnnotation(interface="whatever interface 1", name="whatever name 1"),
            NetworkAnnotation(interface="whatever interface 2", name="whatever name 2"),
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
                            )
                        ],
                    ),
                    metadata=ObjectMeta(
                        annotations={
                            "k8s.v1.cni.cncf.io/networks": json.dumps(
                                [
                                    network_annotation.dict()
                                    for network_annotation in network_annotations
                                ]
                            )
                        },
                    ),
                ),
            )
        )

        is_patched = self.kubernetes_multus.statefulset_is_patched(
            name=statefulset_name,
            network_annotations=network_annotations,
            container_name=container_name,
            privileged=False,
            cap_net_admin=False,
        )

        self.assertTrue(is_patched)

    @patch("lightkube.core.client.Client.get")
    def test_given_annotations_are_already_present_and_security_context_is_missing_when_statefulset_is_patched_then_returns_false(  # noqa: E501
        self, patch_get
    ):
        container_name = "whatever container"
        statefulset_name = "whatever name"
        network_annotations = [
            NetworkAnnotation(interface="whatever interface 1", name="whatever name 1"),
            NetworkAnnotation(interface="whatever interface 2", name="whatever name 2"),
        ]
        patch_get.return_value = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="",
                template=PodTemplateSpec(
                    metadata=ObjectMeta(
                        annotations={
                            "k8s.v1.cni.cncf.io/networks": json.dumps(
                                [
                                    network_annotation.dict()
                                    for network_annotation in network_annotations
                                ]
                            )
                        },
                    ),
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=container_name,
                                securityContext=SecurityContext(
                                    capabilities=Capabilities(add=[], drop=[])
                                ),
                            )
                        ]
                    ),
                ),
            )
        )

        is_patched = self.kubernetes_multus.statefulset_is_patched(
            name=statefulset_name,
            network_annotations=network_annotations,
            container_name=container_name,
            privileged=False,
            cap_net_admin=True,
        )

        self.assertFalse(is_patched)

    @patch("lightkube.core.client.Client.delete")
    def test_given_when_delete_nad_then_k8s_delete_is_called(self, patch_delete):
        nad_name = "whatever name"

        self.kubernetes_multus.delete_network_attachment_definition(name=nad_name)

        patch_delete.assert_called_with(
            res=NetworkAttachmentDefinition, name=nad_name, namespace=self.namespace
        )

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_unauthorized_api_error_when_pod_is_ready_then_returns_false(
        self, patch_get
    ):
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=401, json={"reason": "Unauthorized"}),
        )

        is_ready = self.kubernetes_multus.pod_is_ready(
            pod_name="pod name",
            network_annotations=[
                NetworkAnnotation(interface="whatever interface 1", name="whatever name 1")
            ],
            container_name="container-name",
            cap_net_admin=False,
            privileged=False,
        )

        self.assertFalse(is_ready)

    @patch("lightkube.core.client.Client.get")
    def test_given_annotation_not_set_when_pod_is_ready_then_returns_false(self, patch_get):
        patch_get.return_value = Pod(metadata=ObjectMeta(annotations={}))

        is_ready = self.kubernetes_multus.pod_is_ready(
            pod_name="pod name",
            network_annotations=[
                NetworkAnnotation(interface="whatever interface 1", name="whatever name 1")
            ],
            container_name="container-name",
            cap_net_admin=False,
            privileged=False,
        )

        self.assertFalse(is_ready)

    @patch("lightkube.core.client.Client.get")
    def test_given_annotation_badly_set_when_pod_is_ready_then_returns_false(self, patch_get):
        existing_network_annotation = NetworkAnnotation(
            interface="whatever requested interface", name="whatever existing name"
        )
        requested_network_annotation = NetworkAnnotation(
            interface="whatever requested", name="whatever requested name"
        )
        patch_get.return_value = Pod(
            metadata=ObjectMeta(
                annotations={
                    "k8s.v1.cni.cncf.io/networks": json.dumps([existing_network_annotation.dict()])
                }
            )
        )

        is_ready = self.kubernetes_multus.pod_is_ready(
            pod_name="pod name",
            network_annotations=[requested_network_annotation],
            container_name="container-name",
            cap_net_admin=False,
            privileged=False,
        )

        self.assertFalse(is_ready)

    @patch("lightkube.core.client.Client.get")
    def test_given_net_admin_not_set_when_pod_is_ready_then_returns_false(self, patch_get):
        network_annotation = NetworkAnnotation(
            interface="whatever requested interface", name="whatever existing name"
        )
        container_name = "whatever name"
        patch_get.return_value = Pod(
            metadata=ObjectMeta(
                annotations={
                    "k8s.v1.cni.cncf.io/networks": json.dumps([network_annotation.dict()])
                }
            ),
            spec=PodSpec(
                containers=[
                    Container(
                        name=container_name,
                        securityContext=SecurityContext(capabilities=Capabilities(add=[])),
                    ),
                ]
            ),
        )

        is_ready = self.kubernetes_multus.pod_is_ready(
            pod_name="pod name",
            network_annotations=[network_annotation],
            container_name=container_name,
            cap_net_admin=True,
            privileged=False,
        )

        self.assertFalse(is_ready)

    @patch("lightkube.core.client.Client.get")
    def test_given_pod_is_ready_when_pod_is_ready_then_returns_true(self, patch_get):
        network_annotation = NetworkAnnotation(
            interface="whatever requested interface", name="whatever existing name"
        )
        container_name = "whatever name"
        patch_get.return_value = Pod(
            metadata=ObjectMeta(
                annotations={
                    "k8s.v1.cni.cncf.io/networks": json.dumps([network_annotation.dict()])
                }
            ),
            spec=PodSpec(
                containers=[
                    Container(
                        name=container_name,
                        securityContext=SecurityContext(
                            capabilities=Capabilities(add=["NET_ADMIN"])
                        ),
                    ),
                ]
            ),
        )

        is_ready = self.kubernetes_multus.pod_is_ready(
            pod_name="pod name",
            network_annotations=[network_annotation],
            container_name="container-name",
            cap_net_admin=True,
            privileged=False,
        )

        self.assertTrue(is_ready)

    @patch("lightkube.core.client.Client.list")
    def test_given_k8s_returns_list_when_list_network_attachment_definitions_then_same_list_is_returned(  # noqa: E501
        self, patch_list
    ):
        nad_list_return = ["whatever", "list", "content"]
        patch_list.return_value = nad_list_return
        nad_list = self.kubernetes_multus.list_network_attachment_definitions()

        self.assertEqual(
            nad_list,
            nad_list_return,
        )

    @patch("lightkube.core.client.Client.list")
    def test_given_k8s_apierror_when_list_network_attachment_definitions_then_multus_error_is_raised(  # noqa: E501
        self, patch_list
    ):
        patch_list.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=400, json={"reason": "NotFound"}),
        )

        with pytest.raises(KubernetesMultusError):
            self.kubernetes_multus.list_network_attachment_definitions()

    @patch("lightkube.core.client.Client.delete")
    def test_given_pod_is_deleted_when_delete_pod_then_client_delete_is_called_by_pod_name_and_namespace(  # noqa: E501
        self, patch_delete
    ):
        pod_name = "whatever pod"

        self.kubernetes_multus.delete_pod(pod_name)

        patch_delete.assert_called_with(Pod, pod_name, namespace=self.namespace)


class NadConfigChangedEvent(EventBase):
    """Event triggered when an existing network attachment definition is changed."""

    def __init__(self, handle: Handle):
        super().__init__(handle)


class KubernetesMultusCharmEvents(CharmEvents):
    """Kubernetes Multus Charm Events."""

    nad_config_changed = EventSource(NadConfigChangedEvent)


class _TestCharmNoNAD(CharmBase):
    on = KubernetesMultusCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self.network_annotations = []
        self.kubernetes_multus = KubernetesMultusCharmLib(
            charm=self,
            network_attachment_definitions_func=self._network_annotations_func,
            network_annotations=self.network_annotations,
            container_name="container-name",
            refresh_event=self.on.nad_config_changed,
        )

    def _network_annotations_func(self) -> list[NetworkAttachmentDefinition]:
        return []


class _TestCharmMultipleNAD(CharmBase):
    on = KubernetesMultusCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self.container_name = "container-name"
        self.nad_1_name = "nad-1"
        self.nad_1_spec = {
            "config": {
                "cniVersion": "1.2.3",
                "type": "macvlan",
                "ipam": {"type": "static"},
                "capabilities": {"mac": True},
            }
        }
        self.nad_2_name = "nad-2"
        self.nad_2_spec = {
            "config": {
                "cniVersion": "4.5.6",
                "type": "pizza",
                "ipam": {"type": "whatever"},
                "capabilities": {"mac": True},
            }
        }
        self.annotation_1_name = "eth0"
        self.annotation_2_name = "eth1"
        self.network_annotations = [
            NetworkAnnotation(interface=self.nad_1_name, name=self.annotation_1_name),
            NetworkAnnotation(interface=self.nad_2_name, name=self.annotation_2_name),
        ]
        self.kubernetes_multus = KubernetesMultusCharmLib(
            charm=self,
            network_attachment_definitions_func=self.network_attachment_definitions_func,
            network_annotations=self.network_annotations,
            container_name=self.container_name,
            refresh_event=self.on.nad_config_changed,
        )

    def network_attachment_definitions_func(self) -> list[NetworkAttachmentDefinition]:
        return [
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(name=self.nad_1_name),
                spec=self.nad_1_spec,
            ),
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(name=self.nad_2_name),
                spec=self.nad_2_spec,
            ),
        ]


class TestKubernetesMultusCharmLib(unittest.TestCase):
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.list_network_attachment_definitions")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition")
    def test_given_no_nad_to_create_and_no_existing_nad_when_nad_config_changed_then_create_is_not_called(  # noqa: E501
        self, patch_create_nad, patch_existing_nads
    ):
        patch_existing_nads.return_value = []
        harness = Harness(_TestCharmNoNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.nad_config_changed.emit()

        patch_create_nad.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.list_network_attachment_definitions")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition")
    def test_given_nads_already_exist_when_nad_config_changed_then_create_is_not_called(
        self,
        patch_create_nad,
        patch_list_nads,
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_list_nads.return_value = [
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_1_name,
                    labels={"app.juju.is/created-by": harness.charm.app.name},
                ),
                spec=harness.charm.nad_1_spec,
            ),
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_2_name,
                    labels={"app.juju.is/created-by": harness.charm.app.name},
                ),
                spec=harness.charm.nad_2_spec,
            ),
        ]

        harness.charm.on.nad_config_changed.emit()

        patch_create_nad.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.list_network_attachment_definitions")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition")
    def test_given_nads_not_created_when_nad_config_changed_then_nad_create_is_called(
        self, patch_create_nad, patch_list_nads
    ):
        patch_list_nads.return_value = []
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.nad_config_changed.emit()

        patch_create_nad.assert_has_calls(
            calls=[
                call(
                    network_attachment_definition=NetworkAttachmentDefinition(
                        metadata=ObjectMeta(name=harness.charm.nad_1_name),
                        spec=harness.charm.nad_1_spec,
                    )
                ),
                call(
                    network_attachment_definition=NetworkAttachmentDefinition(
                        metadata=ObjectMeta(name=harness.charm.nad_2_name),
                        spec=harness.charm.nad_2_spec,
                    )
                ),
            ]
        )

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.list_network_attachment_definitions")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition")
    def test_given_nads_not_created_when_config_changed_then_nad_create_is_not_called(
        self, patch_create_nad, patch_list_nads
    ):
        patch_list_nads.return_value = []
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.config_changed.emit()

        patch_create_nad.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.list_network_attachment_definitions")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition")
    def test_given_nads_exist_but_created_by_different_charm_when_nad_config_changed_then_nad_create_is_called(  # noqa: E501
        self, patch_create_nad, patch_list_nads
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_list_nads.return_value = [
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_1_name,
                    labels={"app.juju.is/created-by": "different-app"},
                ),
                spec=harness.charm.nad_1_spec,
            ),
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_2_name,
                    labels={"app.juju.is/created-by": "different-app"},
                ),
                spec=harness.charm.nad_2_spec,
            ),
        ]

        harness.charm.on.nad_config_changed.emit()

        patch_create_nad.assert_has_calls(
            calls=[
                call(
                    network_attachment_definition=NetworkAttachmentDefinition(
                        metadata=ObjectMeta(name=harness.charm.nad_1_name),
                        spec=harness.charm.nad_1_spec,
                    )
                ),
                call(
                    network_attachment_definition=NetworkAttachmentDefinition(
                        metadata=ObjectMeta(name=harness.charm.nad_2_name),
                        spec=harness.charm.nad_2_spec,
                    )
                ),
            ]
        )

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.list_network_attachment_definitions")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(
        f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition", new=Mock
    )
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.delete_network_attachment_definition")
    def test_given_nads_exist_but_are_different_when_nad_config_changed_then_nad_delete_is_called(
        self, patch_delete_nad, patch_list_nads
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_list_nads.return_value = [
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_1_name,
                    labels={"app.juju.is/created-by": harness.charm.app.name},
                ),
                spec={"different": "spec"},
            ),
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_2_name,
                    labels={"app.juju.is/created-by": harness.charm.app.name},
                ),
                spec={"different": "spec"},
            ),
        ]

        harness.charm.on.nad_config_changed.emit()

        patch_delete_nad.assert_has_calls(
            calls=[
                call(name=harness.charm.nad_1_name),
                call(name=harness.charm.nad_2_name),
            ]
        )

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.list_network_attachment_definitions")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(
        f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition", new=Mock
    )
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.delete_network_attachment_definition")
    def test_given_nads_exist_but_are_different_when_config_changed_then_nad_delete_is_not_called(
        self, patch_delete_nad, patch_list_nads
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_list_nads.return_value = [
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_1_name,
                    labels={"app.juju.is/created-by": harness.charm.app.name},
                ),
                spec={"different": "spec"},
            ),
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_2_name,
                    labels={"app.juju.is/created-by": harness.charm.app.name},
                ),
                spec={"different": "spec"},
            ),
        ]

        harness.charm.on.config_changed.emit()

        patch_delete_nad.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.delete_pod")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.list_network_attachment_definitions")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(
        f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition", new=Mock
    )
    @patch(
        f"{MULTUS_LIBRARY_PATH}.KubernetesClient.delete_network_attachment_definition", new=Mock
    )
    def test_given_nads_exist_but_they_are_different_when_nad_config_changed_then_pod_delete_is_called_once(  # noqa: E501
        self, patch_list_nads, patch_delete_pod
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_list_nads.return_value = [
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_1_name,
                    labels={"app.juju.is/created-by": harness.charm.app.name},
                ),
                spec={"different": "spec"},
            ),
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_2_name,
                    labels={"app.juju.is/created-by": harness.charm.app.name},
                ),
                spec={"different": "spec"},
            ),
        ]
        harness.charm.on.nad_config_changed.emit()
        patch_delete_pod.assert_called_once()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.delete_pod")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.list_network_attachment_definitions")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(
        f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition", new=Mock
    )
    @patch(
        f"{MULTUS_LIBRARY_PATH}.KubernetesClient.delete_network_attachment_definition", new=Mock
    )
    def test_given_nads_exist_but_they_are_different_when_config_changed_then_pod_delete_is_not_called(  # noqa: E501
        self, patch_list_nads, patch_delete_pod
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_list_nads.return_value = [
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_1_name,
                    labels={"app.juju.is/created-by": harness.charm.app.name},
                ),
                spec={"different": "spec"},
            ),
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_2_name,
                    labels={"app.juju.is/created-by": harness.charm.app.name},
                ),
                spec={"different": "spec"},
            ),
        ]
        harness.charm.on.config_changed.emit()
        patch_delete_pod.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.delete_pod")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.list_network_attachment_definitions")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(
        f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition", new=Mock
    )
    @patch(
        f"{MULTUS_LIBRARY_PATH}.KubernetesClient.delete_network_attachment_definition", new=Mock
    )
    def test_given_nads_exist_but_are_same_when_nad_config_changed_then_pod_delete_is_not_called(
        self, patch_list_nads, patch_delete_pod
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_list_nads.return_value = [
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(name="nad-1"),
                spec={
                    "config": {
                        "cniVersion": "1.2.3",
                        "type": "macvlan",
                        "ipam": {"type": "static"},
                        "capabilities": {"mac": True},
                    }
                },
            ),
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(name="nad-2"),
                spec={
                    "config": {
                        "cniVersion": "4.5.6",
                        "type": "pizza",
                        "ipam": {"type": "whatever"},
                        "capabilities": {"mac": True},
                    }
                },
            ),
        ]
        harness.charm.on.nad_config_changed.emit()
        patch_delete_pod.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.list_network_attachment_definitions")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition")
    def test_given_nads_exist_but_are_different_when_nad_config_changed_then_nad_create_is_called(
        self, patch_create_nad, patch_list_nads
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_list_nads.return_value = [
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_1_name,
                    labels={"app.juju.is/created-by": harness.charm.app.name},
                ),
                spec={"different": "spec"},
            ),
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(
                    name=harness.charm.nad_2_name,
                    labels={"app.juju.is/created-by": harness.charm.app.name},
                ),
                spec={"different": "spec"},
            ),
        ]

        harness.charm.on.nad_config_changed.emit()

        patch_create_nad.assert_has_calls(
            calls=[
                call(
                    network_attachment_definition=NetworkAttachmentDefinition(
                        metadata=ObjectMeta(name=harness.charm.nad_1_name),
                        spec=harness.charm.nad_1_spec,
                    )
                ),
                call(
                    network_attachment_definition=NetworkAttachmentDefinition(
                        metadata=ObjectMeta(name=harness.charm.nad_2_name),
                        spec=harness.charm.nad_2_spec,
                    )
                ),
            ]
        )

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.list_network_attachment_definitions")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    @patch(
        f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition", new=Mock
    )
    def test_given_nads_not_created_when_nad_config_changed_then_patch_statefulset_is_called(
        self, patch_is_statefulset_patched, patch_patch_statefulset, patch_list_nads
    ):
        patch_list_nads.return_value = []
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_is_statefulset_patched.return_value = False

        harness.charm.on.nad_config_changed.emit()

        patch_patch_statefulset.assert_called_with(
            name=harness.charm.app.name,
            network_annotations=[
                NetworkAnnotation(
                    name=harness.charm.annotation_1_name, interface=harness.charm.nad_1_name
                ),
                NetworkAnnotation(
                    name=harness.charm.annotation_2_name, interface=harness.charm.nad_2_name
                ),
            ],
            container_name=harness.charm.container_name,
            cap_net_admin=False,
            privileged=False,
        )

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.unpatch_statefulset")
    def test_statefulset_unpatched_on_remove(self, patch_unpatch_statefulset):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.charm.on.remove.emit()

        patch_unpatch_statefulset.assert_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.delete_network_attachment_definition")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.network_attachment_definition_is_created")
    def test_given_nad_is_created_when_remove_then_network_attachment_definitions_are_deleted(
        self, patch_is_nad_created, patch_delete_network_attachment_definition
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_is_nad_created.return_value = True

        harness.charm.on.remove.emit()

        patch_delete_network_attachment_definition.assert_has_calls(
            calls=[
                call(name=harness.charm.nad_1_name),
                call(name=harness.charm.nad_2_name),
            ]
        )

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.delete_network_attachment_definition")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.network_attachment_definition_is_created")
    def test_given_nad_is_not_created_when_remove_then_network_attachment_definitions_are_not_deleted(  # noqa: E501
        self, patch_is_nad_created, patch_delete_network_attachment_definition
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_is_nad_created.return_value = False

        harness.charm.on.remove.emit()

        patch_delete_network_attachment_definition.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.delete_network_attachment_definition")
    @patch(
        f"{MULTUS_LIBRARY_PATH}.KubernetesClient.network_attachment_definition_is_created",
        new=Mock,
    )
    def test_given_no_nad_when_remove_then_network_attachment_definitions_are_not_deleted(
        self, patch_delete_network_attachment_definition
    ):
        harness = Harness(_TestCharmNoNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.remove.emit()

        patch_delete_network_attachment_definition.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.pod_is_ready")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.network_attachment_definition_is_created")
    def test_given_pod_not_ready_when_is_ready_then_return_false(
        self,
        patch_nad_is_created,
        patch_statefulest_is_patched,
        patch_pod_is_ready,
    ):
        patch_nad_is_created.return_value = True
        patch_statefulest_is_patched.return_value = True
        patch_pod_is_ready.return_value = False

        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()

        is_ready = harness.charm.kubernetes_multus.is_ready()
        self.assertFalse(is_ready)

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.pod_is_ready")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.network_attachment_definition_is_created")
    def test_given_pod_is_ready_when_is_ready_then_return_false(
        self,
        patch_nad_is_created,
        patch_statefulest_is_patched,
        patch_pod_is_ready,
    ):
        patch_nad_is_created.return_value = True
        patch_statefulest_is_patched.return_value = True
        patch_pod_is_ready.return_value = True

        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()

        is_ready = harness.charm.kubernetes_multus.is_ready()
        self.assertTrue(is_ready)

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.delete_pod")
    def test_given_pod_is_deleted_when_multus_delete_pod_then_k8s_client_delete_pod_is_called(
        self, patch_delete
    ):  # noqa: E501
        harness = Harness(_TestCharmNoNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.charm.kubernetes_multus.delete_pod()
        patch_delete.assert_called_once()
