import os
import json
import random
import logging
import pandas as pd
from datasets import load_dataset
from typing import List, Dict, Any, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DatasetProcessor:
    """
    Processes datasets from HuggingFace for general summarization evaluation.
    Supports Edinburgh NLP xsum, CCDV arxiv-summarization, and Northeastern University big_patent datasets.
    """
    
    def __init__(self, output_dir="data/datasets"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
    def load_edinburgh_xsum(self, sample_size=10) -> pd.DataFrame:
        """
        Load Edinburgh NLP xsum dataset from HuggingFace and sample random documents.
        
        Args:
            sample_size: Number of documents to sample
            
        Returns:
            DataFrame with documents and reference summaries
        """
        logging.info("Loading Edinburgh NLP xsum dataset...")
        
        try:
            # Load dataset
            dataset = load_dataset("EdinburghNLP/xsum", split="test")
            
            # Sample random documents
            total_docs = len(dataset)
            sample_indices = random.sample(range(total_docs), min(sample_size, total_docs))
            
            # Extract data
            data = []
            for idx in sample_indices:
                document = dataset[idx]

                data.append({
                    'Title': f"XSUM_{idx}",
                    'Meeting': document['document'],  # Document text
                    'Gold_Summary': document['summary'],  # Reference summary
                    'Source': 'edinburgh_xsum',
                    'Document_ID': idx
                })
            
            # Convert to DataFrame
            df = pd.DataFrame(data)
            
            # Save to file
            output_path = os.path.join(self.output_dir, "edinburgh_xsum_samples.csv")
            df.to_csv(output_path, index=False)
            logging.info(f"Saved {len(df)} sampled documents to {output_path}")
            
            return df, output_path
            
        except Exception as e:
            logging.error(f"Error loading Edinburgh NLP xsum dataset: {str(e)}")
            return pd.DataFrame(), ""
    
    def load_arxiv_summarization(self, sample_size=10) -> pd.DataFrame:
        """
        Load CCDV arxiv-summarization dataset from HuggingFace and sample random documents.
        
        Args:
            sample_size: Number of documents to sample
            
        Returns:
            DataFrame with documents and reference summaries
        """
        logging.info("Loading CCDV arxiv-summarization dataset...")
        
        try:
            # Load dataset
            dataset = load_dataset("ccdv/arxiv-summarization", split="test")
            
            # Sample random documents
            total_docs = len(dataset)
            sample_indices = random.sample(range(total_docs), min(sample_size, total_docs))
            
            # Extract data
            data = []
            for idx in sample_indices:
                document = dataset[idx]

                data.append({
                    'Title': f"ARXIV_{idx}",
                    'Meeting': document['article'],  # Article text
                    'Gold_Summary': document['abstract'],  # Abstract as summary
                    'Source': 'arxiv_summarization',
                    'Document_ID': idx
                })
            
            # Convert to DataFrame
            df = pd.DataFrame(data)
            
            # Save to file
            output_path = os.path.join(self.output_dir, "arxiv_summarization_samples.csv")
            df.to_csv(output_path, index=False)
            logging.info(f"Saved {len(df)} sampled documents to {output_path}")
            
            return df, output_path
            
        except Exception as e:
            logging.error(f"Error loading CCDV arxiv-summarization dataset: {str(e)}")
            return pd.DataFrame(), ""
    
    def load_big_patent(self, sample_size=10) -> pd.DataFrame:
        """
        Load Northeastern University big_patent dataset from HuggingFace and sample random documents.
        
        Args:
            sample_size: Number of documents to sample
            
        Returns:
            DataFrame with documents and reference summaries
        """
        logging.info("Loading Northeastern University big_patent dataset...")
        
        try:
            # Load dataset (using a specific subset)
            dataset = load_dataset("NortheasternUniversity/big_patent", 'a', split="test",trust_remote_code=True)
            
            # Sample random documents
            total_docs = len(dataset)
            sample_indices = random.sample(range(total_docs), min(sample_size, total_docs))
            
            # Extract data
            data = []
            for idx in sample_indices:
                document = dataset[idx]

                data.append({
                    'Title': f"PATENT_{idx}",
                    'Meeting': document['description'],  # Patent description
                    'Gold_Summary': document['abstract'],  # Abstract as summary
                    'Source': 'big_patent',
                    'Document_ID': idx
                })
            
            # Convert to DataFrame
            df = pd.DataFrame(data)
            
            # Save to file
            output_path = os.path.join(self.output_dir, "big_patent_samples.csv")
            df.to_csv(output_path, index=False)
            logging.info(f"Saved {len(df)} sampled documents to {output_path}")
            
            return df, output_path
            
        except Exception as e:
            logging.error(f"Error loading Northeastern University big_patent dataset: {str(e)}")
            return pd.DataFrame(), ""