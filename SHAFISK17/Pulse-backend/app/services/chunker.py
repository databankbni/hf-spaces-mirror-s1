"""
Text Chunking Service - Replacing LlamaIndex SentenceSplitter

This provides semantic text chunking with:
- Sentence boundary detection
- Configurable chunk sizes
- Context overlap between chunks
- Token-aware splitting

No external dependencies required.
"""

import re
from typing import List, Optional


class SentenceSplitter:
    """
    Intelligent text chunker that splits on sentence boundaries
    
    Replaces LlamaIndex SentenceSplitter with same functionality:
    - Respects sentence boundaries (., !, ?)
    - Maintains chunk_size limits
    - Adds overlap for context preservation
    """
    
    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        separator: str = " "
    ):
        """
        Initialize SentenceSplitter
        
        Args:
            chunk_size: Maximum characters per chunk
            chunk_overlap: Characters to overlap between chunks
            separator: Character to join chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separator = separator
        
        # Sentence boundary regex
        self.sentence_endings = re.compile(r'([.!?])\s+')
    
    def split_text(self, text: str) -> List[str]:
        """
        Split text into semantic chunks
        
        Args:
            text: Text to split
            
        Returns:
            List of text chunks
        """
        if not text or len(text) <= self.chunk_size:
            return [text] if text else []
        
        # Split into sentences
        sentences = self._split_sentences(text)
        
        # Combine sentences into chunks
        chunks = self._combine_sentences(sentences)
        
        return chunks
    
    def _split_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences
        
        Args:
            text: Input text
            
        Returns:
            List of sentences
        """
        # Split on sentence boundaries
        sentences = self.sentence_endings.split(text)
        
        # Recombine sentences with their punctuation
        result = []
        for i in range(0, len(sentences) - 1, 2):
            sentence = sentences[i]
            if i + 1 < len(sentences):
                sentence += sentences[i + 1]
            result.append(sentence.strip())
        
        # Add last sentence if exists
        if sentences and not self.sentence_endings.search(sentences[-1]):
            result.append(sentences[-1].strip())
        
        return [s for s in result if s]
    
    def _combine_sentences(self, sentences: List[str]) -> List[str]:
        """
        Combine sentences into chunks respecting size limits
        
        Args:
            sentences: List of sentences
            
        Returns:
            List of chunks
        """
        chunks = []
        current_chunk = []
        current_length = 0
        
        for sentence in sentences:
            sentence_length = len(sentence)
            
            # If adding this sentence exceeds chunk_size
            if current_length + sentence_length > self.chunk_size and current_chunk:
                # Save current chunk
                chunks.append(self.separator.join(current_chunk))
                
                # Start new chunk with overlap
                overlap_text = self._get_overlap(current_chunk)
                current_chunk = [overlap_text] if overlap_text else []
                current_length = len(overlap_text)
            
            # Add sentence to current chunk
            current_chunk.append(sentence)
            current_length += sentence_length
        
        # Add final chunk
        if current_chunk:
            chunks.append(self.separator.join(current_chunk))
        
        return chunks
    
    def _get_overlap(self, chunk: List[str]) -> str:
        """
        Get overlap text from previous chunk
        
        Args:
            chunk: List of sentences in current chunk
            
        Returns:
            Overlap text
        """
        overlap_text = ""
        overlap_length = 0
        
        # Get last few sentences for overlap
        for sentence in reversed(chunk):
            if overlap_length + len(sentence) <= self.chunk_overlap:
                overlap_text = sentence + " " + overlap_text
                overlap_length += len(sentence)
            else:
                break
        
        return overlap_text.strip()
    
    def split_text_with_metadata(
        self,
        text: str,
        metadata: dict
    ) -> List[dict]:
        """
        Split text and attach metadata to each chunk
        
        Args:
            text: Text to split
            metadata: Metadata to attach to chunks
            
        Returns:
            List of dicts with 'text' and 'metadata'
        """
        chunks = self.split_text(text)
        
        results = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = metadata.copy()
            chunk_metadata['chunk_index'] = i
            chunk_metadata['total_chunks'] = len(chunks)
            
            results.append({
                'text': chunk,
                'metadata': chunk_metadata
            })
        
        return results


def estimate_tokens(text: str) -> int:
    """
    Rough estimate of token count
    
    Args:
        text: Input text
        
    Returns:
        Estimated token count (~4 chars per token)
    """
    return len(text) // 4
