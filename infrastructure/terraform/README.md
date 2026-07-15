# Infrastructure as Code (Terraform)

Reproducible AWS baseline (spec §7.2 Infrastructure, §15 DR).

```
terraform/
  versions.tf     provider + backend pins
  variables.tf    inputs
  main.tf         root composition (wires the modules)
  outputs.tf      exported values
  modules/
    network/      VPC, private subnets, NAT, restricted egress
    security/     KMS, Secrets Manager, WAF, security groups
    database/     RDS PostgreSQL (Multi-AZ, PITR, RLS app role)
    cache/        ElastiCache Redis (cache + Celery)
    compute/      ECS/EKS services (api, workers, relay), ALB, autoscaling
  environments/
    dev/ staging/ production/   per-env root + remote state backend
```

## Usage (per environment)

```bash
cd environments/dev
terraform init
terraform plan  -var environment=dev
terraform apply -var environment=dev
```

**Phase 0 exit criterion:** infrastructure reproducible from code in a clean account.
Modules are scaffolds now and are implemented during Phase 0 hardening.
