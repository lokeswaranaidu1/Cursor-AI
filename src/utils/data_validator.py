"""
Data Validation Utility for HomeCenter Recommendation System
Validates data quality and consistency for training pipeline.
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Any
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class DataValidator:
    """
    Data validation utility for recommendation system
    """
    
    def __init__(self):
        self.validation_rules = {
            'interactions': {
                'required_columns': ['customer_id', 'product_id', 'event_type', 'timestamp'],
                'min_records': 1000,
                'max_null_percentage': 0.05,
                'valid_event_types': ['view', 'click', 'purchase', 'add_to_cart', 'search']
            },
            'products': {
                'required_columns': ['product_id', 'name', 'category', 'brand', 'price'],
                'min_records': 100,
                'max_null_percentage': 0.1
            }
        }
    
    def validate_interactions(self, interactions_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Validate interaction data
        
        Args:
            interactions_df: DataFrame with interaction data
            
        Returns:
            List of validation issues
        """
        issues = []
        rules = self.validation_rules['interactions']
        
        # Check required columns
        missing_cols = set(rules['required_columns']) - set(interactions_df.columns)
        if missing_cols:
            issues.append({
                'type': 'missing_columns',
                'severity': 'critical',
                'message': f"Missing required columns: {missing_cols}",
                'columns': list(missing_cols)
            })
            return issues  # Can't continue without required columns
        
        # Check minimum number of records
        if len(interactions_df) < rules['min_records']:
            issues.append({
                'type': 'insufficient_data',
                'severity': 'critical',
                'message': f"Insufficient records: {len(interactions_df)} < {rules['min_records']}",
                'record_count': len(interactions_df)
            })
        
        # Check for null values
        for col in rules['required_columns']:
            null_pct = interactions_df[col].isnull().sum() / len(interactions_df)
            if null_pct > rules['max_null_percentage']:
                severity = 'critical' if null_pct > 0.2 else 'warning'
                issues.append({
                    'type': 'high_null_percentage',
                    'severity': severity,
                    'message': f"High null percentage in {col}: {null_pct:.2%}",
                    'column': col,
                    'null_percentage': null_pct
                })
        
        # Check valid event types
        if 'event_type' in interactions_df.columns:
            invalid_events = set(interactions_df['event_type'].unique()) - set(rules['valid_event_types'])
            if invalid_events:
                issues.append({
                    'type': 'invalid_event_types',
                    'severity': 'warning',
                    'message': f"Invalid event types found: {invalid_events}",
                    'invalid_types': list(invalid_events)
                })
        
        # Check timestamp format and range
        if 'timestamp' in interactions_df.columns:
            try:
                timestamps = pd.to_datetime(interactions_df['timestamp'])
                
                # Check for future timestamps
                future_count = (timestamps > datetime.utcnow()).sum()
                if future_count > 0:
                    issues.append({
                        'type': 'future_timestamps',
                        'severity': 'warning',
                        'message': f"Found {future_count} future timestamps",
                        'count': future_count
                    })
                
                # Check for very old timestamps (older than 2 years)
                old_threshold = datetime.utcnow() - timedelta(days=730)
                old_count = (timestamps < old_threshold).sum()
                if old_count > len(interactions_df) * 0.5:  # More than 50% old data
                    issues.append({
                        'type': 'old_data',
                        'severity': 'warning',
                        'message': f"High percentage of old data: {old_count/len(interactions_df):.2%}",
                        'old_percentage': old_count/len(interactions_df)
                    })
                    
            except Exception as e:
                issues.append({
                    'type': 'timestamp_parsing_error',
                    'severity': 'critical',
                    'message': f"Error parsing timestamps: {str(e)}"
                })
        
        # Check for duplicate records
        duplicate_cols = ['customer_id', 'product_id', 'event_type', 'timestamp']
        available_cols = [col for col in duplicate_cols if col in interactions_df.columns]
        
        if len(available_cols) >= 3:
            duplicates = interactions_df.duplicated(subset=available_cols).sum()
            duplicate_pct = duplicates / len(interactions_df)
            
            if duplicate_pct > 0.05:  # More than 5% duplicates
                severity = 'critical' if duplicate_pct > 0.2 else 'warning'
                issues.append({
                    'type': 'high_duplicate_rate',
                    'severity': severity,
                    'message': f"High duplicate rate: {duplicate_pct:.2%}",
                    'duplicate_count': duplicates,
                    'duplicate_percentage': duplicate_pct
                })
        
        # Check customer and product ID distributions
        self._check_id_distributions(interactions_df, issues)
        
        # Check rating values if present
        if 'rating' in interactions_df.columns:
            self._check_rating_values(interactions_df, issues)
        
        logger.info(f"Interaction validation complete: {len(issues)} issues found")
        return issues
    
    def validate_products(self, products_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Validate product data
        
        Args:
            products_df: DataFrame with product data
            
        Returns:
            List of validation issues
        """
        issues = []
        rules = self.validation_rules['products']
        
        # Check required columns
        missing_cols = set(rules['required_columns']) - set(products_df.columns)
        if missing_cols:
            issues.append({
                'type': 'missing_columns',
                'severity': 'critical',
                'message': f"Missing required columns: {missing_cols}",
                'columns': list(missing_cols)
            })
            return issues
        
        # Check minimum number of records
        if len(products_df) < rules['min_records']:
            issues.append({
                'type': 'insufficient_data',
                'severity': 'critical',
                'message': f"Insufficient products: {len(products_df)} < {rules['min_records']}",
                'record_count': len(products_df)
            })
        
        # Check for null values in critical columns
        for col in rules['required_columns']:
            null_pct = products_df[col].isnull().sum() / len(products_df)
            if null_pct > rules['max_null_percentage']:
                severity = 'critical' if col in ['product_id', 'name'] else 'warning'
                issues.append({
                    'type': 'high_null_percentage',
                    'severity': severity,
                    'message': f"High null percentage in {col}: {null_pct:.2%}",
                    'column': col,
                    'null_percentage': null_pct
                })
        
        # Check for duplicate product IDs
        if 'product_id' in products_df.columns:
            duplicates = products_df['product_id'].duplicated().sum()
            if duplicates > 0:
                issues.append({
                    'type': 'duplicate_product_ids',
                    'severity': 'critical',
                    'message': f"Found {duplicates} duplicate product IDs",
                    'duplicate_count': duplicates
                })
        
        # Check price values
        if 'price' in products_df.columns:
            self._check_price_values(products_df, issues)
        
        # Check category distribution
        if 'category' in products_df.columns:
            self._check_category_distribution(products_df, issues)
        
        # Check text field lengths
        text_fields = ['name', 'description']
        for field in text_fields:
            if field in products_df.columns:
                self._check_text_field_length(products_df, field, issues)
        
        logger.info(f"Product validation complete: {len(issues)} issues found")
        return issues
    
    def _check_id_distributions(self, interactions_df: pd.DataFrame, issues: List[Dict[str, Any]]):
        """Check customer and product ID distributions"""
        
        # Check customer ID distribution
        if 'customer_id' in interactions_df.columns:
            customer_counts = interactions_df['customer_id'].value_counts()
            
            # Check for customers with too many interactions (possible bots)
            max_interactions = customer_counts.max()
            if max_interactions > 10000:  # Arbitrary threshold
                high_activity_customers = (customer_counts > 1000).sum()
                issues.append({
                    'type': 'high_activity_customers',
                    'severity': 'warning',
                    'message': f"Found {high_activity_customers} customers with >1000 interactions",
                    'max_interactions': max_interactions,
                    'high_activity_count': high_activity_customers
                })
            
            # Check for too few unique customers
            unique_customers = len(customer_counts)
            if unique_customers < 100:
                issues.append({
                    'type': 'few_customers',
                    'severity': 'warning',
                    'message': f"Low number of unique customers: {unique_customers}",
                    'unique_customers': unique_customers
                })
        
        # Check product ID distribution
        if 'product_id' in interactions_df.columns:
            product_counts = interactions_df['product_id'].value_counts()
            
            # Check for products with no interactions
            unique_products = len(product_counts)
            if unique_products < 50:
                issues.append({
                    'type': 'few_products',
                    'severity': 'warning',
                    'message': f"Low number of unique products: {unique_products}",
                    'unique_products': unique_products
                })
    
    def _check_rating_values(self, interactions_df: pd.DataFrame, issues: List[Dict[str, Any]]):
        """Check rating value distribution"""
        ratings = interactions_df['rating'].dropna()
        
        if len(ratings) == 0:
            return
        
        # Check rating range
        min_rating = ratings.min()
        max_rating = ratings.max()
        
        if min_rating < 0:
            issues.append({
                'type': 'negative_ratings',
                'severity': 'warning',
                'message': f"Found negative ratings: min = {min_rating}",
                'min_rating': min_rating
            })
        
        if max_rating > 100:  # Assuming max reasonable rating is 100
            issues.append({
                'type': 'extreme_ratings',
                'severity': 'warning',
                'message': f"Found extreme ratings: max = {max_rating}",
                'max_rating': max_rating
            })
        
        # Check for constant ratings
        if ratings.nunique() == 1:
            issues.append({
                'type': 'constant_ratings',
                'severity': 'warning',
                'message': f"All ratings are the same value: {ratings.iloc[0]}",
                'rating_value': ratings.iloc[0]
            })
    
    def _check_price_values(self, products_df: pd.DataFrame, issues: List[Dict[str, Any]]):
        """Check price value distribution"""
        prices = products_df['price'].dropna()
        
        if len(prices) == 0:
            return
        
        # Check for negative prices
        negative_prices = (prices < 0).sum()
        if negative_prices > 0:
            issues.append({
                'type': 'negative_prices',
                'severity': 'critical',
                'message': f"Found {negative_prices} products with negative prices",
                'negative_count': negative_prices
            })
        
        # Check for zero prices
        zero_prices = (prices == 0).sum()
        zero_pct = zero_prices / len(prices)
        if zero_pct > 0.1:  # More than 10% zero prices
            issues.append({
                'type': 'high_zero_prices',
                'severity': 'warning',
                'message': f"High percentage of zero prices: {zero_pct:.2%}",
                'zero_percentage': zero_pct
            })
        
        # Check for extreme prices
        mean_price = prices.mean()
        std_price = prices.std()
        extreme_threshold = mean_price + 5 * std_price
        
        extreme_prices = (prices > extreme_threshold).sum()
        if extreme_prices > 0:
            issues.append({
                'type': 'extreme_prices',
                'severity': 'warning',
                'message': f"Found {extreme_prices} products with extreme prices",
                'extreme_count': extreme_prices,
                'threshold': extreme_threshold
            })
    
    def _check_category_distribution(self, products_df: pd.DataFrame, issues: List[Dict[str, Any]]):
        """Check category distribution"""
        categories = products_df['category'].dropna()
        
        if len(categories) == 0:
            return
        
        category_counts = categories.value_counts()
        
        # Check for too few categories
        unique_categories = len(category_counts)
        if unique_categories < 3:
            issues.append({
                'type': 'few_categories',
                'severity': 'warning',
                'message': f"Low number of product categories: {unique_categories}",
                'unique_categories': unique_categories
            })
        
        # Check for highly imbalanced categories
        largest_category_pct = category_counts.iloc[0] / len(categories)
        if largest_category_pct > 0.8:  # One category dominates
            issues.append({
                'type': 'imbalanced_categories',
                'severity': 'warning',
                'message': f"Category distribution highly imbalanced: {largest_category_pct:.2%}",
                'dominant_category_pct': largest_category_pct
            })
    
    def _check_text_field_length(self, products_df: pd.DataFrame, field: str, issues: List[Dict[str, Any]]):
        """Check text field length distribution"""
        text_data = products_df[field].dropna().astype(str)
        
        if len(text_data) == 0:
            return
        
        lengths = text_data.str.len()
        
        # Check for very short text
        short_text = (lengths < 3).sum()
        short_pct = short_text / len(text_data)
        
        if short_pct > 0.1:  # More than 10% very short
            issues.append({
                'type': 'short_text_fields',
                'severity': 'warning',
                'message': f"High percentage of short {field} fields: {short_pct:.2%}",
                'field': field,
                'short_percentage': short_pct
            })
        
        # Check for very long text
        long_text = (lengths > 500).sum()
        if long_text > 0:
            issues.append({
                'type': 'long_text_fields',
                'severity': 'info',
                'message': f"Found {long_text} {field} fields longer than 500 characters",
                'field': field,
                'long_count': long_text
            })
    
    def generate_validation_report(self, 
                                 interaction_issues: List[Dict[str, Any]], 
                                 product_issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate a comprehensive validation report
        
        Args:
            interaction_issues: Issues found in interaction data
            product_issues: Issues found in product data
            
        Returns:
            Validation report dictionary
        """
        all_issues = interaction_issues + product_issues
        
        # Count issues by severity
        severity_counts = {}
        for issue in all_issues:
            severity = issue.get('severity', 'unknown')
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        
        # Count issues by type
        type_counts = {}
        for issue in all_issues:
            issue_type = issue.get('type', 'unknown')
            type_counts[issue_type] = type_counts.get(issue_type, 0) + 1
        
        report = {
            'summary': {
                'total_issues': len(all_issues),
                'interaction_issues': len(interaction_issues),
                'product_issues': len(product_issues),
                'severity_breakdown': severity_counts,
                'type_breakdown': type_counts
            },
            'interaction_validation': {
                'issues': interaction_issues,
                'passed': len(interaction_issues) == 0
            },
            'product_validation': {
                'issues': product_issues,
                'passed': len(product_issues) == 0
            },
            'overall_status': 'passed' if len([i for i in all_issues if i.get('severity') == 'critical']) == 0 else 'failed',
            'generated_at': datetime.utcnow().isoformat()
        }
        
        return report