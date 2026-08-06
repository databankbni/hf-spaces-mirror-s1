import unittest
from app import predict

class TestSummarizerApp(unittest.TestCase):

    def test_predict_returns_string(self):
        """Test that the predict function successfully returns a string summary."""
        sample_text = (
            "The Hubble Space Telescope is a space telescope that was launched into "
            "low Earth orbit in 1990 and remains in operation. It was not the first "
            "space telescope, but it is one of the largest and most versatile, renowned "
            "both as a vital research tool and as a public relations boon for astronomy."
        )
        
        result = predict(sample_text)
        
        # Check that we actually got a text response back
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_empty_prompt_handling(self):
        """Test that passing an empty string or spaces returns the safety message."""
        expected_warning = "Please enter some text to summarize."
        
        self.assertEqual(predict(""), expected_warning)
        self.assertEqual(predict("   "), expected_warning)

if __name__ == "__main__":
    unittest.main()