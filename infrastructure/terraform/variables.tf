variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type        = string
  description = "dev | staging | production"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "db_instance_class" {
  type    = string
  default = "db.t3.medium"
}

variable "multi_az" {
  type        = bool
  default     = true
  description = "Multi-AZ RDS for HA (spec §15)."
}
