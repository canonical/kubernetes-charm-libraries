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
    Pod,
    PodSpec,
    PodTemplateSpec,
    SecurityContext,
)
from lightkube.models.meta_v1 import LabelSelector, ObjectMeta
from lightkube.resources.apps_v1 import StatefulSet as StatefulSetResource
from lightkube.types import PatchType
from ops.charm import CharmBase
from ops.testing import Harness

MULTUS_LIBRARY_PATH = "charms.kubernetes_charm_libraries.v0.multus"


class TestKubernetes(unittest.TestCase):
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    def setUp(self) -> None:
        self.namespace = "whatever ns"
        self.kubernetes_multus = KubernetesClient(namespace=self.namespace)

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_doesnt_throw_error_when_nad_is_created_then_return_true(
        self, patch_get
    ):
        patch_get.return_value = Mock()

        is_created = self.kubernetes_multus.network_attachment_definition_is_created(
            name="whatever name"
        )

        assert is_created

    @patch("lightkube.core.client.Client.get")
    def test_given_k8s_get_throws_notfound_api_error_when_nad_is_created_then_return_false(
        self, patch_get
    ):
        patch_get.side_effect = ApiError(
            request=httpx.Request(method="GET", url="http://whatever.com"),
            response=httpx.Response(status_code=400, json={"reason": "NotFound"}),
        )

        is_created = self.kubernetes_multus.network_attachment_definition_is_created(
            name="whatever name"
        )

        assert not is_created

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
            self.kubernetes_multus.network_attachment_definition_is_created(name=nad_name)
        self.assertEqual(
            e.value.message,
            f"Unexpected outcome when retrieving network attachment definition {nad_name}",
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
            self.kubernetes_multus.network_attachment_definition_is_created(name="whatever name")
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
            self.kubernetes_multus.network_attachment_definition_is_created(name=nad_name)
        self.assertEqual(
            e.value.message,
            f"Unexpected outcome when retrieving network attachment definition {nad_name}",
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
            obj={"metadata": ObjectMeta(name=nad_name), "spec": nad_spec}, namespace=self.namespace
        )

    @patch("lightkube.core.client.Client.patch")
    def test_given_no_annotation_when_patch_statefulset_then_statefulset_is_not_patched(
        self, patch_patch
    ):
        multus_annotations = []

        self.kubernetes_multus.patch_statefulset(
            name="whatever statefulset name",
            network_annotations=multus_annotations,
            containers_requiring_net_admin_capability=[],
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
            containers_requiring_net_admin_capability=[container_name],
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
            containers_requiring_net_admin_capability=[],
        )

        assert not is_patched

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
            containers_requiring_net_admin_capability=[],
        )

        assert not is_patched

    @patch("lightkube.core.client.Client.get")
    def test_given_annotations_are_already_present_when_statefulset_is_patched_then_returns_true(
        self, patch_get
    ):
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
                        containers=[],
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
            containers_requiring_net_admin_capability=[],
        )

        assert is_patched

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
            containers_requiring_net_admin_capability=[container_name],
        )

        assert not is_patched

    @patch("lightkube.core.client.Client.delete")
    def test_given_when_delete_nad_then_k8s_delete_is_called(self, patch_delete):
        nad_name = "whatever name"

        self.kubernetes_multus.delete_network_attachment_definition(name=nad_name)

        patch_delete.assert_called_with(
            res=NetworkAttachmentDefinition, name=nad_name, namespace=self.namespace
        )

    @patch("lightkube.core.client.Client.get")
    def test_given_annotation_not_set_when_pod_is_ready_then_returns_false(self, patch_get):
        patch_get.return_value = Pod(metadata=ObjectMeta(annotations={}))

        is_ready = self.kubernetes_multus.pod_is_ready(
            pod_name="pod name",
            network_annotations=[
                NetworkAnnotation(interface="whatever interface 1", name="whatever name 1")
            ],
            containers_requiring_net_admin_capability=[],
        )

        self.assertEqual(False, is_ready)

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
            containers_requiring_net_admin_capability=[],
        )

        self.assertEqual(False, is_ready)

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
            containers_requiring_net_admin_capability=[container_name],
        )

        self.assertEqual(False, is_ready)

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
            containers_requiring_net_admin_capability=[container_name],
        )

        self.assertEqual(True, is_ready)


class _TestCharmNoNAD(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.kubernetes_multus = KubernetesMultusCharmLib(
            charm=self,
            network_attachment_definitions=[],
            network_annotations_func=self._network_annotations_func,
            containers_requiring_net_admin_capability=[],
        )

    def _network_annotations_func(self) -> list[NetworkAnnotation]:
        return []


class _TestCharmMultipleNAD(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
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
        nad_1 = NetworkAttachmentDefinition(
            metadata=ObjectMeta(name=self.nad_1_name),
            spec=self.nad_1_spec,
        )
        nad_2 = NetworkAttachmentDefinition(
            metadata=ObjectMeta(name=self.nad_2_name),
            spec=self.nad_2_spec,
        )
        self.network_attachment_definitions = [nad_1, nad_2]
        self.kubernetes_multus = KubernetesMultusCharmLib(
            charm=self,
            network_attachment_definitions=self.network_attachment_definitions,
            network_annotations_func=self._network_annotations_func,
        )

    def _network_annotations_func(self) -> list[NetworkAnnotation]:
        return [
            NetworkAnnotation(interface=self.nad_1_name, name=self.annotation_1_name),
            NetworkAnnotation(interface=self.nad_2_name, name=self.annotation_2_name),
        ]


class TestKubernetesMultusCharmLib(unittest.TestCase):
    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition")
    def test_given_no_nad_when_config_changed_then_create_is_not_called(self, patch_create_nad):
        harness = Harness(_TestCharmNoNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()

        harness.charm.on.config_changed.emit()

        patch_create_nad.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.network_attachment_definition_is_created")
    def test_given_multiple_nads_already_exist_when_config_changed_then_create_is_not_called(
        self, patch_is_nad_created, patch_create_nad
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_is_nad_created.return_value = True

        harness.charm.on.config_changed.emit()

        patch_create_nad.assert_not_called()

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.network_attachment_definition_is_created")
    def test_given_nads_not_created_when_config_changed_then_create_is_called(
        self,
        patch_is_nad_created,
        patch_create_nad,
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_is_nad_created.return_value = False

        harness.charm.on.config_changed.emit()

        patch_create_nad.assert_has_calls(
            calls=[
                call(
                    network_attachment_definition={
                        "metadata": ObjectMeta(name=harness.charm.nad_1_name),
                        "spec": harness.charm.nad_1_spec,
                    }
                ),
                call(
                    network_attachment_definition={
                        "metadata": ObjectMeta(name=harness.charm.nad_2_name),
                        "spec": harness.charm.nad_2_spec,
                    }
                ),
            ]
        )

    @patch("lightkube.core.client.GenericSyncClient", new=Mock)
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.patch_statefulset")
    @patch(f"{MULTUS_LIBRARY_PATH}.KubernetesClient.statefulset_is_patched")
    @patch(
        f"{MULTUS_LIBRARY_PATH}.KubernetesClient.create_network_attachment_definition", new=Mock
    )
    @patch(
        f"{MULTUS_LIBRARY_PATH}.KubernetesClient.network_attachment_definition_is_created",
        new=Mock,
    )
    def test_given_nads_not_created_when_config_changed_then_patch_statefulset_create_is_called(
        self, patch_is_statefulset_patched, patch_patch_statefulset
    ):
        harness = Harness(_TestCharmMultipleNAD)
        self.addCleanup(harness.cleanup)
        harness.begin()
        patch_is_statefulset_patched.return_value = False

        harness.charm.on.config_changed.emit()

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
            containers_requiring_net_admin_capability=[],
        )

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
        self.assertEqual(False, is_ready)

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
        self.assertEqual(True, is_ready)
