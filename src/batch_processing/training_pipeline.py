"""
Batch Processing Pipeline for HomeCenter Recommendation System
Apache Airflow DAG for training and updating recommendation models.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.operators.bash import BashOperator
from airflow.providers.amazon.aws.operators.s3 import S3CreateObjectOperator
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.utils.task_group import TaskGroup
import pandas as pd
import boto3
import logging
import pickle
import tempfile
import os
from typing import Dict, Any, Tuple

# Import our ML models
import sys
sys.path.append('/workspace/src')
from ml_models.hybrid_model import HybridRecommendationModel
from ml_models.collaborative_filtering import create_interaction_matrix_from_events
from utils.data_validator import DataValidator
from utils.model_evaluator import ModelEvaluator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default arguments for the DAG
default_args = {
    'owner': 'data-team',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'max_active_runs': 1
}

# DAG configuration
dag = DAG(
    'homecentre_recommendation_training',
    default_args=default_args,
    description='Train and deploy HomeCenter recommendation models',
    schedule_interval='@daily',  # Run daily
    catchup=False,
    tags=['ml', 'recommendation', 'training']
)

# Configuration
S3_BUCKET = 'homecentre-ml-artifacts'
MODEL_KEY_PREFIX = 'models/recommendation'
DATA_BUCKET = 'homecentre-data-lake'
POSTGRES_CONN_ID = 'postgres_homecentre'
VALIDATION_THRESHOLD = 0.05  # Minimum precision@10 required

def extract_interaction_data(**context) -> str:
    """
    Extract interaction data from PostgreSQL and save to S3
    """
    logger.info("Extracting interaction data...")
    
    # Get data from the last 30 days for training
    end_date = context['ds']
    start_date = (datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d')
    
    # Connect to PostgreSQL
    postgres_hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
    
    # Query interaction data
    interaction_query = """
    SELECT 
        customer_id,
        product_id,
        event_type,
        timestamp,
        session_id,
        device_type,
        location,
        CASE 
            WHEN event_type = 'purchase' THEN 10.0
            WHEN event_type = 'add_to_cart' THEN 5.0
            WHEN event_type = 'click' THEN 2.0
            WHEN event_type = 'view' THEN 1.0
            ELSE 0.5
        END as rating
    FROM customer_events 
    WHERE timestamp >= %s AND timestamp < %s
    AND customer_id IS NOT NULL 
    AND product_id IS NOT NULL
    """
    
    interactions_df = postgres_hook.get_pandas_df(
        interaction_query, 
        parameters=(start_date, end_date)
    )
    
    logger.info(f"Extracted {len(interactions_df)} interaction records")
    
    # Save to S3
    s3_key = f"training_data/{end_date}/interactions.parquet"
    s3_hook = S3Hook()
    
    with tempfile.NamedTemporaryFile(suffix='.parquet') as tmp_file:
        interactions_df.to_parquet(tmp_file.name, index=False)
        s3_hook.load_file(
            filename=tmp_file.name,
            key=s3_key,
            bucket_name=DATA_BUCKET,
            replace=True
        )
    
    return s3_key

def extract_product_data(**context) -> str:
    """
    Extract product catalog data from PostgreSQL and save to S3
    """
    logger.info("Extracting product data...")
    
    # Connect to PostgreSQL
    postgres_hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
    
    # Query product data
    product_query = """
    SELECT 
        p.product_id,
        p.name,
        p.description,
        p.category,
        p.subcategory,
        p.brand,
        p.price,
        COALESCE(r.avg_rating, 0) as rating,
        COALESCE(r.review_count, 0) as review_count
    FROM products p
    LEFT JOIN (
        SELECT 
            product_id,
            AVG(rating) as avg_rating,
            COUNT(*) as review_count
        FROM product_reviews
        GROUP BY product_id
    ) r ON p.product_id = r.product_id
    WHERE p.is_active = true
    """
    
    products_df = postgres_hook.get_pandas_df(product_query)
    
    logger.info(f"Extracted {len(products_df)} product records")
    
    # Save to S3
    end_date = context['ds']
    s3_key = f"training_data/{end_date}/products.parquet"
    s3_hook = S3Hook()
    
    with tempfile.NamedTemporaryFile(suffix='.parquet') as tmp_file:
        products_df.to_parquet(tmp_file.name, index=False)
        s3_hook.load_file(
            filename=tmp_file.name,
            key=s3_key,
            bucket_name=DATA_BUCKET,
            replace=True
        )
    
    return s3_key

def validate_data(**context) -> bool:
    """
    Validate extracted data quality
    """
    logger.info("Validating data quality...")
    
    # Get S3 keys from previous tasks
    interactions_key = context['task_instance'].xcom_pull(task_ids='extract_interaction_data')
    products_key = context['task_instance'].xcom_pull(task_ids='extract_product_data')
    
    s3_hook = S3Hook()
    
    # Load data from S3
    with tempfile.NamedTemporaryFile(suffix='.parquet') as tmp_file:
        s3_hook.download_file(
            key=interactions_key,
            bucket_name=DATA_BUCKET,
            local_path=tmp_file.name
        )
        interactions_df = pd.read_parquet(tmp_file.name)
    
    with tempfile.NamedTemporaryFile(suffix='.parquet') as tmp_file:
        s3_hook.download_file(
            key=products_key,
            bucket_name=DATA_BUCKET,
            local_path=tmp_file.name
        )
        products_df = pd.read_parquet(tmp_file.name)
    
    # Validate data
    validator = DataValidator()
    
    interaction_issues = validator.validate_interactions(interactions_df)
    product_issues = validator.validate_products(products_df)
    
    total_issues = len(interaction_issues) + len(product_issues)
    
    if total_issues > 0:
        logger.warning(f"Found {total_issues} data quality issues")
        for issue in interaction_issues + product_issues:
            logger.warning(f"Data issue: {issue}")
    
    # Fail if critical issues found
    critical_issues = [issue for issue in interaction_issues + product_issues 
                      if issue.get('severity') == 'critical']
    
    if critical_issues:
        raise ValueError(f"Critical data quality issues found: {critical_issues}")
    
    logger.info("Data validation completed successfully")
    return True

def split_data(**context) -> Dict[str, str]:
    """
    Split data into training and testing sets
    """
    logger.info("Splitting data into train/test sets...")
    
    # Get data
    interactions_key = context['task_instance'].xcom_pull(task_ids='extract_interaction_data')
    s3_hook = S3Hook()
    
    with tempfile.NamedTemporaryFile(suffix='.parquet') as tmp_file:
        s3_hook.download_file(
            key=interactions_key,
            bucket_name=DATA_BUCKET,
            local_path=tmp_file.name
        )
        interactions_df = pd.read_parquet(tmp_file.name)
    
    # Sort by timestamp and split chronologically
    interactions_df = interactions_df.sort_values('timestamp')
    split_point = int(len(interactions_df) * 0.8)  # 80% train, 20% test
    
    train_df = interactions_df.iloc[:split_point]
    test_df = interactions_df.iloc[split_point:]
    
    logger.info(f"Train set: {len(train_df)} records, Test set: {len(test_df)} records")
    
    # Save splits to S3
    end_date = context['ds']
    train_key = f"training_data/{end_date}/train_interactions.parquet"
    test_key = f"training_data/{end_date}/test_interactions.parquet"
    
    for df, key in [(train_df, train_key), (test_df, test_key)]:
        with tempfile.NamedTemporaryFile(suffix='.parquet') as tmp_file:
            df.to_parquet(tmp_file.name, index=False)
            s3_hook.load_file(
                filename=tmp_file.name,
                key=key,
                bucket_name=DATA_BUCKET,
                replace=True
            )
    
    return {'train_key': train_key, 'test_key': test_key}

def train_model(**context) -> str:
    """
    Train the hybrid recommendation model
    """
    logger.info("Training hybrid recommendation model...")
    
    # Get data paths
    data_paths = context['task_instance'].xcom_pull(task_ids='split_data')
    products_key = context['task_instance'].xcom_pull(task_ids='extract_product_data')
    
    s3_hook = S3Hook()
    
    # Load training data
    with tempfile.NamedTemporaryFile(suffix='.parquet') as tmp_file:
        s3_hook.download_file(
            key=data_paths['train_key'],
            bucket_name=DATA_BUCKET,
            local_path=tmp_file.name
        )
        train_interactions = pd.read_parquet(tmp_file.name)
    
    with tempfile.NamedTemporaryFile(suffix='.parquet') as tmp_file:
        s3_hook.download_file(
            key=products_key,
            bucket_name=DATA_BUCKET,
            local_path=tmp_file.name
        )
        products_df = pd.read_parquet(tmp_file.name)
    
    # Initialize and train model
    model = HybridRecommendationModel(
        cf_weight=0.5,
        cb_weight=0.4,
        popularity_weight=0.1,
        cf_params={'factors': 100, 'iterations': 20},
        cb_params={'n_components': 50}
    )
    
    # Train the model
    model.train(train_interactions, products_df)
    
    # Save model to S3
    end_date = context['ds']
    model_key = f"{MODEL_KEY_PREFIX}/{end_date}/hybrid_model"
    
    model.save_model(S3_BUCKET, model_key)
    
    logger.info(f"Model saved to s3://{S3_BUCKET}/{model_key}")
    
    return model_key

def evaluate_model(**context) -> Dict[str, Any]:
    """
    Evaluate the trained model
    """
    logger.info("Evaluating trained model...")
    
    # Get paths
    model_key = context['task_instance'].xcom_pull(task_ids='train_model')
    data_paths = context['task_instance'].xcom_pull(task_ids='split_data')
    
    s3_hook = S3Hook()
    
    # Load test data
    with tempfile.NamedTemporaryFile(suffix='.parquet') as tmp_file:
        s3_hook.download_file(
            key=data_paths['test_key'],
            bucket_name=DATA_BUCKET,
            local_path=tmp_file.name
        )
        test_interactions = pd.read_parquet(tmp_file.name)
    
    # Load model
    model = HybridRecommendationModel()
    model.load_model(S3_BUCKET, model_key)
    
    # Evaluate model
    evaluator = ModelEvaluator()
    metrics = evaluator.evaluate_hybrid_model(model, test_interactions)
    
    logger.info(f"Model evaluation metrics: {metrics}")
    
    # Save evaluation results
    end_date = context['ds']
    eval_key = f"evaluation/{end_date}/metrics.json"
    
    import json
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as tmp_file:
        json.dump(metrics, tmp_file, default=str)
        tmp_file.flush()
        s3_hook.load_file(
            filename=tmp_file.name,
            key=eval_key,
            bucket_name=S3_BUCKET,
            replace=True
        )
    
    return metrics

def check_model_quality(**context) -> str:
    """
    Check if model meets quality thresholds
    """
    metrics = context['task_instance'].xcom_pull(task_ids='evaluate_model')
    
    # Get current model precision@10
    precision_at_10 = metrics.get('component_metrics', {}).get('collaborative_filtering', {}).get('precision_at_10', 0)
    
    logger.info(f"Model precision@10: {precision_at_10}")
    
    if precision_at_10 >= VALIDATION_THRESHOLD:
        logger.info("Model quality check passed - deploying to production")
        return 'deploy_model'
    else:
        logger.warning(f"Model quality check failed - precision@10 {precision_at_10} < {VALIDATION_THRESHOLD}")
        return 'model_quality_alert'

def deploy_model(**context) -> bool:
    """
    Deploy the model to production
    """
    logger.info("Deploying model to production...")
    
    model_key = context['task_instance'].xcom_pull(task_ids='train_model')
    
    # Copy model to production location
    s3_hook = S3Hook()
    prod_model_key = f"{MODEL_KEY_PREFIX}/production/recommendation_model_v1"
    
    # This would copy the model to the production path
    copy_source = {'Bucket': S3_BUCKET, 'Key': f"{model_key}_hybrid.pkl"}
    s3_client = boto3.client('s3')
    s3_client.copy_object(
        CopySource=copy_source,
        Bucket=S3_BUCKET,
        Key=f"{prod_model_key}_hybrid.pkl"
    )
    
    # Copy component models as well
    for suffix in ['_cf.pkl', '_cb.pkl']:
        copy_source = {'Bucket': S3_BUCKET, 'Key': f"{model_key}{suffix}"}
        s3_client.copy_object(
            CopySource=copy_source,
            Bucket=S3_BUCKET,
            Key=f"{prod_model_key}{suffix}"
        )
    
    logger.info("Model deployed to production successfully")
    
    # Trigger model reload in API service (this would be done via API call or message queue)
    # For now, we'll just log it
    logger.info("Model deployment complete - API services should reload the model")
    
    return True

def send_quality_alert(**context) -> bool:
    """
    Send alert when model quality is below threshold
    """
    metrics = context['task_instance'].xcom_pull(task_ids='evaluate_model')
    
    # In a real implementation, this would send notifications via email, Slack, etc.
    logger.error(f"Model quality alert: Model performance below threshold. Metrics: {metrics}")
    
    # For now, just log the alert
    return True

def cleanup_old_artifacts(**context) -> bool:
    """
    Clean up old training artifacts
    """
    logger.info("Cleaning up old training artifacts...")
    
    s3_hook = S3Hook()
    
    # Delete training data older than 7 days
    cutoff_date = datetime.strptime(context['ds'], '%Y-%m-%d') - timedelta(days=7)
    cutoff_str = cutoff_date.strftime('%Y-%m-%d')
    
    # List and delete old files
    old_prefixes = [
        f"training_data/{cutoff_str}/",
        f"evaluation/{cutoff_str}/",
        f"{MODEL_KEY_PREFIX}/{cutoff_str}/"
    ]
    
    for prefix in old_prefixes:
        try:
            keys = s3_hook.list_keys(bucket_name=S3_BUCKET, prefix=prefix)
            if keys:
                s3_hook.delete_objects(bucket=S3_BUCKET, keys=keys)
                logger.info(f"Deleted {len(keys)} objects with prefix {prefix}")
        except Exception as e:
            logger.warning(f"Failed to delete objects with prefix {prefix}: {e}")
    
    return True

# Define the task dependencies
with dag:
    
    # Data extraction tasks
    extract_interactions = PythonOperator(
        task_id='extract_interaction_data',
        python_callable=extract_interaction_data,
        doc_md="Extract customer interaction data from PostgreSQL"
    )
    
    extract_products = PythonOperator(
        task_id='extract_product_data',
        python_callable=extract_product_data,
        doc_md="Extract product catalog data from PostgreSQL"
    )
    
    # Data validation
    validate = PythonOperator(
        task_id='validate_data',
        python_callable=validate_data,
        doc_md="Validate data quality and consistency"
    )
    
    # Data preparation
    split = PythonOperator(
        task_id='split_data',
        python_callable=split_data,
        doc_md="Split data into training and testing sets"
    )
    
    # Model training
    train = PythonOperator(
        task_id='train_model',
        python_callable=train_model,
        doc_md="Train the hybrid recommendation model"
    )
    
    # Model evaluation
    evaluate = PythonOperator(
        task_id='evaluate_model',
        python_callable=evaluate_model,
        doc_md="Evaluate model performance on test set"
    )
    
    # Quality check and branching
    quality_check = BranchPythonOperator(
        task_id='check_model_quality',
        python_callable=check_model_quality,
        doc_md="Check if model meets quality thresholds"
    )
    
    # Deployment
    deploy = PythonOperator(
        task_id='deploy_model',
        python_callable=deploy_model,
        doc_md="Deploy model to production if quality checks pass"
    )
    
    # Alert
    alert = PythonOperator(
        task_id='model_quality_alert',
        python_callable=send_quality_alert,
        doc_md="Send alert if model quality is below threshold"
    )
    
    # Cleanup
    cleanup = PythonOperator(
        task_id='cleanup_old_artifacts',
        python_callable=cleanup_old_artifacts,
        trigger_rule='none_failed_min_one_success',
        doc_md="Clean up old training artifacts"
    )

# Set task dependencies
[extract_interactions, extract_products] >> validate >> split >> train >> evaluate >> quality_check
quality_check >> [deploy, alert]
[deploy, alert] >> cleanup