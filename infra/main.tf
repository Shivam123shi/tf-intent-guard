terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket = "tfstate-intent-guard-shivam-27087"
    key    = "infra/terraform.tfstate"
    region = "ap-south-1"
  }

}

provider "aws" {
  region = "ap-south-1"
}

resource "aws_s3_bucket" "app_logs" {
  bucket        = "intent-guard-newlogs-shivam-27087"
  force_destroy = true

  tags = {
    Environment = "dev"
    CostCenter = "platform-eng"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs_lifecycle" {
  bucket = aws_s3_bucket.app_logs.id

  rule {
    id     = "expire-old-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }
  }
}

resource "aws_iam_role" "worker_role" {
  name = "intent-guard-worker"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "worker_policy" {
  name = "intent-guard-worker-policy"
  role = aws_iam_role.worker_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action   = ["s3:GetObject"]
      Effect   = "Allow"
      Resource = "*"
    }]
  })
}