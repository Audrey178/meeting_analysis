import logging
import json
import os
from typing import List, Dict, Tuple
from similarity_handler import SimilarityHandler

class PersonalizedMemoryBank:
    def __init__(self, storage_dir="./atomic-facts/data_store"):
        self.storage_dir = storage_dir
        # Modified to include persona alignment categories
        self.important_facts = {
            'DECISION': [],
            'HIGH_ALIGNMENT': [],  # High persona alignment and importance
            'MEDIUM_ALIGNMENT': [], # Medium persona alignment
            'CONTEXT': []
        }
        # Updated thresholds to consider combined scores
        self.threshold = {
            'HIGH_ALIGNMENT': 8,    # Combined score threshold
            'MEDIUM_ALIGNMENT': 6,  # Combined score threshold
            'CONTEXT': 6           # Minimum importance for context
        }
        self.atomic_facts_chunks = []
        self.similarity_handler = SimilarityHandler()
        
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
        except FileNotFoundError:
            logging.warning(f"No stored data found for meeting {meeting_id}")
            return False
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding stored data for meeting {meeting_id}: {e}")
            return False
        except Exception as e:
            logging.error(f"Unexpected error loading data: {str(e)}")
            return False

    def calculate_combined_score(self, feature: Dict) -> float:
        """Calculate combined score weighing both importance and persona alignment."""
        return (0.4 * feature['importance_score'] + 
                0.6 * feature['persona_alignment_score'])

    def process_features(self, ranked_features: List[Dict], atomic_facts: List[Dict]) -> None:
        """Store features in appropriate categories based on combined scores."""
        # Store atomic facts chunk
        self.atomic_facts_chunks.append(atomic_facts)
        
        # Process features by category using combined scores
        for feature in ranked_features:
            combined_score = feature.get('combined_score', 
                                      self.calculate_combined_score(feature))
            
            # Store decisions regardless of score
            if feature['feature_type'] == 'DECISION':
                self.important_facts['DECISION'].append(feature)
            
            # Categorize by combined score
            if combined_score >= self.threshold['HIGH_ALIGNMENT']:
                self.important_facts['HIGH_ALIGNMENT'].append(feature)
            elif combined_score >= self.threshold['MEDIUM_ALIGNMENT']:
                self.important_facts['MEDIUM_ALIGNMENT'].append(feature)
            
            # Store context if it meets minimum importance
            if (feature['feature_type'] == 'CONTEXT' and 
                feature['importance_score'] >= self.threshold['CONTEXT']):
                self.important_facts['CONTEXT'].append(feature)
                
        logging.info(f"Processed {len(ranked_features)} features and stored {len(atomic_facts)} atomic facts")

    def get_features_for_outline(self) -> List[Dict]:
        """Return unique features for outline generation with persona alignment."""
        consolidated = []
        seen = set()
        
        # Modified category order to prioritize persona alignment
        categories = ['DECISION', 'HIGH_ALIGNMENT', 'MEDIUM_ALIGNMENT', 'CONTEXT']
        
        for category in categories:
            for feature in self.important_facts[category]:
                feature_id = feature['feature']
                if feature_id not in seen:
                    seen.add(feature_id)
                    consolidated.append({
                        'feature': feature['feature'],
                        'feature_type': feature['feature_type'],
                        'importance_score': feature['importance_score'],
                        'persona_alignment_score': feature.get('persona_alignment_score', 5),
                        'alignment_explanation': feature.get('alignment_explanation', ''),
                        'combined_score': feature.get('combined_score', 
                                                    self.calculate_combined_score(feature))
                    })
        
        # Sort by combined score
        consolidated.sort(key=lambda x: x['combined_score'], reverse=True)
        logging.info(f"Generated outline with {len(consolidated)} unique features")
        return consolidated

    def get_features_for_summary(self) -> Tuple[List[Dict], Dict[str, Dict]]:
        """Return unique features and their matched facts with persona alignment."""
        consolidated_features = []
        seen = set()
        detailed_information = {}
        total_matches = 0
        
        categories = ['DECISION', 'HIGH_ALIGNMENT', 'MEDIUM_ALIGNMENT', 'CONTEXT']
        
        for category in categories:
            for feature in self.important_facts[category]:
                feature_id = feature['feature']
                if feature_id not in seen:
                    seen.add(feature_id)
                    feature['original_category'] = category
                    consolidated_features.append(feature)
                    
                    # Find related facts
                    related_facts = self.similarity_handler.find_related_facts(
                        feature, self.atomic_facts_chunks
                    )
                    
                    # Keep all matched facts with contexts and metadata
                    detailed_info = self.similarity_handler.consolidate_contexts(
                        related_facts, feature
                    )
                    
                    # Add persona-specific metadata
                    detailed_info['feature_metadata'].update({
                        'persona_alignment_score': feature.get('persona_alignment_score', 5),
                        'alignment_explanation': feature.get('alignment_explanation', ''),
                        'combined_score': feature.get('combined_score', 
                                                    self.calculate_combined_score(feature))
                    })
                    
                    detailed_information[feature_id] = detailed_info
                    total_matches += len(related_facts)
        
        # Sort by combined score
        consolidated_features.sort(key=lambda x: x.get('combined_score', 
                                                     self.calculate_combined_score(x)), 
                                 reverse=True)
        
        logging.info(f"Found {len(consolidated_features)} unique features with {total_matches} total matches")
        return consolidated_features, detailed_information