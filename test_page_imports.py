import ast
from pathlib import Path
import unittest

class PageImportsTests(unittest.TestCase):
    def test_auto_page_imports_pandas(self):
        page = Path(__file__).parent / "pages" / "1_Auto_Data.py"
        tree = ast.parse(page.read_text())
        imports = [(alias.name, alias.asname) for node in tree.body if isinstance(node, ast.Import) for alias in node.names]
        self.assertIn(("pandas", "pd"), imports)

if __name__ == "__main__":
    unittest.main()
