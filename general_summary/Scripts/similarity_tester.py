import json
import os
from difflib import SequenceMatcher
import logging
from typing import List, Dict, Set
from pprint import pprint

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class SimilarityTester:
    def __init__(self, storage_dir="data_store"):
        self.storage_dir = storage_dir
        self.atomic_facts_chunks = []
        self.important_features = {
            'DECISION': [],
            'HIGH_PRIORITY': [],
            'MEDIUM_PRIORITY': [],
            'CONTEXT': []
        }
        self.similarity_threshold = 0.5
        self.unique_features = []  # Will store unique features across categories

    def get_unique_features(self) -> List[Dict]:
        """Extract unique features across all categories."""
        seen_features = set()
        unique_features = []
        
        # Process categories in priority order
        categories = ['DECISION', 'HIGH_PRIORITY', 'MEDIUM_PRIORITY', 'CONTEXT']
        for category in categories:
            for feature in self.important_features[category]:
                feature_text = feature['feature']
                if feature_text not in seen_features:
                    seen_features.add(feature_text)
                    unique_features.append({
                        'feature': feature_text,
                        'importance_score': feature['importance_score'],
                        'feature_type': feature['feature_type'],
                        'original_category': category
                    })
        
        return unique_features

    def load_test_data(self, meeting_id: str) -> bool:
        """Load stored atomic facts and important features."""
        try:
            # Load atomic facts (list of chunks)
            atomic_facts_path = os.path.join(self.storage_dir, f"atomic_facts_{meeting_id}.json")
            with open(atomic_facts_path, 'r', encoding='utf-8') as f:
                self.atomic_facts_chunks = json.load(f)
            
            # Count total facts across all chunks
            total_facts = sum(len(chunk) for chunk in self.atomic_facts_chunks)
            
            # Load important features
            features_path = os.path.join(self.storage_dir, f"important_features_{meeting_id}.json")
            with open(features_path, 'r', encoding='utf-8') as f:
                self.important_features = json.load(f)
            
            # Get unique features
            self.unique_features = self.get_unique_features()
            
            # Print summary
            print("\nData Loading Summary:")
            print(f"Total Chunks: {len(self.atomic_facts_chunks)}")
            print(f"Total Atomic Facts: {total_facts}")
            print(f"Total Unique Features: {len(self.unique_features)}")
            return True
            
        except Exception as e:
            logging.error(f"Error loading data: {str(e)}")
            return False

    def get_text_similarity(self, text1: str, text2: str) -> float:
        """Compute similarity between two texts."""
        text1 = text1.lower()
        text2 = text2.lower()
        
        sequence_similarity = SequenceMatcher(None, text1, text2).ratio()
        
        words1 = set(text1.split())
        words2 = set(text2.split())
        overlap = len(words1.intersection(words2))
        max_words = max(len(words1), len(words2))
        word_similarity = overlap / max_words if max_words > 0 else 0
        
        return 0.6 * sequence_similarity + 0.4 * word_similarity

    def find_matches_for_feature(self, feature: Dict) -> List[Dict]:
        """Find atomic facts that match with a given feature."""
        feature_text = feature['feature']
        matches = []
        
        for chunk_idx, chunk in enumerate(self.atomic_facts_chunks):
            for fact_dict in chunk:
                if not isinstance(fact_dict, dict) or 'fact' not in fact_dict:
                    continue
                
                similarity = self.get_text_similarity(feature_text, fact_dict['fact'])
                if similarity >= self.similarity_threshold:
                    matches.append({
                        'chunk_index': chunk_idx,
                        'atomic_fact': fact_dict['fact'],
                        'context': fact_dict['context'],
                        'similarity_score': similarity
                    })
        
        matches.sort(key=lambda x: x['similarity_score'], reverse=True)
        return matches

    def test_similarity_matching(self):
        """Test similarity matching for unique features."""
        # Track matches and coverage
        total_atomic_facts = sum(len(chunk) for chunk in self.atomic_facts_chunks)
        matched_facts = set()  # Track unique atomic facts that match any feature
        feature_coverage = {
            'matched_features': 0,
            'total_features': len(self.unique_features),
            'features_with_matches': []
        }
        
        print("\n=== Testing Similarity Matching for Unique Features ===")
        print("=" * 80)
        
        # Process each unique feature
        for feature in self.unique_features:
            matches = self.find_matches_for_feature(feature)
            
            print(f"\nFeature: {feature['feature']}")
            print(f"Type: {feature['feature_type']}")
            print(f"Importance: {feature['importance_score']}")
            print(f"Original Category: {feature['original_category']}")
            
            if matches:
                feature_coverage['matched_features'] += 1
                feature_coverage['features_with_matches'].append({
                    'feature': feature['feature'],
                    'match_count': len(matches)
                })
                
                print(f"Found {len(matches)} matches:")
                # Show top 3 matches
                for match in matches[:3]:
                    print(f"- Match from Chunk {match['chunk_index']+1} (score: {match['similarity_score']:.3f}):")
                    print(f"  Fact: {match['atomic_fact']}")
                    print(f"  Context: {match['context']}")
                    
                    # Track matched atomic facts
                    matched_facts.add(match['atomic_fact'])
            else:
                print("No matches found")
            
            print("-" * 40)
        
        # Calculate coverage ratios
        feature_match_ratio = (feature_coverage['matched_features'] / 
                             feature_coverage['total_features'] * 100)
        fact_coverage_ratio = (len(matched_facts) / total_atomic_facts * 100)
        
        # Print coverage statistics
        print("\n=== Coverage Statistics ===")
        print("=" * 80)
        print("\nFeature Coverage:")
        print(f"- Total Unique Features: {feature_coverage['total_features']}")
        print(f"- Features with Matches: {feature_coverage['matched_features']}")
        print(f"- Feature Match Ratio: {feature_match_ratio:.1f}%")
        
        print("\nAtomic Facts Coverage:")
        print(f"- Total Atomic Facts: {total_atomic_facts}")
        print(f"- Matched Atomic Facts: {len(matched_facts)}")
        print(f"- Fact Coverage Ratio: {fact_coverage_ratio:.1f}%")
        
        # Distribution of matches
        if feature_coverage['features_with_matches']:
            match_counts = [f['match_count'] for f in feature_coverage['features_with_matches']]
            avg_matches = sum(match_counts) / len(match_counts)
            print(f"\nAverage matches per matched feature: {avg_matches:.1f}")
