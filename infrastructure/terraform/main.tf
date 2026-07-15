# Root composition wiring the platform modules together.
# Modules are scaffolds (spec §7.2 Infrastructure); flesh out in Phase 0 hardening.

module "network" {
  source      = "./modules/network"
  environment = var.environment
  vpc_cidr    = var.vpc_cidr
  # Private subnets, restricted egress, NAT (spec §10.3).
}

module "security" {
  source      = "./modules/security"
  environment = var.environment
  # KMS keys, Secrets Manager, WAF, security groups (spec §10.3).
}

module "database" {
  source            = "./modules/database"
  environment       = var.environment
  db_instance_class = var.db_instance_class
  multi_az          = var.multi_az
  # RDS PostgreSQL, automated backups, PITR, non-superuser app role for RLS.
}

module "cache" {
  source      = "./modules/cache"
  environment = var.environment
  # ElastiCache Redis for cache + Celery broker/result backends.
}

module "compute" {
  source      = "./modules/compute"
  environment = var.environment
  # ECS/EKS services: api, workers, outbox relay; ALB; autoscaling.
}
