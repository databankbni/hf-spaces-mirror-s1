import unittest

from rag_pipeline import CVRAGPipeline


class TestQueryUnderstanding(unittest.TestCase):
    def setUp(self):
        self.pipeline = CVRAGPipeline.__new__(CVRAGPipeline)
        self.pipeline._client = object()
        self.pipeline._full_text = "Experience and projects are listed here."
        self.pipeline._chunks = [
            "Experience: Research Assistant working on machine learning projects.",
            "Publications: Two research papers presented at conferences.",
            "Honors & Awards: Excellence scholarship and research recognition.",
        ]
        self.pipeline.max_rag_top_k = 6

    def test_vague_work_questions_expand_to_current_work(self):
        self.assertIn("current_work", self.pipeline._detect_intents("what do she do?"))
        self.assertIn("current_work", self.pipeline._detect_intents("what is she working on?"))

    def test_work_location_is_not_residence_location(self):
        self.assertNotEqual(self.pipeline._detect_intents("where does she work?"), ["location"])
        self.assertEqual(self.pipeline._detect_intents("where does she live?"), ["location"])

    def test_retrieval_stays_within_token_budget(self):
        selected, _ = self.pipeline._select_relevant_chunks("what does she do?", 10, 600)
        self.assertLessEqual(sum(self.pipeline._estimate_tokens(chunk) for chunk in selected), 600)

    def test_missing_residence_returns_refusal(self):
        answer, source_count = self.pipeline.answer_question("where does she live?")
        self.assertEqual(source_count, 0)
        self.assertIn("not mentioned", answer.lower())


if __name__ == "__main__":
    unittest.main()