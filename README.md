# HomeCenter Product Recommendation System

A comprehensive product recommendation system for retail stores, designed to provide personalized product recommendations using machine learning and real-time data processing.

## Architecture Overview

The system is built on AWS cloud infrastructure with the following key components:

### 1. Data Ingestion Layer
- **AWS Kinesis Data Streams** for real-time customer interaction data
- **AWS API Gateway** for REST API endpoints
- **Apache Kafka** (MSK) for event streaming
- **AWS Lambda** for serverless data processing

### 2. Data Storage Layer
- **Amazon S3** for data lake (raw data, processed data, model artifacts)
- **Amazon RDS (PostgreSQL)** for transactional data
- **Amazon DynamoDB** for user profiles and real-time recommendations
- **Amazon ElastiCache (Redis)** for caching

### 3. ML/Analytics Layer
- **Amazon SageMaker** for model training and deployment
- **AWS Glue** for ETL operations
- **Amazon EMR** for large-scale data processing
- **Apache Spark** for distributed computing

### 4. Application Layer
- **Amazon EKS** for containerized microservices
- **AWS Lambda** for serverless functions
- **Amazon API Gateway** for API management
- **AWS ELB** for load balancing

### 5. Monitoring & Security
- **Amazon CloudWatch** for monitoring and logging
- **AWS X-Ray** for distributed tracing
- **AWS IAM** for access control
- **AWS KMS** for encryption

## Features

- **Real-time Recommendations**: Instant product suggestions based on current browsing
- **Collaborative Filtering**: Recommendations based on similar customer behavior
- **Content-based Filtering**: Product recommendations based on item features
- **Hybrid Approach**: Combines multiple recommendation strategies
- **A/B Testing**: Built-in experimentation framework
- **Real-time Analytics**: Live dashboards and metrics
- **Scalable Architecture**: Auto-scaling based on demand

## Data Pipeline

1. **Data Collection**: Customer interactions, product views, purchases, ratings
2. **Stream Processing**: Real-time event processing with Kinesis
3. **Batch Processing**: Daily/hourly aggregations and model training
4. **Feature Engineering**: Customer and product feature extraction
5. **Model Training**: Automated ML pipeline with SageMaker
6. **Model Deployment**: Real-time serving with low latency
7. **Feedback Loop**: Continuous learning from user interactions

## Quick Start

```bash
# Clone the repository
git clone <repository-url>
cd homecentre-recommendation-system

# Set up environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Deploy infrastructure
cd infrastructure
terraform init
terraform plan
terraform apply

# Deploy application
cd ../deployment
./deploy.sh
```

## Project Structure

```
homecentre-recommendation-system/
├── src/
│   ├── data_ingestion/          # Data collection and streaming
│   ├── ml_models/               # Recommendation algorithms
│   ├── api/                     # REST API services
│   ├── batch_processing/        # ETL and batch jobs
│   └── utils/                   # Shared utilities
├── infrastructure/              # Terraform IaC
├── deployment/                  # Docker and K8s configs
├── notebooks/                   # Jupyter notebooks for analysis
├── tests/                       # Unit and integration tests
├── monitoring/                  # Dashboards and alerts
└── docs/                        # Documentation
```

## Technologies Used

- **Languages**: Python, SQL, JavaScript
- **ML/AI**: TensorFlow, PyTorch, Scikit-learn, XGBoost
- **Big Data**: Apache Spark, Kafka, Airflow
- **Cloud**: AWS (SageMaker, Kinesis, Lambda, EKS, RDS, S3)
- **DevOps**: Docker, Kubernetes, Terraform, GitHub Actions
- **Monitoring**: CloudWatch, Grafana, Prometheus

## Contributors

- Data Engineering Team
- ML Engineering Team
- DevOps Team
- Product Team

## License

MIT License
