# Database module (GA hardening — spec §15 Disaster Recovery & Business Continuity).
#
# Delivers the DR posture the spec requires: Multi-AZ, automated backups with point-in-time
# recovery, encryption at rest, and a versioned + cross-region-replicable backup bucket. The
# reconciliation logic that runs AFTER a restore lives in `domains/continuity` and is exercised
# by the quarterly DR drill; this module provides the infrastructure those drills restore from.

variable "environment" { type = string }

variable "instance_class" {
  type    = string
  default = "db.r6g.large"
}

variable "allocated_storage" {
  type    = number
  default = 100
}

# RPO 15min (spec §15): PITR granularity is ~5 min for RDS; retention bounds how far back.
variable "backup_retention_days" {
  type    = number
  default = 14
}

variable "cross_region_backup" {
  type        = bool
  default     = false # enable per-contract (spec §15 "cross-region backup where required")
  description = "Replicate automated backups to a second region for regional DR."
}

variable "replica_region" {
  type    = string
  default = "us-west-2"
}

# --- Primary transactional database ----------------------------------------------------------

resource "aws_db_instance" "primary" {
  identifier     = "clinara-${var.environment}"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.instance_class

  allocated_storage = var.allocated_storage
  storage_encrypted = true # encryption at rest (spec §10.3)

  # Multi-AZ synchronous standby ⇒ automatic failover, no data loss on AZ failure (spec §15).
  multi_az = true

  # Automated backups + point-in-time recovery (spec §15). Retention > 0 enables PITR.
  backup_retention_period   = var.backup_retention_days
  backup_window             = "07:00-08:00"
  copy_tags_to_snapshot     = true
  delete_automated_backups  = false
  deletion_protection       = true
  final_snapshot_identifier = "clinara-${var.environment}-final"

  performance_insights_enabled = true

  tags = {
    Environment = var.environment
    Compliance  = "hipaa,soc2"
    DR          = "multi-az,pitr"
  }
}

resource "aws_db_instance_automated_backups_replication" "cross_region" {
  count                  = var.cross_region_backup ? 1 : 0
  source_db_instance_arn = aws_db_instance.primary.arn
  retention_period       = var.backup_retention_days
  # Provider alias for the replica region is wired at the environment layer.
}

# --- Versioned backup bucket (logical dumps, integration replay archives) --------------------

resource "aws_s3_bucket" "backups" {
  bucket = "clinara-${var.environment}-backups"
  tags   = { Environment = var.environment, DR = "versioned-backups" }
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration {
    status = "Enabled" # S3 versioning (spec §15)
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    id     = "retain-noncurrent"
    status = "Enabled"
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

output "primary_endpoint" {
  value = aws_db_instance.primary.endpoint
}

output "backup_bucket" {
  value = aws_s3_bucket.backups.id
}
