"""
Content-Based Recommendation Model for HomeCenter
Recommends products based on item features and user preferences.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
import logging
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.decomposition import PCA
import pickle
import boto3
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ContentBasedModel:
    """
    Content-Based Recommendation Model using product features
    """
    
    def __init__(self, 
                 text_features: List[str] = None,
                 categorical_features: List[str] = None,
                 numerical_features: List[str] = None,
                 n_components: int = 50):
        """
        Initialize the content-based model
        
        Args:
            text_features: List of text feature column names
            categorical_features: List of categorical feature column names
            numerical_features: List of numerical feature column names
            n_components: Number of PCA components for dimensionality reduction
        """
        self.text_features = text_features or ['name', 'description', 'category']
        self.categorical_features = categorical_features or ['brand', 'category', 'subcategory']
        self.numerical_features = numerical_features or ['price', 'rating', 'review_count']
        self.n_components = n_components
        
        # Feature processors
        self.tfidf_vectorizer = TfidfVectorizer(
            max_features=1000,
            stop_words='english',
            ngram_range=(1, 2),
            min_df=2
        )
        self.scaler = StandardScaler()
        self.label_encoders = {}
        self.pca = PCA(n_components=n_components, random_state=42)
        
        # Model data
        self.products_df = None
        self.item_features = None
        self.item_similarity_matrix = None
        self.user_profiles = {}
        
        # Mappings
        self.product_to_idx = {}
        self.idx_to_product = {}
        
        self.is_trained = False
    
    def prepare_features(self, products_df: pd.DataFrame) -> np.ndarray:
        """
        Prepare and engineer features from product data
        
        Args:
            products_df: DataFrame with product information
        
        Returns:
            Feature matrix for products
        """
        logger.info(f"Preparing features for {len(products_df)} products")
        
        self.products_df = products_df.copy()
        feature_matrices = []
        
        # Process text features
        if self.text_features:
            text_data = []
            for _, product in products_df.iterrows():
                text_parts = []
                for feature in self.text_features:
                    if feature in product and pd.notna(product[feature]):
                        text_parts.append(str(product[feature]))
                text_data.append(' '.join(text_parts))
            
            # Fit and transform text features
            text_features = self.tfidf_vectorizer.fit_transform(text_data)
            feature_matrices.append(text_features.toarray())
            logger.info(f"Text features shape: {text_features.shape}")
        
        # Process categorical features
        if self.categorical_features:
            categorical_matrix = []
            for feature in self.categorical_features:
                if feature in products_df.columns:
                    # Create label encoder for this feature
                    le = LabelEncoder()
                    encoded_values = le.fit_transform(
                        products_df[feature].fillna('unknown').astype(str)
                    )
                    self.label_encoders[feature] = le
                    
                    # One-hot encode
                    n_classes = len(le.classes_)
                    one_hot = np.eye(n_classes)[encoded_values]
                    categorical_matrix.append(one_hot)
            
            if categorical_matrix:
                categorical_features = np.hstack(categorical_matrix)
                feature_matrices.append(categorical_features)
                logger.info(f"Categorical features shape: {categorical_features.shape}")
        
        # Process numerical features
        if self.numerical_features:
            numerical_data = []
            for feature in self.numerical_features:
                if feature in products_df.columns:
                    values = products_df[feature].fillna(0).astype(float)
                    numerical_data.append(values.values.reshape(-1, 1))
            
            if numerical_data:
                numerical_features = np.hstack(numerical_data)
                # Scale numerical features
                numerical_features = self.scaler.fit_transform(numerical_features)
                feature_matrices.append(numerical_features)
                logger.info(f"Numerical features shape: {numerical_features.shape}")
        
        # Combine all features
        if feature_matrices:
            combined_features = np.hstack(feature_matrices)
            logger.info(f"Combined features shape: {combined_features.shape}")
            
            # Apply PCA for dimensionality reduction
            if combined_features.shape[1] > self.n_components:
                combined_features = self.pca.fit_transform(combined_features)
                logger.info(f"PCA reduced features shape: {combined_features.shape}")
            
            return combined_features
        else:
            logger.warning("No features found, returning zero matrix")
            return np.zeros((len(products_df), self.n_components))
    
    def train(self, products_df: pd.DataFrame, interactions_df: pd.DataFrame = None):
        """
        Train the content-based model
        
        Args:
            products_df: Product catalog with features
            interactions_df: Optional interaction data for user profiling
        """
        logger.info("Starting content-based model training...")
        
        # Create product mappings
        product_ids = products_df['product_id'].unique()
        self.product_to_idx = {pid: idx for idx, pid in enumerate(product_ids)}
        self.idx_to_product = {idx: pid for pid, idx in self.product_to_idx.items()}
        
        # Prepare features
        self.item_features = self.prepare_features(products_df)
        
        # Calculate item similarity matrix
        self.item_similarity_matrix = cosine_similarity(self.item_features)
        logger.info(f"Item similarity matrix shape: {self.item_similarity_matrix.shape}")
        
        # Build user profiles if interaction data is provided
        if interactions_df is not None:
            self._build_user_profiles(interactions_df)
        
        self.is_trained = True
        logger.info("Content-based model training completed")
    
    def _build_user_profiles(self, interactions_df: pd.DataFrame):
        """
        Build user profiles based on interaction history
        
        Args:
            interactions_df: DataFrame with user interactions
        """
        logger.info("Building user profiles...")
        
        for customer_id in interactions_df['customer_id'].unique():
            customer_interactions = interactions_df[
                interactions_df['customer_id'] == customer_id
            ]
            
            # Get interacted products
            interacted_products = customer_interactions['product_id'].unique()
            
            # Filter products that exist in our catalog
            valid_products = [
                pid for pid in interacted_products
                if pid in self.product_to_idx
            ]
            
            if not valid_products:
                continue
            
            # Get product indices and ratings
            product_indices = [self.product_to_idx[pid] for pid in valid_products]
            
            # Calculate weighted average of product features
            if 'rating' in customer_interactions.columns:
                # Use actual ratings if available
                ratings = []
                for pid in valid_products:
                    product_ratings = customer_interactions[
                        customer_interactions['product_id'] == pid
                    ]['rating'].values
                    ratings.append(np.mean(product_ratings))
                ratings = np.array(ratings)
            else:
                # Use equal weights
                ratings = np.ones(len(valid_products))
            
            # Normalize ratings
            if len(ratings) > 1:
                ratings = (ratings - np.mean(ratings)) / (np.std(ratings) + 1e-8)
            
            # Calculate user profile as weighted average of item features
            user_features = np.zeros(self.item_features.shape[1])
            total_weight = 0
            
            for idx, rating in zip(product_indices, ratings):
                weight = max(rating, 0.1)  # Ensure positive weights
                user_features += weight * self.item_features[idx]
                total_weight += weight
            
            if total_weight > 0:
                user_features /= total_weight
                self.user_profiles[customer_id] = user_features
        
        logger.info(f"Built profiles for {len(self.user_profiles)} users")
    
    def get_recommendations(self, 
                          customer_id: str = None, 
                          product_id: str = None,
                          n_recommendations: int = 10,
                          exclude_interacted: bool = True) -> List[Tuple[str, float]]:
        """
        Get content-based recommendations
        
        Args:
            customer_id: Customer ID for personalized recommendations
            product_id: Product ID for similar item recommendations
            n_recommendations: Number of recommendations to return
            exclude_interacted: Whether to exclude already interacted items
        
        Returns:
            List of (product_id, score) tuples
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before making recommendations")
        
        if customer_id and customer_id in self.user_profiles:
            return self._get_user_recommendations(
                customer_id, n_recommendations, exclude_interacted
            )
        elif product_id and product_id in self.product_to_idx:
            return self._get_similar_items(product_id, n_recommendations)
        else:
            # Return popular items as fallback
            return self._get_popular_items(n_recommendations)
    
    def _get_user_recommendations(self, 
                                customer_id: str, 
                                n_recommendations: int,
                                exclude_interacted: bool) -> List[Tuple[str, float]]:
        """Get personalized recommendations for a user"""
        user_profile = self.user_profiles[customer_id]
        
        # Calculate similarity between user profile and all items
        similarities = cosine_similarity([user_profile], self.item_features)[0]
        
        # Get top recommendations
        top_indices = np.argsort(similarities)[::-1]
        
        recommendations = []
        for idx in top_indices:
            if len(recommendations) >= n_recommendations:
                break
            
            product_id = self.idx_to_product[idx]
            score = float(similarities[idx])
            
            # Skip if score is too low
            if score < 0.1:
                continue
            
            recommendations.append((product_id, score))
        
        return recommendations
    
    def _get_similar_items(self, 
                          product_id: str, 
                          n_recommendations: int) -> List[Tuple[str, float]]:
        """Get items similar to a given product"""
        product_idx = self.product_to_idx[product_id]
        
        # Get similarity scores for this product
        similarities = self.item_similarity_matrix[product_idx]
        
        # Get top similar items (excluding the item itself)
        top_indices = np.argsort(similarities)[::-1][1:n_recommendations+1]
        
        recommendations = [
            (self.idx_to_product[idx], float(similarities[idx]))
            for idx in top_indices
        ]
        
        return recommendations
    
    def _get_popular_items(self, n_recommendations: int) -> List[Tuple[str, float]]:
        """Get popular items as fallback"""
        if self.products_df is None:
            return []
        
        # Sort by rating or review count if available
        if 'rating' in self.products_df.columns and 'review_count' in self.products_df.columns:
            # Calculate popularity score
            self.products_df['popularity_score'] = (
                self.products_df['rating'] * np.log1p(self.products_df['review_count'])
            )
            sorted_products = self.products_df.sort_values('popularity_score', ascending=False)
        elif 'rating' in self.products_df.columns:
            sorted_products = self.products_df.sort_values('rating', ascending=False)
        else:
            # Random selection if no rating info
            sorted_products = self.products_df.sample(frac=1, random_state=42)
        
        recommendations = []
        for _, product in sorted_products.head(n_recommendations).iterrows():
            product_id = product['product_id']
            score = product.get('popularity_score', product.get('rating', 1.0))
            recommendations.append((product_id, float(score)))
        
        return recommendations
    
    def get_product_features(self, product_id: str) -> Dict[str, any]:
        """
        Get feature representation of a product
        
        Args:
            product_id: Product ID
        
        Returns:
            Dictionary with product features
        """
        if not self.is_trained or product_id not in self.product_to_idx:
            return {}
        
        product_idx = self.product_to_idx[product_id]
        product_info = self.products_df[
            self.products_df['product_id'] == product_id
        ].iloc[0]
        
        return {
            'product_id': product_id,
            'features': self.item_features[product_idx].tolist(),
            'similarity_scores': self.item_similarity_matrix[product_idx].tolist(),
            'metadata': product_info.to_dict()
        }
    
    def explain_recommendation(self, 
                             customer_id: str, 
                             product_id: str) -> Dict[str, any]:
        """
        Explain why a product was recommended to a customer
        
        Args:
            customer_id: Customer ID
            product_id: Product ID
        
        Returns:
            Explanation dictionary
        """
        if not self.is_trained:
            return {"error": "Model not trained"}
        
        if customer_id not in self.user_profiles:
            return {"error": "Customer profile not found"}
        
        if product_id not in self.product_to_idx:
            return {"error": "Product not found"}
        
        user_profile = self.user_profiles[customer_id]
        product_idx = self.product_to_idx[product_id]
        product_features = self.item_features[product_idx]
        
        # Calculate similarity
        similarity = cosine_similarity([user_profile], [product_features])[0][0]
        
        # Get product info
        product_info = self.products_df[
            self.products_df['product_id'] == product_id
        ].iloc[0]
        
        # Find most similar features
        feature_similarities = user_profile * product_features
        top_feature_indices = np.argsort(feature_similarities)[::-1][:5]
        
        explanation = {
            'customer_id': customer_id,
            'product_id': product_id,
            'similarity_score': float(similarity),
            'product_info': product_info.to_dict(),
            'top_matching_features': top_feature_indices.tolist(),
            'explanation': f"This product matches your preferences with {similarity:.2%} similarity"
        }
        
        return explanation
    
    def update_user_profile(self, 
                          customer_id: str, 
                          new_interactions: pd.DataFrame):
        """
        Update user profile with new interactions
        
        Args:
            customer_id: Customer ID
            new_interactions: New interaction data
        """
        if not self.is_trained:
            return
        
        # Combine with existing profile if exists
        all_interactions = new_interactions[
            new_interactions['customer_id'] == customer_id
        ]
        
        # Rebuild profile for this user
        self._build_user_profiles(all_interactions)
        
        logger.info(f"Updated profile for customer {customer_id}")
    
    def save_model(self, s3_bucket: str, model_key: str):
        """
        Save model to S3
        
        Args:
            s3_bucket: S3 bucket name
            model_key: S3 key for the model
        """
        if not self.is_trained:
            raise ValueError("Cannot save untrained model")
        
        model_data = {
            'tfidf_vectorizer': self.tfidf_vectorizer,
            'scaler': self.scaler,
            'label_encoders': self.label_encoders,
            'pca': self.pca,
            'item_features': self.item_features,
            'item_similarity_matrix': self.item_similarity_matrix,
            'user_profiles': self.user_profiles,
            'product_to_idx': self.product_to_idx,
            'idx_to_product': self.idx_to_product,
            'text_features': self.text_features,
            'categorical_features': self.categorical_features,
            'numerical_features': self.numerical_features,
            'n_components': self.n_components,
            'products_df': self.products_df,
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
        self.tfidf_vectorizer = model_data['tfidf_vectorizer']
        self.scaler = model_data['scaler']
        self.label_encoders = model_data['label_encoders']
        self.pca = model_data['pca']
        self.item_features = model_data['item_features']
        self.item_similarity_matrix = model_data['item_similarity_matrix']
        self.user_profiles = model_data['user_profiles']
        self.product_to_idx = model_data['product_to_idx']
        self.idx_to_product = model_data['idx_to_product']
        self.text_features = model_data['text_features']
        self.categorical_features = model_data['categorical_features']
        self.numerical_features = model_data['numerical_features']
        self.n_components = model_data['n_components']
        self.products_df = model_data['products_df']
        
        self.is_trained = True
        logger.info(f"Model loaded from s3://{s3_bucket}/{model_key}")

# Example usage
if __name__ == "__main__":
    # Sample product data
    products_data = {
        'product_id': ['P1', 'P2', 'P3', 'P4', 'P5'],
        'name': ['Hammer', 'Screwdriver', 'Drill', 'Saw', 'Wrench'],
        'description': ['Heavy duty hammer', 'Phillips screwdriver', 'Electric drill', 'Wood saw', 'Adjustable wrench'],
        'category': ['Tools', 'Tools', 'Power Tools', 'Tools', 'Tools'],
        'brand': ['ToolMaster', 'ToolMaster', 'PowerPro', 'CutRight', 'ToolMaster'],
        'price': [25.99, 12.99, 89.99, 45.99, 18.99],
        'rating': [4.5, 4.0, 4.8, 4.2, 4.1],
        'review_count': [120, 80, 200, 150, 90]
    }
    
    products_df = pd.DataFrame(products_data)
    
    # Sample interaction data
    interactions_data = {
        'customer_id': ['C1', 'C1', 'C2', 'C2', 'C3'],
        'product_id': ['P1', 'P2', 'P1', 'P3', 'P2'],
        'rating': [5.0, 4.0, 4.0, 5.0, 3.0]
    }
    
    interactions_df = pd.DataFrame(interactions_data)
    
    # Create and train model
    model = ContentBasedModel()
    model.train(products_df, interactions_df)
    
    # Get recommendations
    recommendations = model.get_recommendations(customer_id='C1', n_recommendations=3)
    print(f"Recommendations for C1: {recommendations}")
    
    # Get similar items
    similar_items = model.get_recommendations(product_id='P1', n_recommendations=3)
    print(f"Similar items to P1: {similar_items}")
    
    # Get explanation
    explanation = model.explain_recommendation('C1', 'P3')
    print(f"Explanation: {explanation}")