#!/bin/bash

# HomeCenter Recommendation System Deployment Script
# This script deploys the entire recommendation system to AWS

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ENVIRONMENT=${ENVIRONMENT:-dev}
AWS_REGION=${AWS_REGION:-us-east-1}
AWS_ACCOUNT_ID=${AWS_ACCOUNT_ID:-""}
DOCKER_REGISTRY=${DOCKER_REGISTRY:-"$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"}
PROJECT_NAME="homecentre"
NAMESPACE="homecentre"

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check required commands
    local required_commands=("aws" "docker" "kubectl" "terraform")
    for cmd in "${required_commands[@]}"; do
        if ! command -v "$cmd" &> /dev/null; then
            log_error "$cmd is not installed or not in PATH"
            exit 1
        fi
    done
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not configured or invalid"
        exit 1
    fi
    
    # Get AWS Account ID if not provided
    if [ -z "$AWS_ACCOUNT_ID" ]; then
        AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
        log_info "Detected AWS Account ID: $AWS_ACCOUNT_ID"
    fi
    
    log_success "Prerequisites check passed"
}

deploy_infrastructure() {
    log_info "Deploying infrastructure with Terraform..."
    
    cd "$PROJECT_ROOT/infrastructure"
    
    # Initialize Terraform
    terraform init
    
    # Plan infrastructure
    terraform plan \
        -var="environment=$ENVIRONMENT" \
        -var="aws_region=$AWS_REGION" \
        -out=tfplan
    
    # Apply infrastructure
    terraform apply tfplan
    
    log_success "Infrastructure deployed successfully"
    cd "$PROJECT_ROOT"
}

setup_ecr() {
    log_info "Setting up ECR repositories..."
    
    # Create ECR repositories if they don't exist
    local repositories=("recommendation-api" "batch-worker")
    
    for repo in "${repositories[@]}"; do
        if ! aws ecr describe-repositories --repository-names "$PROJECT_NAME/$repo" --region "$AWS_REGION" &> /dev/null; then
            log_info "Creating ECR repository: $PROJECT_NAME/$repo"
            aws ecr create-repository \
                --repository-name "$PROJECT_NAME/$repo" \
                --region "$AWS_REGION" \
                --image-scanning-configuration scanOnPush=true
        else
            log_info "ECR repository already exists: $PROJECT_NAME/$repo"
        fi
    done
    
    # Login to ECR
    aws ecr get-login-password --region "$AWS_REGION" | \
        docker login --username AWS --password-stdin "$DOCKER_REGISTRY"
    
    log_success "ECR setup completed"
}

build_and_push_images() {
    log_info "Building and pushing Docker images..."
    
    cd "$PROJECT_ROOT"
    
    # Build API image
    log_info "Building recommendation API image..."
    docker build -f deployment/Dockerfile.api -t "$PROJECT_NAME/recommendation-api:latest" .
    docker tag "$PROJECT_NAME/recommendation-api:latest" "$DOCKER_REGISTRY/$PROJECT_NAME/recommendation-api:latest"
    docker push "$DOCKER_REGISTRY/$PROJECT_NAME/recommendation-api:latest"
    
    # Build worker image
    log_info "Building batch worker image..."
    docker build -f deployment/Dockerfile.worker -t "$PROJECT_NAME/batch-worker:latest" .
    docker tag "$PROJECT_NAME/batch-worker:latest" "$DOCKER_REGISTRY/$PROJECT_NAME/batch-worker:latest"
    docker push "$DOCKER_REGISTRY/$PROJECT_NAME/batch-worker:latest"
    
    log_success "Docker images built and pushed successfully"
}

setup_kubernetes() {
    log_info "Setting up Kubernetes cluster access..."
    
    # Update kubeconfig
    aws eks update-kubeconfig \
        --region "$AWS_REGION" \
        --name "$PROJECT_NAME-$ENVIRONMENT-eks"
    
    # Install AWS Load Balancer Controller if not already installed
    if ! kubectl get deployment -n kube-system aws-load-balancer-controller &> /dev/null; then
        log_info "Installing AWS Load Balancer Controller..."
        
        # Download and apply the controller
        curl -o iam_policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.7.2/docs/install/iam_policy.json
        
        # Create IAM policy
        aws iam create-policy \
            --policy-name AWSLoadBalancerControllerIAMPolicy \
            --policy-document file://iam_policy.json \
            --region "$AWS_REGION" || true
        
        # Create service account
        eksctl create iamserviceaccount \
            --cluster="$PROJECT_NAME-$ENVIRONMENT-eks" \
            --namespace=kube-system \
            --name=aws-load-balancer-controller \
            --role-name AmazonEKSLoadBalancerControllerRole \
            --attach-policy-arn=arn:aws:iam::$AWS_ACCOUNT_ID:policy/AWSLoadBalancerControllerIAMPolicy \
            --approve \
            --region="$AWS_REGION" || true
        
        # Install controller using Helm
        helm repo add eks https://aws.github.io/eks-charts
        helm repo update
        helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
            -n kube-system \
            --set clusterName="$PROJECT_NAME-$ENVIRONMENT-eks" \
            --set serviceAccount.create=false \
            --set serviceAccount.name=aws-load-balancer-controller
        
        rm -f iam_policy.json
    fi
    
    log_success "Kubernetes setup completed"
}

deploy_application() {
    log_info "Deploying application to Kubernetes..."
    
    cd "$PROJECT_ROOT/deployment/kubernetes"
    
    # Update image references in deployment files
    sed -i.bak "s|homecentre/recommendation-api:latest|$DOCKER_REGISTRY/$PROJECT_NAME/recommendation-api:latest|g" api-deployment.yaml
    sed -i.bak "s|ACCOUNT_ID|$AWS_ACCOUNT_ID|g" namespace.yaml
    
    # Create namespace and apply configurations
    kubectl apply -f namespace.yaml
    kubectl apply -f api-deployment.yaml
    
    # Wait for deployment to be ready
    log_info "Waiting for deployment to be ready..."
    kubectl wait --for=condition=available --timeout=300s deployment/recommendation-api -n "$NAMESPACE"
    
    # Restore original files
    mv api-deployment.yaml.bak api-deployment.yaml
    mv namespace.yaml.bak namespace.yaml
    
    log_success "Application deployed successfully"
    cd "$PROJECT_ROOT"
}

setup_monitoring() {
    log_info "Setting up monitoring and logging..."
    
    # Install Prometheus and Grafana using Helm
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo add grafana https://grafana.github.io/helm-charts
    helm repo update
    
    # Install Prometheus
    if ! helm list -n monitoring | grep -q prometheus; then
        kubectl create namespace monitoring || true
        helm install prometheus prometheus-community/kube-prometheus-stack \
            --namespace monitoring \
            --set grafana.adminPassword=admin123 \
            --set alertmanager.persistentVolume.enabled=false \
            --set server.persistentVolume.enabled=false
    fi
    
    log_success "Monitoring setup completed"
}

run_health_checks() {
    log_info "Running health checks..."
    
    # Check if API is healthy
    local api_url=$(kubectl get ingress recommendation-api-ingress -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
    
    if [ -n "$api_url" ]; then
        log_info "Waiting for load balancer to be ready..."
        sleep 60
        
        if curl -f "http://$api_url/health" &> /dev/null; then
            log_success "API health check passed"
        else
            log_warning "API health check failed - may need more time to start"
        fi
    else
        log_warning "Load balancer not ready yet"
    fi
    
    # Check pod status
    kubectl get pods -n "$NAMESPACE"
    
    log_success "Health checks completed"
}

cleanup_on_error() {
    log_error "Deployment failed. Check the logs above for details."
    log_info "You may need to manually clean up resources."
    exit 1
}

show_deployment_info() {
    log_success "Deployment completed successfully!"
    echo
    echo "=== Deployment Information ==="
    echo "Environment: $ENVIRONMENT"
    echo "AWS Region: $AWS_REGION"
    echo "AWS Account ID: $AWS_ACCOUNT_ID"
    echo "Namespace: $NAMESPACE"
    echo
    echo "=== Access Information ==="
    echo "API Endpoint: $(kubectl get ingress recommendation-api-ingress -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo 'Not ready yet')"
    echo "Grafana Dashboard: kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80"
    echo
    echo "=== Useful Commands ==="
    echo "View pods: kubectl get pods -n $NAMESPACE"
    echo "View logs: kubectl logs -f deployment/recommendation-api -n $NAMESPACE"
    echo "Port forward API: kubectl port-forward svc/recommendation-api-service 8080:80 -n $NAMESPACE"
}

main() {
    log_info "Starting HomeCenter Recommendation System deployment..."
    log_info "Environment: $ENVIRONMENT"
    log_info "AWS Region: $AWS_REGION"
    
    # Set error handler
    trap cleanup_on_error ERR
    
    # Run deployment steps
    check_prerequisites
    deploy_infrastructure
    setup_ecr
    build_and_push_images
    setup_kubernetes
    deploy_application
    setup_monitoring
    run_health_checks
    show_deployment_info
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --environment|-e)
            ENVIRONMENT="$2"
            shift 2
            ;;
        --region|-r)
            AWS_REGION="$2"
            shift 2
            ;;
        --account-id|-a)
            AWS_ACCOUNT_ID="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  -e, --environment    Environment (dev, staging, prod) [default: dev]"
            echo "  -r, --region         AWS region [default: us-east-1]"
            echo "  -a, --account-id     AWS account ID [auto-detected if not provided]"
            echo "  -h, --help           Show this help message"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate environment
if [[ ! "$ENVIRONMENT" =~ ^(dev|staging|prod)$ ]]; then
    log_error "Invalid environment: $ENVIRONMENT. Must be dev, staging, or prod."
    exit 1
fi

# Run main deployment
main