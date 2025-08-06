# HomeCenter Product Recommendation System - Deployment Guide

This guide provides step-by-step instructions for deploying the complete HomeCenter Product Recommendation System to AWS.

## Prerequisites

### Required Tools
- **AWS CLI v2+**: For AWS resource management
- **Terraform v1.0+**: For infrastructure provisioning
- **Docker**: For container building and management
- **kubectl**: For Kubernetes cluster management
- **Helm v3+**: For Kubernetes package management
- **Git**: For source code management

### AWS Requirements
- AWS Account with appropriate permissions
- IAM user with administrative access
- AWS CLI configured with credentials
- Default region set to `us-east-1` (or modify variables)

### Local Environment Setup
```bash
# Install required tools (macOS with Homebrew)
brew install awscli terraform docker kubectl helm git

# Verify installations
aws --version
terraform --version
docker --version
kubectl version --client
helm version
```

## Quick Start (Automated Deployment)

### 1. Clone and Configure
```bash
# Clone the repository
git clone <repository-url>
cd homecentre-recommendation-system

# Set environment variables
export AWS_REGION=us-east-1
export ENVIRONMENT=dev
export PROJECT_NAME=homecentre
export ALERT_EMAIL=your-email@example.com
```

### 2. Run Automated Deployment
```bash
# Make deployment script executable
chmod +x deployment/deploy.sh

# Run complete deployment
./deployment/deploy.sh
```

The automated script will:
- ✅ Check prerequisites
- ✅ Deploy AWS infrastructure
- ✅ Set up container registry
- ✅ Build and push Docker images
- ✅ Configure Kubernetes cluster
- ✅ Deploy applications
- ✅ Set up monitoring
- ✅ Run health checks

## Manual Deployment (Step-by-Step)

### Step 1: Infrastructure Deployment

#### 1.1 Initialize Terraform Backend
```bash
cd infrastructure

# Create S3 bucket for Terraform state (if not exists)
aws s3 mb s3://homecentre-terraform-state --region us-east-1

# Create DynamoDB table for state locking
aws dynamodb create-table \
    --table-name terraform-state-lock \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5
```

#### 1.2 Deploy Infrastructure
```bash
# Initialize Terraform
terraform init

# Plan deployment
terraform plan -var="alert_email=your-email@example.com" -var="db_password=YourSecurePassword123!"

# Apply infrastructure
terraform apply -var="alert_email=your-email@example.com" -var="db_password=YourSecurePassword123!"
```

### Step 2: Container Registry Setup

#### 2.1 Create ECR Repositories
```bash
# Create repositories for API and Worker images
aws ecr create-repository --repository-name homecentre/recommendation-api
aws ecr create-repository --repository-name homecentre/batch-worker

# Get ECR login token
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
```

#### 2.2 Build and Push Images
```bash
cd deployment

# Build API service image
docker build -f Dockerfile.api -t homecentre/recommendation-api:latest ..

# Build batch worker image
docker build -f Dockerfile.worker -t homecentre/batch-worker:latest ..

# Tag and push images
docker tag homecentre/recommendation-api:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/homecentre/recommendation-api:latest
docker tag homecentre/batch-worker:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/homecentre/batch-worker:latest

docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/homecentre/recommendation-api:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/homecentre/batch-worker:latest
```

### Step 3: Kubernetes Configuration

#### 3.1 Configure kubectl
```bash
# Update kubeconfig for EKS cluster
aws eks update-kubeconfig --region us-east-1 --name homecentre-dev-eks

# Verify cluster connection
kubectl get nodes
```

#### 3.2 Install AWS Load Balancer Controller
```bash
# Create IAM service account
eksctl create iamserviceaccount \
  --cluster=homecentre-dev-eks \
  --namespace=kube-system \
  --name=aws-load-balancer-controller \
  --role-name AmazonEKSLoadBalancerControllerRole \
  --attach-policy-arn=arn:aws:iam::aws:policy/ElasticLoadBalancingFullAccess \
  --approve

# Install controller using Helm
helm repo add eks https://aws.github.io/eks-charts
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=homecentre-dev-eks \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller
```

### Step 4: Application Deployment

#### 4.1 Deploy Namespace and RBAC
```bash
cd deployment/kubernetes

# Apply namespace and service accounts
kubectl apply -f namespace.yaml
```

#### 4.2 Update Image References
```bash
# Update deployment files with your ECR URLs
sed -i 's|homecentre/recommendation-api:latest|<account-id>.dkr.ecr.us-east-1.amazonaws.com/homecentre/recommendation-api:latest|g' api-deployment.yaml
```

#### 4.3 Deploy Applications
```bash
# Deploy API service
kubectl apply -f api-deployment.yaml

# Verify deployment
kubectl get pods -n homecentre
kubectl get services -n homecentre
kubectl get ingress -n homecentre
```

### Step 5: Monitoring Setup

#### 5.1 Deploy CloudWatch Dashboard
```bash
cd monitoring

# Create CloudWatch dashboard
aws cloudwatch put-dashboard \
  --dashboard-name homecentre-dev-dashboard \
  --dashboard-body file://cloudwatch-dashboard.json
```

#### 5.2 Deploy CloudWatch Alarms
```bash
cd infrastructure

# Apply monitoring configuration
terraform apply -target=module.monitoring
```

### Step 6: Data Pipeline Setup

#### 6.1 Database Schema Setup
```bash
# Connect to RDS instance (using bastion host or direct connection)
psql -h homecentre-dev-db.cluster-xxx.us-east-1.rds.amazonaws.com -U homecentre -d homecentre

# Create database schema
CREATE TABLE customers (
    customer_id VARCHAR(50) PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    preferences JSONB,
    demographic_data JSONB
);

CREATE TABLE products (
    product_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    category VARCHAR(100),
    price DECIMAL(10,2),
    description TEXT,
    features JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE interactions (
    interaction_id VARCHAR(50) PRIMARY KEY,
    customer_id VARCHAR(50) REFERENCES customers(customer_id),
    product_id VARCHAR(50) REFERENCES products(product_id),
    interaction_type VARCHAR(50) NOT NULL,
    rating DECIMAL(3,2),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    session_id VARCHAR(50),
    metadata JSONB
);

CREATE INDEX idx_interactions_customer ON interactions(customer_id);
CREATE INDEX idx_interactions_product ON interactions(product_id);
CREATE INDEX idx_interactions_timestamp ON interactions(timestamp);
```

#### 6.2 Load Sample Data
```bash
# Insert sample products
INSERT INTO products (product_id, name, category, price, description) VALUES
('prod_001', 'Wireless Bluetooth Headphones', 'Electronics', 79.99, 'High-quality wireless headphones with noise cancellation'),
('prod_002', 'Smart Home Security Camera', 'Electronics', 129.99, '1080p HD security camera with mobile app'),
('prod_003', 'Coffee Maker Machine', 'Appliances', 199.99, 'Programmable coffee maker with thermal carafe');

# Insert sample customers
INSERT INTO customers (customer_id, preferences) VALUES
('cust_001', '{"categories": ["Electronics", "Home"], "price_range": "50-200"}'),
('cust_002', '{"categories": ["Appliances"], "price_range": "100-300"}');
```

## Verification and Testing

### Health Checks

#### 1. Infrastructure Health
```bash
# Check EKS cluster status
kubectl get nodes
kubectl get pods --all-namespaces

# Check RDS connectivity
aws rds describe-db-instances --db-instance-identifier homecentre-dev-db

# Check ElastiCache status
aws elasticache describe-replication-groups --replication-group-id homecentre-dev-redis
```

#### 2. Application Health
```bash
# Check API service health
kubectl get pods -n homecentre -l app=recommendation-api
kubectl logs -n homecentre -l app=recommendation-api

# Test API endpoint
ALB_URL=$(kubectl get ingress -n homecentre recommendation-api-ingress -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
curl http://$ALB_URL/health
```

#### 3. End-to-End Testing
```bash
# Test recommendation endpoint
curl -X POST http://$ALB_URL/recommendations \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "cust_001",
    "n_recommendations": 5,
    "context": {
      "page_type": "product_detail",
      "current_product": "prod_001"
    }
  }'

# Test event tracking
curl -X POST http://$ALB_URL/track-event \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "cust_001",
    "event_type": "page_view",
    "product_id": "prod_001",
    "session_id": "session_123"
  }'
```

### Monitoring Verification

#### 1. CloudWatch Metrics
```bash
# Check if custom metrics are being published
aws cloudwatch list-metrics --namespace "HomeCenter/Recommendations"

# View recent API metrics
aws cloudwatch get-metric-statistics \
  --namespace "HomeCenter/Recommendations" \
  --metric-name "API.RequestCount" \
  --start-time 2024-01-15T10:00:00Z \
  --end-time 2024-01-15T11:00:00Z \
  --period 300 \
  --statistics Sum
```

#### 2. Log Analysis
```bash
# Query application logs
aws logs start-query \
  --log-group-name "/aws/homecentre/dev/app" \
  --start-time 1642248000 \
  --end-time 1642251600 \
  --query-string 'fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc'
```

## Troubleshooting

### Common Issues

#### 1. EKS Pods Not Starting
```bash
# Check pod status and events
kubectl describe pod <pod-name> -n homecentre

# Common fixes:
# - Verify ECR image URLs are correct
# - Check IAM roles for service accounts
# - Ensure node groups have sufficient capacity
```

#### 2. Database Connection Issues
```bash
# Check security groups
aws ec2 describe-security-groups --group-ids <rds-security-group-id>

# Test connectivity from EKS pod
kubectl run test-pod --rm -i --tty --image=postgres:13 -- bash
psql -h homecentre-dev-db.cluster-xxx.us-east-1.rds.amazonaws.com -U homecentre -d homecentre
```

#### 3. Load Balancer Not Accessible
```bash
# Check ingress status
kubectl describe ingress -n homecentre recommendation-api-ingress

# Verify ALB controller logs
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller
```

### Performance Tuning

#### 1. API Service Optimization
```bash
# Adjust resource limits based on load
kubectl patch deployment recommendation-api -n homecentre -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "api",
          "resources": {
            "requests": {"cpu": "500m", "memory": "1Gi"},
            "limits": {"cpu": "2", "memory": "4Gi"}
          }
        }]
      }
    }
  }
}'
```

#### 2. Database Performance
```bash
# Monitor RDS performance insights
aws rds describe-db-instances --db-instance-identifier homecentre-dev-db

# Optimize queries based on CloudWatch metrics
# Consider read replicas for read-heavy workloads
```

## Production Considerations

### Security Hardening
- Enable AWS GuardDuty for threat detection
- Configure AWS Config for compliance monitoring
- Implement AWS Secrets Manager for credential rotation
- Enable VPC Flow Logs for network monitoring

### Backup and Disaster Recovery
- Configure automated RDS backups with point-in-time recovery
- Set up cross-region S3 replication for critical data
- Implement EKS cluster backup using Velero
- Document disaster recovery procedures

### Cost Optimization
- Implement S3 lifecycle policies for data archival
- Use Spot instances for non-critical batch workloads
- Configure auto-scaling policies for cost efficiency
- Monitor costs using AWS Cost Explorer and set up billing alerts

### Compliance
- Enable AWS CloudTrail for audit logging
- Configure data encryption for all services
- Implement data retention policies
- Document security and compliance procedures

---

This deployment guide provides comprehensive instructions for setting up the complete HomeCenter Product Recommendation System. For additional support or customization, refer to the architecture documentation and individual service configurations.