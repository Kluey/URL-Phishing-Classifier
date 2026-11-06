# Build from the repo root: docker build -f api/Dockerfile -t phishing-api .
FROM public.ecr.aws/lambda/python:3.12

ENV TIKTOKEN_CACHE_DIR=${LAMBDA_TASK_ROOT}/.tiktoken
COPY api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
# Lambda's filesystem is read-only outside /tmp, and fetching the BPE at cold start would add latency
RUN python -c "import tiktoken; tiktoken.get_encoding('gpt2')"

# Copied, not pip-installed, so pandas, sklearn, tldextract and TF stay out of the image
COPY components/ ${LAMBDA_TASK_ROOT}/components/
COPY api/ ${LAMBDA_TASK_ROOT}/api/
# Own last layer: unchanged weights keep the same digest and aren't re-pushed
COPY model/phishing_classifier.pth ${LAMBDA_TASK_ROOT}/model/phishing_classifier.pth

CMD ["api.main.handler"]
