import logging
from typing import List, Dict, Tuple
import json
import os
from similarity_handler import SimilarityHandler

class MemoryBank:
    def __init__(self, storage_dir="data_store"):
        self.storage_dir = storage_dir
        self.important_facts = {
            'DECISION': [],
            'HIGH_PRIORITY': [],
            'MEDIUM_PRIORITY': [],
            'CONTEXT': []
        }
        self.importance_threshold = {
            'HIGH': 8,
            'MEDIUM': 6,
            'CONTEXT': 5
        }
        self.atomic_facts_chunks = []  # List of chunks, each chunk is a list of facts
        self.similarity_handler = SimilarityHandler()
        
        # Create storage directory if it doesn't exist
        os.makedirs(storage_dir, exist_ok=True)

    def save_data(self, meeting_id: str):
        """Save atomic facts chunks and important features."""
        try:
            atomic_facts_path = os.path.join(self.storage_dir, f"atomic_facts_{meeting_id}.json")
            with open(atomic_facts_path, 'w', encoding='utf-8') as f:
                json.dump(self.atomic_facts_chunks, f, indent=2, ensure_ascii=False)
            
            features_path = os.path.join(self.storage_dir, f"important_features_{meeting_id}.json")
            with open(features_path, 'w', encoding='utf-8') as f:
                json.dump(self.important_facts, f, indent=2, ensure_ascii=False)
            
            logging.info(f"Successfully saved data for meeting {meeting_id}")
        except Exception as e:
            logging.error(f"Error saving data: {str(e)}")

    def load_data(self, meeting_id: str) -> bool:
        """Load atomic facts chunks and important features."""
        try:
            atomic_facts_path = os.path.join(self.storage_dir, f"atomic_facts_{meeting_id}.json")
            with open(atomic_facts_path, 'r', encoding='utf-8') as f:
                self.atomic_facts_chunks = json.load(f)
            
            features_path = os.path.join(self.storage_dir, f"important_features_{meeting_id}.json")
            with open(features_path, 'r', encoding='utf-8') as f:
                self.important_facts = json.load(f)
            
            logging.info(f"Successfully loaded data for meeting {meeting_id}")
            return True
        except FileNotFoundError as e:
            logging.warning(f"No stored data found for meeting {meeting_id}: {e}")
            return False
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding stored data for meeting {meeting_id}: {e}")
            return False
        except Exception as e:
            logging.error(f"Unexpected error loading data: {str(e)}")
            return False

    def process_features(self, ranked_features: List[Dict], atomic_facts: List[Dict]) -> None:
        """Store features in appropriate categories and atomic facts chunk."""
        # Store atomic facts chunk
        self.atomic_facts_chunks.append(atomic_facts)
        
        # Process features by category
        for feature in ranked_features:
            if feature['feature_type'] == 'DECISION':
                self.important_facts['DECISION'].append(feature)
                
            if feature['importance_score'] >= self.importance_threshold['HIGH']:
                self.important_facts['HIGH_PRIORITY'].append(feature)
                
            elif feature['importance_score'] >= self.importance_threshold['MEDIUM']:
                self.important_facts['MEDIUM_PRIORITY'].append(feature)
                
            if (feature['feature_type'] == 'CONTEXT' and 
                feature['importance_score'] >= self.importance_threshold['CONTEXT']):
                self.important_facts['CONTEXT'].append(feature)
                
        logging.info(f"Processed {len(ranked_features)} features and stored {len(atomic_facts)} atomic facts")

    def get_features_for_outline(self) -> List[Dict]:
        """Return unique features for outline generation."""
        consolidated = []
        seen = set()
        for category in ['DECISION', 'HIGH_PRIORITY', 'MEDIUM_PRIORITY', 'CONTEXT']:
            for feature in self.important_facts[category]:
                feature_id = feature['feature']
                if feature_id not in seen:
                    seen.add(feature_id)
                    consolidated.append({
                        'feature': feature['feature'],
                        'feature_type': feature['feature_type'],
                        'importance_score': feature['importance_score']
                    })
        
        logging.info(f"Generated outline with {len(consolidated)} unique features")
        return consolidated

    def get_features_for_summary(self) -> Tuple[List[Dict], Dict[str, Dict]]:
        """
        Return unique features and their matched atomic facts with all contexts.
        Returns: (unique_features, detailed_information)
        where detailed_information maps feature_text to all matched facts and contexts
        """
        consolidated_features = []
        seen = set()
        detailed_information = {}
        
        # Track total matches for logging
        total_matches = 0
        logging.info("In get_features_for_summary function ")

        # Process each feature once, preserving original category
        for category in ['DECISION', 'HIGH_PRIORITY', 'MEDIUM_PRIORITY', 'CONTEXT']:
            for feature in self.important_facts[category]:
                feature_id = feature['feature']
                if feature_id not in seen:
                    seen.add(feature_id)
                    # Add original category to feature
                    feature['original_category'] = category
                    consolidated_features.append(feature)
                    logging.info("before find_related_facts function")

                    # Find related facts across all chunks
                    related_facts = self.similarity_handler.find_related_facts(
                        feature, self.atomic_facts_chunks
                    )
                    logging.info("before consolidate_contexts function")
                    logging.info(f"related_facts = {related_facts}")
                    # Keep all matched facts with their contexts
                    detailed_info = self.similarity_handler.consolidate_contexts(
                        related_facts, feature
                    )

                    logging.info(f"detailed_info = {detailed_info}")

                    detailed_information[feature_id] = detailed_info
                    
                    # Update match count
                    total_matches += len(related_facts)
        
        logging.info(f"Found {len(consolidated_features)} unique features with {total_matches} total matches")
        return consolidated_features, detailed_information