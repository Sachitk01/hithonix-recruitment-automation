terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.3.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  type        = string
  description = "GCP project that hosts Cloud Run"
}

variable "region" {
  type        = string
  description = "GCP region for scheduler"
  default     = "us-central1"
}

variable "service_url" {
  type        = string
  description = "Base HTTPS URL of the Cloud Run service"
}

variable "invoker_service_account" {
  type        = string
  description = "Service account with Cloud Run Invoker role"
}

locals {
  jobs = [
    {
      name     = "riva-l1-1300"
      schedule = "0 13 * * *"
      endpoint = "/run-l1-batch"
    },
    {
      name     = "riva-l1-2100"
      schedule = "0 21 * * *"
      endpoint = "/run-l1-batch"
    },
    {
      name     = "arjun-l2-1600"
      schedule = "0 16 * * *"
      endpoint = "/run-l2-batch"
    },
    {
      name     = "arjun-l2-2300"
      schedule = "0 23 * * *"
      endpoint = "/run-l2-batch"
    }
  ]
}

resource "google_cloud_scheduler_job" "batch_jobs" {
  for_each = { for job in local.jobs : job.name => job }

  name        = each.value.name
  description = "Automated trigger for ${each.value.endpoint}"
  schedule    = each.value.schedule
  time_zone   = "UTC"

  http_target {
    uri         = "${var.service_url}${each.value.endpoint}"
    http_method = "POST"

    oidc_token {
      service_account_email = var.invoker_service_account
      audience              = var.service_url
    }
  }
}
