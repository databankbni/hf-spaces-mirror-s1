import unittest
from unittest.mock import patch, MagicMock
from src.client import OllamaClient

class TestOllamaClient(unittest.TestCase):
    def setUp(self):
        self.client = OllamaClient(base_url="http://test:11434")

    @patch('src.client.requests.Session.get')
    def test_list_models(self, mock_get):
        # Mocking the response from /api/tags
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "test-model"}]}
        mock_get.return_value = mock_resp

        models = self.client.list_models()
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]['name'], "test-model")
        mock_get.assert_called_with("http://test:11434/api/tags", timeout=30)

    @patch('src.client.requests.Session.post')
    def test_generate(self, mock_post):
        # Mocking the response from /api/generate
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Hello!"}
        mock_post.return_value = mock_resp

        response = self.client.generate(prompt="Hi", model="test-model")
        self.assertEqual(response['response'], "Hello!")
        mock_post.assert_called()

if __name__ == '__main__':
    unittest.main()
