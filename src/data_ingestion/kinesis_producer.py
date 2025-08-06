"""
Kinesis Data Streams Producer for HomeCenter Recommendation System
Handles real-time data ingestion for customer interactions, product views, and purchases.
"""

import json
import boto3
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from botocore.exceptions import ClientError
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class CustomerEvent:
    """Data class for customer interaction events"""
    event_id: str
    customer_id: str
    session_id: str
    event_type: str  # 'view', 'click', 'purchase', 'add_to_cart', 'search'
    product_id: Optional[str] = None
    category_id: Optional[str] = None
    brand: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    search_query: Optional[str] = None
    timestamp: str = None
    page_url: Optional[str] = None
    device_type: Optional[str] = None
    location: Optional[str] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()

class KinesisProducer:
    """
    Kinesis Data Streams producer for real-time event streaming
    """
    
    def __init__(self, stream_name: str, region_name: str = 'us-east-1'):
        self.stream_name = stream_name
        self.region_name = region_name
        self.kinesis_client = boto3.client('kinesis', region_name=region_name)
        self.batch_size = 500  # Max records per batch
        self.batch_timeout = 1.0  # Seconds to wait before flushing batch
        
    async def put_record(self, event: CustomerEvent) -> bool:
        """
        Put a single record to Kinesis stream
        """
        try:
            record_data = json.dumps(asdict(event))
            partition_key = event.customer_id or str(uuid.uuid4())
            
            response = self.kinesis_client.put_record(
                StreamName=self.stream_name,
                Data=record_data,
                PartitionKey=partition_key
            )
            
            logger.info(f"Record sent to shard: {response['ShardId']}")
            return True
            
        except ClientError as e:
            logger.error(f"Failed to put record: {e}")
            return False
    
    async def put_records_batch(self, events: list[CustomerEvent]) -> Dict[str, Any]:
        """
        Put multiple records to Kinesis stream in batch
        """
        records = []
        for event in events:
            record_data = json.dumps(asdict(event))
            partition_key = event.customer_id or str(uuid.uuid4())
            
            records.append({
                'Data': record_data,
                'PartitionKey': partition_key
            })
        
        try:
            response = self.kinesis_client.put_records(
                Records=records,
                StreamName=self.stream_name
            )
            
            failed_count = response['FailedRecordCount']
            if failed_count > 0:
                logger.warning(f"{failed_count} records failed to send")
            
            return response
            
        except ClientError as e:
            logger.error(f"Failed to put records batch: {e}")
            return {}

class EventCollector:
    """
    Collects and buffers events before sending to Kinesis
    """
    
    def __init__(self, producer: KinesisProducer):
        self.producer = producer
        self.buffer = []
        self.buffer_lock = asyncio.Lock()
        self.running = False
        
    async def add_event(self, event: CustomerEvent):
        """Add event to buffer"""
        async with self.buffer_lock:
            self.buffer.append(event)
            
    async def start_processing(self):
        """Start the batch processing loop"""
        self.running = True
        while self.running:
            await asyncio.sleep(self.producer.batch_timeout)
            await self._flush_buffer()
    
    async def _flush_buffer(self):
        """Flush buffer to Kinesis"""
        async with self.buffer_lock:
            if not self.buffer:
                return
                
            batch = self.buffer[:self.producer.batch_size]
            self.buffer = self.buffer[self.producer.batch_size:]
            
        if batch:
            await self.producer.put_records_batch(batch)
            logger.info(f"Flushed {len(batch)} events to Kinesis")
    
    async def stop_processing(self):
        """Stop processing and flush remaining events"""
        self.running = False
        await self._flush_buffer()

# Example usage and event generators
class EventSimulator:
    """
    Simulates customer events for testing
    """
    
    def __init__(self):
        self.product_ids = [f"PROD_{i:06d}" for i in range(1, 10001)]
        self.category_ids = ["HOME", "GARDEN", "TOOLS", "LIGHTING", "KITCHEN", "BATHROOM"]
        self.brands = ["HomeMax", "GardenPro", "ToolMaster", "LightTech", "KitchenPlus"]
        self.customers = [f"CUST_{i:06d}" for i in range(1, 1001)]
        
    def generate_view_event(self, customer_id: str = None) -> CustomerEvent:
        """Generate a product view event"""
        import random
        
        return CustomerEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id or random.choice(self.customers),
            session_id=str(uuid.uuid4()),
            event_type="view",
            product_id=random.choice(self.product_ids),
            category_id=random.choice(self.category_ids),
            brand=random.choice(self.brands),
            price=round(random.uniform(10.0, 1000.0), 2),
            device_type=random.choice(["desktop", "mobile", "tablet"]),
            location=random.choice(["store_1", "store_2", "online"])
        )
    
    def generate_purchase_event(self, customer_id: str = None) -> CustomerEvent:
        """Generate a purchase event"""
        import random
        
        return CustomerEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id or random.choice(self.customers),
            session_id=str(uuid.uuid4()),
            event_type="purchase",
            product_id=random.choice(self.product_ids),
            category_id=random.choice(self.category_ids),
            brand=random.choice(self.brands),
            price=round(random.uniform(10.0, 1000.0), 2),
            quantity=random.randint(1, 5),
            device_type=random.choice(["desktop", "mobile", "tablet"]),
            location=random.choice(["store_1", "store_2", "online"])
        )

async def main():
    """
    Example usage of the Kinesis producer
    """
    # Initialize producer and collector
    producer = KinesisProducer(stream_name="homecentre-events")
    collector = EventCollector(producer)
    simulator = EventSimulator()
    
    # Start processing
    processing_task = asyncio.create_task(collector.start_processing())
    
    try:
        # Simulate events
        for i in range(100):
            if i % 2 == 0:
                event = simulator.generate_view_event()
            else:
                event = simulator.generate_purchase_event()
            
            await collector.add_event(event)
            await asyncio.sleep(0.1)  # 100ms between events
            
    finally:
        await collector.stop_processing()
        processing_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())