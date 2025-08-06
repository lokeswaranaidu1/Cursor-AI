"""
Model Evaluation Utility for HomeCenter Recommendation System
Evaluates recommendation model performance and quality.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple
import logging
from datetime import datetime
from sklearn.metrics import precision_score, recall_score, f1_score
import math

logger = logging.getLogger(__name__)

class ModelEvaluator:
    """
    Model evaluation utility for recommendation systems
    """
    
    def __init__(self):
        self.k_values = [5, 10, 20]  # Top-k values for evaluation
        self.min_interactions = 5    # Minimum interactions per user for evaluation
    
    def evaluate_hybrid_model(self, 
                             model, 
                             test_interactions: pd.DataFrame) -> Dict[str, Any]:
        """
        Evaluate hybrid recommendation model
        
        Args:
            model: Trained hybrid recommendation model
            test_interactions: Test interaction data
            
        Returns:
            Evaluation metrics dictionary
        """
        logger.info("Evaluating hybrid recommendation model...")
        
        metrics = {
            'evaluation_timestamp': datetime.utcnow().isoformat(),
            'test_data_size': len(test_interactions),
            'model_info': {
                'is_trained': model.is_trained,
                'cf_weight': model.cf_weight,
                'cb_weight': model.cb_weight,
                'popularity_weight': model.popularity_weight
            }
        }
        
        # Evaluate component models separately
        if model.cf_model.is_trained:
            cf_metrics = self._evaluate_collaborative_filtering(model.cf_model, test_interactions)
            metrics['component_metrics'] = {'collaborative_filtering': cf_metrics}
        
        if model.cb_model.is_trained:
            cb_metrics = self._evaluate_content_based(model.cb_model, test_interactions)
            if 'component_metrics' not in metrics:
                metrics['component_metrics'] = {}
            metrics['component_metrics']['content_based'] = cb_metrics
        
        # Evaluate hybrid model
        hybrid_metrics = self._evaluate_recommendation_quality(model, test_interactions)
        metrics['hybrid_metrics'] = hybrid_metrics
        
        # Calculate overall performance score
        metrics['overall_score'] = self._calculate_overall_score(metrics)
        
        logger.info(f"Model evaluation completed. Overall score: {metrics['overall_score']:.3f}")
        return metrics
    
    def _evaluate_collaborative_filtering(self, cf_model, test_interactions: pd.DataFrame) -> Dict[str, Any]:
        """Evaluate collaborative filtering model"""
        logger.info("Evaluating collaborative filtering model...")
        
        # Prepare test data in the format expected by CF model
        from ..ml_models.collaborative_filtering import create_interaction_matrix_from_events
        
        if 'rating' in test_interactions.columns:
            test_data = test_interactions[['customer_id', 'product_id', 'rating']].copy()
        else:
            test_data = create_interaction_matrix_from_events(test_interactions)
        
        # Use CF model's built-in evaluation
        try:
            cf_metrics = cf_model.evaluate(test_data)
            cf_metrics['model_stats'] = {
                'n_users': cf_model.n_users,
                'n_items': cf_model.n_items,
                'sparsity': 1.0 - (len(test_data) / (cf_model.n_users * cf_model.n_items))
            }
        except Exception as e:
            logger.warning(f"CF evaluation failed: {e}")
            cf_metrics = {'error': str(e)}
        
        return cf_metrics
    
    def _evaluate_content_based(self, cb_model, test_interactions: pd.DataFrame) -> Dict[str, Any]:
        """Evaluate content-based model"""
        logger.info("Evaluating content-based model...")
        
        metrics = {
            'model_stats': {
                'n_user_profiles': len(cb_model.user_profiles),
                'n_products': len(cb_model.product_to_idx),
                'has_similarity_matrix': cb_model.item_similarity_matrix is not None
            }
        }
        
        # Calculate coverage metrics
        if cb_model.item_similarity_matrix is not None:
            similarity_matrix = cb_model.item_similarity_matrix
            
            # Catalog coverage: percentage of items that can be recommended
            non_zero_similarities = (similarity_matrix > 0.1).sum(axis=1)
            recommendable_items = (non_zero_similarities > 0).sum()
            catalog_coverage = recommendable_items / len(cb_model.product_to_idx)
            
            metrics['catalog_coverage'] = catalog_coverage
            
            # Average similarity
            avg_similarity = similarity_matrix.mean()
            metrics['average_similarity'] = float(avg_similarity)
            
            # Similarity distribution
            similarities = similarity_matrix[np.triu_indices_from(similarity_matrix, k=1)]
            metrics['similarity_stats'] = {
                'mean': float(similarities.mean()),
                'std': float(similarities.std()),
                'min': float(similarities.min()),
                'max': float(similarities.max())
            }
        
        return metrics
    
    def _evaluate_recommendation_quality(self, model, test_interactions: pd.DataFrame) -> Dict[str, Any]:
        """Evaluate overall recommendation quality"""
        logger.info("Evaluating recommendation quality...")
        
        # Group interactions by customer
        customer_interactions = test_interactions.groupby('customer_id')['product_id'].apply(set).to_dict()
        
        # Filter customers with minimum interactions
        valid_customers = {
            customer_id: products 
            for customer_id, products in customer_interactions.items()
            if len(products) >= self.min_interactions
        }
        
        if not valid_customers:
            logger.warning("No customers with sufficient interactions for evaluation")
            return {'error': 'insufficient_data'}
        
        logger.info(f"Evaluating {len(valid_customers)} customers")
        
        metrics = {}
        
        # Calculate metrics for each k value
        for k in self.k_values:
            k_metrics = self._calculate_topk_metrics(model, valid_customers, k)
            metrics[f'top_{k}'] = k_metrics
        
        # Calculate additional metrics
        metrics['diversity'] = self._calculate_diversity(model, list(valid_customers.keys()))
        metrics['novelty'] = self._calculate_novelty(model, list(valid_customers.keys()))
        metrics['coverage'] = self._calculate_catalog_coverage(model, list(valid_customers.keys()))
        
        return metrics
    
    def _calculate_topk_metrics(self, model, customer_interactions: Dict[str, set], k: int) -> Dict[str, float]:
        """Calculate top-k metrics (precision, recall, F1)"""
        precisions = []
        recalls = []
        hit_rates = []
        
        for customer_id, actual_products in customer_interactions.items():
            try:
                # Get recommendations
                recommendations = model.get_recommendations(
                    customer_id=customer_id,
                    n_recommendations=k,
                    include_explanations=False
                )
                
                if not recommendations:
                    continue
                
                # Extract recommended product IDs
                recommended_products = set([rec[0] for rec in recommendations])
                
                # Calculate metrics
                intersection = actual_products & recommended_products
                
                if len(recommended_products) > 0:
                    precision = len(intersection) / len(recommended_products)
                    precisions.append(precision)
                
                if len(actual_products) > 0:
                    recall = len(intersection) / len(actual_products)
                    recalls.append(recall)
                
                # Hit rate (at least one correct recommendation)
                hit_rate = 1.0 if len(intersection) > 0 else 0.0
                hit_rates.append(hit_rate)
                
            except Exception as e:
                logger.warning(f"Error evaluating customer {customer_id}: {e}")
                continue
        
        # Calculate average metrics
        avg_precision = np.mean(precisions) if precisions else 0.0
        avg_recall = np.mean(recalls) if recalls else 0.0
        avg_hit_rate = np.mean(hit_rates) if hit_rates else 0.0
        
        # Calculate F1 score
        f1 = 2 * (avg_precision * avg_recall) / (avg_precision + avg_recall) if (avg_precision + avg_recall) > 0 else 0.0
        
        return {
            'precision': avg_precision,
            'recall': avg_recall,
            'f1_score': f1,
            'hit_rate': avg_hit_rate,
            'n_evaluated_customers': len(precisions)
        }
    
    def _calculate_diversity(self, model, customer_ids: List[str]) -> Dict[str, float]:
        """Calculate recommendation diversity"""
        logger.info("Calculating diversity metrics...")
        
        all_recommendations = set()
        customer_diversities = []
        
        for customer_id in customer_ids[:100]:  # Sample for performance
            try:
                recommendations = model.get_recommendations(
                    customer_id=customer_id,
                    n_recommendations=10,
                    include_explanations=False
                )
                
                if not recommendations:
                    continue
                
                recommended_products = [rec[0] for rec in recommendations]
                all_recommendations.update(recommended_products)
                
                # Calculate intra-list diversity for this customer
                if hasattr(model, 'cb_model') and model.cb_model.is_trained:
                    diversity = self._calculate_intra_list_diversity(
                        recommended_products, model.cb_model
                    )
                    customer_diversities.append(diversity)
                
            except Exception as e:
                logger.warning(f"Error calculating diversity for {customer_id}: {e}")
                continue
        
        # Calculate catalog coverage (diversity across all recommendations)
        total_products = len(model.cb_model.product_to_idx) if hasattr(model, 'cb_model') else 1
        catalog_coverage = len(all_recommendations) / total_products
        
        avg_intra_list_diversity = np.mean(customer_diversities) if customer_diversities else 0.0
        
        return {
            'catalog_coverage': catalog_coverage,
            'intra_list_diversity': avg_intra_list_diversity,
            'unique_recommendations': len(all_recommendations)
        }
    
    def _calculate_intra_list_diversity(self, product_ids: List[str], cb_model) -> float:
        """Calculate diversity within a recommendation list"""
        if len(product_ids) < 2:
            return 0.0
        
        try:
            similarities = []
            for i in range(len(product_ids)):
                for j in range(i + 1, len(product_ids)):
                    prod1, prod2 = product_ids[i], product_ids[j]
                    
                    if (prod1 in cb_model.product_to_idx and 
                        prod2 in cb_model.product_to_idx):
                        
                        idx1 = cb_model.product_to_idx[prod1]
                        idx2 = cb_model.product_to_idx[prod2]
                        
                        similarity = cb_model.item_similarity_matrix[idx1][idx2]
                        similarities.append(similarity)
            
            # Diversity is 1 - average similarity
            avg_similarity = np.mean(similarities) if similarities else 0.0
            return 1.0 - avg_similarity
            
        except Exception as e:
            logger.warning(f"Error calculating intra-list diversity: {e}")
            return 0.0
    
    def _calculate_novelty(self, model, customer_ids: List[str]) -> Dict[str, float]:
        """Calculate recommendation novelty"""
        logger.info("Calculating novelty metrics...")
        
        # Get popularity scores
        popularity_scores = model.popularity_scores if hasattr(model, 'popularity_scores') else {}
        
        if not popularity_scores:
            return {'error': 'no_popularity_data'}
        
        novelties = []
        
        for customer_id in customer_ids[:100]:  # Sample for performance
            try:
                recommendations = model.get_recommendations(
                    customer_id=customer_id,
                    n_recommendations=10,
                    include_explanations=False
                )
                
                if not recommendations:
                    continue
                
                # Calculate novelty as negative log of popularity
                customer_novelty = 0.0
                valid_recs = 0
                
                for product_id, _ in recommendations:
                    if product_id in popularity_scores:
                        popularity = popularity_scores[product_id]
                        novelty = -math.log2(popularity + 1e-10)  # Add small value to avoid log(0)
                        customer_novelty += novelty
                        valid_recs += 1
                
                if valid_recs > 0:
                    customer_novelty /= valid_recs
                    novelties.append(customer_novelty)
                
            except Exception as e:
                logger.warning(f"Error calculating novelty for {customer_id}: {e}")
                continue
        
        avg_novelty = np.mean(novelties) if novelties else 0.0
        
        return {
            'average_novelty': avg_novelty,
            'n_evaluated_customers': len(novelties)
        }
    
    def _calculate_catalog_coverage(self, model, customer_ids: List[str]) -> Dict[str, float]:
        """Calculate catalog coverage"""
        all_recommended_products = set()
        
        for customer_id in customer_ids:
            try:
                recommendations = model.get_recommendations(
                    customer_id=customer_id,
                    n_recommendations=10,
                    include_explanations=False
                )
                
                recommended_products = [rec[0] for rec in recommendations]
                all_recommended_products.update(recommended_products)
                
            except Exception as e:
                logger.warning(f"Error getting recommendations for {customer_id}: {e}")
                continue
        
        # Calculate coverage
        total_products = len(model.cb_model.product_to_idx) if hasattr(model, 'cb_model') else len(model.popularity_scores)
        coverage = len(all_recommended_products) / total_products if total_products > 0 else 0.0
        
        return {
            'catalog_coverage': coverage,
            'recommended_products': len(all_recommended_products),
            'total_products': total_products
        }
    
    def _calculate_overall_score(self, metrics: Dict[str, Any]) -> float:
        """Calculate overall model performance score"""
        score = 0.0
        weight_sum = 0.0
        
        # Precision@10 (weight: 0.3)
        if 'hybrid_metrics' in metrics and 'top_10' in metrics['hybrid_metrics']:
            precision_10 = metrics['hybrid_metrics']['top_10'].get('precision', 0.0)
            score += precision_10 * 0.3
            weight_sum += 0.3
        
        # Recall@10 (weight: 0.2)
        if 'hybrid_metrics' in metrics and 'top_10' in metrics['hybrid_metrics']:
            recall_10 = metrics['hybrid_metrics']['top_10'].get('recall', 0.0)
            score += recall_10 * 0.2
            weight_sum += 0.2
        
        # Diversity (weight: 0.2)
        if 'hybrid_metrics' in metrics and 'diversity' in metrics['hybrid_metrics']:
            diversity = metrics['hybrid_metrics']['diversity'].get('intra_list_diversity', 0.0)
            score += diversity * 0.2
            weight_sum += 0.2
        
        # Coverage (weight: 0.15)
        if 'hybrid_metrics' in metrics and 'coverage' in metrics['hybrid_metrics']:
            coverage = metrics['hybrid_metrics']['coverage'].get('catalog_coverage', 0.0)
            score += coverage * 0.15
            weight_sum += 0.15
        
        # Novelty (weight: 0.15)
        if 'hybrid_metrics' in metrics and 'novelty' in metrics['hybrid_metrics']:
            novelty = min(metrics['hybrid_metrics']['novelty'].get('average_novelty', 0.0) / 10.0, 1.0)
            score += novelty * 0.15
            weight_sum += 0.15
        
        # Normalize score
        return score / weight_sum if weight_sum > 0 else 0.0
    
    def generate_evaluation_report(self, metrics: Dict[str, Any]) -> str:
        """Generate human-readable evaluation report"""
        report = [
            "=" * 60,
            "HOMECENTRE RECOMMENDATION MODEL EVALUATION REPORT",
            "=" * 60,
            "",
            f"Evaluation Date: {metrics.get('evaluation_timestamp', 'Unknown')}",
            f"Test Data Size: {metrics.get('test_data_size', 'Unknown')} interactions",
            f"Overall Score: {metrics.get('overall_score', 0.0):.3f}",
            "",
            "MODEL CONFIGURATION:",
            f"  CF Weight: {metrics.get('model_info', {}).get('cf_weight', 'N/A'):.2f}",
            f"  CB Weight: {metrics.get('model_info', {}).get('cb_weight', 'N/A'):.2f}",
            f"  Popularity Weight: {metrics.get('model_info', {}).get('popularity_weight', 'N/A'):.2f}",
            "",
        ]
        
        # Add component metrics
        if 'component_metrics' in metrics:
            report.append("COMPONENT MODEL PERFORMANCE:")
            
            if 'collaborative_filtering' in metrics['component_metrics']:
                cf_metrics = metrics['component_metrics']['collaborative_filtering']
                report.extend([
                    f"  Collaborative Filtering:",
                    f"    Precision@10: {cf_metrics.get('precision_at_10', 0.0):.3f}",
                    f"    Recall@10: {cf_metrics.get('recall_at_10', 0.0):.3f}",
                    f"    Coverage: {cf_metrics.get('catalog_coverage', 0.0):.3f}",
                ])
            
            if 'content_based' in metrics['component_metrics']:
                cb_metrics = metrics['component_metrics']['content_based']
                report.extend([
                    f"  Content-Based:",
                    f"    User Profiles: {cb_metrics.get('model_stats', {}).get('n_user_profiles', 0)}",
                    f"    Products: {cb_metrics.get('model_stats', {}).get('n_products', 0)}",
                    f"    Avg Similarity: {cb_metrics.get('average_similarity', 0.0):.3f}",
                ])
        
        # Add hybrid metrics
        if 'hybrid_metrics' in metrics:
            report.append("")
            report.append("HYBRID MODEL PERFORMANCE:")
            
            hybrid_metrics = metrics['hybrid_metrics']
            
            # Top-k metrics
            for k in [5, 10, 20]:
                if f'top_{k}' in hybrid_metrics:
                    k_metrics = hybrid_metrics[f'top_{k}']
                    report.extend([
                        f"  Top-{k}:",
                        f"    Precision: {k_metrics.get('precision', 0.0):.3f}",
                        f"    Recall: {k_metrics.get('recall', 0.0):.3f}",
                        f"    F1-Score: {k_metrics.get('f1_score', 0.0):.3f}",
                        f"    Hit Rate: {k_metrics.get('hit_rate', 0.0):.3f}",
                    ])
            
            # Quality metrics
            if 'diversity' in hybrid_metrics:
                diversity = hybrid_metrics['diversity']
                report.extend([
                    "",
                    "QUALITY METRICS:",
                    f"  Diversity: {diversity.get('intra_list_diversity', 0.0):.3f}",
                    f"  Coverage: {diversity.get('catalog_coverage', 0.0):.3f}",
                ])
            
            if 'novelty' in hybrid_metrics:
                novelty = hybrid_metrics['novelty']
                report.append(f"  Novelty: {novelty.get('average_novelty', 0.0):.3f}")
        
        report.extend([
            "",
            "=" * 60
        ])
        
        return "\n".join(report)