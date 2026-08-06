import unittest

from tools.job_tools import ToolExecutionError, execute_tool


class JobToolsTest(unittest.TestCase):
    def test_calculate_tool_returns_typed_result(self):
        result = execute_tool(
            "calcular_risco_vaga",
            {"vaga": {"title": "Vaga", "description": "Envie PIX", "has_company_logo": False}},
        )
        self.assertIsInstance(result["score_risco"], int)
        self.assertIn("veredito", result)

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(ToolExecutionError):
            execute_tool("ler_arquivo", {})


if __name__ == "__main__":
    unittest.main()
