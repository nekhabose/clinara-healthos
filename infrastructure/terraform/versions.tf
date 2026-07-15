terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state is configured per environment (S3 + DynamoDB lock).
  # backend "s3" {}   # see environments/<env>/backend.tf
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "clinara-healthos"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}
