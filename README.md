# Pacific BioArchive

Pacific BioArchive is a multi-cloud, serverless wildlife media platform developed for FIT5225 Assignment 2.

Users can upload wildlife images and videos through a protected web application. Uploaded media is automatically deduplicated, processed by machine-learning models, tagged with detected species, given a thumbnail, and replicated across AWS and Alibaba Cloud for secure querying and management.

## Live Application

[Open Pacific BioArchive](https://df3cv9pa7eg7p.cloudfront.net)

Authentication is required. Users may register with an email address or sign in with Google.

## Key Features

### Authentication

- Amazon Cognito registration and email verification
- Email and password sign-in
- First-login password challenge support
- Google OAuth sign-in
- Protected frontend routes
- JWT authorization for both AWS and Alibaba Cloud APIs

### Media Processing

- Image and video uploads
- SHA-256 checksum deduplication
- Automatic thumbnail generation
- MegaDetector animal detection
- SpeciesNet species classification
- Video processing at one frame per second
- Species occurrence counting across video frames
- Upload progress and processing-status feedback

### Search and Management

- Search by multiple species tags using AND logic
- Specify minimum species occurrence counts
- Find the original media using a thumbnail URL
- Upload a query file and search by its detected species
- Filter the media library by filename, tag, or checksum
- Add and remove tags from multiple files
- Delete media and its associated cross-cloud copies
- Open private media through temporary signed URLs

### Notifications

- Subscribe an email address to selected species tags
- Filter Amazon SNS notifications using message attributes
- Receive notifications only when watched species are detected
- Open media through a seven-day HTTPS signed URL
- Access notification links without a Cognito account

## Architecture

```text
React SPA
  |
  | Cognito access token
  v
Amazon CloudFront
  |
  +-- Private S3 web bucket
  |
  +-- Amazon API Gateway
        |
        +-- API Handler Lambda
        |     +-- DynamoDB Files table
        |     +-- DynamoDB QueryJobs table
        |     +-- S3 upload and query buckets
        |     +-- Amazon SNS
        |
        +-- Process Media container Lambda
              +-- MegaDetector
              +-- SpeciesNet
              +-- Thumbnail generation
              +-- Private S3 model bucket
              +-- Private Alibaba Cloud OSS replication

Alibaba Cloud Function Compute
  |
  +-- Validates Cognito access tokens
  +-- Reads the private OSS media index
  +-- Performs tag and thumbnail queries
  +-- Generates temporary signed OSS URLs
```

## Technology Stack

### Frontend

- React 18
- TypeScript
- Vite
- Amazon Cognito Identity SDK
- Amazon CloudFront
- Private Amazon S3 origin

### AWS

- AWS SAM and CloudFormation
- Amazon Cognito
- Amazon API Gateway
- AWS Lambda
- Amazon ECR
- Amazon S3
- Amazon DynamoDB
- Amazon SNS

### Alibaba Cloud

- Function Compute
- Object Storage Service
- Serverless Devs

### Machine Learning

- PyTorch
- MegaDetector
- SpeciesNet
- Pillow
- FFmpeg

## Repository Structure

```text
pacific-bioarchive/
├── frontend/          # React, TypeScript and Vite application
├── aws/               # AWS SAM infrastructure and Lambda functions
├── aliyun/            # Alibaba Cloud Function Compute service
├── docs/              # Environment and provider configuration
└── scripts/           # Deployment and setup scripts
```

## Prerequisites

Install and configure:

- AWS CLI
- AWS SAM CLI
- Docker with Buildx
- Node.js and npm
- Python 3.12
- Alibaba Cloud CLI
- Serverless Devs
- `jq`

AWS and Alibaba Cloud credentials must be configured before deployment.

Run the local setup script where applicable:

```bash
./scripts/setup-local.sh
```

Environment setup instructions are available in [`docs/env-setup.md`](docs/env-setup.md).

## Environment Configuration

Create a `.env` file in the repository root:

```dotenv
AWS_DEFAULT_REGION=us-east-1

ALIBABA_CLOUD_ACCESS_KEY_ID=your-access-key-id
ALIBABA_CLOUD_ACCESS_KEY_SECRET=your-access-key-secret

GOOGLE_OAUTH_CLIENT_ID=your-google-client-id
GOOGLE_OAUTH_CLIENT_SECRET=your-google-client-secret

ALIYUN_QUERY_URL=https://your-function-compute-endpoint
```

The `.env` file is excluded from Git and must never be committed.

## Deployment

The deployment order is important:

```text
ECR image
→ AWS infrastructure
→ ML models
→ Alibaba Cloud
→ Frontend
→ End-to-end verification
```

### 1. Build and Push the Processing Image

```bash
./scripts/deploy-ecr.sh
```

This builds a Linux AMD64 container image and pushes it to Amazon ECR.

### 2. Deploy AWS Infrastructure

```bash
./scripts/deploy-aws.sh
```

This deploys the Cognito user pool, API Gateway, Lambda functions, private S3 buckets, DynamoDB tables, SNS topic, and CloudFront distribution.

### 3. Upload the Machine-Learning Models

```bash
./scripts/upload-models.sh
```

The model bucket receives:

```text
models/mdv5a.pt
models/model.pt
models/pointer.json
```

The processing Lambda reads the model pointer and model files through the private S3 API.

### 4. Deploy Alibaba Cloud Resources

```bash
./scripts/deploy-aliyun.sh
```

This deploys the Function Compute query service and configures the private OSS replication bucket.

### 5. Deploy the Frontend

```bash
./scripts/deploy-frontend.sh
```

The script reads the deployed AWS outputs, injects runtime configuration, builds the React application, synchronises it to the private web bucket, and invalidates the CloudFront cache.

## Local Frontend Development

```bash
cd frontend
npm install
npm run dev
```

Create a production build with:

```bash
npm run build
```

## Security Design

- All Amazon S3 and Alibaba Cloud OSS buckets remain private.
- Public bucket access is disabled.
- The frontend contains no AWS or Alibaba Cloud credentials.
- Uploads use time-limited presigned S3 URLs.
- Media access uses time-limited signed OSS URLs.
- AWS API routes are protected by an API Gateway JWT authorizer.
- Alibaba Cloud verifies Cognito JWT signatures, expiry, issuer, client ID, and token use.
- Query files are isolated from normal uploads and automatically removed.
- Model files are loaded from a private S3 bucket.
- Deployment secrets are read from `.env` and are not committed.

## Implementation Notes

- The processing Lambda uses 4096 MB of ephemeral storage for models, media, thumbnails, and video frames.
- Lambda memory is limited to 3008 MB in the AWS Learner Lab environment.
- MegaDetector is loaded once when processing video frames.
- MegaDetector and SpeciesNet run in separate memory stages to reduce peak memory usage.
- Query-file uploads use a separate S3 bucket and never become permanent media records.
- Tag changes and deletions rebuild the Alibaba Cloud OSS query index.
- Notification links expire after seven days while the OSS bucket remains private.

## Documentation

- [`docs/env-setup.md`](docs/env-setup.md) — local and cloud environment setup
- [`docs/google-oauth.md`](docs/google-oauth.md) — Google OAuth configuration

## Team Responsibilities

- Frontend and authentication
- Machine-learning processing pipeline
- AWS infrastructure and backend APIs
- Alibaba Cloud integration and project documentation

All team members should commit their own work using their individual Git identities so that contribution history is visible.

## Academic Project

This repository was created for FIT5225 Assignment 2. Cloud resources, credentials, and external service accounts must be managed according to the unit requirements and university policies.
