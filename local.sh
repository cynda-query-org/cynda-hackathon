# Depkoy to cloud Run
gcloud run deploy cynda-query-slack \
  --source . \
  --project cynda-query \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --env-vars-file env.yaml

# Check the cloud run service service account
gcloud run services describe cynda-query-slack \
  --region europe-west1 \
  --project cynda-query \
  --format="value(spec.template.spec.serviceAccountName)"

# Show me the service URL
gcloud run services describe cynda-query-slack \
  --region europe-west1 \
  --project cynda-query \
  --format="value(status.url)"

# Create access to view the data for the service account
# --member must be linked with correct service account from the above command
gcloud projects add-iam-policy-binding cynda-query \
  --member="serviceAccount:42682021693-compute@developer.gserviceaccount.com" \ 
  --role="roles/bigquery.dataViewer"

# Provide access to submit jobs
# --member must be linked with correct service account from the above command
gcloud projects add-iam-policy-binding cynda-query \
  --member="serviceAccount:42682021693-compute@developer.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"

