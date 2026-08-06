import unittest

from otc_agent.catalog import Catalog, default_catalog_path
from otc_agent.classification import classify_change
from otc_agent.domain import ChangeKind, ChangeRequest
from otc_agent.sdk_layout import LayoutKind, OperationLocation, SDKLayoutAnalysis


class ClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = Catalog.load(default_catalog_path())

    def classify(self, description: str) -> ChangeKind:
        mapping = self.catalog.resolve("apigw")
        return classify_change(ChangeRequest("apigw", None, description), mapping).kind

    def test_new_endpoint_is_feature(self) -> None:
        self.assertEqual(self.classify("Add a new endpoint to list routes"), ChangeKind.FEATURE)

    def test_http_method_and_path_is_feature(self) -> None:
        self.assertEqual(self.classify("Support POST /v2/widgets"), ChangeKind.FEATURE)

    def test_contract_shape_change_is_fix(self) -> None:
        self.assertEqual(self.classify("Response parameters changed from string to integer"), ChangeKind.FIX)
        self.assertEqual(self.classify("Fix the existing data source response"), ChangeKind.FIX)

    def test_additive_attribute_is_update(self) -> None:
        self.assertEqual(self.classify("Add new attributes to the existing gateway response"), ChangeKind.UPDATE)

    def test_new_resource_without_endpoint_evidence_is_ambiguous(self) -> None:
        mapping = self.catalog.resolve("apigw")
        result = classify_change(ChangeRequest("apigw", None, "Add a documented resource"), mapping)
        self.assertLess(result.confidence, 0.70)

    def test_unmapped_repository_is_new_service(self) -> None:
        mapping = self.catalog.resolve_documentation("modelarts")
        result = classify_change(ChangeRequest(None, None, "Implement API support"), mapping)
        self.assertEqual(result.kind, ChangeKind.NEW_SERVICE)
        self.assertEqual(result.confidence, 1.0)

    def test_legacy_hint_does_not_override_evidence(self) -> None:
        mapping = self.catalog.resolve("apigw")
        request = ChangeRequest("apigw", ChangeKind.FIX, "Add a new endpoint")
        self.assertEqual(classify_change(request, mapping).kind, ChangeKind.FEATURE)

    def test_repository_layout_overrides_text_classification(self) -> None:
        mapping = self.catalog.resolve("apigw")
        layout = SDKLayoutAnalysis(
            service="apigw",
            kind=LayoutKind.LEGACY,
            operations=(
                OperationLocation(
                    name="Create",
                    path="openstack/apigw/v2/widgets/requests.go",
                    operation_file=False,
                ),
            ),
            legacy_files=("openstack/apigw/v2/widgets/requests.go",),
        )

        result = classify_change(
            ChangeRequest("apigw", None, "Add a new endpoint"),
            mapping,
            layout,
        )

        self.assertEqual(result.kind, ChangeKind.REFACTORING)
        self.assertEqual(result.confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
