import os
import unittest


class TestGroqModelResolution(unittest.TestCase):
    def test_default_model_uses_supported_groq_fallback(self):
        os.environ["GROQ_API_KEY"] = ""
        os.environ["GROQ_MODEL"] = ""
        os.environ["CV_PATH"] = "missing_cv.pdf"

        from rag_pipeline import CVRAGPipeline

        pipeline = CVRAGPipeline()
        self.assertEqual(pipeline.model_name, "groq/compound")


if __name__ == "__main__":
    unittest.main()
