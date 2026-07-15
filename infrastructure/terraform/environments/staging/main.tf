# staging environment root. Own backend.tf (S3 state + DynamoDB lock) in practice.
module "platform" {
  source      = "../../"
  environment = "staging"
  multi_az    = true
}
