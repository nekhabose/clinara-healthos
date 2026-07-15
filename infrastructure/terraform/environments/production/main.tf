# production environment root. Own backend.tf (S3 state + DynamoDB lock) in practice.
module "platform" {
  source      = "../../"
  environment = "production"
  multi_az    = true
}
