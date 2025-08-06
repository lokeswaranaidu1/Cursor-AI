"""
Hybrid Recommendation Model for HomeCenter
Combines collaborative filtering and content-based approaches for better recommendations.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
import logging
from datetime import datetime
import pickle
import boto3

from .collaborative_filtering import CollaborativeFilteringModel
from .content_based import ContentBasedModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HybridRecommendationModel:
    """
    Hybrid recommendation model combining multiple approaches
    """
    
    def __init__(self, 
                 cf_weight: float = 0.6,
                 cb_weight: float = 0.4,
                 popularity_weight: float = 0.1,
                 cf_params: Dict = None,
                 cb_params: Dict = None):
        """
        Initialize the hybrid model
        
        Args:
            cf_weight: Weight for collaborative filtering recommendations
            cb_weight: Weight for content-based recommendations
            popularity_weight: Weight for popularity-based recommendations
            cf_params: Parameters for collaborative filtering model
            cb_params: Parameters for content-based model
        """
        self.cf_weight = cf_weight
        self.cb_weight = cb_weight
        self.popularity_weight = popularity_weight
        
        # Normalize weights
        total_weight = cf_weight + cb_weight + popularity_weight
        self.cf_weight /= total_weight
        self.cb_weight /= total_weight
        self.popularity_weight /= total_weight
        
        # Initialize models
        self.cf_model = CollaborativeFilteringModel(**(cf_params or {}))
        self.cb_model = ContentBasedModel(**(cb_params or {}))
        
        # Popularity data
        self.popularity_scores = {}
        self.products_df = None
        
        self.is_trained = False
    
    def train(self, 
              interactions_df: pd.DataFrame,
              products_df: pd.DataFrame):
        """
        Train all component models
        
        Args:
            interactions_df: User-item interaction data
            products_df: Product catalog with features
        """
        logger.info("Starting hybrid model training...")
        
        self.products_df = products_df.copy()
        
        # Calculate popularity scores
        self._calculate_popularity_scores(interactions_df)
        
        # Train collaborative filtering model
        logger.info("Training collaborative filtering model...")
        cf_interactions = self._prepare_cf_data(interactions_df)
        if len(cf_interactions) > 0:
            self.cf_model.train(cf_interactions)
        
        # Train content-based model
        logger.info("Training content-based model...")
        self.cb_model.train(products_df, interactions_df)
        
        self.is_trained = True
        logger.info("Hybrid model training completed")
    
    def _prepare_cf_data(self, interactions_df: pd.DataFrame) -> pd.DataFrame:
        """Prepare data for collaborative filtering"""
        # Convert events to implicit feedback ratings
        from .collaborative_filtering import create_interaction_matrix_from_events
        
        if 'rating' in interactions_df.columns:
            return interactions_df[['customer_id', 'product_id', 'rating']].copy()
        else:
            return create_interaction_matrix_from_events(interactions_df)
    
    def _calculate_popularity_scores(self, interactions_df: pd.DataFrame):
        """Calculate popularity scores for products"""
        product_counts = interactions_df['product_id'].value_counts()
        max_count = product_counts.max()
        
        # Normalize to 0-1 range
        self.popularity_scores = {
            product_id: count / max_count
            for product_id, count in product_counts.items()
        }
        
        logger.info(f"Calculated popularity scores for {len(self.popularity_scores)} products")
    
    def get_recommendations(self, 
                          customer_id: str,
                          n_recommendations: int = 10,
                          diversity_threshold: float = 0.3,
                          include_explanations: bool = False) -> List[Tuple[str, float, Dict]]:
        """
        Get hybrid recommendations
        
        Args:
            customer_id: Customer ID
            n_recommendations: Number of recommendations to return
            diversity_threshold: Minimum diversity score for recommendations
            include_explanations: Whether to include explanation data
        
        Returns:
            List of (product_id, score, explanation) tuples
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before making recommendations")
        
        # Get recommendations from each model
        cf_recs = self._get_cf_recommendations(customer_id, n_recommendations * 2)
        cb_recs = self._get_cb_recommendations(customer_id, n_recommendations * 2)
        pop_recs = self._get_popularity_recommendations(n_recommendations * 2)
        
        # Combine recommendations
        combined_scores = self._combine_recommendations(cf_recs, cb_recs, pop_recs)
        
        # Apply diversity filtering
        if diversity_threshold > 0:
            combined_scores = self._apply_diversity_filter(
                combined_scores, diversity_threshold
            )
        
        # Sort and select top recommendations
        sorted_recs = sorted(combined_scores.items(), key=lambda x: x[1]['final_score'], reverse=True)
        
        final_recommendations = []
        for product_id, score_data in sorted_recs[:n_recommendations]:
            explanation = score_data if include_explanations else {}
            final_recommendations.append((product_id, score_data['final_score'], explanation))
        
        return final_recommendations
    
    def _get_cf_recommendations(self, customer_id: str, n_recs: int) -> List[Tuple[str, float]]:
        """Get collaborative filtering recommendations"""
        try:
            if self.cf_model.is_trained:
                return self.cf_model.get_recommendations(customer_id, n_recs)
        except Exception as e:
            logger.warning(f"CF model failed: {e}")
        return []
    
    def _get_cb_recommendations(self, customer_id: str, n_recs: int) -> List[Tuple[str, float]]:
        """Get content-based recommendations"""
        try:
            if self.cb_model.is_trained:
                return self.cb_model.get_recommendations(customer_id=customer_id, n_recommendations=n_recs)
        except Exception as e:
            logger.warning(f"CB model failed: {e}")
        return []
    
    def _get_popularity_recommendations(self, n_recs: int) -> List[Tuple[str, float]]:
        """Get popularity-based recommendations"""
        sorted_products = sorted(
            self.popularity_scores.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        return sorted_products[:n_recs]
    
    def _combine_recommendations(self, 
                               cf_recs: List[Tuple[str, float]], 
                               cb_recs: List[Tuple[str, float]], 
                               pop_recs: List[Tuple[str, float]]) -> Dict[str, Dict]:
        """
        Combine recommendations from different models
        """
        combined_scores = {}
        
        # Process CF recommendations
        for product_id, score in cf_recs:
            if product_id not in combined_scores:
                combined_scores[product_id] = {
                    'cf_score': 0.0,
                    'cb_score': 0.0,
                    'pop_score': 0.0,
                    'final_score': 0.0
                }
            combined_scores[product_id]['cf_score'] = score
        
        # Process CB recommendations
        for product_id, score in cb_recs:
            if product_id not in combined_scores:
                combined_scores[product_id] = {
                    'cf_score': 0.0,
                    'cb_score': 0.0,
                    'pop_score': 0.0,
                    'final_score': 0.0
                }
            combined_scores[product_id]['cb_score'] = score
        
        # Process popularity recommendations
        for product_id, score in pop_recs:
            if product_id not in combined_scores:
                combined_scores[product_id] = {
                    'cf_score': 0.0,
                    'cb_score': 0.0,
                    'pop_score': 0.0,
                    'final_score': 0.0
                }
            combined_scores[product_id]['pop_score'] = score
        
        # Calculate final weighted scores
        for product_id, scores in combined_scores.items():
            final_score = (
                self.cf_weight * scores['cf_score'] +
                self.cb_weight * scores['cb_score'] +
                self.popularity_weight * scores['pop_score']
            )
            scores['final_score'] = final_score
        
        return combined_scores
    
    def _apply_diversity_filter(self, 
                              recommendations: Dict[str, Dict],
                              threshold: float) -> Dict[str, Dict]:
        """
        Apply diversity filtering to avoid too similar recommendations
        """
        if not self.cb_model.is_trained or len(recommendations) <= 1:
            return recommendations
        
        product_ids = list(recommendations.keys())
        filtered_recs = {}
        
        for i, product_id in enumerate(product_ids):
            if product_id in filtered_recs:
                continue
            
            # Add this product
            filtered_recs[product_id] = recommendations[product_id]
            
            # Check similarity with remaining products
            for j in range(i + 1, len(product_ids)):
                other_product = product_ids[j]
                if other_product in filtered_recs:
                    continue
                
                # Calculate similarity
                similarity = self._calculate_product_similarity(product_id, other_product)
                
                # If too similar, skip the lower-scored product
                if similarity > threshold:
                    current_score = recommendations[product_id]['final_score']
                    other_score = recommendations[other_product]['final_score']
                    
                    if other_score > current_score:
                        # Remove current and add other
                        del filtered_recs[product_id]
                        filtered_recs[other_product] = recommendations[other_product]
                        break
        
        return filtered_recs
    
    def _calculate_product_similarity(self, product_id1: str, product_id2: str) -> float:
        """Calculate similarity between two products"""
        try:
            if (product_id1 in self.cb_model.product_to_idx and 
                product_id2 in self.cb_model.product_to_idx):
                
                idx1 = self.cb_model.product_to_idx[product_id1]
                idx2 = self.cb_model.product_to_idx[product_id2]
                
                return float(self.cb_model.item_similarity_matrix[idx1][idx2])
        except:
            pass
        return 0.0
    
    def get_similar_items(self, 
                         product_id: str, 
                         n_recommendations: int = 10) -> List[Tuple[str, float]]:
        """
        Get items similar to a given product
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before making recommendations")
        
        # Combine similar items from both models
        cf_similar = []
        cb_similar = []
        
        try:
            if self.cf_model.is_trained:
                cf_similar = self.cf_model.get_similar_items(product_id, n_recommendations)
        except:
            pass
        
        try:
            if self.cb_model.is_trained:
                cb_similar = self.cb_model.get_recommendations(
                    product_id=product_id, n_recommendations=n_recommendations
                )
        except:
            pass
        
        # Combine and deduplicate
        combined_items = {}
        
        for item_id, score in cf_similar:
            combined_items[item_id] = combined_items.get(item_id, 0) + self.cf_weight * score
        
        for item_id, score in cb_similar:
            combined_items[item_id] = combined_items.get(item_id, 0) + self.cb_weight * score
        
        # Sort and return
        sorted_items = sorted(combined_items.items(), key=lambda x: x[1], reverse=True)
        return sorted_items[:n_recommendations]
    
    def explain_recommendation(self, 
                             customer_id: str, 
                             product_id: str) -> Dict[str, any]:
        """
        Explain why a product was recommended
        """
        explanation = {
            'customer_id': customer_id,
            'product_id': product_id,
            'model_weights': {
                'collaborative_filtering': self.cf_weight,
                'content_based': self.cb_weight,
                'popularity': self.popularity_weight
            },
            'scores': {},
            'explanations': {}
        }
        
        # Get CF explanation
        try:
            if self.cf_model.is_trained:
                cf_recs = self.cf_model.get_recommendations(customer_id, 50)
                cf_score = next((score for pid, score in cf_recs if pid == product_id), 0.0)
                explanation['scores']['collaborative_filtering'] = cf_score
                
                if cf_score > 0:
                    similar_users = self.cf_model.get_similar_users(customer_id, 5)
                    explanation['explanations']['collaborative_filtering'] = {
                        'similar_users': similar_users,
                        'message': 'Recommended based on similar customers\' preferences'
                    }
        except Exception as e:
            logger.warning(f"CF explanation failed: {e}")
        
        # Get CB explanation
        try:
            if self.cb_model.is_trained:
                cb_explanation = self.cb_model.explain_recommendation(customer_id, product_id)
                explanation['scores']['content_based'] = cb_explanation.get('similarity_score', 0.0)
                explanation['explanations']['content_based'] = cb_explanation
        except Exception as e:
            logger.warning(f"CB explanation failed: {e}")
        
        # Get popularity score
        explanation['scores']['popularity'] = self.popularity_scores.get(product_id, 0.0)
        explanation['explanations']['popularity'] = {
            'score': self.popularity_scores.get(product_id, 0.0),
            'message': 'Popular item among all customers'
        }
        
        # Calculate final score
        final_score = (
            self.cf_weight * explanation['scores'].get('collaborative_filtering', 0.0) +
            self.cb_weight * explanation['scores'].get('content_based', 0.0) +
            self.popularity_weight * explanation['scores'].get('popularity', 0.0)
        )
        explanation['final_score'] = final_score
        
        return explanation
    
    def get_model_performance(self, test_interactions_df: pd.DataFrame) -> Dict[str, any]:
        """
        Evaluate hybrid model performance
        """
        performance = {
            'hybrid_metrics': {},
            'component_metrics': {}
        }
        
        # Evaluate CF model
        try:
            if self.cf_model.is_trained:
                cf_test_data = self._prepare_cf_data(test_interactions_df)
                cf_metrics = self.cf_model.evaluate(cf_test_data)
                performance['component_metrics']['collaborative_filtering'] = cf_metrics
        except Exception as e:
            logger.warning(f"CF evaluation failed: {e}")
        
        # Evaluate CB model (implicit evaluation)
        performance['component_metrics']['content_based'] = {
            'model_trained': self.cb_model.is_trained,
            'user_profiles': len(self.cb_model.user_profiles),
            'products_in_catalog': len(self.cb_model.product_to_idx)
        }
        
        # Calculate hybrid-specific metrics
        performance['hybrid_metrics'] = {
            'model_weights': {
                'cf_weight': self.cf_weight,
                'cb_weight': self.cb_weight,
                'popularity_weight': self.popularity_weight
            },
            'coverage': {
                'products_with_popularity': len(self.popularity_scores),
                'total_products': len(self.products_df) if self.products_df is not None else 0
            }
        }
        
        return performance
    
    def update_with_new_data(self, 
                           new_interactions_df: pd.DataFrame,
                           new_products_df: pd.DataFrame = None):
        """
        Update models with new data
        """
        logger.info("Updating hybrid model with new data...")
        
        # Update popularity scores
        self._calculate_popularity_scores(new_interactions_df)
        
        # Update CF model (requires retraining for new users/items)
        cf_data = self._prepare_cf_data(new_interactions_df)
        if len(cf_data) > 0:
            self.cf_model.train(cf_data)
        
        # Update CB model
        if new_products_df is not None:
            self.products_df = pd.concat([self.products_df, new_products_df]).drop_duplicates()
            self.cb_model.train(self.products_df, new_interactions_df)
        else:
            # Update user profiles only
            for customer_id in new_interactions_df['customer_id'].unique():
                customer_interactions = new_interactions_df[
                    new_interactions_df['customer_id'] == customer_id
                ]
                self.cb_model.update_user_profile(customer_id, customer_interactions)
        
        logger.info("Hybrid model update completed")
    
    def save_model(self, s3_bucket: str, model_key: str):
        """
        Save hybrid model to S3
        """
        if not self.is_trained:
            raise ValueError("Cannot save untrained model")
        
        model_data = {
            'cf_weight': self.cf_weight,
            'cb_weight': self.cb_weight,
            'popularity_weight': self.popularity_weight,
            'popularity_scores': self.popularity_scores,
            'products_df': self.products_df,
            'trained_at': datetime.utcnow().isoformat()
        }
        
        # Save component models
        cf_key = f"{model_key}_cf.pkl"
        cb_key = f"{model_key}_cb.pkl"
        
        self.cf_model.save_model(s3_bucket, cf_key)
        self.cb_model.save_model(s3_bucket, cb_key)
        
        # Save hybrid model data
        import tempfile
        with tempfile.NamedTemporaryFile() as tmp_file:
            pickle.dump(model_data, tmp_file)
            tmp_file.flush()
            
            s3_client = boto3.client('s3')
            s3_client.upload_file(tmp_file.name, s3_bucket, f"{model_key}_hybrid.pkl")
        
        logger.info(f"Hybrid model saved to s3://{s3_bucket}/{model_key}")
    
    def load_model(self, s3_bucket: str, model_key: str):
        """
        Load hybrid model from S3
        """
        # Load component models
        cf_key = f"{model_key}_cf.pkl"
        cb_key = f"{model_key}_cb.pkl"
        
        self.cf_model.load_model(s3_bucket, cf_key)
        self.cb_model.load_model(s3_bucket, cb_key)
        
        # Load hybrid model data
        import tempfile
        with tempfile.NamedTemporaryFile() as tmp_file:
            s3_client = boto3.client('s3')
            s3_client.download_file(s3_bucket, f"{model_key}_hybrid.pkl", tmp_file.name)
            
            tmp_file.seek(0)
            model_data = pickle.load(tmp_file)
        
        # Restore state
        self.cf_weight = model_data['cf_weight']
        self.cb_weight = model_data['cb_weight']
        self.popularity_weight = model_data['popularity_weight']
        self.popularity_scores = model_data['popularity_scores']
        self.products_df = model_data['products_df']
        
        self.is_trained = True
        logger.info(f"Hybrid model loaded from s3://{s3_bucket}/{model_key}")

# Example usage
if __name__ == "__main__":
    # Sample data
    interactions_data = {
        'customer_id': ['C1', 'C1', 'C2', 'C2', 'C3', 'C3'] * 20,
        'product_id': ['P1', 'P2', 'P1', 'P3', 'P2', 'P3'] * 20,
        'event_type': ['purchase', 'view', 'purchase', 'view', 'purchase', 'view'] * 20,
        'rating': [5.0, 3.0, 4.0, 2.0, 5.0, 4.0] * 20
    }
    
    products_data = {
        'product_id': ['P1', 'P2', 'P3'],
        'name': ['Hammer', 'Screwdriver', 'Drill'],
        'category': ['Tools', 'Tools', 'Power Tools'],
        'brand': ['ToolMaster', 'ToolMaster', 'PowerPro'],
        'price': [25.99, 12.99, 89.99],
        'rating': [4.5, 4.0, 4.8],
        'review_count': [120, 80, 200]
    }
    
    interactions_df = pd.DataFrame(interactions_data)
    products_df = pd.DataFrame(products_data)
    
    # Create and train hybrid model
    hybrid_model = HybridRecommendationModel(
        cf_weight=0.5,
        cb_weight=0.4,
        popularity_weight=0.1
    )
    
    hybrid_model.train(interactions_df, products_df)
    
    # Get recommendations
    recommendations = hybrid_model.get_recommendations('C1', n_recommendations=3, include_explanations=True)
    print(f"Hybrid recommendations for C1: {recommendations}")
    
    # Get explanation
    explanation = hybrid_model.explain_recommendation('C1', 'P3')
    print(f"Explanation: {explanation}")