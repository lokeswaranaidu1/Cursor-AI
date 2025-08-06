# CloudWatch Alarms for HomeCenter Recommendation System

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# SNS Topic for Alerts
resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
  
  tags = {
    Name        = "${local.name_prefix}-alerts"
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_sns_topic_subscription" "email_alerts" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# API Gateway/ALB Alarms
resource "aws_cloudwatch_metric_alarm" "api_response_time" {
  alarm_name          = "${local.name_prefix}-api-response-time-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = "300"
  statistic           = "Average"
  threshold           = "2.0"
  alarm_description   = "This metric monitors ALB response time"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
  }

  tags = {
    Name        = "${local.name_prefix}-api-response-time-alarm"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_metric_alarm" "api_error_rate" {
  alarm_name          = "${local.name_prefix}-api-error-rate-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = "300"
  statistic           = "Sum"
  threshold           = "10"
  alarm_description   = "This metric monitors ALB 5XX error count"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
  }

  tags = {
    Name        = "${local.name_prefix}-api-error-rate-alarm"
    Environment = var.environment
  }
}

# RDS Alarms
resource "aws_cloudwatch_metric_alarm" "rds_cpu_high" {
  alarm_name          = "${local.name_prefix}-rds-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = "300"
  statistic           = "Average"
  threshold           = "80"
  alarm_description   = "This metric monitors RDS cpu utilization"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }

  tags = {
    Name        = "${local.name_prefix}-rds-cpu-alarm"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_connection_count" {
  alarm_name          = "${local.name_prefix}-rds-connection-count-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = "300"
  statistic           = "Average"
  threshold           = "80"
  alarm_description   = "This metric monitors RDS connection count"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }

  tags = {
    Name        = "${local.name_prefix}-rds-connections-alarm"
    Environment = var.environment
  }
}

# ElastiCache Redis Alarms
resource "aws_cloudwatch_metric_alarm" "redis_cpu_high" {
  alarm_name          = "${local.name_prefix}-redis-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ElastiCache"
  period              = "300"
  statistic           = "Average"
  threshold           = "75"
  alarm_description   = "This metric monitors Redis CPU utilization"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    CacheClusterId = "${aws_elasticache_replication_group.main.replication_group_id}-001"
  }

  tags = {
    Name        = "${local.name_prefix}-redis-cpu-alarm"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_metric_alarm" "redis_memory_high" {
  alarm_name          = "${local.name_prefix}-redis-memory-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "DatabaseMemoryUsagePercentage"
  namespace           = "AWS/ElastiCache"
  period              = "300"
  statistic           = "Average"
  threshold           = "80"
  alarm_description   = "This metric monitors Redis memory usage"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    CacheClusterId = "${aws_elasticache_replication_group.main.replication_group_id}-001"
  }

  tags = {
    Name        = "${local.name_prefix}-redis-memory-alarm"
    Environment = var.environment
  }
}

# Kinesis Alarms
resource "aws_cloudwatch_metric_alarm" "kinesis_iterator_age" {
  alarm_name          = "${local.name_prefix}-kinesis-iterator-age-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "IteratorAgeMilliseconds"
  namespace           = "AWS/Kinesis"
  period              = "300"
  statistic           = "Maximum"
  threshold           = "60000"  # 1 minute
  alarm_description   = "This metric monitors Kinesis iterator age"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    StreamName = aws_kinesis_stream.events.name
  }

  tags = {
    Name        = "${local.name_prefix}-kinesis-iterator-age-alarm"
    Environment = var.environment
  }
}

# DynamoDB Alarms
resource "aws_cloudwatch_metric_alarm" "dynamodb_throttled_requests" {
  alarm_name          = "${local.name_prefix}-dynamodb-throttled-requests"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "ThrottledRequests"
  namespace           = "AWS/DynamoDB"
  period              = "300"
  statistic           = "Sum"
  threshold           = "0"
  alarm_description   = "This metric monitors DynamoDB throttled requests"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    TableName = aws_dynamodb_table.user_profiles.name
  }

  tags = {
    Name        = "${local.name_prefix}-dynamodb-throttle-alarm"
    Environment = var.environment
  }
}

# EKS Node Count Alarm
resource "aws_cloudwatch_metric_alarm" "eks_node_count_low" {
  alarm_name          = "${local.name_prefix}-eks-node-count-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "cluster_node_count"
  namespace           = "AWS/EKS"
  period              = "300"
  statistic           = "Average"
  threshold           = "2"
  alarm_description   = "This metric monitors EKS node count"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    ClusterName = module.eks.cluster_name
  }

  tags = {
    Name        = "${local.name_prefix}-eks-node-count-alarm"
    Environment = var.environment
  }
}

# Custom Application Metrics Alarms
resource "aws_cloudwatch_metric_alarm" "model_prediction_latency" {
  alarm_name          = "${local.name_prefix}-model-prediction-latency-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "Model.PredictionLatency"
  namespace           = "HomeCenter/Recommendations"
  period              = "300"
  statistic           = "Average"
  threshold           = "1000"  # 1 second
  alarm_description   = "This metric monitors model prediction latency"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  tags = {
    Name        = "${local.name_prefix}-model-latency-alarm"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_metric_alarm" "event_processing_lag" {
  alarm_name          = "${local.name_prefix}-event-processing-lag-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "Events.ProcessingLatency"
  namespace           = "HomeCenter/Recommendations"
  period              = "300"
  statistic           = "Average"
  threshold           = "5000"  # 5 seconds
  alarm_description   = "This metric monitors event processing lag"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  tags = {
    Name        = "${local.name_prefix}-event-lag-alarm"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_metric_alarm" "cache_hit_rate_low" {
  alarm_name          = "${local.name_prefix}-cache-hit-rate-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = "3"
  metric_name         = "Model.CacheHitRate"
  namespace           = "HomeCenter/Recommendations"
  period              = "300"
  statistic           = "Average"
  threshold           = "70"  # 70%
  alarm_description   = "This metric monitors cache hit rate"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  tags = {
    Name        = "${local.name_prefix}-cache-hit-rate-alarm"
    Environment = var.environment
  }
}

# Log-based Metric Filter and Alarm for Errors
resource "aws_cloudwatch_log_metric_filter" "error_count" {
  name           = "${local.name_prefix}-error-count"
  pattern        = "ERROR"
  log_group_name = aws_cloudwatch_log_group.app_logs.name

  metric_transformation {
    name      = "ErrorCount"
    namespace = "HomeCenter/Logs"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "error_count_high" {
  alarm_name          = "${local.name_prefix}-error-count-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "ErrorCount"
  namespace           = "HomeCenter/Logs"
  period              = "300"
  statistic           = "Sum"
  threshold           = "10"
  alarm_description   = "This metric monitors error count in logs"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  tags = {
    Name        = "${local.name_prefix}-error-count-alarm"
    Environment = var.environment
  }
}

# Composite Alarm for Overall System Health
resource "aws_cloudwatch_composite_alarm" "system_health" {
  alarm_name        = "${local.name_prefix}-system-health"
  alarm_description = "Composite alarm for overall system health"

  alarm_rule = join(" OR ", [
    "ALARM(${aws_cloudwatch_metric_alarm.api_response_time.alarm_name})",
    "ALARM(${aws_cloudwatch_metric_alarm.api_error_rate.alarm_name})",
    "ALARM(${aws_cloudwatch_metric_alarm.rds_cpu_high.alarm_name})",
    "ALARM(${aws_cloudwatch_metric_alarm.redis_cpu_high.alarm_name})",
    "ALARM(${aws_cloudwatch_metric_alarm.error_count_high.alarm_name})"
  ])

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name        = "${local.name_prefix}-system-health"
    Environment = var.environment
  }
}

# Variables for alarm configuration
variable "alert_email" {
  description = "Email address for CloudWatch alerts"
  type        = string
}

# Outputs
output "sns_topic_arn" {
  description = "ARN of the SNS topic for alerts"
  value       = aws_sns_topic.alerts.arn
}

output "cloudwatch_dashboard_url" {
  description = "URL to the CloudWatch dashboard"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${local.name_prefix}-dashboard"
}