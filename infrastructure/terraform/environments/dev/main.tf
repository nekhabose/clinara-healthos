# Dev environment root. Calls the shared root composition with dev inputs.
# In practice each environment has its own backend.tf (S3 state + DynamoDB lock).

module "platform" {
  source      = "../../"
  environment = "dev"
  multi_az    = false
}
