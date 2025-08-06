"""
Real-time Recommendation API Service for HomeCenter
FastAPI-based service providing real-time product recommendations.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
import asyncio
import logging
import redis
import json
import boto3
from datetime import datetime, timedelta
import uvicorn
import os
from contextlib import asynccontextmanager
import time

# Import our ML models
import sys
sys.path.append('/workspace/src')
from ml_models.hybrid_model import HybridRecommendationModel
from data_ingestion.kinesis_producer import KinesisProducer, CustomerEvent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pydantic models for API
class RecommendationRequest(BaseModel):
    customer_id: str = Field(..., description="Customer ID")
    n_recommendations: int = Field(default=10, ge=1, le=50, description="Number of recommendations")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context")
    include_explanations: bool = Field(default=False, description="Include recommendation explanations")
    diversity_threshold: float = Field(default=0.3, ge=0.0, le=1.0, description="Diversity threshold")

class SimilarItemsRequest(BaseModel):
    product_id: str = Field(..., description="Product ID")
    n_recommendations: int = Field(default=10, ge=1, le=50, description="Number of similar items")

class EventTrackingRequest(BaseModel):
    customer_id: str = Field(..., description="Customer ID")
    event_type: str = Field(..., description="Event type (view, click, purchase, etc.)")
    product_id: Optional[str] = Field(default=None, description="Product ID")
    session_id: Optional[str] = Field(default=None, description="Session ID")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional event metadata")

class RecommendationResponse(BaseModel):
    customer_id: str
    recommendations: List[Dict[str, Any]]
    generated_at: datetime
    model_version: str
    processing_time_ms: float

class SimilarItemsResponse(BaseModel):
    product_id: str
    similar_items: List[Dict[str, Any]]
    generated_at: datetime
    processing_time_ms: float

class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    model_status: Dict[str, bool]
    cache_status: bool
    version: str

# Global variables for models and services
recommendation_model: Optional[HybridRecommendationModel] = None
redis_client: Optional[redis.Redis] = None
kinesis_producer: Optional[KinesisProducer] = None

# Configuration
MODEL_BUCKET = os.getenv("MODEL_BUCKET", "homecentre-models")
MODEL_KEY = os.getenv("MODEL_KEY", "recommendation_model_v1")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
KINESIS_STREAM = os.getenv("KINESIS_STREAM", "homecentre-events")
API_VERSION = "1.0.0"
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))  # 1 hour default

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    await startup_event()
    yield
    # Shutdown
    await shutdown_event()

# Create FastAPI app
app = FastAPI(
    title="HomeCenter Recommendation API",
    description="Real-time product recommendation service",
    version=API_VERSION,
    lifespan=lifespan
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

async def startup_event():
    """Initialize services on startup"""
    global recommendation_model, redis_client, kinesis_producer
    
    logger.info("Starting recommendation service...")
    
    try:
        # Initialize Redis
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        redis_client = None
    
    try:
        # Initialize Kinesis producer
        kinesis_producer = KinesisProducer(stream_name=KINESIS_STREAM)
        logger.info("Kinesis producer initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Kinesis producer: {e}")
        kinesis_producer = None
    
    try:
        # Load recommendation model
        recommendation_model = HybridRecommendationModel()
        recommendation_model.load_model(MODEL_BUCKET, MODEL_KEY)
        logger.info("Recommendation model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load recommendation model: {e}")
        recommendation_model = None

async def shutdown_event():
    """Cleanup on shutdown"""
    global redis_client
    
    logger.info("Shutting down recommendation service...")
    
    if redis_client:
        redis_client.close()
    
    logger.info("Service shutdown complete")

def get_redis() -> Optional[redis.Redis]:
    """Dependency to get Redis client"""
    return redis_client

def get_model() -> HybridRecommendationModel:
    """Dependency to get recommendation model"""
    if recommendation_model is None:
        raise HTTPException(status_code=503, detail="Recommendation model not available")
    return recommendation_model

async def cache_get(key: str) -> Optional[Dict]:
    """Get data from cache"""
    if redis_client is None:
        return None
    
    try:
        data = redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning(f"Cache get failed: {e}")
    
    return None

async def cache_set(key: str, data: Dict, ttl: int = CACHE_TTL):
    """Set data in cache"""
    if redis_client is None:
        return
    
    try:
        redis_client.setex(key, ttl, json.dumps(data, default=str))
    except Exception as e:
        logger.warning(f"Cache set failed: {e}")

async def track_event_async(event: CustomerEvent):
    """Track event asynchronously"""
    if kinesis_producer:
        try:
            await kinesis_producer.put_record(event)
        except Exception as e:
            logger.error(f"Failed to track event: {e}")

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    model_status = {
        "hybrid_model": recommendation_model is not None and recommendation_model.is_trained,
        "cf_model": recommendation_model is not None and recommendation_model.cf_model.is_trained,
        "cb_model": recommendation_model is not None and recommendation_model.cb_model.is_trained,
    }
    
    cache_status = redis_client is not None
    
    # Overall health status
    overall_status = "healthy" if any(model_status.values()) else "degraded"
    
    return HealthResponse(
        status=overall_status,
        timestamp=datetime.utcnow(),
        model_status=model_status,
        cache_status=cache_status,
        version=API_VERSION
    )

@app.post("/recommendations", response_model=RecommendationResponse)
async def get_recommendations(
    request: RecommendationRequest,
    background_tasks: BackgroundTasks,
    model: HybridRecommendationModel = Depends(get_model)
):
    """Get personalized recommendations for a customer"""
    start_time = time.time()
    
    # Check cache first
    cache_key = f"recommendations:{request.customer_id}:{request.n_recommendations}:{request.diversity_threshold}"
    cached_result = await cache_get(cache_key)
    
    if cached_result:
        logger.info(f"Cache hit for customer {request.customer_id}")
        cached_result['processing_time_ms'] = (time.time() - start_time) * 1000
        return RecommendationResponse(**cached_result)
    
    try:
        # Get recommendations from model
        recommendations = model.get_recommendations(
            customer_id=request.customer_id,
            n_recommendations=request.n_recommendations,
            diversity_threshold=request.diversity_threshold,
            include_explanations=request.include_explanations
        )
        
        # Format response
        formatted_recommendations = []
        for product_id, score, explanation in recommendations:
            rec_item = {
                "product_id": product_id,
                "score": score,
                "rank": len(formatted_recommendations) + 1
            }
            if request.include_explanations:
                rec_item["explanation"] = explanation
            formatted_recommendations.append(rec_item)
        
        response_data = {
            "customer_id": request.customer_id,
            "recommendations": formatted_recommendations,
            "generated_at": datetime.utcnow(),
            "model_version": API_VERSION,
            "processing_time_ms": (time.time() - start_time) * 1000
        }
        
        # Cache the result (without processing time)
        cache_data = response_data.copy()
        del cache_data['processing_time_ms']
        background_tasks.add_task(cache_set, cache_key, cache_data)
        
        # Track recommendation request event
        if kinesis_producer:
            event = CustomerEvent(
                event_id=f"rec_request_{int(time.time())}",
                customer_id=request.customer_id,
                session_id=request.context.get('session_id') if request.context else None,
                event_type="recommendation_request",
                timestamp=datetime.utcnow().isoformat()
            )
            background_tasks.add_task(track_event_async, event)
        
        return RecommendationResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate recommendations")

@app.post("/similar-items", response_model=SimilarItemsResponse)
async def get_similar_items(
    request: SimilarItemsRequest,
    background_tasks: BackgroundTasks,
    model: HybridRecommendationModel = Depends(get_model)
):
    """Get items similar to a given product"""
    start_time = time.time()
    
    # Check cache first
    cache_key = f"similar_items:{request.product_id}:{request.n_recommendations}"
    cached_result = await cache_get(cache_key)
    
    if cached_result:
        logger.info(f"Cache hit for similar items to {request.product_id}")
        cached_result['processing_time_ms'] = (time.time() - start_time) * 1000
        return SimilarItemsResponse(**cached_result)
    
    try:
        # Get similar items from model
        similar_items = model.get_similar_items(
            product_id=request.product_id,
            n_recommendations=request.n_recommendations
        )
        
        # Format response
        formatted_items = []
        for product_id, score in similar_items:
            formatted_items.append({
                "product_id": product_id,
                "similarity_score": score,
                "rank": len(formatted_items) + 1
            })
        
        response_data = {
            "product_id": request.product_id,
            "similar_items": formatted_items,
            "generated_at": datetime.utcnow(),
            "processing_time_ms": (time.time() - start_time) * 1000
        }
        
        # Cache the result
        cache_data = response_data.copy()
        del cache_data['processing_time_ms']
        background_tasks.add_task(cache_set, cache_key, cache_data)
        
        return SimilarItemsResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Error finding similar items: {e}")
        raise HTTPException(status_code=500, detail="Failed to find similar items")

@app.post("/track-event")
async def track_event(
    request: EventTrackingRequest,
    background_tasks: BackgroundTasks
):
    """Track customer events for real-time learning"""
    try:
        # Create event object
        event = CustomerEvent(
            event_id=f"{request.event_type}_{int(time.time())}",
            customer_id=request.customer_id,
            session_id=request.session_id,
            event_type=request.event_type,
            product_id=request.product_id,
            timestamp=datetime.utcnow().isoformat()
        )
        
        # Add metadata if provided
        if request.metadata:
            for key, value in request.metadata.items():
                if hasattr(event, key):
                    setattr(event, key, value)
        
        # Track event asynchronously
        background_tasks.add_task(track_event_async, event)
        
        # Invalidate relevant caches
        if request.customer_id:
            cache_patterns = [
                f"recommendations:{request.customer_id}:*",
            ]
            if redis_client:
                for pattern in cache_patterns:
                    try:
                        keys = redis_client.keys(pattern)
                        if keys:
                            redis_client.delete(*keys)
                    except Exception as e:
                        logger.warning(f"Cache invalidation failed: {e}")
        
        return {"status": "success", "message": "Event tracked successfully"}
        
    except Exception as e:
        logger.error(f"Error tracking event: {e}")
        raise HTTPException(status_code=500, detail="Failed to track event")

@app.get("/recommendations/explain/{customer_id}/{product_id}")
async def explain_recommendation(
    customer_id: str,
    product_id: str,
    model: HybridRecommendationModel = Depends(get_model)
):
    """Get explanation for why a product was recommended"""
    try:
        explanation = model.explain_recommendation(customer_id, product_id)
        return {
            "customer_id": customer_id,
            "product_id": product_id,
            "explanation": explanation,
            "generated_at": datetime.utcnow()
        }
    except Exception as e:
        logger.error(f"Error generating explanation: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate explanation")

@app.get("/model/stats")
async def get_model_stats(model: HybridRecommendationModel = Depends(get_model)):
    """Get model statistics and performance metrics"""
    try:
        stats = {
            "model_info": {
                "version": API_VERSION,
                "is_trained": model.is_trained,
                "weights": {
                    "collaborative_filtering": model.cf_weight,
                    "content_based": model.cb_weight,
                    "popularity": model.popularity_weight
                }
            },
            "collaborative_filtering": {
                "is_trained": model.cf_model.is_trained,
                "n_users": model.cf_model.n_users if model.cf_model.is_trained else 0,
                "n_items": model.cf_model.n_items if model.cf_model.is_trained else 0
            },
            "content_based": {
                "is_trained": model.cb_model.is_trained,
                "n_user_profiles": len(model.cb_model.user_profiles),
                "n_products": len(model.cb_model.product_to_idx)
            },
            "popularity": {
                "n_products_with_scores": len(model.popularity_scores)
            }
        }
        return stats
    except Exception as e:
        logger.error(f"Error getting model stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get model statistics")

@app.post("/model/reload")
async def reload_model(background_tasks: BackgroundTasks):
    """Reload the recommendation model from S3"""
    try:
        global recommendation_model
        
        new_model = HybridRecommendationModel()
        new_model.load_model(MODEL_BUCKET, MODEL_KEY)
        
        # Replace the model atomically
        recommendation_model = new_model
        
        # Clear all caches
        if redis_client:
            background_tasks.add_task(redis_client.flushdb)
        
        return {
            "status": "success",
            "message": "Model reloaded successfully",
            "timestamp": datetime.utcnow()
        }
    except Exception as e:
        logger.error(f"Error reloading model: {e}")
        raise HTTPException(status_code=500, detail="Failed to reload model")

@app.get("/cache/stats")
async def get_cache_stats():
    """Get cache statistics"""
    if redis_client is None:
        raise HTTPException(status_code=503, detail="Cache not available")
    
    try:
        info = redis_client.info('memory')
        keyspace = redis_client.info('keyspace')
        
        return {
            "memory_usage": info.get('used_memory_human', 'N/A'),
            "total_keys": sum(db.get('keys', 0) for db in keyspace.values()),
            "connected_clients": redis_client.info('clients').get('connected_clients', 0),
            "cache_hits": redis_client.info('stats').get('keyspace_hits', 0),
            "cache_misses": redis_client.info('stats').get('keyspace_misses', 0)
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get cache statistics")

@app.delete("/cache/clear")
async def clear_cache():
    """Clear all cached data"""
    if redis_client is None:
        raise HTTPException(status_code=503, detail="Cache not available")
    
    try:
        redis_client.flushdb()
        return {"status": "success", "message": "Cache cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear cache")

# Development server
if __name__ == "__main__":
    uvicorn.run(
        "recommendation_service:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )