from typing import List, Dict
from difflib import SequenceMatcher
import logging

class SimilarityHandler:
    def __init__(self, similarity_threshold=0.5):
        self.similarity_threshold = similarity_threshold

    def get_text_similarity(self, text1: str, text2: str) -> float:
        """Compute similarity between two texts."""
        # Convert to lowercase for better matching
        text1 = text1.lower()
        text2 = text2.lower()
        
        # Method 1: Sequence Matcher
        sequence_similarity = SequenceMatcher(None, text1, text2).ratio()
        
        # Method 2: Word overlap
        words1 = set(text1.split())
        words2 = set(text2.split())
        overlap = len(words1.intersection(words2))
        max_words = max(len(words1), len(words2))
        word_similarity = overlap / max_words if max_words > 0 else 0
        
        # Combined score (adjustable weights)
        return 0.6 * sequence_similarity + 0.4 * word_similarity

    def find_related_facts(self, feature: Dict, atomic_facts_chunks: List[List[Dict]]) -> List[Dict]:
        """
        Find atomic facts related to a feature across all chunks.
        Returns: List of related facts with their contexts and similarity scores.
        """
        feature_text = feature['feature']
        related_facts = []

        # Search through all chunks
        for chunk_idx, chunk in enumerate(atomic_facts_chunks):
            for fact in chunk:
                similarity = self.get_text_similarity(feature_text, fact['fact'])
                
                if similarity >= self.similarity_threshold:
                    related_facts.append({
                        'fact': fact['fact'],
                        'context': fact['context'],
                        'verbose_context': fact['verbose_context'],
                        'chunk_index': chunk_idx,
                        'similarity_score': similarity
                    })

        # Sort by similarity score
        related_facts.sort(key=lambda x: x['similarity_score'], reverse=True)
        return related_facts

    def consolidate_contexts(self, related_facts: List[Dict], feature: Dict) -> Dict:
        """
        Create structured information for a feature with all its matched facts.
        Returns: Dict containing feature metadata and all matched facts with their contexts
        """
        if not related_facts:
            return {
                'feature_metadata': {
                    'feature_type': feature['feature_type'],
                    'importance_score': feature['importance_score'],
                    'original_category': feature.get('original_category', '')
                },
                'matched_facts': []
            }
        
        # Keep all matched facts with their individual contexts
        matched_facts = []
        for fact in related_facts:
            matched_facts.append({
                'fact': fact['fact'],
                'context': fact['context'],
                'verbose_context': fact['verbose_context'],
                'chunk_index': fact['chunk_index'],
                'similarity_score': fact['similarity_score']
            })

        return {
            'feature_metadata': {
                'feature_type': feature['feature_type'],
                'importance_score': feature['importance_score'],
                'original_category': feature.get('original_category', '')
            },
            'matched_facts': matched_facts
        }