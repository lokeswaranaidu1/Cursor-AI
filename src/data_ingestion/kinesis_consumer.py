"""
Kinesis Data Streams Consumer for HomeCenter Recommendation System
Processes real-time customer events and triggers recommendation updates.
"""

import json
import boto3
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from botocore.exceptions import ClientError
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ProcessedEvent:
    """Processed event with enriched data"""
    original_event: Dict[str, Any]
    customer_id: str
    event_type: str
    product_id: Optional[str]
    timestamp: datetime
    processed_at: datetime
    features: Dict[str, Any]

class EventProcessor:
    """
    Processes customer events and extracts features
    """
    
    def __init__(self):
        self.event_handlers = {
            'view': self._process_view_event,
            'click': self._process_click_event,
            'purchase': self._process_purchase_event,
            'add_to_cart': self._process_cart_event,
            'search': self._process_search_event
        }
    
    def process_event(self, raw_event: Dict[str, Any]) -> Optional[ProcessedEvent]:
        """
        Process a raw event and extract features
        """
        try:
            event_type = raw_event.get('event_type')
            if event_type not in self.event_handlers:
                logger.warning(f"Unknown event type: {event_type}")
                return None
            
            # Parse timestamp
            timestamp_str = raw_event.get('timestamp')
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            
            # Extract common features
            features = self._extract_common_features(raw_event)
            
            # Process specific event type
            handler = self.event_handlers[event_type]
            additional_features = handler(raw_event)
            features.update(additional_features)
            
            return ProcessedEvent(
                original_event=raw_event,
                customer_id=raw_event['customer_id'],
                event_type=event_type,
                product_id=raw_event.get('product_id'),
                timestamp=timestamp,
                processed_at=datetime.utcnow(),
                features=features
            )
            
        except Exception as e:
            logger.error(f"Error processing event: {e}")
            return None
    
    def _extract_common_features(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Extract common features from all events"""
        return {
            'session_id': event.get('session_id'),
            'device_type': event.get('device_type'),
            'location': event.get('location'),
            'category_id': event.get('category_id'),
            'brand': event.get('brand'),
            'price': event.get('price'),
            'hour_of_day': datetime.fromisoformat(
                event.get('timestamp', '').replace('Z', '+00:00')
            ).hour,
            'day_of_week': datetime.fromisoformat(
                event.get('timestamp', '').replace('Z', '+00:00')
            ).weekday()
        }
    
    def _process_view_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process product view events"""
        return {
            'event_value': 1.0,
            'interaction_strength': 'weak',
            'page_url': event.get('page_url')
        }
    
    def _process_click_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process click events"""
        return {
            'event_value': 2.0,
            'interaction_strength': 'medium'
        }
    
    def _process_purchase_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process purchase events"""
        quantity = event.get('quantity', 1)
        price = event.get('price', 0.0)
        return {
            'event_value': 10.0,
            'interaction_strength': 'strong',
            'quantity': quantity,
            'revenue': price * quantity
        }
    
    def _process_cart_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process add to cart events"""
        return {
            'event_value': 5.0,
            'interaction_strength': 'medium',
            'quantity': event.get('quantity', 1)
        }
    
    def _process_search_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process search events"""
        return {
            'event_value': 1.5,
            'interaction_strength': 'weak',
            'search_query': event.get('search_query')
        }

class KinesisConsumer:
    """
    Kinesis Data Streams consumer with automatic scaling
    """
    
    def __init__(self, stream_name: str, region_name: str = 'us-east-1'):
        self.stream_name = stream_name
        self.region_name = region_name
        self.kinesis_client = boto3.client('kinesis', region_name=region_name)
        self.processor = EventProcessor()
        self.shard_iterators = {}
        self.running = False
        
    async def start_consuming(self, callback: Callable[[List[ProcessedEvent]], None]):
        """
        Start consuming events from all shards
        """
        self.running = True
        
        try:
            # Get stream description
            stream_desc = self.kinesis_client.describe_stream(
                StreamName=self.stream_name
            )
            
            shards = stream_desc['StreamDescription']['Shards']
            logger.info(f"Found {len(shards)} shards")
            
            # Create tasks for each shard
            tasks = []
            for shard in shards:
                shard_id = shard['ShardId']
                task = asyncio.create_task(
                    self._consume_shard(shard_id, callback)
                )
                tasks.append(task)
            
            # Wait for all tasks
            await asyncio.gather(*tasks)
            
        except Exception as e:
            logger.error(f"Error in consumer: {e}")
        finally:
            self.running = False
    
    async def _consume_shard(self, shard_id: str, callback: Callable[[List[ProcessedEvent]], None]):
        """
        Consume events from a specific shard
        """
        try:
            # Get shard iterator
            shard_iterator = self._get_shard_iterator(shard_id)
            
            while self.running and shard_iterator:
                # Get records
                response = self.kinesis_client.get_records(
                    ShardIterator=shard_iterator,
                    Limit=100
                )
                
                records = response.get('Records', [])
                if records:
                    processed_events = self._process_records(records)
                    if processed_events:
                        await asyncio.get_event_loop().run_in_executor(
                            None, callback, processed_events
                        )
                
                # Update shard iterator
                shard_iterator = response.get('NextShardIterator')
                
                # Small delay to avoid throttling
                await asyncio.sleep(0.1)
                
        except Exception as e:
            logger.error(f"Error consuming shard {shard_id}: {e}")
    
    def _get_shard_iterator(self, shard_id: str) -> str:
        """
        Get shard iterator for the given shard
        """
        try:
            response = self.kinesis_client.get_shard_iterator(
                StreamName=self.stream_name,
                ShardId=shard_id,
                ShardIteratorType='LATEST'  # Start from latest records
            )
            return response['ShardIterator']
        except ClientError as e:
            logger.error(f"Error getting shard iterator: {e}")
            return None
    
    def _process_records(self, records: List[Dict[str, Any]]) -> List[ProcessedEvent]:
        """
        Process a batch of records
        """
        processed_events = []
        
        for record in records:
            try:
                # Decode the data
                data = json.loads(record['Data'])
                
                # Process the event
                processed_event = self.processor.process_event(data)
                if processed_event:
                    processed_events.append(processed_event)
                    
            except Exception as e:
                logger.error(f"Error processing record: {e}")
        
        return processed_events
    
    def stop_consuming(self):
        """Stop consuming events"""
        self.running = False

class RecommendationTrigger:
    """
    Triggers recommendation updates based on processed events
    """
    
    def __init__(self):
        self.event_buffers = {}  # customer_id -> list of events
        self.trigger_thresholds = {
            'view': 5,      # Trigger after 5 views
            'purchase': 1,  # Trigger immediately after purchase
            'search': 3     # Trigger after 3 searches
        }
        
    def handle_events(self, events: List[ProcessedEvent]):
        """
        Handle a batch of processed events
        """
        for event in events:
            self._buffer_event(event)
            self._check_triggers(event)
    
    def _buffer_event(self, event: ProcessedEvent):
        """Buffer event for the customer"""
        customer_id = event.customer_id
        if customer_id not in self.event_buffers:
            self.event_buffers[customer_id] = []
        
        self.event_buffers[customer_id].append(event)
        
        # Keep only recent events (last 100)
        if len(self.event_buffers[customer_id]) > 100:
            self.event_buffers[customer_id] = self.event_buffers[customer_id][-100:]
    
    def _check_triggers(self, event: ProcessedEvent):
        """Check if we should trigger recommendation update"""
        customer_id = event.customer_id
        event_type = event.event_type
        
        if event_type in self.trigger_thresholds:
            # Count recent events of this type
            recent_events = [
                e for e in self.event_buffers[customer_id]
                if e.event_type == event_type and
                (datetime.utcnow() - e.processed_at).seconds < 300  # Last 5 minutes
            ]
            
            if len(recent_events) >= self.trigger_thresholds[event_type]:
                self._trigger_recommendation_update(customer_id, event_type)
    
    def _trigger_recommendation_update(self, customer_id: str, trigger_type: str):
        """Trigger recommendation update for customer"""
        logger.info(f"Triggering recommendation update for {customer_id} ({trigger_type})")
        # Here you would call the recommendation service
        # For example: send message to SQS, call Lambda, or API

# Example data persistence classes
class EventStore:
    """
    Stores processed events for analytics and model training
    """
    
    def __init__(self):
        # In production, this would be DynamoDB, S3, or other storage
        self.events = []
    
    def store_events(self, events: List[ProcessedEvent]):
        """Store events for future processing"""
        for event in events:
            self.events.append({
                'customer_id': event.customer_id,
                'event_type': event.event_type,
                'product_id': event.product_id,
                'timestamp': event.timestamp.isoformat(),
                'features': event.features
            })
        
        logger.info(f"Stored {len(events)} events")

async def main():
    """
    Example usage of the Kinesis consumer
    """
    consumer = KinesisConsumer(stream_name="homecentre-events")
    trigger = RecommendationTrigger()
    store = EventStore()
    
    def event_callback(events: List[ProcessedEvent]):
        """Callback to handle processed events"""
        logger.info(f"Processing {len(events)} events")
        
        # Trigger recommendations
        trigger.handle_events(events)
        
        # Store events
        store.store_events(events)
    
    try:
        await consumer.start_consuming(event_callback)
    except KeyboardInterrupt:
        logger.info("Stopping consumer...")
        consumer.stop_consuming()

if __name__ == "__main__":
    asyncio.run(main())