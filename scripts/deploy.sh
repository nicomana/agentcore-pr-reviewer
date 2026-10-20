#!/usr/bin/env bash
# Build the agent code zip, upload it to S3 and deploy infra/agent.yaml with configs/<env>.yaml.
#   AWS_PROFILE=<your-profile> scripts/deploy.sh sandbox
# Config keys: StackName (default pr-reviewer), Region (default us-east-1),
#   ArtifactBucket (default pr-reviewer-artifacts-<account>-<region>, created if missing),
#   Parameters (stack parameters), Tags (stack tags). Strings support $ENV_VARS.
# DRY_RUN=1 uploads the code and creates the change set without executing it.
# Requires: aws, uv, yq (mikefarah, v4), zip.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
APP="$ROOT/app/reviewer"
BUILD="$ROOT/build"
ENV_NAME=${1:?usage: scripts/deploy.sh <env>  (reads configs/<env>.yaml)}
CONFIG="$ROOT/configs/$ENV_NAME.yaml"
[ -f "$CONFIG" ] || { echo "Config not found: $CONFIG" >&2; exit 1; }

# Read a value from the config with environment variables substituted into every string.
cfg() { yq "(.. | select(tag == \"!!str\")) |= envsubst | $1" "$CONFIG"; }
# Print one Key=Value line per entry of a config map.
cfg_pairs() { cfg "$1 // {} | to_entries | .[] | .key + \"=\" + (.value | tostring)"; }

STACK_NAME=$(cfg '.StackName // "pr-reviewer"')
REGION=$(cfg '.Region // "us-east-1"')
export AWS_REGION=$REGION
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET=$(cfg ".ArtifactBucket // \"pr-reviewer-artifacts-$ACCOUNT-$REGION\"")

PARAMS=() TAGS=()
while IFS= read -r line; do [ -n "$line" ] && PARAMS+=("$line"); done < <(cfg_pairs .Parameters)
while IFS= read -r line; do [ -n "$line" ] && TAGS+=("$line"); done < <(cfg_pairs .Tags)
echo "Deploying $STACK_NAME to $ACCOUNT/$REGION with configs/$ENV_NAME.yaml"

if ! aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
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
  ${DRY_RUN:+--no-execute-changeset} \
  --parameter-overrides CodeBucket="$BUCKET" CodeKey="$KEY" ${PARAMS[@]+"${PARAMS[@]}"} \
  ${TAGS[@]+--tags "${TAGS[@]}"}

aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
