"""
Collaborative Filtering Recommendation Model for HomeCenter
Implements matrix factorization using implicit feedback and ALS algorithm.
"""

import numpy as np
import pandas as pd
import scipy.sparse as sp
from typing import List, Dict, Tuple, Optional
import logging
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error
import implicit
import pickle
import boto3
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CollaborativeFilteringModel:
    """
    Collaborative Filtering model using Alternating Least Squares (ALS)
    """
    
    def __init__(self, 
                 factors: int = 100,
                 regularization: float = 0.01,
                 iterations: int = 15,
                 alpha: float = 40.0):
        """
        Initialize the collaborative filtering model
        
        Args:
            factors: Number of latent factors
            regularization: Regularization parameter
            iterations: Number of iterations for ALS
            alpha: Confidence scaling parameter for implicit feedback
        """
        self.factors = factors
        self.regularization = regularization
        self.iterations = iterations
        self.alpha = alpha
        
        # Model and mappings
        self.model = None
        self.user_mapping = {}  # customer_id -> internal_user_id
        self.item_mapping = {}  # product_id -> internal_item_id
        self.reverse_user_mapping = {}
        self.reverse_item_mapping = {}
        
        # Interaction matrix
        self.user_item_matrix = None
        self.item_user_matrix = None
        
        # Model metadata
        self.n_users = 0
        self.n_items = 0
        self.is_trained = False
        
    def prepare_data(self, interactions_df: pd.DataFrame) -> sp.csr_matrix:
        """
        Prepare interaction data for training
        
        Args:
            interactions_df: DataFrame with columns ['customer_id', 'product_id', 'rating']
                           where rating represents implicit feedback strength
        
        Returns:
            Sparse user-item interaction matrix
        """
        logger.info(f"Preparing data with {len(interactions_df)} interactions")
        
        # Create mappings
        unique_users = interactions_df['customer_id'].unique()
        unique_items = interactions_df['product_id'].unique()
        
        self.user_mapping = {user: idx for idx, user in enumerate(unique_users)}
        self.item_mapping = {item: idx for idx, item in enumerate(unique_items)}
        self.reverse_user_mapping = {idx: user for user, idx in self.user_mapping.items()}
        self.reverse_item_mapping = {idx: item for item, idx in self.item_mapping.items()}
        
        self.n_users = len(unique_users)
        self.n_items = len(unique_items)
        
        logger.info(f"Created mappings: {self.n_users} users, {self.n_items} items")
        
        # Create interaction matrix
        user_indices = interactions_df['customer_id'].map(self.user_mapping)
        item_indices = interactions_df['product_id'].map(self.item_mapping)
        ratings = interactions_df['rating'].values
        
        # Create sparse matrix
        self.user_item_matrix = sp.csr_matrix(
            (ratings, (user_indices, item_indices)),
            shape=(self.n_users, self.n_items)
        )
        
        # Transpose for item-user matrix (needed by implicit library)
        self.item_user_matrix = self.user_item_matrix.T.tocsr()
        
        return self.user_item_matrix
    
    def train(self, interactions_df: pd.DataFrame):
        """
        Train the collaborative filtering model
        
        Args:
            interactions_df: DataFrame with interaction data
        """
        logger.info("Starting model training...")
        
        # Prepare data
        self.prepare_data(interactions_df)
        
        # Initialize and train ALS model
        self.model = implicit.als.AlternatingLeastSquares(
            factors=self.factors,
            regularization=self.regularization,
            iterations=self.iterations,
            alpha=self.alpha,
            use_gpu=False,  # Set to True if GPU available
            random_state=42
        )
        
        # Train model (expects item-user matrix)
        self.model.fit(self.item_user_matrix)
        
        self.is_trained = True
        logger.info("Model training completed")
    
    def get_recommendations(self, 
                          customer_id: str, 
                          n_recommendations: int = 10,
                          filter_already_liked: bool = True) -> List[Tuple[str, float]]:
        """
        Get recommendations for a customer
        
        Args:
            customer_id: Customer ID
            n_recommendations: Number of recommendations to return
            filter_already_liked: Whether to filter items customer already interacted with
        
        Returns:
            List of (product_id, score) tuples
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before making recommendations")
        
        if customer_id not in self.user_mapping:
            logger.warning(f"Customer {customer_id} not found in training data")
            return self._get_popular_items(n_recommendations)
        
        user_idx = self.user_mapping[customer_id]
        
        # Get recommendations from model
        item_indices, scores = self.model.recommend(
            user_idx,
            self.user_item_matrix[user_idx],
            N=n_recommendations,
            filter_already_liked_items=filter_already_liked
        )
        
        # Convert back to product IDs
        recommendations = [
            (self.reverse_item_mapping[item_idx], float(score))
            for item_idx, score in zip(item_indices, scores)
        ]
        
        return recommendations
    
    def get_similar_items(self, 
                         product_id: str, 
                         n_similar: int = 10) -> List[Tuple[str, float]]:
        """
        Get items similar to a given product
        
        Args:
            product_id: Product ID
            n_similar: Number of similar items to return
        
        Returns:
            List of (product_id, similarity_score) tuples
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before finding similar items")
        
        if product_id not in self.item_mapping:
            logger.warning(f"Product {product_id} not found in training data")
            return []
        
        item_idx = self.item_mapping[product_id]
        
        # Get similar items
        similar_indices, scores = self.model.similar_items(
            item_idx,
            N=n_similar + 1  # +1 because it includes the item itself
        )
        
        # Filter out the item itself and convert to product IDs
        similar_items = [
            (self.reverse_item_mapping[idx], float(score))
            for idx, score in zip(similar_indices[1:], scores[1:])  # Skip first item (itself)
        ]
        
        return similar_items
    
    def get_similar_users(self, 
                         customer_id: str, 
                         n_similar: int = 10) -> List[Tuple[str, float]]:
        """
        Get users similar to a given customer
        
        Args:
            customer_id: Customer ID
            n_similar: Number of similar users to return
        
        Returns:
            List of (customer_id, similarity_score) tuples
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before finding similar users")
        
        if customer_id not in self.user_mapping:
            logger.warning(f"Customer {customer_id} not found in training data")
            return []
        
        user_idx = self.user_mapping[customer_id]
        
        # Get similar users
        similar_indices, scores = self.model.similar_users(
            user_idx,
            N=n_similar + 1  # +1 because it includes the user itself
        )
        
        # Filter out the user itself and convert to customer IDs
        similar_users = [
            (self.reverse_user_mapping[idx], float(score))
            for idx, score in zip(similar_indices[1:], scores[1:])  # Skip first user (itself)
        ]
        
        return similar_users
    
    def _get_popular_items(self, n_items: int = 10) -> List[Tuple[str, float]]:
        """
        Get popular items for new/unknown users
        
        Args:
            n_items: Number of popular items to return
        
        Returns:
            List of (product_id, popularity_score) tuples
        """
        if self.user_item_matrix is None:
            return []
        
        # Calculate item popularity (sum of interactions)
        item_popularity = np.array(self.user_item_matrix.sum(axis=0)).flatten()
        
        # Get top items
        top_indices = np.argsort(item_popularity)[::-1][:n_items]
        
        popular_items = [
            (self.reverse_item_mapping[idx], float(item_popularity[idx]))
            for idx in top_indices
        ]
        
        return popular_items
    
    def evaluate(self, test_interactions_df: pd.DataFrame) -> Dict[str, float]:
        """
        Evaluate model performance
        
        Args:
            test_interactions_df: Test interaction data
        
        Returns:
            Dictionary with evaluation metrics
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before evaluation")
        
        # Filter test data to include only known users and items
        test_filtered = test_interactions_df[
            (test_interactions_df['customer_id'].isin(self.user_mapping)) &
            (test_interactions_df['product_id'].isin(self.item_mapping))
        ]
        
        if len(test_filtered) == 0:
            logger.warning("No valid test interactions found")
            return {}
        
        # Calculate metrics
        precision_at_10 = self._calculate_precision_at_k(test_filtered, k=10)
        recall_at_10 = self._calculate_recall_at_k(test_filtered, k=10)
        coverage = self._calculate_catalog_coverage(test_filtered)
        
        metrics = {
            'precision_at_10': precision_at_10,
            'recall_at_10': recall_at_10,
            'catalog_coverage': coverage,
            'test_interactions': len(test_filtered)
        }
        
        logger.info(f"Evaluation metrics: {metrics}")
        return metrics
    
    def _calculate_precision_at_k(self, test_df: pd.DataFrame, k: int = 10) -> float:
        """Calculate precision@k"""
        total_precision = 0
        n_users = 0
        
        for customer_id in test_df['customer_id'].unique():
            if customer_id not in self.user_mapping:
                continue
            
            # Get test items for this user
            test_items = set(test_df[test_df['customer_id'] == customer_id]['product_id'])
            
            # Get recommendations
            recommendations = self.get_recommendations(customer_id, n_recommendations=k)
            recommended_items = set([item_id for item_id, _ in recommendations])
            
            # Calculate precision
            if len(recommended_items) > 0:
                precision = len(test_items & recommended_items) / len(recommended_items)
                total_precision += precision
                n_users += 1
        
        return total_precision / n_users if n_users > 0 else 0.0
    
    def _calculate_recall_at_k(self, test_df: pd.DataFrame, k: int = 10) -> float:
        """Calculate recall@k"""
        total_recall = 0
        n_users = 0
        
        for customer_id in test_df['customer_id'].unique():
            if customer_id not in self.user_mapping:
                continue
            
            # Get test items for this user
            test_items = set(test_df[test_df['customer_id'] == customer_id]['product_id'])
            
            if len(test_items) == 0:
                continue
            
            # Get recommendations
            recommendations = self.get_recommendations(customer_id, n_recommendations=k)
            recommended_items = set([item_id for item_id, _ in recommendations])
            
            # Calculate recall
            recall = len(test_items & recommended_items) / len(test_items)
            total_recall += recall
            n_users += 1
        
        return total_recall / n_users if n_users > 0 else 0.0
    
    def _calculate_catalog_coverage(self, test_df: pd.DataFrame) -> float:
        """Calculate catalog coverage"""
        all_recommended_items = set()
        
        for customer_id in test_df['customer_id'].unique():
            if customer_id not in self.user_mapping:
                continue
            
            recommendations = self.get_recommendations(customer_id, n_recommendations=10)
            recommended_items = set([item_id for item_id, _ in recommendations])
            all_recommended_items.update(recommended_items)
        
        return len(all_recommended_items) / self.n_items if self.n_items > 0 else 0.0
    
    def save_model(self, s3_bucket: str, model_key: str):
        """
        Save model to S3
        
        Args:
            s3_bucket: S3 bucket name
            model_key: S3 key for the model
        """
        if not self.is_trained:
            raise ValueError("Cannot save untrained model")
        
        # Prepare model data
        model_data = {
            'model': self.model,
            'user_mapping': self.user_mapping,
            'item_mapping': self.item_mapping,
            'reverse_user_mapping': self.reverse_user_mapping,
            'reverse_item_mapping': self.reverse_item_mapping,
            'n_users': self.n_users,
            'n_items': self.n_items,
            'factors': self.factors,
            'regularization': self.regularization,
            'iterations': self.iterations,
            'alpha': self.alpha,
            'trained_at': datetime.utcnow().isoformat()
        }
        
        # Serialize and upload to S3
        import tempfile
        with tempfile.NamedTemporaryFile() as tmp_file:
            pickle.dump(model_data, tmp_file)
            tmp_file.flush()
            
            s3_client = boto3.client('s3')
            s3_client.upload_file(tmp_file.name, s3_bucket, model_key)
        
        logger.info(f"Model saved to s3://{s3_bucket}/{model_key}")
    
    def load_model(self, s3_bucket: str, model_key: str):
        """
        Load model from S3
        
        Args:
            s3_bucket: S3 bucket name
            model_key: S3 key for the model
        """
        # Download and deserialize from S3
        import tempfile
        with tempfile.NamedTemporaryFile() as tmp_file:
            s3_client = boto3.client('s3')
            s3_client.download_file(s3_bucket, model_key, tmp_file.name)
            
            tmp_file.seek(0)
            model_data = pickle.load(tmp_file)
        
        # Restore model state
        self.model = model_data['model']
        self.user_mapping = model_data['user_mapping']
        self.item_mapping = model_data['item_mapping']
        self.reverse_user_mapping = model_data['reverse_user_mapping']
        self.reverse_item_mapping = model_data['reverse_item_mapping']
        self.n_users = model_data['n_users']
        self.n_items = model_data['n_items']
        self.factors = model_data['factors']
        self.regularization = model_data['regularization']
        self.iterations = model_data['iterations']
        self.alpha = model_data['alpha']
        
        self.is_trained = True
        logger.info(f"Model loaded from s3://{s3_bucket}/{model_key}")

def create_interaction_matrix_from_events(events_df: pd.DataFrame) -> pd.DataFrame:
    """
    Create interaction matrix from customer events
    
    Args:
        events_df: DataFrame with customer events
    
    Returns:
        DataFrame with columns ['customer_id', 'product_id', 'rating']
    """
    # Define weights for different event types
    event_weights = {
        'view': 1.0,
        'click': 2.0,
        'add_to_cart': 5.0,
        'purchase': 10.0,
        'search': 0.5
    }
    
    # Calculate implicit ratings based on events
    interactions = []
    
    for customer_id in events_df['customer_id'].unique():
        customer_events = events_df[events_df['customer_id'] == customer_id]
        
        for product_id in customer_events['product_id'].dropna().unique():
            product_events = customer_events[customer_events['product_id'] == product_id]
            
            # Calculate weighted score
            total_score = 0
            for _, event in product_events.iterrows():
                event_type = event['event_type']
                weight = event_weights.get(event_type, 1.0)
                total_score += weight
            
            # Add time decay (recent events are more important)
            if 'timestamp' in product_events.columns:
                latest_timestamp = pd.to_datetime(product_events['timestamp']).max()
                days_ago = (datetime.utcnow() - latest_timestamp).days
                time_decay = np.exp(-days_ago / 30.0)  # 30-day decay
                total_score *= time_decay
            
            interactions.append({
                'customer_id': customer_id,
                'product_id': product_id,
                'rating': total_score
            })
    
    return pd.DataFrame(interactions)

# Example usage
if __name__ == "__main__":
    # Sample data
    sample_interactions = pd.DataFrame({
        'customer_id': ['C1', 'C1', 'C2', 'C2', 'C3', 'C3'] * 50,
        'product_id': ['P1', 'P2', 'P1', 'P3', 'P2', 'P3'] * 50,
        'rating': [5.0, 3.0, 4.0, 2.0, 5.0, 4.0] * 50
    })
    
    # Create and train model
    model = CollaborativeFilteringModel(factors=50)
    model.train(sample_interactions)
    
    # Get recommendations
    recommendations = model.get_recommendations('C1', n_recommendations=5)
    print(f"Recommendations for C1: {recommendations}")
    
    # Get similar items
    similar_items = model.get_similar_items('P1', n_similar=3)
    print(f"Similar items to P1: {similar_items}")