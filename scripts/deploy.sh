#!/usr/bin/env bash
# Build the agent code zip, upload it to S3 and deploy infra/agent.yaml.
#   AWS_PROFILE=<your-profile> scripts/deploy.sh
# Env: STACK_NAME (default pr-reviewer), AWS_REGION (default profile region or us-east-1),
#      ARTIFACT_BUCKET (default pr-reviewer-artifacts-<account>-<region>, created if missing).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
APP="$ROOT/app/reviewer"
BUILD="$ROOT/build"
STACK_NAME=${STACK_NAME:-pr-reviewer}
REGION=${AWS_REGION:-$(aws configure get region || true)}
REGION=${REGION:-us-east-1}
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET=${ARTIFACT_BUCKET:-pr-reviewer-artifacts-$ACCOUNT-$REGION}
export AWS_REGION=$REGION

if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "Creating artifact bucket $BUCKET"
  if [ "$REGION" = us-east-1 ]; then
    aws s3api create-bucket --bucket "$BUCKET" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET" --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
  aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi

rm -rf "$BUILD" && mkdir -p "$BUILD/pkg"
uv export --project "$APP" --frozen --no-dev --no-emit-project --no-hashes -q -o "$BUILD/requirements.txt"
SOURCES=$(cd "$APP" && find . -name '*.py' -not -path './tests/*' -not -path './.venv/*' | sort)

# Content hash of dependencies + sources, so unchanged code doesn't trigger a runtime update.
HASH=$( (cat "$BUILD/requirements.txt"; cd "$APP" && cat $SOURCES) | shasum -a 256 | cut -c1-16)
KEY="reviewer/$HASH.zip"

if aws s3api head-object --bucket "$BUCKET" --key "$KEY" >/dev/null 2>&1; then
  echo "Code package s3://$BUCKET/$KEY already uploaded"
else
  echo "Building code package (linux arm64, Python 3.14)"
  uv pip install -q -r "$BUILD/requirements.txt" --target "$BUILD/pkg" \
    --python-version 3.14 --python-platform aarch64-manylinux2014 --only-binary :all:
  (cd "$APP" && for f in $SOURCES; do mkdir -p "$BUILD/pkg/$(dirname "$f")" && cp "$f" "$BUILD/pkg/$f"; done)
  (cd "$BUILD/pkg" && zip -qr "$BUILD/reviewer.zip" .)
  aws s3 cp --only-show-errors "$BUILD/reviewer.zip" "s3://$BUCKET/$KEY"
fi

aws cloudformation deploy \
  --stack-name "$STACK_NAME" \
  --template-file "$ROOT/infra/agent.yaml" \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides CodeBucket="$BUCKET" CodeKey="$KEY"

aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
