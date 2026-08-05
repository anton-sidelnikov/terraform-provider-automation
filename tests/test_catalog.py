import unittest

from otc_agent.catalog import Catalog, CatalogError, default_catalog_path


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = Catalog.load(default_catalog_path())

    def test_resolves_all_naming_layers(self) -> None:
        self.assertEqual(self.catalog.resolve("fgs").docs, "function-graph")
        self.assertEqual(self.catalog.resolve("function-graph").provider, "fgs")
        self.assertEqual(self.catalog.resolve("IAM").sdk, "identity")

    def test_rejects_unknown_instead_of_fuzzy_autoselection(self) -> None:
        with self.assertRaisesRegex(CatalogError, "no unambiguous reviewed mapping"):
            self.catalog.resolve("api-gatway")

    def test_rejects_conflicting_override(self) -> None:
        with self.assertRaisesRegex(CatalogError, "conflicts"):
            self.catalog.resolve("fgs", "api-gateway")

    def test_explicit_variant_key_wins_over_shared_provider_path(self) -> None:
        self.assertEqual(self.catalog.resolve("sfs").sdk, "sfs")
        self.assertEqual(self.catalog.resolve("sfs-turbo").sdk, "sfs_turbo")
        with self.assertRaisesRegex(CatalogError, "no unambiguous reviewed mapping"):
            self.catalog.resolve("scalable-file-service")

    def test_unmapped_api_repository_enters_bootstrap(self) -> None:
        mapping = self.catalog.resolve_documentation("modelarts")
        self.assertTrue(mapping.bootstrap)
        self.assertEqual(mapping.sdk, "modelarts")
        self.assertEqual(mapping.provider, "modelarts")

    def test_only_api_ref_repositories_are_mapped(self) -> None:
        for mapping in self.catalog.mappings:
            self.assertIn(mapping.docs, self.catalog.eligible_docs_repositories)


if __name__ == "__main__":
    unittest.main()
